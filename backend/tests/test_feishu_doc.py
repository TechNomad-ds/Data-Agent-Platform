"""飞书云文档接入单测：链接抽取 / 单元格转换 / CSV / 抓取路由（假 adapter，不发真请求）。

只依赖 stdlib + 服务本身；用 asyncio.run 驱动异步，免 pytest-asyncio。
"""
import asyncio

from app.services.feishu_doc import (
    extract_feishu_doc_links,
    _cell_to_str,
    _values_to_csv,
    _safe_filename,
    fetch_feishu_doc,
    FeishuDocError,
)


# ---------- 链接抽取 ----------

def test_extract_links_types():
    text = (
        "看下这个 https://abc.feishu.cn/docx/Doc123 还有 "
        "https://abc.feishu.cn/sheets/Sht456 和 https://x.larksuite.com/wiki/Wik789"
    )
    links = extract_feishu_doc_links(text)
    assert ("docx", "Doc123") in links
    assert ("sheets", "Sht456") in links
    assert ("wiki", "Wik789") in links


def test_extract_links_dedup_and_empty():
    text = "https://a.feishu.cn/docx/SAME https://a.feishu.cn/docx/SAME"
    assert extract_feishu_doc_links(text) == [("docx", "SAME")]
    assert extract_feishu_doc_links("没有链接") == []
    assert extract_feishu_doc_links("") == []


def test_extract_ignores_non_doc_urls():
    assert extract_feishu_doc_links("https://feishu.cn/about https://google.com/docx/x") == []


# ---------- 单元格 / CSV ----------

def test_cell_to_str_variants():
    assert _cell_to_str(None) == ""
    assert _cell_to_str(12) == "12"
    assert _cell_to_str(True) == "TRUE"
    assert _cell_to_str("hi") == "hi"
    assert _cell_to_str([{"type": "text", "text": "你好"}, {"type": "text", "text": "世界"}]) == "你好世界"
    assert _cell_to_str({"text": "链接文字"}) == "链接文字"


def test_values_to_csv():
    csv_bytes = _values_to_csv([["名称", "数量"], ["苹果", 3], ["香蕉", None]])
    text = csv_bytes.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "名称,数量"
    assert lines[1] == "苹果,3"
    assert lines[2] == "香蕉,"


def test_safe_filename():
    assert _safe_filename("a/b:c*?", ".md") == "a_b_c_.md"
    assert _safe_filename("", ".csv") == "feishu_doc.csv"


# ---------- 抓取路由（假 adapter）----------

class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeHttp:
    def __init__(self, routes):
        self.routes = routes  # dict: url-substring -> payload

    async def get(self, url, params=None, headers=None):
        for frag, payload in self.routes.items():
            if frag in url:
                return _FakeResp(payload)
        raise AssertionError(f"unexpected url {url}")


class _FakeAdapter:
    def __init__(self, routes):
        self._http = _FakeHttp(routes)

    async def _get_token(self):
        return "tok"


def test_fetch_docx():
    adapter = _FakeAdapter({
        "/docx/v1/documents/Doc123/raw_content": {"code": 0, "data": {"content": "正文内容"}},
        "/docx/v1/documents/Doc123": {"code": 0, "data": {"document": {"title": "我的文档"}}},
    })
    files = asyncio.run(fetch_feishu_doc(adapter, "docx", "Doc123"))
    assert files == [("我的文档.md", "正文内容".encode("utf-8"))]


def test_fetch_sheets_multi():
    adapter = _FakeAdapter({
        "/sheets/v3/spreadsheets/Sht456/sheets/query": {"code": 0, "data": {"sheets": [
            {"sheet_id": "s1", "title": "一月"}, {"sheet_id": "s2", "title": "二月"}]}},
        "/sheets/v3/spreadsheets/Sht456": {"code": 0, "data": {"spreadsheet": {"title": "销售表"}}},
        "/sheets/v2/spreadsheets/Sht456/values/s1": {"code": 0, "data": {"valueRange": {"values": [["a", 1]]}}},
        "/sheets/v2/spreadsheets/Sht456/values/s2": {"code": 0, "data": {"valueRange": {"values": [["b", 2]]}}},
    })
    files = asyncio.run(fetch_feishu_doc(adapter, "sheets", "Sht456"))
    names = [f[0] for f in files]
    assert names == ["销售表-一月.csv", "销售表-二月.csv"]


def test_fetch_api_error_raises():
    adapter = _FakeAdapter({
        "/docx/v1/documents/X": {"code": 99991672, "msg": "no permission"},
    })
    try:
        asyncio.run(fetch_feishu_doc(adapter, "docx", "X"))
        assert False, "should raise"
    except FeishuDocError as e:
        assert "no permission" in str(e)


def test_old_docs_unsupported():
    try:
        asyncio.run(fetch_feishu_doc(_FakeAdapter({}), "docs", "X"))
        assert False
    except FeishuDocError as e:
        assert "旧版" in str(e)
