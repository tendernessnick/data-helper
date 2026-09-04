"""导出数据为 CSV / XLSX 文件。"""
from pathlib import Path

import pandas as pd

from .paths import EXPORT_DIR


def _safe_name(name: str) -> str:
    # 去掉 Windows 文件名非法字符
    bad = '<>:"/\\|?*'
    name = "".join("-" if ch in bad else ch for ch in (name or "数据"))
    name = name.strip().rstrip(".")[:60] or "数据"
    return name


XLSX_MAX_ROWS = 1_048_575  # Excel 单表上限 1,048,576 行（含表头）


def export_df(df: pd.DataFrame, filename: str, fmt: str) -> Path:
    fmt = fmt.lower()
    stem = _safe_name(filename)
    if fmt == "csv":
        path = EXPORT_DIR / f"{stem}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
    elif fmt == "xlsx":
        if len(df) > XLSX_MAX_ROWS:
            raise ValueError(f"数据 {len(df)} 行超过 Excel 单表上限（1,048,576 行），请改用 CSV 导出")
        path = EXPORT_DIR / f"{stem}.xlsx"
        try:
            df.to_excel(path, index=False)
        except ImportError as e:  # 精简运行环境未装 openpyxl
            raise ValueError(f"Excel 导出需要 openpyxl 库：{e}（可先改用 CSV 导出）") from e
    else:
        raise ValueError(f"不支持的导出格式: {fmt}（可选 csv / xlsx）")
    return path


def export_table(columns: list, rows: list, filename: str, fmt: str) -> Path:
    """导出分析结果表（columns: [名称], rows: [[...]]）。dict 单元格（如预测区间）展平为可读文本。"""

    def _flat_cell(v):
        # 前端表格单元格可能是 dict（预测区间等）：缺 lower/upper 时用 .get 容错而非 KeyError
        if isinstance(v, dict):
            if "value" in v:
                lower, upper = v.get("lower"), v.get("upper")
                if lower is None and upper is None:
                    return v["value"]
                return f"{v['value']}(下限{lower}~上限{upper})"
            return str(v)
        return v

    flat = [[_flat_cell(v) for v in row] for row in rows]
    names = [c.get("name", f"列{i + 1}") if isinstance(c, dict) else c for i, c in enumerate(columns)]
    df = pd.DataFrame(flat, columns=names)
    return export_df(df, filename, fmt)
