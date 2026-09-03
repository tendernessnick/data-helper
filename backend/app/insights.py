"""一键本地洞察：纯规则引擎（无需 AI），把分析师的常规检查清单固化成代码。"""
import numpy as np
import pandas as pd

from .analysis import outlier_bounds


def _r(x, nd=2):
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        return None if np.isinf(v) else round(v, nd)
    except (TypeError, ValueError):
        return None


def _detect_date_col(df: pd.DataFrame):
    """返回第一个日期列：(列名, 解析后的Series)。datetime 类型优先，其次可解析的文本列。"""
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c, df[c]
    for c in df.columns:
        if df[c].dtype == object or str(df[c].dtype) == "str":
            s = pd.to_datetime(df[c], errors="coerce")
            if len(s.dropna()) >= 0.8 * max(len(df), 1) and s.nunique() > 3:
                return c, s
    return None, None


def quality_score(df: pd.DataFrame, insights: dict) -> dict:
    """数据质量评分（0-100）：加权扣分制，输出分数、等级与扣分明细。"""
    n = max(len(df), 1)
    m = max(df.shape[1], 1)
    score = 100.0
    deductions = []

    dup = insights["overview"]["duplicates"]
    if dup:
        cut = min(15.0, dup / n * 100 * 0.5)
        score -= cut
        deductions.append((f"{dup} 行重复数据", cut))

    miss_pct = insights["overview"]["missing_pct"]
    if miss_pct > 0:
        cut = min(25.0, miss_pct * 0.5)
        score -= cut
        deductions.append((f"缺失单元格占 {miss_pct}%", cut))

    const_cols = [q for q in insights["quality"] if "常量列" in q["msg"]]
    if const_cols:
        cut = min(15.0, len(const_cols) * 5)
        score -= cut
        deductions.append((f"{len(const_cols)} 个常量列", cut))

    high_missing = [c for c in insights.get("_col_missing", []) if c["pct"] > 30]
    if high_missing:
        cut = min(15.0, len(high_missing) * 5)
        score -= cut
        deductions.append((f"{len(high_missing)} 列缺失超 30%", cut))

    skewed = [x for x in insights["numeric"] if x["skew"] is not None and abs(x["skew"]) > 2]
    if skewed:
        cut = min(10.0, len(skewed) * 2)
        score -= cut
        deductions.append((f"{len(skewed)} 列分布严重偏斜", cut))

    outlier_heavy = [x for x in insights["numeric"] if x["outlier_pct"] > 5]
    if outlier_heavy:
        cut = min(9.0, len(outlier_heavy) * 3)
        score -= cut
        deductions.append((f"{len(outlier_heavy)} 列离群值占比超 5%", cut))

    score = max(0.0, round(score, 1))
    if score >= 90:
        level, color = "优秀", "#34c759"
    elif score >= 75:
        level, color = "良好", "#007aff"
    elif score >= 60:
        level, color = "一般", "#ff9500"
    else:
        level, color = "较差", "#ff3b30"
    return {
        "score": score,
        "level": level,
        "color": color,
        "deductions": [{"reason": r, "cut": round(c, 1)} for r, c in deductions],
        "note": "评分基于重复、缺失、常量列、偏态与离群值的加权扣分（满分 100）",
    }


