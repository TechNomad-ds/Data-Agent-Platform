"""read_file 的 find 关键词定位 + 页码推断单元测试。

针对「在厚文档里定位某问题、不整本读」的能力：纯函数测试，不触发外部接口。
"""
from app.agent.tools import (
    _page_at_line,
    _find_in_lines,
    _render_find,
    get_tool_definitions,
)


# read_file 重建 PDF 时的行表示：带 `--- 第 N 页 ---` 页标记
PDF_LINES = (
    ["--- 第 1 页 ---", "intro line", "about cats"]
    + ["--- 第 2 页 ---", "some theory", "the FOURIER transform is key", "more text"]
    + ["--- 第 3 页 ---", "fourier again here", "end"]
)


def test_page_at_line_backtracks_to_marker():
    assert _page_at_line(PDF_LINES, 1) == 1
    assert _page_at_line(PDF_LINES, 5) == 2
    assert _page_at_line(PDF_LINES, 8) == 3


def test_page_at_line_no_marker_returns_none():
    assert _page_at_line(["a", "b", "c"], 1) is None


def test_find_in_lines_case_insensitive_all_hits():
    assert _find_in_lines(PDF_LINES, "fourier", 0) == [5, 8]
    # from_line 之后才算
    assert _find_in_lines(PDF_LINES, "fourier", 6) == [8]


def test_render_find_first_hit_reports_page_and_navigation():
    out = _render_find("book.pdf", "PDF", PDF_LINES, "fourier", 0, 4)
    assert "约在第 2 页" in out
    assert "共匹配 2 处" in out
    # 看下一处 = 命中行(5)+1
    assert "start_line=6" in out
    # 命中文本应在上下文窗口里
    assert "FOURIER transform" in out


def test_render_find_iterate_to_next_hit():
    out = _render_find("book.pdf", "PDF", PDF_LINES, "fourier", 6, 4)
    assert "约在第 3 页" in out
    assert "只匹配这 1 处" in out


def test_render_find_no_match():
    out = _render_find("book.pdf", "PDF", PDF_LINES, "quantum", 0, 4)
    assert "未找到" in out


def test_render_find_plain_text_no_fake_page():
    plain = ["line a", "find me here", "line c"]
    out = _render_find("notes.txt", "文本", plain, "find me", 0, 4)
    assert "约在第" not in out  # 无页标记不假造页码


def test_read_file_tool_exposes_find_param():
    defs = {t["function"]["name"]: t for t in get_tool_definitions()}
    rf = defs["read_file"]["function"]["parameters"]["properties"]
    assert "find" in rf


def test_tool_surface_core_trio_present_and_db_import_removed():
    names = {t["function"]["name"] for t in get_tool_definitions()}
    # 读文件核心三件套必须在
    assert {"list_files", "read_file", "search_data_space"} <= names
    # 冗余工具已删（sqlite_query 自动加载，无需单独导入）
    assert "db_import_csv" not in names


# PDF 抽取后多词短语跨行的真实排布（CSAPP 寄存器表）
PDF_CROSS_LINE = [
    "--- 第 216 页 ---",
    "Figure 3.2",
    "Integer registers. The low-order portions of all 16 registers can be",
    "accessed as byte, word, double word, and quad word.",
    "%rax   Return value",
]


def test_find_cross_line_whole_phrase():
    # 短语被 PDF 拦腰切成两行，跨行拼接后应命中（算 1 处）。
    # 命中起点是能拼出该短语的最早窗口起点（JOIN_SPAN 滑窗，可能早于短语首词所在行）。
    hits = _find_in_lines(PDF_CROSS_LINE, "all 16 registers can be accessed as byte", 0)
    assert len(hits) == 1
    assert hits[0] in (1, 2)


def test_find_multiword_cooccurrence_when_words_scattered():
    # "Figure 3.2 integer registers" 词散落在不同行：整串/跨行都不中，靠词共现命中（1 处）
    hits = _find_in_lines(PDF_CROSS_LINE, "Figure 3.2 integer registers", 0)
    assert len(hits) == 1


def test_find_single_line_exact_still_precise():
    # 单行整串仍优先、精确
    assert _find_in_lines(PDF_CROSS_LINE, "Return value", 0) == [4]


def test_find_truly_absent_returns_empty():
    assert _find_in_lines(PDF_CROSS_LINE, "quantum entanglement theory", 0) == []

