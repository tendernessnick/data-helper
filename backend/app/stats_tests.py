"""统计检验套件（scipy）：正态性 / 组间比较 / 卡方 / 相关性检验 / A-B 实验方法。"""
import math

import pandas as pd
from scipy import stats

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
        "desc_columns": ["统计量", "值"],
        "desc": [
            ["样本数", int(len(s))],
            ["均值", round(float(s.mean()), 4)],
            ["标准差", round(float(s.std()), 4)],
            ["偏度", round(float(s.skew()), 4)],
            ["峰度", round(float(s.kurt()), 4)],
        ],
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
        d = cohens_d(arrs[0], arrs[1])
        out["effect_size"] = d
        out["tests"].append({"name": "Cohen's d 效应量", "stat": round(d, 4), **_effect_verdict(abs(d))})
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


# ---------------- A/B 实验方法 ----------------


def _z_crit(two_sided: bool, alpha: float) -> float:
    """标准正态分位数。"""
    return float(stats.norm.ppf(1 - alpha / (2 if two_sided else 1)))


def cohens_d(a, b) -> float:
    """Cohen's d：合并标准差标准化均值差。"""
    n1, n2 = len(a), len(b)
    s2 = ((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / max(n1 + n2 - 2, 1)
    if s2 <= 0:
        return 0.0
    return float((a.mean() - b.mean()) / math.sqrt(s2))


def _effect_verdict(v: float) -> dict:
    """效应量分级（Cohen 惯例：0.2 小 / 0.5 中 / 0.8 大）。"""
    level = "可忽略"
    for t, name in ((0.8, "大"), (0.5, "中"), (0.2, "小")):
        if v >= t:
            level = name
            break
    return {"p": None, "significant": None, "verdict": f"效应量：{level}（0.2 小 / 0.5 中 / 0.8 大）"}


def _prop_stats(successes: float, n: float) -> float:
    return float(successes) / float(n) if n else 0.0


def _success_flag(s: pd.Series, success_value) -> pd.Series:
    """转化判定：数值列按数值比较，文本列按精确匹配；NaN 保持缺失以便剔除。"""
    if pd.api.types.is_numeric_dtype(s):
        try:
            return pd.to_numeric(s, errors="coerce") == float(success_value)
        except (TypeError, ValueError):
            raise TestError("success_value 应为数值（转化列是数值列）")
    return s.astype(str).str.strip() == str(success_value)


def prop_z_test(df: pd.DataFrame | None, params: dict) -> dict:
    """两比例 z 检验（A/B 转化率场景）。

    两种输入：
    - 数据集模式：group_column（实验组标记列）+ success_column（转化事件列）+ success_value（转化取值）
    - 直接计数模式：success_a / n_a / success_b / n_b
    输出转化率、差值、相对提升、z 统计量、p 值与差值的置信区间。
    """
    if df is None or "success_a" in params:
        sa = float(params.get("success_a", 0))
        na = float(params.get("n_a", 0))
        sb = float(params.get("success_b", 0))
        nb = float(params.get("n_b", 0))
        if min(sa, na, sb, nb) < 0 or sa > na or sb > nb:
            raise TestError("成功数不能为负且不能超过总数")
        if na <= 0 or nb <= 0:
            raise TestError("两组样本数都必须大于 0")
        label_a, label_b = "A 组", "B 组"
    else:
        group_col = params.get("group_column", "")
        success_col = params.get("success_column", "")
        success_value = params.get("success_value", "")
        if group_col not in df.columns:
            raise TestError(f"列不存在: {group_col}")
        if success_col not in df.columns:
            raise TestError(f"列不存在: {success_col}（需要提供转化事件列）")
        tmp = df[[group_col]].dropna().astype(str)
        levels = tmp[group_col].value_counts()
        if len(levels) != 2:
            raise TestError(f"分组列需要恰好 2 个取值（当前 {len(levels)} 个：{', '.join(map(str, levels.index[:5]))}）")
        g_a, g_b = levels.index.tolist()
        sub = pd.DataFrame({
            "g": df[group_col].astype(str),
            "hit": _success_flag(df[success_col], success_value),
        }).dropna()
        na = int((sub["g"] == g_a).sum())
        nb = int((sub["g"] == g_b).sum())
        sa = int(sub.loc[sub["g"] == g_a, "hit"].sum())
        sb = int(sub.loc[sub["g"] == g_b, "hit"].sum())
        label_a, label_b = str(g_a), str(g_b)
        if min(na, nb) == 0:
            raise TestError("两组样本数都必须大于 0")

    pa, pb = _prop_stats(sa, na), _prop_stats(sb, nb)
    diff = pb - pa
    pooled = (sa + sb) / (na + nb)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / na + 1 / nb))
    if se_pooled == 0:
        raise TestError("两组转化率均为 0 或 1，无法检验")
    z = diff / se_pooled
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    # 差值置信区间用非合并标准误（更保守、惯例做法）
    se_diff = math.sqrt(pa * (1 - pa) / na + pb * (1 - pb) / nb)
    zc = _z_crit(True, float(params.get("alpha", ALPHA)))
    lo, hi = diff - zc * se_diff, diff + zc * se_diff
    rel = diff / pa if pa > 0 else None
    return {
        "tests": [{"name": "两比例 z 检验", "stat": round(float(z), 4), **_conclusion(float(p))}],
        "desc_columns": ["组", "样本数", "转化数", "转化率"],
        "desc": [
            [label_a, int(na), int(sa), f"{pa * 100:.2f}%"],
            [label_b, int(nb), int(sb), f"{pb * 100:.2f}%"],
        ],
        "rate_a": round(pa, 6), "rate_b": round(pb, 6),
        "diff": round(diff, 6),
        "diff_ci95": [round(lo, 6), round(hi, 6)],
        "relative_lift": None if rel is None else round(rel, 6),
        "note": (
            f"转化率 {label_a} {pa * 100:.2f}% → {label_b} {pb * 100:.2f}%，"
            f"绝对差 {(diff * 100):+.2f}pp" + (f"，相对提升 {(rel * 100):+.1f}%" if rel is not None else "")
            + f"；差值 95% CI [{lo * 100:.2f}%, {hi * 100:.2f}%]"
            + ("（区间不含 0，与 p 值结论一致）" if (lo > 0 or hi < 0) else "")
        ),
    }


