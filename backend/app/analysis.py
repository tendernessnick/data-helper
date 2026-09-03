"""统计分析：描述统计 / 分组聚合 / 透视表 / 相关性 / 直方图 / 箱线图。

统一返回 {"columns": [...], "rows": [[...]], "kind": ...} 结构，
前端据此渲染表格与图表。
"""
import numpy as np
import pandas as pd


class AnalysisError(ValueError):
    pass


AGGS = ("count", "sum", "mean", "min", "max", "median", "std", "nunique", "first", "last")


def _check(df, column):
    if column not in df.columns:
        raise AnalysisError(f"列不存在: {column}")


def _num_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _to_table(df: pd.DataFrame) -> dict:
    """把结果 DataFrame 转成 JSON 表（含列名与行列数据）。"""
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [" / ".join(str(x) for x in tup) for tup in out.columns]
    if out.index.name or not isinstance(out.index, pd.RangeIndex):
        out = out.reset_index()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].astype(str)
    from .serialize import cell

    return {
        "columns": [
            {"name": str(c), "dtype": str(out[c].dtype), "numeric": pd.api.types.is_numeric_dtype(out[c])}
            for c in out.columns
        ],
        "rows": [[cell(v) for v in row] for row in out.itertuples(index=False, name=None)],
    }


def describe(df: pd.DataFrame, params: dict) -> dict:
    cols = params.get("columns")
    for c in cols or []:
        _check(df, c)
    sub = df[cols] if cols else df
    desc = sub.describe(include="all")
    desc.index.name = desc.index.name or "统计量"
    table = _to_table(desc)
    table["note"] = "describe 汇总统计（count/mean/std/min/四分位/max 等）"
    return table


def groupby(df: pd.DataFrame, params: dict) -> dict:
    by = params.get("by") or []
    metrics = params.get("metrics") or []
    if isinstance(by, str):
        by = [by]
    if not by or not metrics:
        raise AnalysisError("需要至少一个分组列和一个聚合指标")
    for c in by:
        _check(df, c)
    agg_map = {}
    for m in metrics:
        col, agg = m.get("column"), m.get("agg")
        _check(df, col)
        if agg not in AGGS:
            raise AnalysisError(f"未知聚合方式 {agg}，可选: {', '.join(AGGS)}")
        agg_map.setdefault(col, []).append(agg)
    grouped = df.groupby(by, dropna=False).agg(agg_map)
    table = _to_table(grouped)
    table["note"] = f"按 {', '.join(map(str, by))} 分组聚合"
    table["chart"] = {"type": "bar", "label_col": by[0]}
    return table


def pivot(df: pd.DataFrame, params: dict) -> dict:
    index = params.get("index")
    columns = params.get("columns")
    values = params.get("values")
    aggfunc = params.get("aggfunc", "sum")
    for c in (index, columns, values):
        if c is not None:
            _check(df, c)
    if not index or not values:
        raise AnalysisError("透视表需要行维度(index)与数值列(values)")
    if aggfunc not in AGGS:
        raise AnalysisError(f"未知聚合方式 {aggfunc}")
    pt = pd.pivot_table(
        df, index=index, columns=columns, values=values, aggfunc=aggfunc, dropna=False
    )
    table = _to_table(pt)
    table["note"] = f"透视表: 行={index}" + (f" 列={columns}" if columns else "") + f" 值={values}({aggfunc})"
    return table


def corr(df: pd.DataFrame, params: dict) -> dict:
    cols = params.get("columns")
    num = cols if cols else _num_cols(df)
    for c in num:
        _check(df, c)
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise AnalysisError(f"列 [{c}] 不是数值列，无法计算相关性")
    if len(num) < 2:
        raise AnalysisError("至少需要两个数值列")
    matrix = df[num].corr(numeric_only=True).round(4)
    table = _to_table(matrix)
    table["note"] = "Pearson 相关系数矩阵（-1 ~ 1）"
    table["matrix"] = {
        "columns": list(matrix.columns),
        "values": [[None if pd.isna(v) else round(float(v), 4) for v in row]
                   for row in matrix.itertuples(index=False, name=None)],
    }
    return table