def run_insights(df: pd.DataFrame, meta: dict) -> dict:
    n, m = len(df), df.shape[1]
    alerts = []

    # ---------- 整体概览 ----------
    duplicates = int(df.duplicated().sum())
    missing_cells = int(df.isna().sum().sum())
    missing_pct = round(missing_cells / max(n * m, 1) * 100, 2)
    overview = {
        "rows": int(n),
        "cols": int(m),
        "duplicates": duplicates,
        "missing_cells": missing_cells,
        "missing_pct": missing_pct,
        "mem_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
    }

    # ---------- 质量问题 ----------
    quality = []
    if duplicates:
        quality.append({"level": "warn", "msg": f"存在 {duplicates} 行完全重复的数据（建议去重）"})
    if missing_pct > 10:
        worst = df.isna().mean().mul(100).sort_values(ascending=False)
        top3 = "、".join(f"{k}（{_r(v, 1)}%）" for k, v in worst.head(3).items() if v > 0)
        quality.append({"level": "warn", "msg": f"缺失单元格占 {missing_pct}%，最严重：{top3}"})
    elif missing_cells:
        quality.append({"level": "info", "msg": f"缺失单元格 {missing_cells} 个（{missing_pct}%），整体健康"})
    for c in df.columns:
        if df[c].nunique(dropna=True) <= 1:
            quality.append({"level": "warn", "msg": f"列 [{c}] 是常量列（只有一个值），分析价值有限"})
        elif (
            not pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_datetime64_any_dtype(df[c])
            and df[c].nunique(dropna=True) > max(50, n * 0.5)
        ):
            quality.append({"level": "info", "msg": f"列 [{c}] 唯一值极多（{df[c].nunique()} 个），可能是 ID 类列"})
    # 看起来像数值的文本列
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        s = df[c].dropna()
        if len(s) and (pd.to_numeric(s, errors="coerce").notna().mean() if len(s) else 0) > 0.9 and s.nunique() > 3:
            quality.append({"level": "info", "msg": f"列 [{c}] 内容几乎全是数字，建议在清洗中转为数值类型"})

    # ---------- 数值列画像 ----------
    numeric = []
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]):
            continue
        s = df[c].dropna()
        if s.empty:
            continue
        skew = _r(s.skew())
        shape = "右偏（长尾在大值）" if skew and skew > 1 else ("左偏（长尾在小值）" if skew and skew < -1 else "接近对称")
        _, _, mask = outlier_bounds(df[c])
        outliers_n = int(mask.sum())
        numeric.append(
            {
                "name": str(c),
                "min": _r(s.min()), "max": _r(s.max()),
                "mean": _r(s.mean()), "median": _r(s.median()),
                "std": _r(s.std()), "skew": skew, "shape": shape,
                "zeros": int((s == 0).sum()),
                "negatives": int((s < 0).sum()),
                "outliers": outliers_n,
                "outlier_pct": round(outliers_n / max(n, 1) * 100, 2),
            }
        )
        if outliers_n / max(n, 1) > 0.05:
            alerts.append(f"🟡 列 [{c}] 有 {outliers_n} 个离群值（占 {round(outliers_n / max(n, 1) * 100, 1)}%），检查是否录入错误")
        if skew and skew > 1:
            alerts.append(f"🟡 列 [{c}] 分布明显右偏（偏度 {skew}），均值会被极端值拉高，看中位数更稳")

    # ---------- 类别列画像 ----------
    categorical = []
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        vc = df[c].value_counts(dropna=True)
        if vc.empty:
            continue
        top_share = round(float(vc.iloc[0]) / max(n, 1) * 100, 2)
        categorical.append(
            {
                "name": str(c),
                "nunique": int(vc.size),
                "top_value": str(vc.index[0]),
                "top_count": int(vc.iloc[0]),
                "top_share": top_share,
                "rare": int((vc == 1).sum()),
            }
        )
        if top_share > 50 and vc.size > 1:
            alerts.append(f"🔵 列 [{c}] 高度集中：「{vc.index[0]}」占 {top_share}%")

    # ---------- 时间趋势 ----------
    datetime_info = None
    date_col, dates = _detect_date_col(df)
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    if date_col is not None and num_cols:
        vcol = num_cols[0]
        tmp = pd.DataFrame({"日期": dates, "值": pd.to_numeric(df[vcol], errors="coerce")}).dropna()
        if len(tmp) >= 4:
            monthly = tmp.set_index("日期").resample("MS")["值"].sum().dropna()
            if len(monthly) >= 3:
                first, last = float(monthly.iloc[0]), float(monthly.iloc[-1])
                change = _r((last - first) / first * 100) if first else None
                direction = "上升" if (change or 0) > 0 else ("下降" if (change or 0) < 0 else "持平")
                slope = float(np.polyfit(range(len(monthly)), monthly.values, 1)[0])
                if slope > 0 and (change or 0) < 0 or slope < 0 and (change or 0) > 0:
                    direction = "波动"
                big = None
                if len(monthly) >= 4:
                    pc = monthly.pct_change() * 100
                    if pc.notna().any():
                        idx = pc.abs().idxmax()
                        big = {"period": idx.strftime("%Y-%m"), "pct": _r(pc[idx], 1)}
                        if abs(big["pct"]) >= 20:
                            alerts.append(
                                f"🟢 {vcol} 在 {big['period']} 出现最大环比变动：{big['pct']}%"
                            )
                datetime_info = {
                    "column": str(date_col),
                    "value_column": str(vcol),
                    "min": str(dates.min())[:10],
                    "max": str(dates.max())[:10],
                    "span_days": int((dates.max() - dates.min()).days),
                    "direction": direction,
                    "change_pct": change,
                    "big_shift": big,
                }
                alerts.append(
                    f"🟢 时间范围 {str(dates.min())[:10]} ~ {str(dates.max())[:10]}（{(dates.max() - dates.min()).days} 天）：{vcol} 按月整体呈{direction}"
                    + (f"（首末期变化 {change}%）" if change is not None else "")
                )

    # ---------- 相关性 ----------
    correlations = []
    if len(num_cols) >= 2:
        corr = df[num_cols].corr(numeric_only=True)
        pairs = []
        for i in range(len(num_cols)):
            for j in range(i + 1, len(num_cols)):
                r = corr.iloc[i, j]
                if pd.notna(r) and abs(r) >= 0.6:
                    pairs.append({"a": str(num_cols[i]), "b": str(num_cols[j]), "r": _r(r, 3)})
        pairs.sort(key=lambda p: -abs(p["r"]))
        correlations = pairs[:8]
        for p in correlations[:3]:
            sign = "正" if p["r"] > 0 else "负"
            alerts.append(f"🟢 [{p['a']}] 与 [{p['b']}] 强{sign}相关（r={p['r']}）")

    # ---------- 汇总 ----------
    if duplicates:
        alerts.insert(0, f"🔴 发现 {duplicates} 行重复数据，建议先在「数据清洗」中去重")
    if missing_pct > 10:
        alerts.insert(0, f"🔴 缺失比例达 {missing_pct}%，先处理缺失再分析更可靠")
    if not any(a.startswith(("🔴", "🟡")) for a in alerts):
        alerts.insert(0, "🟢 未发现明显数据质量问题，可以直接开始分析")

    result = {
        "overview": overview,
        "quality": quality,
        "numeric": numeric,
        "categorical": categorical,
        "datetime": datetime_info,
        "correlations": correlations,
        "alerts": alerts,
        "_col_missing": [
            {"name": str(c), "pct": round(float(df[c].isna().mean() * 100), 2)} for c in df.columns
        ],
    }
    result["quality_score"] = quality_score(df, result)
    del result["_col_missing"]
    return result
