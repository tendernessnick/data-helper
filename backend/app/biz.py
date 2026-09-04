"""业务分析模板：漏斗分析 / 同期群留存 / K-means 聚类。

与 analysis.py 的约定一致：统一返回 {"columns", "rows", "note", ...} 结构，
并附带前端渲染所需的特征字段（funnel / cohort / cluster_points）。

设计约定：
- 全部手写实现（pandas/numpy），不引入 sklearn，与 forecast.py 的零依赖取向一致
- 聚类内置 k-means++ 初始化与多次重启取最优（inertia），k 用肘部法+轮廓系数自动推荐
- 留存矩阵的期数偏移基于 Period 差值，天然支持月/周两种粒度
"""
import numpy as np
import pandas as pd

from .analysis import AnalysisError, _num_cols


def _check(df, column):
    if column not in df.columns:
        raise AnalysisError(f"列不存在: {column}")


# ---------------- 漏斗分析 ----------------


def funnel(df: pd.DataFrame, params: dict) -> dict:
    """转化漏斗：用户在步骤 1..i 中每一步都有行为的去重人数。

    采用"到达制"口径：用户到达第 i 步 = 该用户完成了第 1..i 全部步骤的事件
    （不校验事件间先后顺序），这是业务漏斗最常用的宽松口径。
    """
    user_col = params.get("user_column", "")
    event_col = params.get("event_column", "")
    steps = [str(s).strip() for s in (params.get("steps") or []) if str(s).strip()]
    for c in (user_col, event_col):
        _check(df, c)
    if len(steps) < 2:
        raise AnalysisError("漏斗至少需要 2 个步骤")

    sub = df[[user_col, event_col]].dropna().astype(str)
    if sub.empty:
        raise AnalysisError("用户列或事件列没有有效数据")

    reached = None
    counts = []
    for s in steps:
        users = set(sub.loc[sub[event_col] == s, user_col])
        reached = users if reached is None else (reached & users)
        counts.append(len(reached))
    if counts[0] == 0:
        raise AnalysisError(f"第一步「{steps[0]}」没有任何用户，请检查事件值填写")

    rows = []
    for i, (s, n) in enumerate(zip(steps, counts)):
        if i == 0:
            step_rate = 100.0
        elif counts[i - 1]:
            step_rate = n / counts[i - 1] * 100
        else:
            step_rate = 0.0  # 前一步已无人到达，本步转化率记 0（0/0 无定义）
        overall = n / counts[0] * 100
        drop = counts[i - 1] - n if i else 0
        rows.append([s, n, round(step_rate, 2), round(overall, 2), drop])
    total_rate = counts[-1] / counts[0] * 100
    return {
        "columns": [
            {"name": "步骤", "numeric": False},
            {"name": "用户数", "numeric": True},
            {"name": "单步转化率%", "numeric": True},
            {"name": "整体转化率%", "numeric": True},
            {"name": "较上步流失", "numeric": True},
        ],
        "rows": rows,
        "funnel": {"steps": steps, "values": counts},
        "overall_rate": round(total_rate, 2),
        "note": f"漏斗整体转化率 {total_rate:.2f}%（{counts[0]} → {counts[-1]} 人，到达制口径，不校验步骤先后顺序）",
    }


# ---------------- 同期群留存 ----------------