def histogram(df: pd.DataFrame, params: dict) -> dict:
    column = params.get("column")
    bins = int(params.get("bins", 20))
    _check(df, column)
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise AnalysisError(f"列 [{column}] 不是数值列")
    s = df[column].dropna()
    if s.empty:
        raise AnalysisError("该列没有有效数值")
    bins = max(2, min(bins, 200))
    counts, edges = np.histogram(s, bins=bins)
    labels = [f"{edges[i]:.4g}~{edges[i + 1]:.4g}" for i in range(len(counts))]
    return {
        "columns": [{"name": "区间", "numeric": False}, {"name": "频次", "numeric": True}],
        "rows": [[labels[i], int(counts[i])] for i in range(len(counts))],
        "note": f"{column} 分布直方图（{bins} 桶）",
        "chart": {"type": "bar", "label_col": "区间"},
    }


def boxplot(df: pd.DataFrame, params: dict) -> dict:
    cols = params.get("columns") or _num_cols(df)
    if not cols:
        raise AnalysisError("没有可用的数值列")
    stats = []
    for c in cols:
        _check(df, c)
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = df[c].dropna()
        if s.empty:
            continue
        q1, med, q3 = s.quantile([0.25, 0.5, 0.75])
        iqr = q3 - q1
        stats.append(
            {
                "name": str(c),
                "min": round(float(s.min()), 6),
                "q1": round(float(q1), 6),
                "median": round(float(med), 6),
                "q3": round(float(q3), 6),
                "max": round(float(s.max()), 6),
                "lower": round(float(q1 - 1.5 * iqr), 6),
                "upper": round(float(q3 + 1.5 * iqr), 6),
            }
        )
    if not stats:
        raise AnalysisError("所选列均无数值数据")
    return {"columns": [], "rows": [], "box_stats": stats, "note": "箱线图五数概括"}


FREQ_MAP = {"D": "D", "W": "W", "M": "MS", "Q": "QS", "Y": "YS"}
# 同比需要的周期数（上一个"同口径期间"距离当前多少个周期）
YOY_PERIODS = {"D": 365, "W": 52, "M": 12, "Q": 4, "Y": None}
FREQ_LABEL = {"D": "天", "W": "周", "M": "月", "Q": "季", "Y": "年"}


def _resample_series(df: pd.DataFrame, date_col: str, value_col: str, freq: str, agg: str):
    """按时间频率重采样为数值序列，返回 (期间标签列表, 数值Series)。"""
    _check(df, date_col)
    _check(df, value_col)
    if agg not in AGGS:
        raise AnalysisError(f"未知聚合方式 {agg}")
    s = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, errors="coerce")
    if s.isna().all():
        raise AnalysisError(f"列 [{date_col}] 无法解析为日期（可先在清洗中做类型转换）")
    tmp = pd.DataFrame({"日期": s, "值": pd.to_numeric(df[value_col], errors="coerce")}).dropna(subset=["日期"])
    if tmp.empty:
        raise AnalysisError("没有同时具备日期与数值的行")
    rule = FREQ_MAP.get(freq, "MS")
    series = tmp.set_index("日期").resample(rule)["值"].agg(agg).dropna()
    if series.empty:
        raise AnalysisError("重采样后没有数据")
    return series


