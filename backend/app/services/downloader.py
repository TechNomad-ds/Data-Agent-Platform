"""从外部下载数据到数据空间的服务。

支持直链 URL、GitHub（raw/release/repo 文件）、HuggingFace（datasets/models，
自动走 hf-mirror.com 中国镜像）。下载后落到用户存储目录并登记进数据空间、触发索引。

安全：
- 仅允许 http/https；拒绝内网/本机地址，避免 SSRF。
- 限制单文件大小（默认 500MB），流式下载边写边计数，超限即中止。
"""
import ipaddress
import socket
import logging
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx

from app.config import settings

logger = logging.getLogger("downloader")

MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500MB 单文件上限
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, read=300.0)

# HuggingFace 整仓下载上限：防把磁盘下满 / 误下超大模型权重仓库
HF_REPO_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # 整仓累计 2GB
HF_REPO_MAX_FILES = 200                            # 文件数上限
_HF_MIRROR = "hf-mirror.com"


def _is_private_host(host: str) -> bool:
    """解析主机名，判断是否指向内网/本机（SSRF 防护）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # 解析不了，保守拒绝
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return True
    return False


def _rewrite_known_hosts(url: str) -> str:
    """把已知海外数据源改写到国内镜像，提升下载成功率/速度。

    - huggingface.co -> hf-mirror.com（HF 官方镜像，路径完全一致）
    其它（github、kaggle 等）保持原样：github 通常可直连，kaggle 需认证另行处理。
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in ("huggingface.co", "www.huggingface.co"):
        return url.replace(parsed.netloc, "hf-mirror.com")
    return url


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(path.rsplit("/", 1)[-1]) if "/" in path else ""
    return name or "downloaded_file"


async def download_url_to_path(url: str, dest_dir: Path) -> tuple[Path, str]:
    """流式下载 url 到 dest_dir，返回 (落盘路径, 文件名)。做大小/SSRF 校验。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("只支持 http/https 链接")
    if not parsed.netloc or _is_private_host(parsed.hostname or ""):
        raise ValueError("拒绝访问内网/本机地址")

    url = _rewrite_known_hosts(url)
    filename = _filename_from_url(url)
    dest = dest_dir / filename
    await _stream_to_file(url, dest)
    return dest, filename


async def _stream_to_file(url: str, dest: Path) -> int:
    """把 url 流式下载到 dest（绝对路径），返回写入字节数。带大小上限校验。

    调用方需保证 url 已通过 scheme/SSRF 校验（HF 整仓下载经镜像域名，安全）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise ValueError(f"下载失败：HTTP {resp.status_code}")
            clen = resp.headers.get("content-length")
            if clen and int(clen) > MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"文件过大（{int(clen)//1024//1024}MB），超过 {MAX_DOWNLOAD_BYTES//1024//1024}MB 上限"
                )
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        f.close()
                        dest.unlink(missing_ok=True)
                        raise ValueError(
                            f"文件超过 {MAX_DOWNLOAD_BYTES//1024//1024}MB 上限，已中止"
                        )
                    f.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("下载内容为空")
    return written


def parse_hf_url(url: str) -> tuple[str, str] | None:
    """从 URL/简写识别 HuggingFace 仓库，返回 (repo_type, repo_id)，否则 None。

    支持：
    - https://huggingface.co/datasets/{owner}/{name}            -> ("dataset", "owner/name")
    - https://huggingface.co/{owner}/{name}（模型）              -> ("model",   "owner/name")
    - 裸简写 "datasets/owner/name" / "owner/name"
    指向具体文件的 resolve/blob 链接返回 None（交给单文件下载）。
    """
    s = (url or "").strip()
    if not s:
        return None
    # 指向单文件的链接不当作整仓
    if "/resolve/" in s or "/blob/" in s:
        return None

    path = s
    parsed = urlparse(s)
    if parsed.scheme in ("http", "https"):
        host = (parsed.netloc or "").lower()
        if host not in ("huggingface.co", "www.huggingface.co", _HF_MIRROR):
            return None
        path = parsed.path.strip("/")
    else:
        path = s.strip("/")

    if not path:
        return None
    parts = path.split("/")
    if parts[0] in ("datasets", "dataset"):
        rest = parts[1:]
        if len(rest) >= 2:
            return ("dataset", f"{rest[0]}/{rest[1]}")
        return None
    if parts[0] in ("models", "model"):
        rest = parts[1:]
        if len(rest) >= 2:
            return ("model", f"{rest[0]}/{rest[1]}")
        return None
    # owner/name 形式 → 默认按模型
    if len(parts) >= 2 and parts[0] not in ("spaces", "space"):
        return ("model", f"{parts[0]}/{parts[1]}")
    return None


