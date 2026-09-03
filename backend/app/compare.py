"""数据对比：两个数据集的结构差异 + 数值列统计差异 + 按键行级差异概览。"""
import pandas as pd

from .analysis import AnalysisError


def _kind(s: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "categorical"


def compare(df_a: pd.DataFrame, df_b: pd.DataFrame, name_a: str, name_b: str, key: str = "") -> dict:
    cols_a, cols_b = set(df_a.columns), set(df_b.columns)
    only_a = sorted(cols_a - cols_b)
    only_b = sorted(cols_b - cols_a)
    common = [c for c in df_a.columns if c in cols_b]

    retype = [c for c in common if _kind(df_a[c]) != _kind(df_b[c])]

    rows = [
        [f"仅 {name_a} 有列", len(only_a), ", ".join(map(str, only_a)) or "—"],
        [f"仅 {name_b} 有列", len(only_b), ", ".join(map(str, only_b)) or "—"],
        ["类型变化的列", len(retype), ", ".join(map(str, retype)) or "—"],
        ["行数", f"{len(df_a)} vs {len(df_b)}", f"差 {abs(len(df_a) - len(df_b))} 行"],
    ]

    # 共同数值列统计差异
    stat_rows = []
    for c in common:
        if _kind(df_a[c]) != "numeric" or _kind(df_b[c]) != "numeric":
            continue
        sa, sb = pd.to_numeric(df_a[c], errors="coerce"), pd.to_numeric(df_b[c], errors="coerce")
        stat_rows.append([
            str(c),
            round(float(sa.mean()), 4), round(float(sb.mean()), 4),
            round(float(sa.sum()), 4), round(float(sb.sum()), 4),
            round(float(sb.sum() - sa.sum()), 4),
        ])

    # 键级差异
    key_info = None
    if key:
        if key not in cols_a or key not in cols_b:
            raise AnalysisError(f"键列 [{key}] 必须在两个数据集中都存在")
        keys_a, keys_b = set(df_a[key].dropna()), set(df_b[key].dropna())
        key_info = {
            "only_in_a": len(keys_a - keys_b),
            "only_in_b": len(keys_b - keys_a),
            "matched": len(keys_a & keys_b),
        }
        rows.append([f"键 [{key}] 匹配", f"{key_info['matched']} 匹配",
                     f"仅A: {key_info['only_in_a']}，仅B: {key_info['only_in_b']}"])

    return {
        "columns": [
            {"name": "对比项", "numeric": False},
            {"name": "结果", "numeric": False},
            {"name": "明细", "numeric": False},
        ],
        "rows": rows,
        "stat_columns": [
            {"name": "共同数值列", "numeric": False},
            {"name": f"均值({name_a})", "numeric": True},
            {"name": f"均值({name_b})", "numeric": True},
            {"name": f"合计({name_a})", "numeric": True},
            {"name": f"合计({name_b})", "numeric": True},
            {"name": "合计差(B-A)", "numeric": True},
        ],
        "stat_rows": stat_rows,
        "key": key,
        "note": f"对比 {name_a} vs {name_b}：{len(common)} 个共同列" + (f"，键 [{key}] 匹配 {key_info['matched']} 行" if key else ""),
    }


def sample_create(df: pd.DataFrame, method: str, n: int, by: str = "", seed: int = 42) -> pd.DataFrame:
    """采样：随机 / 分层 / 前 N 行。返回采样后的 df。"""
    n = max(1, int(n))
    if method == "top":
        return df.head(n)
    if method == "random":
        if n >= len(df):
            return df
        return df.sample(n=n, random_state=seed).reset_index(drop=True)
    if method == "stratified":
        if not by:
            raise AnalysisError("分层采样需要指定分层列")
        if by not in df.columns:
            raise AnalysisError(f"列不存在: {by}")
        # 显式按组采样后拼接（不用 groupby.apply：pandas3 默认丢弃分组列）
        picked = []
        for _, g in df.groupby(by, dropna=False, sort=False):
            picked.append(g.sample(n=min(n, len(g)), random_state=seed))
        out = pd.concat(picked).reset_index(drop=True)
        return out
    raise AnalysisError("method 仅支持 random / stratified / top")
