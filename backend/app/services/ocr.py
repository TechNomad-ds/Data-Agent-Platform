"""PaddleOCR-VL 远程 OCR 客户端

用于把 PDF / 图片解析成 Markdown 文本，供 Agent 分析。
配置（接口地址 / 令牌 / 模型）由管理后台写入 Redis，运行时优先读 Redis，
未配置时回退到 settings 默认值。

设计要点：
- 全异步（httpx.AsyncClient），不阻塞事件循环；提交 job 后轮询直至完成。
- 任何异常 / 未配置 / 失败 / 超时都返回 None，调用方据此保留本地抽取结果。
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("ocr")

# 轮询参数
_POLL_INTERVAL = 5          # 秒
_MAX_POLL_SECONDS = 300     # 单个文件最长等待 5 分钟
_SUBMIT_TIMEOUT = 60        # 提交 job 的超时
_DEFAULT_OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useChartRecognition": False,
}


async def _get_ocr_settings() -> dict:
    """读取 OCR 配置：Redis 优先，回退 settings。"""
    base = settings.ocr_api_base
    token = settings.ocr_api_key
    model = settings.ocr_model
    try:
        from app.core.redis_client import get_redis
        from app.core.security import decrypt_api_key
        redis = await get_redis()
        base = (await redis.get("global:ocr_base")) or base
        stored_token = await redis.get("global:ocr_token")
        if stored_token:
            try:
                token = decrypt_api_key(stored_token)
            except ValueError:
                token = stored_token
        model = (await redis.get("global:ocr_model")) or model
    except Exception as e:
        logger.warning(f"读取 Redis OCR 配置失败，使用默认值: {e}")
    return {"base": base, "token": token, "model": model}


async def is_ocr_configured() -> bool:
    """OCR 令牌是否已配置。"""
    cfg = await _get_ocr_settings()
    return bool(cfg["token"] and cfg["base"])


async def ocr_extract_markdown(file_path: Path) -> Optional[str]:
    """对本地文件调用 PaddleOCR-VL，返回拼接后的 Markdown 文本。

    失败/未配置/超时一律返回 None，调用方应保留本地抽取结果。
    """
    cfg = await _get_ocr_settings()
    base = (cfg["base"] or "").rstrip("/")
    token = cfg["token"]
    model = cfg["model"]
    if not (base and token):
        return None
    if not file_path.exists():
        return None

    headers = {"Authorization": f"bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT) as client:
            # 1) 提交 job（Local File Mode）
            data = {
                "model": model,
                "optionalPayload": json.dumps(_DEFAULT_OPTIONAL_PAYLOAD),
            }
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f)}
                resp = await client.post(base, headers=headers, data=data, files=files)
            if resp.status_code != 200:
                logger.warning(f"OCR 提交失败 {file_path.name}: {resp.status_code} {resp.text[:200]}")
                return None
            job_id = resp.json().get("data", {}).get("jobId")
            if not job_id:
                logger.warning(f"OCR 未返回 jobId: {file_path.name}")
                return None

            # 2) 轮询
            jsonl_url = await _poll_job(client, base, job_id, headers, file_path.name)
            if not jsonl_url:
                return None

            # 3) 下载并拼接 Markdown
            return await _fetch_markdown(client, jsonl_url, file_path.name)
    except Exception as e:
        logger.warning(f"OCR 处理异常 {file_path.name}: {e}")
        return None


async def _poll_job(
    client: httpx.AsyncClient, base: str, job_id: str, headers: dict, name: str
) -> Optional[str]:
    """轮询 job 状态，done 返回 jsonUrl，否则返回 None。"""
    waited = 0
    while waited <= _MAX_POLL_SECONDS:
        try:
            r = await client.get(f"{base}/{job_id}", headers=headers)
            if r.status_code != 200:
                logger.warning(f"OCR 轮询失败 {name}: {r.status_code}")
                return None
            data = r.json().get("data", {})
            state = data.get("state")
            if state == "done":
                return data.get("resultUrl", {}).get("jsonUrl")
            if state == "failed":
                logger.warning(f"OCR job 失败 {name}: {data.get('errorMsg')}")
                return None
        except Exception as e:
            logger.warning(f"OCR 轮询异常 {name}: {e}")
            return None
        await asyncio.sleep(_POLL_INTERVAL)
        waited += _POLL_INTERVAL
    logger.warning(f"OCR 轮询超时 {name}（>{_MAX_POLL_SECONDS}s）")
    return None


async def _fetch_markdown(client: httpx.AsyncClient, jsonl_url: str, name: str) -> Optional[str]:
    """下载 jsonl 结果，拼接所有页的 markdown 文本。"""
    try:
        r = await client.get(jsonl_url, timeout=_SUBMIT_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"OCR 结果下载失败 {name}: {e}")
        return None

    parts: list[str] = []
    for line in r.text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            result = json.loads(line).get("result", {})
            for res in result.get("layoutParsingResults", []):
                text = res.get("markdown", {}).get("text", "")
                if text:
                    parts.append(text)
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue

    md = "\n\n".join(parts).strip()
    if not md:
        logger.info(f"OCR 结果为空 {name}")
        return None
    return md
