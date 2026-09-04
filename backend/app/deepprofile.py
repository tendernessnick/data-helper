"""深度画像增强（对标 ydata-profiling）：
- 多方法相关性矩阵（Pearson / Spearman / Kendall Tau）
- 缺失值矩阵（按行分段 × 列，热力图用）
- 重复行明细
- 文本列长度统计
- 两列交互散点数据（降采样）
"""
import numpy as np
import pandas as pd

from .analysis import AnalysisError

BUCKETS = 40


def _num_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def corr_matrix(df: pd.DataFrame, method: str = "pearson") -> dict:
    if method not in ("pearson", "spearman", "kendall"):
        raise AnalysisError("method 仅支持 pearson / spearman / kendall")
    cols = _num_cols(df)
    if len(cols) < 2:
        raise AnalysisError("至少需要两个数值列")
    matrix = df[cols].corr(method=method).round(4)
    return {
        "method": method,
        "columns": [str(c) for c in matrix.columns],
        "values": [[None if pd.isna(v) else round(float(v), 4) for v in row]
                   for row in matrix.itertuples(index=False, name=None)],
        # 前端热力图渲染依赖 matrix 结构（与 analysis.corr 输出保持一致）
        "matrix": {
            "columns": [str(c) for c in matrix.columns],
            "values": [[None if pd.isna(v) else round(float(v), 4) for v in row]
                       for row in matrix.itertuples(index=False, name=None)],
        },
        "note": {"pearson": "Pearson 线性相关", "spearman": "Spearman 秩相关（单调，抗离群）",
                  "kendall": "Kendall Tau 秩相关（小样本稳健）"}[method],
    }


def missing_matrix(df: pd.DataFrame) -> dict:
    """行按 BUCKETS 分段，输出每段每列的缺失率（%），供热力图。"""
    n = len(df)
    labels = df.columns.astype(str).tolist()
    if n == 0:
        raise AnalysisError("数据为空")
    seg = min(BUCKETS, n)
    bucket_id = np.linspace(0, seg, num=n, endpoint=False).astype(int)
    values = []
    for b in range(seg):
        part = df[bucket_id == b]
        values.append([round(float(part[c].isna().mean() * 100), 2) for c in df.columns])
    return {
        "columns": labels,
        "row_labels": [f"{int(i * n / seg) + 1}-{int((i + 1) * n / seg)}" for i in range(seg)],
        "values": values,
        "note": "缺失值矩阵：每一行是数据的 1/40 分段，颜色越深缺失越多（定位缺失集中的区域）",
    }


def duplicates_detail(df: pd.DataFrame, max_rows: int = 100) -> dict:
    dup_mask = df.duplicated(keep=False)
    dup_df = df[dup_mask]
    groups = int(len(dup_df) - int(df.duplicated().sum())) if len(dup_df) else 0  # 重复组数（近似）
    from .serialize import cell
    rows = [[cell(v) for v in row] for row in dup_df.head(max_rows).itertuples(index=False, name=None)]
    return {
        "total_dup_rows": int(len(dup_df)),
        "total_extra": int(df.duplicated().sum()),
        "groups": groups,
        "columns": [{"name": str(c), "numeric": pd.api.types.is_numeric_dtype(df[c])} for c in df.columns],
        "rows": rows,
        "note": f"共 {len(dup_df)} 行参与重复（含 {df.duplicated().sum()} 行冗余），显示前 {min(max_rows, len(dup_df))} 行",
    }


def text_stats(df: pd.DataFrame) -> list:
    """文本列长度统计：最短/最长/平均/空串数。"""
    out = []
    for c in df.columns:
        s = df[c]
        if not (pd.api.types.is_object_dtype(s) or str(s.dtype) == "str"):
            continue
        sv = s.dropna().astype(str)
        if sv.empty:
            continue
        lens = sv.str.len()
        out.append({
            "name": str(c),
            "min_len": int(lens.min()),
            "max_len": int(lens.max()),
            "mean_len": round(float(lens.mean()), 1),
            "empty": int((sv.str.strip() == "").sum()),
            "with_space": int((sv != sv.str.strip()).sum()),
        })
    return out


def interactions(df: pd.DataFrame, x: str, y: str, max_points: int = 1000) -> dict:
    """两数值列散点数据（简单等距降采样）。"""
    for c in (x, y):
        if c not in df.columns:
            raise AnalysisError(f"列不存在: {c}")
        if c not in _num_cols(df):
            raise AnalysisError(f"列 [{c}] 不是数值列")
    tmp = df[[x, y]].replace([float("inf"), float("-inf")], float("nan")).dropna()
    if tmp.empty:
        raise AnalysisError("没有同时有效的两列数值")
    if len(tmp) > max_points:
        step = max(1, len(tmp) // max_points)
        tmp = tmp.iloc[::step]
    spearman = float(tmp[x].corr(tmp[y], method="spearman")) if len(tmp) > 2 else None
    return {
        "x": str(x), "y": str(y),
        "points": [[round(float(a), 6), round(float(b), 6)] for a, b in
                   tmp.itertuples(index=False, name=None)],
        "spearman": None if spearman is None else round(spearman, 4),
        "total_sampled": int(len(tmp)),
        "note": f"{x} × {y} 交互散点（采样 {len(tmp)} 点，Spearman ρ={round(spearman, 3) if spearman is not None else '—'}）",
    }
