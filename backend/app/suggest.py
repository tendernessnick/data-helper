"""自动图表推荐（Tableau "Show Me" 思路）：根据列类型组合推荐一键可视化。"""
import pandas as pd

from .analysis import _resample_series, outlier_bounds


def _num_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def _cat_cols(df):
    return [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])]


def _date_col(df):
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
    for c in _cat_cols(df):
        s = pd.to_datetime(df[c], errors="coerce")
        if s.notna().mean() > 0.8 and s.nunique() > 3:
            return c
    return ""


def suggest(df: pd.DataFrame) -> list:
    n = len(df)
    if n == 0:
        return []
    nums, cats, date = _num_cols(df), _cat_cols(df), _date_col(df)
    out = []

    # 1) 时间趋势：日期 × 首个数值
    if date and nums:
        out.append({"title": f"{nums[0]} 时间趋势", "kind": "trend",
                    "params": {"date_column": date, "value_column": nums[0], "freq": "M"}})
        out.append({"title": f"{nums[0]} 环比/同比", "kind": "growth",
                    "params": {"date_column": date, "value_column": nums[0], "freq": "M"}})

    # 2) 首个类别 × 首个数值：柱状 / 饼
    if cats and nums:
        out.append({"title": f"各{cats[0]}的{nums[0]}（柱）", "kind": "groupby",
                    "params": {"by": [cats[0]], "metrics": [{"column": nums[0], "agg": "sum"}]}})
        if df[cats[0]].nunique() <= 12:
            out.append({"title": f"{cats[0]} 占比（饼）", "kind": "value_counts",
                        "params": {"column": cats[0], "top": 10}})

    # 3) 前两个数值列：散点（含相关性）
    if len(nums) >= 2:
        out.append({"title": f"{nums[0]} × {nums[1]} 散点", "kind": "scatter",
                    "params": {"x": nums[0], "y": nums[1]}})

    # 4) 首个数值：直方图 + 箱线 + 异常
    if nums:
        out.append({"title": f"{nums[0]} 分布", "kind": "histogram", "params": {"column": nums[0], "bins": 20}})
        s = pd.to_numeric(df[nums[0]], errors="coerce")
        _, _, mask = outlier_bounds(s)
        if int(mask.sum()) > 0:
            out.append({"title": f"{nums[0]} 异常值({int(mask.sum())})", "kind": "boxplot",
                        "params": {"columns": nums[:6]}})

    # 5) 两个类别：热力图（交叉计数）
    if len(cats) >= 2 and df[cats[0]].nunique() <= 30 and df[cats[1]].nunique() <= 30:
        out.append({"title": f"{cats[0]} × {cats[1]} 热力", "kind": "cross_heat",
                    "params": {"row": cats[0], "col": cats[1]}})

    # 6) 多数值列：相关性
    if len(nums) >= 3:
        out.append({"title": "相关性热力图", "kind": "corr", "params": {}})

    return out[:10]


def cross_heat(df: pd.DataFrame, params: dict) -> dict:
    """两类别列交叉计数热力图。"""
    row_c, col_c = params.get("row", ""), params.get("col", "")
    for c in (row_c, col_c):
        if c not in df.columns:
            raise AnalysisError(f"列不存在: {c}")
    table = pd.crosstab(df[row_c], df[col_c])
    return {
        "columns": [{"name": str(row_c), "numeric": False}] + [{"name": str(c), "numeric": True} for c in table.columns],
        "rows": [[str(i)] + [int(v) for v in row] for row, i in zip(table.values, table.index)],
        "heatmap": {"rows": [str(i) for i in table.index], "cols": [str(c) for c in table.columns],
                     "values": table.values.tolist()},
        "matrix": {"columns": [str(c) for c in table.columns],
                    "values": [[int(v) for v in row] for row in table.values]},
        "matrix_rows": [str(i) for i in table.index],
        "note": f"{row_c} × {col_c} 交叉计数热力图",
    }