def sample_size(df: pd.DataFrame | None, params: dict) -> dict:
    """A/B 样本量计算：基线转化率 + 最小可检测效应（MDE）→ 每组所需样本数。"""
    baseline = float(params.get("baseline", 0))
    mde = float(params.get("mde", 0))
    relative = bool(params.get("relative", False))
    alpha = float(params.get("alpha", ALPHA))
    power = float(params.get("power", 0.8))
    if not (0 < baseline < 1):
        raise TestError("基线转化率需在 (0,1) 之间，如填 0.10 表示 10%")
    if relative:
        if not (-1 < mde and mde != 0):
            raise TestError("相对 MDE 需非零且大于 -100%")
        delta = baseline * mde
    else:
        delta = mde
    p2 = baseline + delta
    if not (0 < p2 < 1):
        raise TestError(f"目标转化率 {p2:.4f} 超出 (0,1)，请检查 MDE 方向与大小")
    if not (0 < alpha < 1 and 0 < power < 1):
        raise TestError("alpha 与 power 需在 (0,1) 之间")
    za = _z_crit(True, alpha)
    zb = float(stats.norm.ppf(power))
    p_bar = (baseline + p2) / 2
    n = ((za * math.sqrt(2 * p_bar * (1 - p_bar)) + zb * math.sqrt(baseline * (1 - baseline) + p2 * (1 - p2))) ** 2
         / delta ** 2)
    n = math.ceil(n)
    days_1k = math.ceil(n * 2 / 1000) if n * 2 > 1000 else 1
    return {
        "tests": [],
        "desc_columns": ["参数", "值"],
        "desc": [
            ["基线转化率", f"{baseline * 100:.2f}%"],
            ["目标转化率", f"{p2 * 100:.2f}%"],
            ["绝对 MDE", f"{delta * 100:+.2f}pp"],
            ["相对提升", f"{(delta / baseline) * 100:+.1f}%"],
            ["显著性水平 α（双尾）", alpha],
            ["统计效能 1-β", power],
            ["每组所需样本数", n],
            ["两组合计", n * 2],
        ],
        "n_per_group": n,
        "note": f"按双尾 α={alpha}、效能 {power:.0%} 估算，每组至少 {n} 个样本；"
                f"若每组每天新增 1000 用户，约需 {days_1k} 天跑完实验（正态近似公式，转化率很小时建议改用精确检验）",
    }


TESTS.update({"prop_z": prop_z_test, "sample_size": sample_size})