async def _hf_list_files(repo_type: str, repo_id: str) -> list[dict]:
    """经 hf-mirror 列出仓库文件树（递归），返回 [{path, size}]。"""
    seg = "datasets" if repo_type == "dataset" else "models"
    # models 的 API 路径不带 models 前缀：/api/models/{id}；datasets：/api/datasets/{id}
    api = f"https://{_HF_MIRROR}/api/{seg}/{repo_id}/tree/main?recursive=true"
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(api)
        if resp.status_code == 404:
            raise ValueError(f"HuggingFace 仓库不存在或不可访问：{repo_id}")
        if resp.status_code >= 400:
            raise ValueError(f"列举仓库文件失败：HTTP {resp.status_code}")
        data = resp.json()
    files = [
        {"path": item["path"], "size": item.get("size", 0)}
        for item in data
        if item.get("type") == "file"
    ]
    return files


def _hf_resolve_url(repo_type: str, repo_id: str, file_path: str) -> str:
    seg = "datasets/" if repo_type == "dataset" else ""
    return f"https://{_HF_MIRROR}/{seg}{repo_id}/resolve/main/{file_path}"


async def download_hf_repo_to_dir(url: str, dest_dir: Path) -> dict:
    """下载一个 HuggingFace 仓库的全部文件到 dest_dir（保留子路径，扁平化为文件名）。

    返回 {repo_id, repo_type, files: [(path, name)], skipped: [(name, reason)], total_bytes}。
    带单文件/总量/文件数上限，超大文件（如模型权重）跳过并记录，不静默失败。
    """
    parsed = parse_hf_url(url)
    if not parsed:
        raise ValueError("不是有效的 HuggingFace 仓库链接")
    repo_type, repo_id = parsed

    entries = await _hf_list_files(repo_type, repo_id)
    if not entries:
        raise ValueError(f"仓库 {repo_id} 没有可下载的文件")

    downloaded: list[tuple[Path, str]] = []
    skipped: list[tuple[str, str]] = []
    total = 0
    repo_tag = repo_id.replace("/", "_")

    for ent in entries:
        if len(downloaded) >= HF_REPO_MAX_FILES:
            skipped.append((ent["path"], f"超过文件数上限({HF_REPO_MAX_FILES})"))
            continue
        size = ent.get("size", 0) or 0
        if size > MAX_DOWNLOAD_BYTES:
            skipped.append((ent["path"], f"单文件过大({size//1024//1024}MB)"))
            continue
        if total + size > HF_REPO_MAX_TOTAL_BYTES:
            skipped.append((ent["path"], "超过整仓总量上限(2GB)"))
            continue

        # 扁平化文件名：子目录用 __ 连接，避免目录穿越与同名覆盖
        flat_name = f"{repo_tag}__{ent['path'].replace('/', '__')}"
        dl_url = _hf_resolve_url(repo_type, repo_id, ent["path"])
        try:
            written = await _stream_to_file(dl_url, dest_dir / flat_name)
            total += written
            downloaded.append((dest_dir / flat_name, flat_name))
        except Exception as e:
            skipped.append((ent["path"], f"下载失败：{str(e)[:80]}"))

    if not downloaded:
        raise ValueError("仓库内没有成功下载到任何文件（可能都超限或下载失败）")

    return {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "files": downloaded,
        "skipped": skipped,
        "total_bytes": total,
    }
