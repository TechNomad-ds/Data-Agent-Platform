"""飞书云文档接入：把分享给 bot 的飞书云文档/表格/知识库链接抓取成文件，落进数据空间。

用户在飞书里把云文档链接发给 bot → 本服务用 bot 的 tenant_access_token 调飞书 OpenAPI
取内容（docx→纯文本 .md / sheets→CSV / wiki→解析到底层文档），写入用户存储目录后走
file_intake.register_file_to_space 登记 + 触发后台解析索引。之后 agent 即可像普通上传文件
一样检索/分析。

仅依赖 adapter 暴露的 _get_token() + _http（同一 FeishuAdapter 实例，dispatch 里直接拿到）。
飞书自建应用需开通 docx:document:readonly / sheets 读 / wiki 读权限，并把文档授权给应用，
否则 API 返回非 0 code，本服务抛 FeishuDocError 由 dispatch 回告用户。
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import uuid
from typing import Any

FEISHU_OPEN_API = "https://open.feishu.cn/open-apis"

# 匹配 feishu.cn / larksuite.com 的云文档链接 → (doc_type, token)
FEISHU_DOC_RE = re.compile(
    r"https?://[\w.-]+\.(?:feishu\.cn|larksuite\.com)/(docx|docs|sheets|wiki|base)/([A-Za-z0-9]+)"
)


class FeishuDocError(Exception):
    """飞书云文档抓取失败（含 API 非 0 code / 不支持的类型）。"""


def extract_feishu_doc_links(text: str) -> list[tuple[str, str]]:
    """从文本里抽出所有飞书云文档链接，返回去重后的 [(doc_type, token), ...]。"""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for m in FEISHU_DOC_RE.finditer(text or ""):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _safe_filename(name: str, suffix: str) -> str:
    """清洗文件名里的非法字符，限长，补后缀。"""
    cleaned = re.sub(r'[/\\:*?"<>|\r\n\t]+', "_", (name or "").strip()) or "feishu_doc"
    cleaned = cleaned[:80].rstrip(" .") or "feishu_doc"
    return cleaned + suffix


def _cell_to_str(cell: Any) -> str:
    """飞书表格单元格 → 字符串（兼容富文本段数组 / 超链接对象 / 基础类型）。"""
    if cell is None:
        return ""
    if isinstance(cell, bool):
        return "TRUE" if cell else "FALSE"
    if isinstance(cell, (int, float, str)):
        return str(cell)
    if isinstance(cell, list):
        # 富文本：段数组，每段可能是 {"type":"text","text":"..."} 或带超链接
        parts = []
        for seg in cell:
            if isinstance(seg, dict):
                parts.append(seg.get("text") or seg.get("link") or "")
            else:
                parts.append(str(seg))
        return "".join(parts)
    if isinstance(cell, dict):
        return cell.get("text") or json.dumps(cell, ensure_ascii=False)
    return str(cell)


def _values_to_csv(values: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in values or []:
        writer.writerow([_cell_to_str(c) for c in row])
    return buf.getvalue().encode("utf-8-sig")  # BOM 便于 Excel 正确识别中文


# ---------------------------------------------------------------------------
# 飞书 OpenAPI 调用（复用 adapter 的 token + http client）
# ---------------------------------------------------------------------------

async def _api_get(adapter: Any, url: str, params: dict | None = None) -> dict:
    token = await adapter._get_token()
    resp = await adapter._http.get(
        url, params=params, headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", -1) != 0:
        raise FeishuDocError(data.get("msg") or f"飞书 API 错误 code={data.get('code')}")
    return data.get("data") or {}


async def _fetch_docx(adapter: Any, token: str) -> list[tuple[str, bytes]]:
    meta = await _api_get(adapter, f"{FEISHU_OPEN_API}/docx/v1/documents/{token}")
    title = (meta.get("document") or {}).get("title") or token
    raw = await _api_get(adapter, f"{FEISHU_OPEN_API}/docx/v1/documents/{token}/raw_content")
    content = raw.get("content") or ""
    return [(_safe_filename(title, ".md"), content.encode("utf-8"))]


async def _fetch_sheets(adapter: Any, token: str) -> list[tuple[str, bytes]]:
    meta = await _api_get(adapter, f"{FEISHU_OPEN_API}/sheets/v3/spreadsheets/{token}")
    ss_title = (meta.get("spreadsheet") or {}).get("title") or token
    q = await _api_get(adapter, f"{FEISHU_OPEN_API}/sheets/v3/spreadsheets/{token}/sheets/query")
    sheets = q.get("sheets") or []
    if not sheets:
        raise FeishuDocError("表格里没有可读的工作表")
    out: list[tuple[str, bytes]] = []
    multi = len(sheets) > 1
    for sh in sheets:
        sid = sh.get("sheet_id")
        stitle = sh.get("title") or sid
        vr = await _api_get(
            adapter, f"{FEISHU_OPEN_API}/sheets/v2/spreadsheets/{token}/values/{sid}"
        )
        values = ((vr.get("valueRange") or {}).get("values")) or []
        base = f"{ss_title}-{stitle}" if multi else ss_title
        out.append((_safe_filename(base, ".csv"), _values_to_csv(values)))
    return out


async def _fetch_wiki(adapter: Any, token: str) -> list[tuple[str, bytes]]:
    data = await _api_get(
        adapter, f"{FEISHU_OPEN_API}/wiki/v2/spaces/get_node", params={"token": token}
    )
    node = data.get("node") or {}
    obj_type = node.get("obj_type")
    obj_token = node.get("obj_token")
    if not obj_token:
        raise FeishuDocError("无法解析该 wiki 节点对应的文档")
    if obj_type == "docx":
        return await _fetch_docx(adapter, obj_token)
    if obj_type in ("sheet", "sheets"):
        return await _fetch_sheets(adapter, obj_token)
    raise FeishuDocError(f"暂不支持的 wiki 节点类型：{obj_type}")


async def fetch_feishu_doc(adapter: Any, doc_type: str, token: str) -> list[tuple[str, bytes]]:
    """按链接类型抓取内容，返回 [(filename, bytes), ...]（表格可能多个工作表→多文件）。"""
    if doc_type == "docx":
        return await _fetch_docx(adapter, token)
    if doc_type == "sheets":
        return await _fetch_sheets(adapter, token)
    if doc_type == "wiki":
        return await _fetch_wiki(adapter, token)
    if doc_type == "docs":
        raise FeishuDocError("暂不支持旧版文档（/docs），请用新版云文档（/docx）或表格")
    if doc_type == "base":
        raise FeishuDocError("暂不支持多维表格（/base），请用云文档或普通表格")
    raise FeishuDocError(f"暂不支持的文档类型：{doc_type}")


async def try_ingest_feishu_doc(
    adapter: Any,
    inbound: Any,
    user_id: uuid.UUID,
    space_id: uuid.UUID,
) -> list[dict]:
    """抽取消息里的飞书文档链接，逐个抓取并登记进数据空间。无链接返回 []。

    任一链接抓取失败直接抛 FeishuDocError（dispatch 捕获并回告用户，禁兜底）。
    """
    links = extract_feishu_doc_links(getattr(inbound, "text", "") or "")
    if not links:
        return []
    from app.services.channel_ingest import ingest_files_to_space

    # 多链接并发抓取（各自独立网络 I/O），再展平登记
    results = await asyncio.gather(
        *(fetch_feishu_doc(adapter, doc_type, token) for doc_type, token in links)
    )
    files = [f for group in results for f in group]
    return await ingest_files_to_space(user_id, space_id, files)
