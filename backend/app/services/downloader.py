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

    written = 0
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise ValueError(f"下载失败：HTTP {resp.status_code}")
            # Content-Length 预检（有则用）
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
    return dest, filename
