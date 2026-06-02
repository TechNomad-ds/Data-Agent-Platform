"""公共文件加载工具 — 统一 DataFrame 加载逻辑，避免各模块重复实现"""
import json
from pathlib import Path

import pandas as pd


def load_dataframe(file_path: Path, ext: str) -> pd.DataFrame:
    """根据文件扩展名加载为 pandas DataFrame"""
    if ext == "csv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
        return pd.read_csv(file_path, encoding=encoding, on_bad_lines="skip")
    elif ext == "tsv":
        from app.services.preprocessing import _detect_encoding
        encoding = _detect_encoding(file_path)
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
