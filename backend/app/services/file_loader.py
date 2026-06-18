"""公共文件加载工具 — 统一 DataFrame 加载逻辑，避免各模块重复实现"""
import json
import re
from pathlib import Path

import pandas as pd


def detect_encoding(file_path: Path) -> str:
    """Detect text encoding without importing the heavy preprocessing module."""
    try:
        import chardet
        raw = file_path.read_bytes()[:10000]
        result = chardet.detect(raw)
        return result.get("encoding", "utf-8") or "utf-8"
    except ImportError:
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1", "shift_jis"):
            try:
                file_path.read_text(encoding=enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "utf-8"


def safe_table_name(value: str, fallback: str = "table") -> str:
    """Return a SQLite/Python friendly table suffix."""
    name = re.sub(r"\W+", "_", value.lower()).strip("_")
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def load_dataframe(file_path: Path, ext: str) -> pd.DataFrame:
    """根据文件扩展名加载为 pandas DataFrame"""
    if ext == "csv":
        encoding = detect_encoding(file_path)
        return pd.read_csv(file_path, encoding=encoding, on_bad_lines="skip")
    elif ext == "tsv":
        encoding = detect_encoding(file_path)
        return pd.read_csv(file_path, sep="\t", encoding=encoding, on_bad_lines="skip")
    elif ext in ("xlsx", "xls"):
        return pd.read_excel(file_path)
    elif ext == "parquet":
        try:
            return pd.read_parquet(file_path)
        except ImportError:
            try:
                return pd.read_parquet(file_path, engine="fastparquet")
            except ImportError:
                return pd.DataFrame()
    elif ext == "feather":
        try:
            return pd.read_feather(file_path)
        except ImportError:
            return pd.DataFrame()
    elif ext == "json":
        return _load_json(file_path)
    elif ext == "jsonl":
        return pd.read_json(file_path, lines=True)
    elif ext == "dta":
        return pd.read_stata(file_path)
    elif ext == "sav":
        try:
            return pd.read_spss(file_path)
        except ImportError:
            return pd.DataFrame()
    elif ext == "sas7bdat":
        return pd.read_sas(file_path)
    return pd.DataFrame()


def load_excel_sheets(file_path: Path, nrows: int | None = None) -> dict[str, pd.DataFrame]:
    """Load every worksheet in an Excel workbook.

    pandas defaults to the first sheet, which hid data from users who uploaded
    multi-sheet course workbooks. This helper makes that behavior explicit and
    reusable across SQL, inspect/read_file and sandbox preload paths.
    """
    excel = pd.ExcelFile(file_path)
    sheets: dict[str, pd.DataFrame] = {}
    for sheet_name in excel.sheet_names:
        try:
            df = pd.read_excel(excel, sheet_name=sheet_name, nrows=nrows)
        except Exception:
            continue
        sheets[str(sheet_name)] = df
    return sheets


def iter_named_dataframes(
    file_path: Path,
    ext: str,
    *,
    base_name: str | None = None,
    nrows: int | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    """Return one or more named DataFrames for a file.

    Excel workbooks produce one DataFrame per sheet. Other tabular files produce
    a single DataFrame named after the file stem/base_name.
    """
    base = safe_table_name(base_name or file_path.stem, "data")
    if ext in ("xlsx", "xls"):
        frames: list[tuple[str, pd.DataFrame]] = []
        for sheet_name, df in load_excel_sheets(file_path, nrows=nrows).items():
            sheet = safe_table_name(sheet_name, "sheet")
            table_name = base if len(frames) == 0 and sheet in ("sheet1", "sheet") else f"{base}__{sheet}"
            frames.append((table_name, df))
        return frames

    df = load_dataframe(file_path, ext)
    if nrows is not None:
        df = df.head(nrows)
    return [(base, df)]


def _load_json(file_path: Path) -> pd.DataFrame:
    content = file_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return pd.DataFrame(data)
    elif isinstance(data, dict) and "records" in data:
        return pd.DataFrame(data["records"])
    elif isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()