def growth(df: pd.DataFrame, params: dict) -> dict:
    """同比/环比/累计分析。"""
    date_col = params.get("date_column", "")
    value_col = params.get("value_column", "")
    freq = params.get("freq", "M")
    agg = params.get("agg", "sum")
    series = _resample_series(df, date_col, value_col, freq, agg)
    freq_label = FREQ_LABEL.get(freq, freq)
    mom = (series.pct_change() * 100).round(2)
    yoy_periods = YOY_PERIODS.get(freq)
    yoy = (series.pct_change(periods=yoy_periods) * 100).round(2) if yoy_periods else pd.Series([None] * len(series), index=series.index)
    cum = series.cumsum().round(4)
    rows_out = []
    for idx, v in series.items():
        rows_out.append(
            [
                idx.strftime("%Y-%m-%d"),
                round(float(v), 4),
                None if pd.isna(mom.get(idx)) else float(mom.get(idx)),
                None if pd.isna(yoy.get(idx)) else float(yoy.get(idx)),
                round(float(cum.get(idx)), 4),
            ]
        )
    return {
        "columns": [
            {"name": "期间", "numeric": False},
            {"name": value_col, "numeric": True},
            {"name": "环比%", "numeric": True},
            {"name": "同比%", "numeric": True},
            {"name": "累计值", "numeric": True},
        ],
        "rows": rows_out,
        "note": f"{value_col} 按{freq_label}{agg}：环比/同比增长率与累计值（同比按{freq_label}对齐）",
        "chart": {"type": "line", "label_col": "期间"},
    }


def moving_avg(df: pd.DataFrame, params: dict) -> dict:
    """移动平均（滚动均值）平滑趋势。"""
    date_col = params.get("date_column", "")
    value_col = params.get("value_column", "")
    freq = params.get("freq", "M")
    agg = params.get("agg", "sum")
    window = int(params.get("window", 3))
    if window < 2:
        raise AnalysisError("窗口至少为 2")
    series = _resample_series(df, date_col, value_col, freq, agg)
    freq_label = FREQ_LABEL.get(freq, freq)
    ma = series.rolling(window=window, min_periods=1).mean().round(4)
    rows_out = []
    for idx, v in series.items():
        rows_out.append([idx.strftime("%Y-%m-%d"), round(float(v), 4), float(ma.get(idx))])
    return {
        "columns": [
            {"name": "期间", "numeric": False},
            {"name": value_col, "numeric": True},
            {"name": f"{window}期移动平均", "numeric": True},
        ],
        "rows": rows_out,
        "note": f"{value_col} 按{freq_label}{agg}的 {window} 期移动平均（平滑波动看趋势）",
        "chart": {"type": "line", "label_col": "期间"},
    }


def value_counts(df: pd.DataFrame, params: dict) -> dict:
    column = params.get("column")
    top = int(params.get("top", 20))
    _check(df, column)
    vc = df[column].value_counts(dropna=False).head(max(1, top))
    return {
        "columns": [{"name": str(column), "numeric": False}, {"name": "计数", "numeric": True}],
        "rows": [[str(k), int(v)] for k, v in vc.items()],
        "note": f"{column} 频次统计（Top {top}）",
        "chart": {"type": "pie", "label_col": str(column)},
    }


def trend(df: pd.DataFrame, params: dict) -> dict:
    """按时间列聚合数值列，得到趋势数据（折线图）。"""
    date_col = params.get("date_column", "")
    value_col = params.get("value_column", "")
    freq = params.get("freq", "M")  # D/W/M/Q/Y
    agg = params.get("agg", "sum")
    series = _resample_series(df, date_col, value_col, freq, agg)
    freq_label = FREQ_LABEL.get(freq, freq)
    return {
        "columns": [{"name": "日期", "numeric": False}, {"name": value_col, "numeric": True}],
        "rows": [[idx.strftime("%Y-%m-%d"), round(float(v), 4)] for idx, v in series.items()],
        "note": f"{value_col} 按{freq_label} {agg} 的趋势",
        "chart": {"type": "line", "label_col": "日期"},
    }


KINDS = {
    "describe": describe,
    "groupby": groupby,
    "pivot": pivot,
    "corr": corr,
    "histogram": histogram,
    "boxplot": boxplot,
    "value_counts": value_counts,
    "trend": trend,
    "growth": growth,
    "moving_avg": moving_avg,
}


def run(df: pd.DataFrame, kind: str, params: dict) -> dict:
    if kind not in KINDS:
        raise AnalysisError(f"未知分析类型: {kind}，可选: {', '.join(KINDS)}")
    return KINDS[kind](df, params or {})
