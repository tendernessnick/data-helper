"""统计检验套件（scipy）：正态性 / 组间比较 / 卡方 / 相关性检验。"""
import pandas as pd
from scipy import stats

from .cleaning import CleanError

ALPHA = 0.05


class TestError(ValueError):
    pass


def _desc_table(df: pd.DataFrame, group_col: str, value_col: str) -> list:
    g = df.groupby(group_col, dropna=False)[value_col]
    rows = []
    for name, s in g:
        rows.append([str(name), int(s.count()), round(float(s.mean()), 4), round(float(s.std()), 4),
                     round(float(s.median()), 4)])
    return rows


def _conclusion(p) -> dict:
    sig = p is not None and p == p and p < ALPHA
    return {
        "p": None if p is None or p != p else round(float(p), 6),
        "significant": bool(sig),
        "verdict": ("拒绝原假设（p < 0.05，差异/效应显著）" if sig else "不能拒绝原假设（p ≥ 0.05，无足够证据）"),
    }


def _num_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def _cat_cols(df):
    return [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]


def _clean_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").dropna()


def normality(df: pd.DataFrame, params: dict) -> dict:
    """正态性检验：Shapiro-Wilk（n≤5000）+ Jarque-Bera。"""
    column = params.get("column", "")
    if column not in df.columns:
        raise TestError(f"列不存在: {column}")
    if column not in _num_cols(df):
        raise TestError(f"列 [{column}] 不是数值列")
    s = _clean_series(df[column])
    if len(s) < 8:
        raise TestError("样本量过少（至少 8 个有效数值）")
    jb_stat, jb_p = stats.jarque_bera(s)
    out = {
        "column": str(column),
        "n": int(len(s)),
        "tests": [
            {"name": "Jarque-Bera", "stat": round(float(jb_stat), 4), **_conclusion(jb_p)},
        ],
        "desc": {"skew": round(float(s.skew()), 4), "kurt": round(float(s.kurt()), 4),
                  "mean": round(float(s.mean()), 4), "std": round(float(s.std()), 4)},
        "note": "原假设：数据来自正态分布。p<0.05 表示明显偏离正态。",
    }
    if len(s) <= 5000:
        sw_stat, sw_p = stats.shapiro(s)
        out["tests"].insert(0, {"name": "Shapiro-Wilk", "stat": round(float(sw_stat), 4), **_conclusion(sw_p)})
    return out


def _groups(df: pd.DataFrame, group_col: str, value_col: str, min_n: int = 3):
    tmp = df[[group_col, value_col]].dropna()
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
    tmp = tmp.dropna()
    return [ (str(k), v[value_col]) for k, v in tmp.groupby(group_col) if len(v) >= min_n ]


def compare_groups(df: pd.DataFrame, params: dict) -> dict:
    """组间比较：2 组用 t 检验（Welch）+ Mann-Whitney U；3+ 组用 ANOVA + Kruskal-Wallis。"""
    group_col = params.get("group_column", "")
    value_col = params.get("value_column", "")
    if group_col not in df.columns:
        raise TestError(f"列不存在: {group_col}")
    if value_col not in df.columns:
        raise TestError(f"列不存在: {value_col}")
    groups = _groups(df, group_col, value_col)
    if len(groups) < 2:
        raise TestError("有效分组不足 2 个（每组至少 3 个有效数值）")
    arrs = [s.values for _, s in groups]
    out = {
        "group_column": str(group_col),
        "value_column": str(value_col),
        "n_groups": len(groups),
        "desc_columns": ["分组", "样本数", "均值", "标准差", "中位数"],
        "desc": _desc_table(df, group_col, value_col),
        "note": "原假设：各组均值相同。",
        "tests": [],
    }
    if len(groups) == 2:
        t_stat, t_p = stats.ttest_ind(arrs[0], arrs[1], equal_var=False)
        out["tests"].append({"name": "Welch t 检验（两组均值）", "stat": round(float(t_stat), 4), **_conclusion(t_p)})
        u_stat, u_p = stats.mannwhitneyu(arrs[0], arrs[1], alternative="two-sided")
        out["tests"].append({"name": "Mann-Whitney U（非参数）", "stat": round(float(u_stat), 4), **_conclusion(u_p)})
        out["pair"] = [groups[0][0], groups[1][0]]
    else:
        f_stat, f_p = stats.f_oneway(*arrs)
        out["tests"].append({"name": "单因素方差分析 ANOVA", "stat": round(float(f_stat), 4), **_conclusion(f_p)})
        h_stat, h_p = stats.kruskal(*arrs)
        out["tests"].append({"name": "Kruskal-Wallis（非参数）", "stat": round(float(h_stat), 4), **_conclusion(h_p)})
        # 方差齐性
        try:
            w_stat, w_p = stats.levene(*arrs)
            out["tests"].append({"name": "Levene 方差齐性", "stat": round(float(w_stat), 4), **_conclusion(w_p)})
        except Exception:
            pass
    return out


