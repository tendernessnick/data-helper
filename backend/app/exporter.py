"""导出数据为 CSV / XLSX 文件。"""
import unicodedata
from pathlib import Path

import pandas as pd

from .paths import EXPORT_DIR


def _safe_name(name: str) -> str:
    # 去掉 Windows 文件名非法字符
    bad = '<>:"/\\|?*'
    name = "".join("-" if ch in bad else ch for ch in (name or "数据"))
    name = name.strip().rstrip(".")[:60] or "数据"
    return name


def export_df(df: pd.DataFrame, filename: str, fmt: str) -> Path:
    fmt = fmt.lower()
    stem = _safe_name(filename)
    if fmt == "csv":
        path = EXPORT_DIR / f"{stem}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
    elif fmt == "xlsx":
        path = EXPORT_DIR / f"{stem}.xlsx"
        df.to_excel(path, index=False)
    else:
        raise ValueError(f"不支持的导出格式: {fmt}（可选 csv / xlsx）")
    return path


def export_table(columns: list, rows: list, filename: str, fmt: str) -> Path:
    """导出分析结果表（columns: [名称], rows: [[...]]）。dict 单元格（如预测区间）展平为可读文本。"""
    flat = [
        [
            "{value}(下限{lower}~上限{upper})".format(**v) if isinstance(v, dict) and "value" in v else v
            for v in row
        ]
        for row in rows
    ]
    df = pd.DataFrame(flat, columns=[c["name"] if isinstance(c, dict) else c for c in columns])
    return export_df(df, filename, fmt)
