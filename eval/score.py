"""答案比对评分

gold.csv 是 SQL 查询结果集。agent 的回答是自由文本+markdown表格+工具输出。
策略：从 trace 中抽取所有候选"结果集"（markdown 表格 / sqlite_query 输出 / 数字串），
与 gold 做集合级比对（顺序无关、数值容差、字符串归一化），取最佳匹配。

判定：
- 单值 gold (1行1列)：该值是否出现在候选结果或文本中
- 多行 gold：候选集合与 gold 集合的匹配率（F1），≥0.99 视为 pass
"""
import csv
import io
import re
import json
from pathlib import Path

OUTPUT_ROOT = Path("/root/datamind/demo_samples_phase2/output")


def load_gold(task_id: str) -> tuple[list[str], list[tuple]]:
    """读 gold.csv，返回 (header, rows)。每行是字符串元组。"""
    f = OUTPUT_ROOT / task_id / "gold.csv"
    text = f.read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    header = rows[0]
    data = [tuple(r) for r in rows[1:]]
    return header, data


def norm_cell(v: str) -> str:
    """归一化单元格：去空白/引号，数值统一格式（容差靠 round）。"""
    if v is None:
        return ""
    s = str(v).strip().strip('"').strip()
    if s in ("", "nan", "None", "null", "NaN"):
        return ""
    # 数值：归一到固定精度，吸收浮点尾差（如 230426.99999 vs 230427）
    try:
        fv = float(s.replace(",", ""))
        if abs(fv - round(fv)) < 1e-6:
            return str(int(round(fv)))
        return f"{fv:.2f}"
    except ValueError:
        return s.lower()


def norm_row(row: tuple) -> tuple:
    return tuple(norm_cell(c) for c in row)


def multiset(rows: list[tuple]) -> dict:
    """行的多重集（顺序无关）。单列时按值计数。"""
    from collections import Counter
    return Counter(norm_row(r) for r in rows)


def compare_sets(gold: list[tuple], cand: list[tuple]) -> dict:
    """多重集比对，返回 precision/recall/f1 与匹配数。"""
    g = multiset(gold)
    c = multiset(cand)
    inter = 0
    for k, gv in g.items():
        inter += min(gv, c.get(k, 0))
    gold_n = sum(g.values())
    cand_n = sum(c.values())
    recall = inter / gold_n if gold_n else 0.0
    precision = inter / cand_n if cand_n else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "matched": inter, "gold_n": gold_n, "cand_n": cand_n}


# ---------- 从 trace 抽取候选结果集 ----------

def parse_markdown_tables(text: str) -> list[list[tuple]]:
    """抽取 markdown 表格 → 每个表为 rows（不含表头分隔行）。"""
    tables = []
    lines = text.split("\n")
    cur = []
    for ln in lines:
        if ln.strip().startswith("|") and ln.strip().endswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            # 跳过分隔行 |---|---|
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            cur.append(tuple(cells))
        else:
            if len(cur) >= 1:
                tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def parse_df_tostring(text: str) -> list[list[tuple]]:
    """抽取 pandas df.to_string() 风格的块（sqlite_query/pandas_query 输出）。
    形如：列名行 + 多行带行号的数据。粗略按空白分列。"""
    blocks = []
    # 匹配 "返回 N 行" 之后的表块
    chunks = re.split(r"返回 \d+ 行[^\n]*\n", text)
    for ch in chunks[1:]:
        rows = []
        for ln in ch.split("\n"):
            if not ln.strip():
                break
            parts = ln.split()
            if parts and re.fullmatch(r"\d+", parts[0]):
                parts = parts[1:]  # 去掉 pandas 行号
            if parts:
                rows.append(tuple(parts))
        if rows:
            blocks.append(rows)
    return blocks


def extract_candidates(result: dict) -> list[list[tuple]]:
    """从 agent result.json 抽取所有候选结果集。"""
    cands = []
    answer = result.get("answer", "")
    cands.extend(parse_markdown_tables(answer))
    cands.extend(parse_df_tostring(answer))
    for t in result.get("tool_log", []):
        if t.get("phase") == "result" and not t.get("is_error"):
            content = t.get("content", "")
            cands.extend(parse_df_tostring(content))
            cands.extend(parse_markdown_tables(content))
    cands = [c for c in cands if c]
    # 每个候选表额外加一个"去掉首行"的变体，吸收被当成数据行的表头
    expanded = []
    for c in cands:
        expanded.append(c)
        if len(c) > 1:
            expanded.append(c[1:])
    return expanded


def project_columns(cand_rows: list[tuple], ncol: int) -> list[list[tuple]]:
    """gold 有 ncol 列。候选表可能多列，尝试所有 ncol 列的子集投影。
    简化：若候选列数==ncol 直接用；否则尝试每个连续/单列投影。"""
    variants = []
    if not cand_rows:
        return variants
    width = max(len(r) for r in cand_rows)
    if ncol == 1:
        for ci in range(width):
            variants.append([(r[ci],) for r in cand_rows if ci < len(r)])
    else:
        # 连续列窗口
        for start in range(0, max(1, width - ncol + 1)):
            cols = list(range(start, start + ncol))
            if cols[-1] < width:
                variants.append([tuple(r[ci] for ci in cols) for r in cand_rows if cols[-1] < len(r)])
        if width == ncol:
            variants.append([tuple(r) for r in cand_rows])
    return variants


def score_task(task_id: str, runs_dir: Path) -> dict:
    res_path = runs_dir / task_id / "result.json"
    if not res_path.exists():
        return {"task_id": task_id, "status": "no_run", "f1": 0.0}
    result = json.loads(res_path.read_text(encoding="utf-8"))
    header, gold = load_gold(task_id)
    ncol = len(header)

    candidates = extract_candidates(result)
    best = {"f1": 0.0, "recall": 0.0, "precision": 0.0, "matched": 0,
            "gold_n": len(gold), "cand_n": 0}
    for cand in candidates:
        for proj in project_columns(cand, ncol):
            sc = compare_sets(gold, proj)
            if sc["f1"] > best["f1"]:
                best = sc

    # 单值 gold 兜底：值是否出现在答案文本里
    if len(gold) == 1 and ncol == 1 and best["f1"] < 0.99:
        gval = norm_cell(gold[0][0])
        ans_norm = result.get("answer", "").lower().replace(",", "")
        if gval and (gval in ans_norm):
            best = {"f1": 1.0, "recall": 1.0, "precision": 1.0, "matched": 1,
                    "gold_n": 1, "cand_n": 1, "via": "text_match"}

    passed = best["f1"] >= 0.99
    return {"task_id": task_id, "status": "pass" if passed else "fail",
            "ncol": ncol, "gold_rows": len(gold), **best}


if __name__ == "__main__":
    import sys
    runs = Path("/root/datamind/Data-Agent-Platform/eval/runs")
    tid = sys.argv[1] if len(sys.argv) > 1 else "task_2"
    print(json.dumps(score_task(tid, runs), ensure_ascii=False, indent=2))