def chi2_test(df: pd.DataFrame, params: dict) -> dict:
    """卡方独立性检验：两个类别列是否相关。"""
    a = params.get("column_a", "")
    b = params.get("column_b", "")
    max_cat = int(params.get("max_categories", 10))
    for c in (a, b):
        if c not in df.columns:
            raise TestError(f"列不存在: {c}")
        if c in _num_cols(df):
            raise TestError(f"列 [{c}] 是数值列，卡方检验需要类别列（可先在清洗中分箱）")
    tmp = df[[a, b]].dropna()
    # 类别过多时截取高频 Top N，其余合并为"其他"
    def _top(s):
        vc = s.value_counts()
        keep = vc.head(max_cat).index
        return s.where(s.isin(keep), "其他")
    table = pd.crosstab(_top(tmp[a]), _top(tmp[b]))
    if table.shape[0] < 2 or table.shape[1] < 2:
        raise TestError("交叉表至少需要 2×2 个类别")
    chi, p, dof, expected = stats.chi2_contingency(table)
    n = table.values.sum()
    cramers_v = (chi / (n * (min(table.shape) - 1))) ** 0.5 if min(table.shape) > 1 else 0.0
    return {
        "column_a": str(a), "column_b": str(b),
        "tests": [{"name": "卡方独立性检验", "stat": round(float(chi), 4), "dof": int(dof), **_conclusion(p)}],
        "cramers_v": round(float(cramers_v), 4),
        "contingency": {
            "row_labels": [str(i) for i in table.index],
            "col_labels": [str(c) for c in table.columns],
            "values": table.values.tolist(),
        },
        "note": "原假设：两列相互独立。Cramér's V 越接近 1 关联越强。",
    }


def corr_test(df: pd.DataFrame, params: dict) -> dict:
    """相关性显著性检验：Pearson / Spearman。"""
    x_col, y_col = params.get("column_x", ""), params.get("column_y", "")
    method = params.get("method", "pearson")
    for c in (x_col, y_col):
        if c not in df.columns:
            raise TestError(f"列不存在: {c}")
        if c not in _num_cols(df):
            raise TestError(f"列 [{c}] 不是数值列")
    tmp = df[[x_col, y_col]].replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(tmp) < 5:
        raise TestError("有效样本过少（至少 5 行）")
    if method == "spearman":
        r, p = stats.spearmanr(tmp[x_col], tmp[y_col])
    else:
        r, p = stats.pearsonr(tmp[x_col], tmp[y_col])
    return {
        "column_x": str(x_col), "column_y": str(y_col), "method": method,
        "n": int(len(tmp)),
        "tests": [{"name": f"{('Pearson' if method == 'pearson' else 'Spearman')} 相关性检验",
                    "stat": round(float(r), 4), **_conclusion(p)}],
        "note": "原假设：两列不相关。统计量即相关系数 r。",
    }


TESTS = {
    "normality": normality,
    "compare_groups": compare_groups,
    "chi2": chi2_test,
    "corr_test": corr_test,
}


def run_test(df: pd.DataFrame, test: str, params: dict) -> dict:
    if test not in TESTS:
        raise TestError(f"未知检验: {test}，可选: {', '.join(TESTS)}")
    return TESTS[test](df, params or {})