def cohort(df: pd.DataFrame, params: dict) -> dict:
    """同期群留存：按用户首次活跃月/周分群，计算第 N 期留存率矩阵。"""
    user_col = params.get("user_column", "")
    date_col = params.get("date_column", "")
    freq = params.get("freq", "M")
    if freq not in ("M", "W"):
        raise AnalysisError("粒度仅支持 M（月）或 W（周）")
    max_periods = min(max(int(params.get("periods", 8)), 2), 12)
    max_cohorts = max(int(params.get("max_cohorts", 12)), 1)
    for c in (user_col, date_col):
        _check(df, c)

    dates = pd.to_datetime(df[date_col], errors="coerce")
    sub = pd.DataFrame({
        "u": df[user_col].astype(str),
        "p": dates.dt.to_period(freq),
    })[dates.notna()]
    sub = sub.dropna()
    if sub.empty:
        raise AnalysisError("日期列解析后没有有效日期（请检查日期格式）")

    first = sub.groupby("u")["p"].min().rename("first")
    j = sub.join(first, on="u")
    j = j[(j["p"] >= j["first"])]
    j["offset"] = (j["p"] - j["first"]).apply(lambda x: x.n)

    sizes = first.value_counts().sort_index()
    if len(sizes) > max_cohorts:
        sizes = sizes.iloc[-max_cohorts:]
        j = j[j["first"].isin(sizes.index)]

    act = j[j["offset"].between(0, max_periods - 1)].drop_duplicates(["u", "first", "offset"])
    counts = act.pivot_table(index="first", columns="offset", values="u", aggfunc="count").fillna(0)

    col_labels = [f"第{i}期" for i in range(max_periods)]
    row_labels, rows, matrix = [], [], []
    for p, size in sizes.items():
        label = p.strftime("%Y-%m") if freq == "M" else str(p.start_time.date())
        row = [label, int(size)]
        ret_row = []
        for off in range(max_periods):
            n = counts.loc[p, off] if (p in counts.index and off in counts.columns) else 0
            rate = round(float(n) / int(size) * 100, 1)
            row.append(rate)
            ret_row.append(rate)
        row_labels.append(label)
        rows.append(row)
        matrix.append(ret_row)

    p2 = sizes.iloc[-1] if len(sizes) else None
    return {
        "columns": [{"name": "同期群", "numeric": False}, {"name": "用户数", "numeric": True}]
        + [{"name": c, "numeric": True} for c in col_labels],
        "rows": rows,
        "cohort": {"row_labels": row_labels, "col_labels": col_labels, "values": matrix},
        "freq": freq,
        "note": (
            f"按首次活跃{'月' if freq == 'M' else '周'}分群，共 {len(sizes)} 个同期群；"
            "单元格 = 该群用户在第 N 期仍活跃的比例（%）"
            + ("；较新的群尚未走完全部期数，右侧留存率自然偏低" if p2 is not None else "")
        ),
    }


# ---------------- K-means 聚类（手写） ----------------


