"""联网搜索服务。支持 Tavily 与 Serper(google) 两种 provider，按 settings 配置选择。

设计：未配置 API key 时抛 _NotConfigured，由工具层翻译成对用户/模型友好的提示，
而不是 500 报错——让 agent 能据此换用 search_data_space 或如实告知用户。
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger("web_search")

_TIMEOUT = httpx.Timeout(20.0)


class WebSearchNotConfigured(Exception):
    pass


async def web_search(query: str, max_results: int | None = None) -> list[dict]:
    """返回 [{title, url, snippet}]。未配置 key 抛 WebSearchNotConfigured。"""
    key = (settings.web_search_api_key or "").strip()
    if not key:
        raise WebSearchNotConfigured()
    provider = (settings.web_search_provider or "tavily").lower()
    n = max_results or settings.web_search_max_results

    if provider == "serper":
        return await _serper(query, key, n)
    return await _tavily(query, key, n)


async def _tavily(query: str, key: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": n,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    out = []
    for r in data.get("results", [])[:n]:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        })
    return out


async def _serper(query: str, key: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": n},
        )
        resp.raise_for_status()
        data = resp.json()
    out = []
    for r in data.get("organic", [])[:n]:
        out.append({
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
        })
    return out
