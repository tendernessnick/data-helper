"""把 pandas 单元格值转换为可 JSON 序列化的原生类型。"""
import math
from datetime import datetime

import numpy as np
import pandas as pd


def cell(v):
    if isinstance(v, (str, bool, int)):
        return v
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isinf(f) else f
    if isinstance(v, (pd.Timestamp, datetime, np.datetime64)):
        return str(v)
    return str(v)


def rows_payload(df: pd.DataFrame, page: int, page_size: int) -> dict:
    total = len(df)
    start = (page - 1) * page_size
    part = df.iloc[start : start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        "rows": [[cell(v) for v in row] for row in part.itertuples(index=False, name=None)],
    }
