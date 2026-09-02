"""列画像：每列的类型、缺失情况、统计量、高频值。"""
import math

import pandas as pd


def _f(x):
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        return None if math.isinf(v) else round(v, 6)
    except (TypeError, ValueError):
        return None


def classify(dtype) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_numeric_dtype(dtype):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    return "categorical"


def profile_columns(df: pd.DataFrame) -> list:
    n = len(df)
    out = []
    for col in df.columns:
        s = df[col]
        na = int(s.isna().sum()) if n else 0
        info = {
            "name": str(col),
            "dtype": str(s.dtype),
            "kind": classify(s.dtype),
            "count": n,
            "missing": na,
            "missing_pct": round(na / n * 100, 2) if n else 0.0,
            "nunique": int(s.nunique(dropna=True)) if n else 0,
        }
        try:
            if info["kind"] == "numeric":
                desc = s.describe()
                info.update(
                    min=_f(desc.get("min")),
                    max=_f(desc.get("max")),
                    mean=_f(desc.get("mean")),
                    median=_f(desc.get("50%")),
                    std=_f(desc.get("std")),
                    p25=_f(desc.get("25%")),
                    p75=_f(desc.get("75%")),
                )
            elif info["kind"] == "datetime":
                info.update(min=str(s.min()), max=str(s.max()))
            elif info["kind"] in ("categorical", "boolean"):
                vc = s.value_counts(dropna=True).head(5)
                info["top_values"] = [{"value": str(k), "count": int(v)} for k, v in vc.items()]
        except (TypeError, ValueError):
            pass
        out.append(info)
    return out