def _kmeans_pp_init(X: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++：首个中心随机，其后按"离已有中心的最小距离²"加权采样。"""
    n = X.shape[0]
    centers = np.empty((k, X.shape[1]))
    centers[0] = X[rng.integers(n)]
    closest = ((X - centers[0]) ** 2).sum(axis=1)
    for j in range(1, k):
        total = closest.sum()
        idx = rng.integers(n) if total <= 1e-12 else rng.choice(n, p=closest / total)
        centers[j] = X[idx]
        closest = np.minimum(closest, ((X - centers[j]) ** 2).sum(axis=1))
    return centers


def _kmeans_single(X: np.ndarray, k: int, rng: np.random.Generator,
                   max_iter: int = 300, tol: float = 1e-6):
    """单次 Lloyd 迭代。返回 (centers, labels, inertia)。"""
    n = X.shape[0]
    centers = _kmeans_pp_init(X, k, rng)
    for _ in range(max_iter):
        d2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = d2.argmin(axis=1)
        new_centers = centers.copy()
        for j in range(k):
            mask = labels == j
            # 空簇重置为随机样本点，避免中心坍缩
            new_centers[j] = X[mask].mean(axis=0) if mask.any() else X[rng.integers(n)]
        shift = float(((new_centers - centers) ** 2).sum())
        centers = new_centers
        if shift <= tol:
            break
    d2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    labels = d2.argmin(axis=1)
    inertia = float(d2[np.arange(n), labels].sum())
    return centers, labels, inertia


def _kmeans(X: np.ndarray, k: int, n_init: int, seed: int):
    """多次重启取 inertia 最小的一轮，保证结果稳定。"""
    best = None
    for i in range(max(n_init, 1)):
        rng = np.random.default_rng(seed + i)
        res = _kmeans_single(X, k, rng)
        if best is None or res[2] < best[2]:
            best = res
    return best


def _silhouette(X: np.ndarray, labels: np.ndarray, sample: int = 1000, seed: int = 0) -> float:
    """轮廓系数（大样本随机抽样计算，控制 O(n²) 距离矩阵开销）。"""
    n = len(X)
    if len(set(labels.tolist())) < 2:
        return 0.0
    if n > sample:
        idx = np.random.default_rng(seed).choice(n, sample, replace=False)
        Xs, ls = X[idx], labels[idx]
    else:
        Xs, ls = X, labels
    m = len(Xs)
    D = np.linalg.norm(Xs[:, None, :] - Xs[None, :, :], axis=2)
    total = 0.0
    for i in range(m):
        same = ls == ls[i]
        cluster_size = int(same.sum())
        if cluster_size <= 1:
            continue  # 单样本簇记 0
        a = float(D[i, same].sum() - D[i, i]) / (cluster_size - 1)
        b = min(float(D[i, ls == c].mean()) for c in set(ls.tolist()) if c != ls[i])
        total += (b - a) / max(a, b)
    return float(total / m)


def cluster(df: pd.DataFrame, params: dict) -> dict:
    """K-means 聚类：k-means++ 初始化 + 多重启，肘部法 SSE 与轮廓系数自动推荐 k。"""
    cols = [c for c in (params.get("columns") or []) if c]
    for c in cols:
        _check(df, c)
    if len(cols) < 2:
        raise AnalysisError("聚类至少需要 2 个数值列")
    bad = [c for c in cols if c not in _num_cols(df)]
    if bad:
        raise AnalysisError(f"以下不是数值列，无法参与聚类：{', '.join(map(str, bad))}")

    k_user = int(params.get("k", 0))
    k_min = max(int(params.get("k_min", 2)), 2)
    k_max = min(max(int(params.get("k_max", 8)), k_min), 10)
    standardize = bool(params.get("standardize", True))
    sample_limit = max(int(params.get("sample_limit", 5000)), 200)
    seed = int(params.get("seed", 42))

    X_raw = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(X_raw) < k_min * 5:
        raise AnalysisError(f"有效样本过少（{len(X_raw)} 行，至少 {k_min * 5} 行）")
    const_cols = [c for c in cols if float(X_raw[c].std()) == 0.0]
    if const_cols:
        raise AnalysisError(f"以下列是常数列，没有区分度：{', '.join(map(str, const_cols))}")

    if len(X_raw) > sample_limit:
        X_raw = X_raw.sample(sample_limit, random_state=seed)
    X = X_raw.to_numpy(dtype=float)
    if standardize:
        mu, sigma = X.mean(axis=0), X.std(axis=0)
        sigma = np.where(sigma == 0, 1.0, sigma)  # 抽样后某列可能退化为常数，除零会产生 NaN 污染全表
        X = (X - mu) / sigma

    ks = list(range(k_min, k_max + 1))
    if len(X) < max(ks) * 5:
        ks = [k for k in ks if len(X) >= k * 5]
    inertias, silhouettes, fits = [], [], {}
    for k in ks:
        centers, labels, inertia = _kmeans(X, k, n_init=10, seed=seed)
        sil = _silhouette(X, labels, seed=seed)
        inertias.append(round(inertia, 2))
        silhouettes.append(round(sil, 4))
        fits[k] = (centers, labels, sil)

    best_k = k_user if k_user in fits else max(fits, key=lambda k: fits[k][2])
    centers, labels, best_sil = fits[best_k]

    # 簇画像：反标准化回原始量纲，业务可读
    X_disp = X * sigma + mu if standardize else X
    profile_rows = []
    for j in range(best_k):
        mask = labels == j
        row = [f"簇{j + 1}", int(mask.sum()), round(float(mask.mean() * 100), 1)]
        row += [round(float(X_disp[mask, c].mean()), 2) for c in range(len(cols))]
        profile_rows.append(row)

    # 散点降采样（≤1000 点），前两个特征维度
    step = max(1, len(X_disp) // 1000)
    pts = X_disp[::step]
    pts_labels = labels[::step]
    scatter = {
        "x": [round(float(v), 4) for v in pts[:, 0]],
        "y": [round(float(v), 4) for v in pts[:, 1]],
        "labels": [int(lb) for lb in pts_labels],
        "xlabel": str(cols[0]),
        "ylabel": str(cols[1]),
        "centers": [[round(float(c[0] * sigma[0] + mu[0]) if standardize else float(c[0]), 4),
                     round(float(c[1] * sigma[1] + mu[1]) if standardize else float(c[1]), 4)]
                    for c in centers],
    }

    return {
        "columns": [{"name": "簇", "numeric": False}, {"name": "样本数", "numeric": True},
                    {"name": "占比%", "numeric": True}]
        + [{"name": f"{c} 均值", "numeric": True} for c in cols],
        "rows": profile_rows,
        "best_k": int(best_k),
        "silhouette": round(best_sil, 4),
        "elbow": {"ks": ks, "inertias": inertias, "silhouettes": silhouettes},
        "cluster_points": scatter,
        "cluster_meta": {"standardize": standardize, "n": int(len(X)), "seed": seed},
        "note": (
            f"自动推荐 k={best_k}（轮廓系数 {best_sil:.3f}，越高越紧凑；"
            f"0.2 以下结构较弱）；特征{'已 Z-score 标准化，簇均值为原始量纲' if standardize else '未标准化'}"
        ),
    }
