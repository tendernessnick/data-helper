"""快速统计：描述统计 / 分组聚合 / 相关性 / 直方图 / 箱线图 / 频次 / 时间趋势 / 异常值 / KPI / 漏斗。

统一返回 {"columns": [...], "rows": [[...]], "kind": ...} 结构（kpi/funnel 为运营看板专用结构），
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
    top = params.get("top")  # 只返回前 N 组（AI 工具对高基数列防爆炸；界面路径不传保持全量）
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
    if top:
        try:
            grouped = grouped.head(max(1, int(top)))
        except (TypeError, ValueError):
            pass
    table = _to_table(grouped)
    table["note"] = f"按 {', '.join(map(str, by))} 分组聚合" + (f"（前 {int(top)} 组）" if top else "")
    table["chart"] = {"type": "bar", "label_col": by[0]}
    return table


def corr(df: pd.DataFrame, params: dict) -> dict:
    cols = params.get("columns")
    method = params.get("method", "pearson")
    if method not in ("pearson", "spearman", "kendall"):
        raise AnalysisError("method 仅支持 pearson / spearman / kendall")
    num = cols if cols else _num_cols(df)
    for c in num:
        _check(df, c)
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise AnalysisError(f"列 [{c}] 不是数值列，无法计算相关性")
    if len(num) < 2:
        raise AnalysisError("至少需要两个数值列")
    matrix = df[num].corr(method=method).round(4)
    table = _to_table(matrix)
    table["note"] = {"pearson": "Pearson 相关系数矩阵（-1 ~ 1）", "spearman": "Spearman 秩相关矩阵（单调，抗离群）",
                     "kendall": "Kendall Tau 秩相关矩阵（小样本稳健）"}[method]
    table["matrix"] = {
        "columns": list(matrix.columns),
        "values": [[None if pd.isna(v) else round(float(v), 4) for v in row]
                   for row in matrix.itertuples(index=False, name=None)],
    }
    table["method"] = method
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


def outlier_bounds(s: pd.Series, method: str = "iqr", k: float = 3.0):
    """返回 (下界, 上界, 离群布尔掩码)；s 需为数值列。"""
    s2 = s.dropna()
    if s2.empty:
        return None, None, pd.Series(False, index=s.index)
    if method == "zscore":
        mean, std = float(s2.mean()), float(s2.std(ddof=0))
        if std == 0:
            return None, None, pd.Series(False, index=s.index)
        z = (s - mean).abs() / std
        return None, None, z > k
    q1, q3 = s2.quantile([0.25, 0.75])
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return lower, upper, (s < lower) | (s > upper)


def outliers(df: pd.DataFrame, params: dict) -> dict:
    """异常值统计（IQR / Z-score）。"""
    cols = params.get("columns") or _num_cols(df)
    method = params.get("method", "iqr")
    if method not in ("iqr", "zscore"):
        raise AnalysisError("method 仅支持 iqr / zscore")
    if not cols:
        raise AnalysisError("没有数值列")
    rows_out = []
    for c in cols:
        _check(df, c)
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        lower, upper, mask = outlier_bounds(df[c], method)
        n = int(mask.sum())
        rows_out.append(
            [
                str(c),
                None if lower is None else round(float(lower), 6),
                None if upper is None else round(float(upper), 6),
                n,
                round(n / max(len(df), 1) * 100, 2),
                round(float(df[c].min()), 6),
                round(float(df[c].max()), 6),
            ]
        )
    if not rows_out:
        raise AnalysisError("所选列均无数值数据")
    return {
        "columns": [
            {"name": "列", "numeric": False},
            {"name": "下界", "numeric": True},
            {"name": "上界", "numeric": True},
            {"name": "离群数", "numeric": True},
            {"name": "离群占比%", "numeric": True},
            {"name": "最小值", "numeric": True},
            {"name": "最大值", "numeric": True},
        ],
        "rows": rows_out,
        "note": f"异常值检测（{ 'IQR 1.5倍四分位距' if method == 'iqr' else 'Z-score |z|>3' }）；可在清洗中用「剔除异常值」一键处理",
    }


def value_counts(df: pd.DataFrame, params: dict) -> dict:
    column = params.get("column")
    top = int(params.get("top", 20))
    _check(df, column)
    # 缺失行不进值列表：前端筛选用 __NULL__ 哨兵单独表达缺失，混进来会变成假的 "nan" 取值
    vc = df[column].value_counts(dropna=True).head(max(1, top))
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


KPI_AGGS = ("sum", "mean", "count")


def kpi(df: pd.DataFrame, params: dict) -> dict:
    """KPI 指标卡：数值列聚合为大数字；有日期列时按「后半段 vs 前等长段」给环比。"""
    agg = params.get("agg", "sum")
    if agg not in KPI_AGGS:
        raise AnalysisError(f"不支持的聚合方式: {agg}，可选: {', '.join(KPI_AGGS)}")
    value_col = params.get("value_column", "")
    if agg == "count":
        value, label = int(len(df)), "行数"
    else:
        _check(df, value_col)
        s = pd.to_numeric(df[value_col], errors="coerce")
        value = float(s.mean()) if agg == "mean" else float(s.sum())
        value = round(value, 4)
        label = str(value_col)
    result = {"kind": "kpi", "column": label, "agg": agg, "value": value}

    date_col = (params.get("date_column") or "").strip()
    if date_col and date_col in df.columns and agg != "count":
        d = pd.to_datetime(df[date_col], errors="coerce")
        valid = d.notna()
        if int(valid.sum()) >= 2:
            dmin, dmax = d[valid].min(), d[valid].max()
            span = (dmax - dmin).days + 1
            half = span // 2
            if half >= 1 and span >= 2:
                cur_start = dmax - pd.Timedelta(days=half - 1)
                prev_start = cur_start - pd.Timedelta(days=half)
                cur_mask = valid & (d >= cur_start)
                prev_mask = valid & (d >= prev_start) & (d < cur_start)
                s_all = pd.to_numeric(df[value_col], errors="coerce")
                cur_v = float(s_all[cur_mask].sum() if agg == "sum" else s_all[cur_mask].mean())
                prev_v = float(s_all[prev_mask].sum() if agg == "sum" else s_all[prev_mask].mean())
                # 口径说明写清期初日；大数字即当期值（运营语境：最新周期 + 环比）
                note = f"近{half}天（{cur_start:%m-%d} 起）vs 前{half}天"
                delta = round((cur_v - prev_v) / abs(prev_v) * 100, 1) if prev_v not in (0, 0.0) else None
                result.update({
                    "value": round(cur_v, 4),
                    "prev": round(prev_v, 4),
                    "delta_pct": delta,
                    "span_note": note,
                })
    return result


def funnel(df: pd.DataFrame, params: dict) -> dict:
    """轻量漏斗：events 模式按步骤列取值计数（可按用户列去重），columns 模式每列非空即达成。"""
    mode = params.get("mode", "events")
    if mode == "columns":
        cols = [c for c in (params.get("columns") or []) if c]
        if len(cols) < 2:
            raise AnalysisError("columns 模式需按顺序提供至少 2 个步骤列")
        names = []
        counts = []
        for c in cols:
            _check(df, c)
            names.append(str(c))
            counts.append(int(df[c].notna().sum()))
        note = "每列非空视为达成该步骤"
    else:
        col = params.get("column")
        steps = [s for s in (params.get("steps") or []) if s]
        if len(steps) < 2:
            raise AnalysisError("请按顺序提供至少 2 个步骤")
        _check(df, col)
        base = df[df[col].isin(steps)]
        user_col = (params.get("user_column") or "").strip()
        if user_col:
            _check(df, user_col)
            grp = base.groupby(col)[user_col].nunique()
            counts = [int(grp.get(s, 0)) for s in steps]
            note = f"按 {user_col} 去重人数"
        else:
            vc = base[col].value_counts()
            counts = [int(vc.get(s, 0)) for s in steps]
            note = "按行数统计（提供用户列可去重）"
        names = [str(s) for s in steps]

    steps_out = []
    prev = None
    for name, c in zip(names, counts):
        conv = None if prev is None or prev == 0 else round(c / prev * 100, 1)
        steps_out.append({"name": name, "count": c, "conv_from_prev": conv})
        prev = c
    return {"kind": "funnel", "steps": steps_out, "total": int(counts[0]) if counts else 0, "note": note}


KINDS = {
    "describe": describe,
    "groupby": groupby,
    "corr": corr,
    "histogram": histogram,
    "boxplot": boxplot,
    "value_counts": value_counts,
    "trend": trend,
    "outliers": outliers,
    "kpi": kpi,
    "funnel": funnel,
}


def run(df: pd.DataFrame, kind: str, params: dict) -> dict:
    if kind not in KINDS:
        raise AnalysisError(f"未知分析类型: {kind}，可选: {', '.join(KINDS)}")
    return KINDS[kind](df, params or {})
