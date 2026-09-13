"""一键数据体检：纯规则引擎（无需 AI），把分析师的数据前置检查清单固化成代码。

输出结构：
- overview    行列数 / 重复行 / 缺失单元格 / 内存概览
- findings    结构化问题清单，每条 {level, category, column, msg, detail, samples, fix}
              level: error(🔴)/warn(🟡)/info(🔵)；fix 为 null 或 {op, params, label}
              （op 是清洗面板操作名、params 为预填参数，前端「一键修复」直接复用）
- numeric / categorical / datetime / correlations   列画像与快洞察
- alerts      由 findings 派生的一行式清单（供 AI 解读与速览）
- quality_score   0-100 加权扣分（重复/缺失/结构/格式/异常值）

规则行业无关：只依赖"表格数据长什么样"，不预设业务含义。
"""
import re
from datetime import datetime

import numpy as np
import pandas as pd

from .analysis import outlier_bounds
from .cleaning import _FALSE_SET, _TRUE_SET, _WS_CHARS, parse_number_value, to_halfwidth

MAX_FINDINGS = 80  # 问题条数上限（error 优先保留）
_SAMPLE_TEXT = 20000  # 逐值扫描（数值/日期解析）的采样上限
_SAMPLE_DATE = 5000
LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}

DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y年%m月%d日",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S",
)
_FULLWIDTH_RE = re.compile(r"[０-９Ａ-Ｚａ-ｚ＄％＃＠＆]")
# 控制字符/零宽/乱码：用字面字符构造（pyarrow 的正则引擎不支持 \u 转义）
_CTRL_CHARS = "".join(
    chr(c) for c in [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F, 0x200B, 0x200C, 0x200D, 0xFEFF, 0xFFFD]
)
_CTRL_RE = re.compile("[" + re.escape(_CTRL_CHARS) + "]")
_MULTI_WS_RE = re.compile(r"\S[ \t　]{2,}\S")


def _r(x, nd=2):
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        return None if np.isinf(v) else round(v, nd)
    except (TypeError, ValueError):
        return None


def _f(level, category, msg, column=None, detail=None, samples=None, fix=None):
    """构造一条 finding。fix = {"op": 清洗操作名, "params": {...}, "label": 按钮文案} 或 None。"""
    return {
        "level": level,
        "category": category,
        "column": column,
        "msg": msg,
        "detail": detail,
        "samples": samples or [],
        "fix": fix,
    }


def _samples_of(values, k=3):
    """取前 k 个非空去重样本（短字符串，供前端展示证据）。"""
    out = []
    for v in values:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v)
        if len(s) > 24:
            s = s[:21] + "…"
        if s not in out:
            out.append(s)
        if len(out) >= k:
            break
    return out


def _pct(n, d):
    return round(n / max(d, 1) * 100, 2)


def _detect_date_col(df: pd.DataFrame):
    """返回第一个日期列：(列名, 解析后的Series)。datetime 类型优先，其次可解析的文本列。"""
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c, df[c]
    for c in df.columns:
        if df[c].dtype == object or str(df[c].dtype) == "str":
            s = pd.to_datetime(df[c], errors="coerce", format="mixed")
            if len(s.dropna()) >= 0.8 * max(len(df), 1) and s.nunique() > 3:
                return c, s
    return None, None


def _canonical(v: str) -> str:
    """类别值规范化键：全角→半角、去首尾空白、内部空白折叠、小写。仅差这些写法的值视为同义。"""
    return re.sub(r"\s+", " ", to_halfwidth(v).strip(_WS_CHARS)).lower()


# ---------------- 各类检查 ----------------


def _check_columns_and_structure(df, findings):
    """列名问题 / 常量列 / 全空列 / 高基数 ID 列 / ID 重复。"""
    # 列名
    unnamed = [str(c) for c in df.columns if str(c).strip() == "" or str(c).startswith("Unnamed:")]
    if unnamed:
        findings.append(_f("error", "structure", f"{len(unnamed)} 个列名为空或自动生成（Unnamed）",
                           detail=", ".join(unnamed[:5])))
    ws_cols = [c for c in df.columns if str(c) != str(c).strip()]
    if ws_cols:
        mapping = {str(c): str(c).strip() for c in ws_cols}
        stripped = set(mapping.values()) | {str(c) for c in df.columns if c not in ws_cols}
        fix = None
        if len(stripped) == len(df.columns):  # 去空格后不与其他列名冲突才提供一键修复
            fix = {"op": "rename_columns", "params": {"mapping": mapping}, "label": "清理列名空白"}
        findings.append(_f("warn", "structure", f"{len(ws_cols)} 个列名含首尾空白",
                           detail=", ".join(map(str, ws_cols[:5])), fix=fix))

    n = len(df)
    for c in df.columns:
        nonnull = df[c].dropna()
        if nonnull.empty:
            findings.append(_f("error", "structure", f"列 [{c}] 整列为空", column=str(c),
                               fix={"op": "drop_columns", "params": {"columns": [c]}, "label": "删除空列"}))
            continue
        nu = int(nonnull.nunique())
        if nu <= 1:
            findings.append(_f("info", "structure", f"列 [{c}] 是常量列（只有一个值 {nonnull.iloc[0]!s}）", column=str(c),
                               detail="分析价值有限",
                               fix={"op": "drop_columns", "params": {"columns": [c]}, "label": "删除常量列"}))
            continue
        # 高基数 ID 类列与"疑似 ID 列出现重复"仅对文本列检查：
        # 数值列（价格/金额等）取值重复是正常现象，不算主键冲突
        is_text = not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])
        if is_text and nu > max(50, n * 0.5):
            findings.append(_f("info", "structure", f"列 [{c}] 唯一值极多（{nu} 个），可能是 ID 类列", column=str(c)))
        if is_text and nu >= 20 and nu / len(nonnull) >= 0.9:
            dups = int(nonnull.duplicated().sum())
            if dups:
                findings.append(_f(
                    "warn", "structure", f"疑似 ID 列 [{c}] 有 {dups} 个重复值", column=str(c),
                    detail="该列几乎每行唯一，重复通常意味着整行重复或主键冲突",
                    samples=_samples_of(nonnull[nonnull.duplicated(keep=False)]),
                    fix={"op": "drop_duplicates", "params": {"columns": [c]}, "label": "按键去重"},
                ))


def _check_missing(df, findings, overview):
    miss_pct = overview["missing_pct"]
    worst = df.isna().mean().mul(100).sort_values(ascending=False)
    if miss_pct > 10:
        top3 = "、".join(f"{k}（{_r(v, 1)}%）" for k, v in worst.head(3).items() if v > 0)
        findings.append(_f("warn", "missing", f"缺失单元格占 {miss_pct}%，最严重：{top3}",
                           detail=f"共 {overview['missing_cells']} 个缺失单元格"))
    elif overview["missing_cells"]:
        findings.append(_f("info", "missing", f"缺失单元格 {overview['missing_cells']} 个（{miss_pct}%），整体健康"))
    high = [str(c) for c, v in worst.items() if v > 50]
    if high:
        findings.append(_f(
            "error", "missing", f"{len(high)} 列缺失超 50%：{', '.join(high[:5])}",
            detail="缺失过半的列通常信息量极低",
            fix={"op": "drop_high_missing", "params": {"threshold": 0.5}, "label": "删除缺失>50%的列"},
        ))
    elif any(v > 30 for v in worst.head(1)):
        mid = [str(c) for c, v in worst.items() if 30 < v <= 50]
        findings.append(_f("info", "missing", f"{len(mid)} 列缺失在 30%~50%：{', '.join(mid[:5])}",
                           detail="可按需删除或填充"))


def _scan_text(s: pd.Series):
    """扫描文本列的格式脏污与类型特征（行业无关）。返回统计 dict。"""
    txt = s.astype("string")
    nn = txt.dropna()
    total = len(nn)
    if total == 0:
        return {"total": 0}
    stripped = nn.str.strip(_WS_CHARS)
    edge_ws = int((nn != stripped).fillna(False).sum())
    empty_like = int((stripped.str.len() == 0).fillna(False).sum())
    # 向量化正则扫描：全列（成本可控）
    fullwidth = int(nn.str.contains(_FULLWIDTH_RE, na=False).sum())
    ctrl = int(nn.str.contains(_CTRL_RE, na=False).sum())
    multi_ws = int(nn.str.contains(_MULTI_WS_RE, na=False).sum())
    # 数值特征
    plain_num = pd.to_numeric(nn, errors="coerce")
    plain_ratio = float(plain_num.notna().mean()) if total else 0.0
    # 逐值解析（带格式数字/日期）在采样上做
    sample = nn.sample(n=min(total, _SAMPLE_TEXT), random_state=0) if total > _SAMPLE_TEXT else nn
    not_plain = sample[plain_num.reindex(sample.index).isna()]
    formatted = []
    for v in not_plain:
        f = parse_number_value(v)
        if f == f:  # not nan
            formatted.append(v)
    # 日期特征（采样）
    date_ratio = 0.0
    dsample = nn.sample(n=min(total, _SAMPLE_DATE), random_state=0) if total > _SAMPLE_DATE else nn
    try:
        parsed = pd.to_datetime(dsample, errors="coerce", format="mixed")
        date_ratio = float(parsed.notna().mean())
    except (ValueError, TypeError):
        date_ratio = 0.0
    return {
        "total": total, "edge_ws": edge_ws, "empty_like": empty_like,
        "fullwidth": fullwidth, "ctrl": ctrl, "multi_ws": multi_ws,
        "plain_ratio": plain_ratio,
        "formatted": len(formatted), "formatted_samples": formatted,
        "sample_size": len(sample), "date_ratio": date_ratio,
    }


def _check_text_format(df, c, sc, findings):
    """单列文本格式 findings（sc 为 _scan_text 结果）。"""
    total = sc["total"]
    col = str(c)
    if sc["edge_ws"]:
        findings.append(_f(
            "warn", "text", f"列 [{c}] 有 {sc['edge_ws']} 个值带首尾空格（{_pct(sc['edge_ws'], total)}%）",
            column=col, detail="空格不一致会导致分组、匹配时同值不同串",
            fix={"op": "trim_whitespace", "params": {"columns": [c]}, "label": "去除首尾空格"},
        ))
    if sc["empty_like"]:
        findings.append(_f(
            "warn", "text", f"列 [{c}] 有 {sc['empty_like']} 个空字符串/纯空白值",
            column=col, detail="空串不是标准缺失值（NaN），统计缺失时会被漏算",
            fix={"op": "normalize_text", "params": {"columns": [c], "empty_to_na": True}, "label": "空串转缺失"},
        ))
    if sc["fullwidth"]:
        findings.append(_f(
            "warn", "text", f"列 [{c}] 有 {sc['fullwidth']} 个值含全角字符（１２３／ＡＢＣ）",
            column=col, detail="全角数字/字母无法直接参与计算与匹配",
            samples=_samples_of(df[c].dropna().head(200)),
            fix={"op": "normalize_text", "params": {"columns": [c]}, "label": "全角转半角"},
        ))
    if sc["ctrl"]:
        findings.append(_f(
            "error", "text", f"列 [{c}] 有 {sc['ctrl']} 个值含控制字符/乱码字符",
            column=col, detail="多为复制粘贴或编码事故带入（零宽字符、\\ufffd 等）",
            fix={"op": "normalize_text", "params": {"columns": [c]}, "label": "清理不可见字符"},
        ))
    if sc["multi_ws"]:
        findings.append(_f(
            "info", "text", f"列 [{c}] 有 {sc['multi_ws']} 个值含连续多余空格",
            column=col,
            fix={"op": "normalize_text", "params": {"columns": [c]}, "label": "压缩连续空格"},
        ))


def _check_text_type(df, c, sc, findings):
    """单列类型类 findings：看起来像数值 / 混合类型 / 带格式数字 / 日期文本。"""
    total = sc["total"]
    col = str(c)
    pr = sc["plain_ratio"]
    if pr >= 0.9:
        findings.append(_f(
            "info", "type", f"列 [{c}] 内容几乎全是数字（可转数值比例约 {_pct(round(pr * total), total)}%）",
            column=col, detail="文本数字无法直接计算，建议转为数值类型",
            fix={"op": "cast_type", "params": {"column": c, "to": "float"}, "label": "转为数值"},
        ))
    elif 0.3 < pr < 0.9 and pr * total >= 3:
        findings.append(_f(
            "warn", "type", f"列 [{c}] 是混合类型：约 {_pct(round(pr * total), total)}% 可转数值，其余是文本",
            column=col, detail="同列混放数字与文字，多为单位、备注混入或录入错误",
            samples=_samples_of(df[c].dropna().head(200)),
            fix={"op": "parse_number", "params": {"column": c}, "label": "提取数值（其余置空）"},
        ))
    if sc["formatted"] >= max(3, 0.005 * sc["sample_size"]):
        findings.append(_f(
            "warn", "type", f"列 [{c}] 有 {sc['formatted']} 个带格式数字（千分位/货币/百分号/万·亿单位）",
            column=col, detail="如 1,234、¥100、12%、1.5万，需解析后才能计算",
            samples=_samples_of(sc["formatted_samples"]),
            fix={"op": "parse_number", "params": {"column": c}, "label": "解析为数值"},
        ))
    if sc["date_ratio"] >= 0.8 and pr < 0.8 and df[c].nunique(dropna=True) > 3:
        findings.append(_f(
            "info", "type", f"列 [{c}] 看起来是日期列（当前为文本）",
            column=col, detail="转为日期后才能做趋势、重采样",
            fix={"op": "cast_type", "params": {"column": c, "to": "datetime"}, "label": "转为日期"},
        ))


def _check_mixed_date_formats(s: pd.Series, findings):
    """文本日期列的混合格式检测：多种 format 各能解析一部分 → 提示。"""
    nn = s.astype("string").dropna()
    if len(nn) > 1000:
        nn = nn.sample(n=1000, random_state=0)
    if len(nn) < 10:
        return
    counts = {}
    for fmt in DATE_FORMATS:
        ok = 0
        for v in nn:
            try:
                datetime.strptime(v, fmt)
                ok += 1
            except (ValueError, TypeError):
                continue
        if ok >= len(nn) * 0.15:
            counts[fmt] = ok
    if len(counts) >= 2 and max(counts.values()) < len(nn) * 0.9:
        fmts = "、".join(counts.keys())
        findings.append(_f(
            "warn", "type", f"列 [{s.name}] 日期格式不统一（检测到 {fmts} 多种写法）",
            column=str(s.name), detail="格式混用会让部分日期解析失败变空值",
            fix={"op": "cast_type", "params": {"column": s.name, "to": "datetime"}, "label": "统一解析日期"},
        ))


def _check_datetime_range(s: pd.Series, c, findings):
    """日期列取值范围检查：未来日期 / 超远历史。"""
    now = pd.Timestamp.now() + pd.Timedelta(days=1)
    future = s > now
    n_future = int(future.sum())
    if n_future:
        findings.append(_f(
            "warn", "datetime", f"列 [{c}] 有 {n_future} 个未来日期（晚于今天）",
            column=str(c), detail="多为录入年份错误（如 2102 ↔ 2012）",
            samples=_samples_of(s[future]),
        ))
    ancient = s < pd.Timestamp("1900-01-01")
    n_old = int(ancient.sum())
    if n_old:
        findings.append(_f(
            "warn", "datetime", f"列 [{c}] 有 {n_old} 个早于 1900 年的日期",
            column=str(c), samples=_samples_of(s[ancient]),
        ))


def _check_numeric(df, c, findings):
    """数值列：离群值 / 偏态 / 负值 / 零值占比。"""
    col = str(c)
    s = df[c].dropna()
    if s.empty:
        return
    n = len(df)
    _, _, mask = outlier_bounds(df[c])
    outliers_n = int(mask.sum())
    if outliers_n and outliers_n / max(n, 1) > 0.05:
        findings.append(_f(
            "warn", "numeric", f"列 [{c}] 有 {outliers_n} 个离群值（占 {_pct(outliers_n, n)}%，IQR 口径）",
            column=col, detail="先确认是真实极端值还是录入错误；盖帽不删行",
            fix={"op": "cap_outliers", "params": {"columns": [c], "method": "iqr"}, "label": "盖帽到上下界"},
        ))
    skew = _r(s.skew())
    if skew and abs(skew) > 2:
        findings.append(_f(
            "info", "numeric", f"列 [{c}] 分布严重{'右' if skew > 0 else '左'}偏（偏度 {skew}）",
            column=col, detail="均值会被极端值拉偏，看中位数更稳",
        ))
    neg = int((s < 0).sum())
    pos = int((s > 0).sum())
    if neg and pos / max(neg + pos, 1) >= 0.9:
        findings.append(_f(
            "warn", "numeric", f"列 [{c}] 几乎全为正但有 {neg} 个负值",
            column=col, detail="若该列不应为负（数量、年龄等），多为录入错误或哨兵值（-1/-999）",
            samples=_samples_of(s[s < 0]),
        ))
    zeros = int((s == 0).sum())
    if zeros and zeros / len(s) > 0.5:
        findings.append(_f(
            "info", "numeric", f"列 [{c}] 有 {_pct(zeros, len(s))}% 的值为 0",
            column=col, detail="高零占比可能表示缺失被填成了 0",
        ))


def _check_categorical(df, c, findings):
    """类别列：布尔语义不统一 / 疑似同义标签 / 高度集中。"""
    col = str(c)
    vc = df[c].value_counts(dropna=True)
    if vc.empty:
        return
    n = len(df)
    # 布尔语义
    if 2 <= vc.size <= 12:
        cover = sum(int(v) for k, v in vc.items() if str(k).strip().lower() in _TRUE_SET | _FALSE_SET)
        if cover / max(int(vc.sum()), 1) >= 0.95 and vc.size >= 2:
            findings.append(_f(
                "info", "category", f"列 [{c}] 是布尔语义列但取值写法不统一",
                column=col, detail=f"取值：{', '.join(map(str, vc.index[:6]))}",
                fix={"op": "unify_boolean_text", "params": {"column": c}, "label": "统一为 是/否"},
            ))
    # 疑似同义标签（仅差空格/大小写/全角）
    if 2 < vc.size <= 500:
        groups = {}
        for v in vc.index:
            try:
                key = _canonical(str(v))
            except TypeError:
                continue
            groups.setdefault(key, []).append((v, int(vc[v])))
        dup_groups = [g for g in groups.values() if len(g) > 1]
        if dup_groups:
            mapping = {}
            shown = []
            affected = 0
            for g in dup_groups[:5]:
                g_sorted = sorted(g, key=lambda x: -x[1])
                canonical_value = g_sorted[0][0]
                for v, _ in g_sorted[1:]:
                    mapping[str(v)] = str(canonical_value)
                affected += sum(cnt for _, cnt in g)
                shown.append("/".join(str(v) for v, _ in g_sorted))
            findings.append(_f(
                "warn", "category", f"列 [{c}] 有 {len(dup_groups)} 组疑似同义标签（仅空格/大小写/全角不同）",
                column=col, detail="；".join(shown[:5]) + (f" 等 {len(dup_groups)} 组" if len(dup_groups) > 5 else ""),
                fix={"op": "map_values", "params": {"column": c, "mapping": mapping}, "label": "合并同义标签"},
            ))
    top_share = round(float(vc.iloc[0]) / max(n, 1) * 100, 2)
    if top_share > 50 and vc.size > 1:
        findings.append(_f(
            "info", "category", f"列 [{c}] 高度集中：「{vc.index[0]}」占 {top_share}%",
            column=col,
        ))


# ---------------- v4.4 深化：列间关系 / 格式语义 / 数值粒度 / 时序 ----------------

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")
_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_IDCARD_RE = re.compile(r"^\d{15}(\d{2}[0-9Xx])?$")
_FORMAT_PATTERNS = (("手机号", _PHONE_RE), ("邮箱", _EMAIL_RE), ("网址", _URL_RE), ("身份证号", _IDCARD_RE))


def _num_cols_of(df):
    return [c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def _check_arithmetic_relations(df, findings):
    """列间算术关系发现 + 违反行检测（数量×单价≈金额 / A+B≈C / A−B≈C）。

    采样判定关系成立后回全量找违反行——这是找录入错误的最强信号；
    不能替用户判断哪个列错，因此不提供自动修复。
    """
    cols = _num_cols_of(df)
    if len(cols) < 3:
        return
    if len(cols) > 12:  # 防组合爆炸：取方差最大的 12 列（业务度量列通常方差靠前）
        cols = sorted(cols, key=lambda c: -(df[c].std() or 0))[:12]
    sub = df[cols].dropna()
    if len(sub) > 5000:
        sub = sub.sample(n=5000, random_state=0)
    if len(sub) < 30:
        return

    arrs = {c: sub[c].to_numpy(dtype=float) for c in cols}

    def _match_rate(a, b, c, op):
        x, y, z = arrs[a], arrs[b], arrs[c]
        expr = x * y if op == "×" else (x + y if op == "+" else x - y)
        denom = np.abs(z)
        denom[denom < 1e-9] = 1.0
        return float((np.abs(expr - z) / denom <= 0.01).mean())

    found = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            for k in range(len(cols)):
                if k in (i, j):
                    continue
                c = cols[k]
                for op in ("×", "+"):
                    if _match_rate(a, b, c, op) >= 0.95:
                        found.append((a, op, b, c))
                        break
        for j in range(len(cols)):  # 减法有序：A−B≈C 与 B−A≈C 不同
            if j == i:
                continue
            a, b = cols[i], cols[j]
            for k in range(len(cols)):
                if k in (i, j):
                    continue
                c = cols[k]
                if _match_rate(a, b, c, "−") >= 0.95:
                    found.append((a, "−", b, c))

    n_reported_info = 0
    for a, op, b, c in found:
        full = df[[a, b, c]].dropna()
        if len(full) < 30:
            continue
        x, y, z = full[a], full[b], full[c]
        expr = x * y if op == "×" else (x + y if op == "+" else x - y)
        denom = z.abs().mask(z.abs() < 1e-9, 1.0)
        rel_err = (expr - z).abs() / denom
        viol = rel_err > 0.01
        rate = 1 - float(viol.mean())
        if rate < 0.9:
            continue  # 全量匹配率低：关系不稳定，不报
        desc = f"{a} {op} {b} ≈ {c}"
        if viol.any():
            n_viol = int(viol.sum())
            shown = []
            for idx in full[viol].head(3).index:
                shown.append(f"{x[idx]}{op}{y[idx]}≠{z[idx]}")
            findings.append(_f(
                "warn", "consistency", f"列间关系 {desc} 有 {n_viol} 行不满足（匹配率 {_pct(round(rate * len(full)), len(full))}%）",
                column=str(c), detail="常见于金额/数量类录入错误；无法自动判断哪一列出错，建议按样本核查",
                samples=shown,
            ))
        elif n_reported_info < 3:  # 关系成立且无违反：作为正面洞察报告（限 3 条）
            findings.append(_f(
                "info", "consistency", f"发现列间关系：{desc}（匹配率 {_pct(round(rate * len(full)), len(full))}%）",
                column=str(c), detail="数据内部自洽；做校验或特征工程时可利用该关系",
            ))
            n_reported_info += 1


def _check_functional_deps(df, findings):
    """函数依赖冲突：近似「A 决定 B」但存在同 A 不同 B（订单号→客户名、邮编→城市）。"""
    n = len(df)
    det_cols, dep_cols = [], []
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        try:
            nu = int(df[c].nunique(dropna=True))
        except TypeError:  # 含不可哈希单元格（list 等）
            continue
        if nu > max(50, n * 0.5) and nu >= 20:
            det_cols.append(str(c))
        elif 2 <= nu <= 500 and nu < n * 0.5:
            dep_cols.append(str(c))
    det_cols, dep_cols = det_cols[:3], dep_cols[:20]
    if not det_cols or not dep_cols:
        return
    sub = df if n <= 10000 else df.sample(n=10000, random_state=0)
    for a in det_cols:
        for b in dep_cols:
            if a == b:
                continue
            try:
                g = sub.groupby(sub[a], dropna=False)[b].nunique()
            except TypeError:
                continue
            conflicts = g[g > 1]
            g_size = len(g)
            if not len(conflicts) or g_size == 0 or len(conflicts) > g_size * 0.1:
                continue  # 冲突组太多说明本来就不是函数依赖
            shown = []
            for av in conflicts.index[:3]:
                if pd.isna(av):
                    continue
                vals = sub.loc[sub[a] == av, b].dropna().unique()[:3]
                if len(vals) > 1:
                    shown.append(f"{av}→{' | '.join(map(str, vals))}")
            if shown:
                findings.append(_f(
                    "warn", "consistency", f"列 [{a}] 近似决定 [{b}]，但有 {len(conflicts)} 个值对应多个 {b}",
                    column=a, detail="同键不同值通常是录入不一致或合并数据源时未对齐",
                    samples=shown,
                ))


def _check_format_semantics(s: pd.Series, c, findings):
    """常见格式列（手机号/邮箱/网址/身份证）识别 + 不符合格式的值；长度异常值。"""
    nn = s.astype("string").dropna()
    if len(nn) < 20:
        return
    sample = nn if len(nn) <= _SAMPLE_TEXT else nn.sample(n=_SAMPLE_TEXT, random_state=0)
    total = len(nn)
    for name, rx in _FORMAT_PATTERNS:
        matched = sample.str.fullmatch(rx).fillna(False)
        ratio = float(matched.mean())
        if ratio < 0.8:
            continue
        bad = sample[~matched]
        n_bad_est = round(len(bad) / max(len(sample), 1) * total)
        if len(bad) >= 3:
            findings.append(_f(
                "warn", "type", f"列 [{c}] 疑似{name}列，但有约 {n_bad_est} 个值不符合{name}格式",
                column=str(c), detail="多为位数缺失、多输或混入了其他内容",
                samples=_samples_of(bad),
            ))
        break
    # 长度异常（截断/拼接风险）
    lens = sample.str.len()
    med = float(lens.median()) if len(lens) else 0
    if med >= 3:
        odd = int(((lens > med * 3) | (lens < med * 0.3)).sum())
        if odd >= 1 and odd / max(len(sample), 1) > 0.005:
            findings.append(_f(
                "info", "type", f"列 [{c}] 有 {odd} 个值长度显著偏离该列常见长度（中位数 {int(med)}）",
                column=str(c), detail="可能存在截断或多个值被拼接",
            ))


def _check_numeric_granularity(s: pd.Series, c, findings):
    """数值粒度：小数位异常（精度突增）与量级断裂（疑似单位混用）。"""
    if len(s) < 30:
        return
    sample = s if len(s) <= 2000 else s.sample(n=2000, random_state=0)
    decs = []
    for v in sample:
        f = float(v)
        d = 0 if f == int(f) else len(("%r" % f).split(".")[1])
        decs.append(d)
    mode_d = max(set(decs), key=decs.count)
    finer = sum(1 for d in decs if d > mode_d)
    if mode_d <= 2 and finer >= 2 and finer / len(decs) > 0.005:
        findings.append(_f(
            "info", "numeric", f"列 [{c}] 常见精度为 {mode_d} 位小数，但有约 {_pct(finer, len(decs))}% 的值精度更高",
            column=str(c), detail="可能是计算值与录入值混放，或浮点误差",
        ))
    pos = sample[sample > 0]
    if len(pos) >= 30:
        lg = np.log10(pos)
        far = int((np.abs(lg - lg.mean()) > 3).sum())
        if far >= 1 and far / len(pos) > 0.005:
            findings.append(_f(
                "info", "numeric", f"列 [{c}] 有 {far} 个值与主体相差 3 个数量级以上",
                column=str(c), detail="疑似单位混用（如 米/毫米）或极端异常值，建议核查",
            ))


def _check_datetime_series(s: pd.Series, c, findings):
    """时序检查：重复时间戳 / 时间覆盖缺口（漏采时段）。"""
    nn = s.dropna()
    if len(nn) < 30:
        return
    nu = nn.nunique()
    if nu / max(len(nn), 1) >= 0.9:
        dups = int(nn.duplicated().sum())
        if dups and dups / max(len(nn), 1) <= 0.1:
            findings.append(_f(
                "info", "datetime", f"列 [{c}] 时间戳近乎唯一，但有 {dups} 个重复时刻",
                column=str(c), detail="可能是同一事件被记录了多次",
            ))
    span_days = (nn.max() - nn.min()).days
    if span_days > 366 * 5 or span_days < 7:
        return  # 跨度太长（粒度不明）或太短，跳过缺口检测
    daily = nn.dt.normalize().drop_duplicates().sort_values()
    gaps = daily.diff().dropna().dt.days
    if not len(gaps) or float(gaps.median()) > 7:
        return  # 中位间隔 >7 天：月度/季度类数据，"缺口"是正常节奏
    expected = span_days + 1
    have = len(daily)
    missing = expected - have
    if expected >= 30 and missing / expected > 0.1:
        findings.append(_f(
            "info", "datetime", f"列 [{c}] 时间覆盖有缺口：{expected} 天中仅 {have} 天有数据（缺 {missing} 天）",
            column=str(c), detail="可能是漏采/停服时段；若本就非逐日采集可忽略",
        ))


# ---------------- 评分与主入口 ----------------


def quality_score(overview: dict, findings: list) -> dict:
    """数据质量评分（0-100）：加权扣分制，输出分数、等级与扣分明细。"""
    n = max(overview["rows"], 1)
    score = 100.0
    deductions = []

    dup = overview["duplicates"]
    if dup:
        cut = min(15.0, dup / n * 100 * 0.5)
        score -= cut
        deductions.append((f"{dup} 行重复数据", cut))

    miss_pct = overview["missing_pct"]
    if miss_pct > 0:
        cut = min(25.0, miss_pct * 0.5)
        score -= cut
        deductions.append((f"缺失单元格占 {miss_pct}%", cut))

    n_error = sum(1 for f in findings if f["level"] == "error")
    if n_error:
        cut = min(21.0, n_error * 3)
        score -= cut
        deductions.append((f"{n_error} 个严重问题（结构/格式）", cut))

    n_warn = sum(1 for f in findings if f["level"] == "warn")
    if n_warn:
        cut = min(18.0, n_warn * 1.5)
        score -= cut
        deductions.append((f"{n_warn} 个警告级问题", cut))

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
        "note": "评分基于重复、缺失、结构/格式问题与异常值的加权扣分（满分 100）",
    }


_DIM_NAMES = [
    ("completeness", "完整性"), ("uniqueness", "唯一性"), ("consistency", "一致性"),
    ("validity", "有效性"), ("timeliness", "及时性"), ("structure", "结构"),
]
# finding 归维规则：structure 里的"重复"类归唯一性，其余按 category 直配
_DIM_OF_CATEGORY = {
    "missing": "completeness", "consistency": "consistency", "category": "consistency",
    "text": "validity", "type": "validity", "numeric": "validity",
    "datetime": "timeliness", "structure": "structure",
}
_DIM_CUT = {"error": 8.0, "warn": 4.0, "info": 1.0}


def quality_dims(overview: dict, findings: list, has_date: bool) -> list:
    """六维质量雷达（0-100/维）：完整性/唯一性/一致性/有效性/及时性/结构。

    无日期列时及时性为 None（前端雷达隐藏该轴）。与总分并存：总分是加权扣分，
    雷达回答"差在哪一类"。
    """
    n = max(overview["rows"], 1)
    scores = dict.fromkeys((k for k, _ in _DIM_NAMES), 100.0)
    # 概率指标打底
    scores["completeness"] -= min(60.0, overview["missing_pct"] * 2)
    scores["uniqueness"] -= min(50.0, overview["duplicates"] / n * 100 * 1.5)
    for f in findings:
        dim = _DIM_OF_CATEGORY.get(f["category"], "validity")
        if f["category"] == "structure" and "重复" in f["msg"]:
            dim = "uniqueness"
        scores[dim] -= _DIM_CUT.get(f["level"], 1.0)
    out = []
    for key, name in _DIM_NAMES:
        v = None if (key == "timeliness" and not has_date) else max(0.0, min(100.0, round(scores[key], 1)))
        out.append({"key": key, "name": name, "score": v})
    return out


def run_insights(df: pd.DataFrame, meta: dict) -> dict:
    n, m = len(df), df.shape[1]
    findings = []

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
    if duplicates:
        findings.insert(0, _f(
            "error", "structure", f"存在 {duplicates} 行完全重复的数据",
            detail="重复行会让统计结果被重复计入",
            fix={"op": "drop_duplicates", "params": {}, "label": "一键去重"},
        ))

    # ---------- 各类检查 ----------
    _check_columns_and_structure(df, findings)
    _check_missing(df, findings, overview)
    has_date_col = False
    for c in df.columns:
        is_num = pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
        is_dt = pd.api.types.is_datetime64_any_dtype(df[c])
        if is_num:
            _check_numeric(df, c, findings)
            _check_numeric_granularity(df[c].dropna(), c, findings)
        elif is_dt:
            has_date_col = True
            _check_datetime_range(df[c], c, findings)
            _check_datetime_series(df[c], c, findings)
        else:
            sc = _scan_text(df[c])
            if sc["total"] == 0:
                continue
            _check_text_format(df, c, sc, findings)
            _check_text_type(df, c, sc, findings)
            _check_format_semantics(df[c], c, findings)
            _check_categorical(df, c, findings)
            if sc["date_ratio"] >= 0.8 and sc["plain_ratio"] < 0.8 and df[c].nunique(dropna=True) > 3:
                has_date_col = True
                _check_mixed_date_formats(df[c], findings)
                dd = df[c].dropna()
                if len(dd) > 50000:
                    dd = dd.sample(50000, random_state=0)
                try:
                    parsed = pd.to_datetime(dd, errors="coerce", format="mixed")
                    _check_datetime_range(parsed, c, findings)
                    _check_datetime_series(parsed, c, findings)
                except (ValueError, TypeError):
                    pass

    # 列间关系（算术关系 / 函数依赖）：只对整数/浮点列足够多的表检测
    _check_arithmetic_relations(df, findings)
    _check_functional_deps(df, findings)

    # 排序 + 封顶（error 优先）
    findings.sort(key=lambda f: LEVEL_ORDER.get(f["level"], 9))
    truncated = 0
    if len(findings) > MAX_FINDINGS:
        truncated = len(findings) - MAX_FINDINGS
        findings = findings[:MAX_FINDINGS]

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

    # ---------- 时间趋势快洞察 ----------
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

    # ---------- alerts（一行式清单，供速览与 AI 解读） ----------
    icon = {"error": "🔴", "warn": "🟡", "info": "🔵"}
    alerts = [f"{icon[f['level']]} {f['msg']}" + (f"（{f['detail']}）" if f["detail"] else "") for f in findings]
    for p in correlations[:3]:
        sign = "正" if p["r"] > 0 else "负"
        alerts.append(f"🟢 [{p['a']}] 与 [{p['b']}] 强{sign}相关（r={p['r']}）")
    if datetime_info:
        alerts.append(
            f"🟢 时间范围 {datetime_info['min']} ~ {datetime_info['max']}（{datetime_info['span_days']} 天）："
            f"{datetime_info['value_column']} 按月整体呈{datetime_info['direction']}"
            + (f"（首末期变化 {datetime_info['change_pct']}%）" if datetime_info["change_pct"] is not None else "")
        )
    if not any(a.startswith(("🔴", "🟡")) for a in alerts):
        alerts.insert(0, "🟢 未发现明显数据质量问题，可以直接开始分析")

    result = {
        "overview": overview,
        "findings": findings,
        "findings_truncated": truncated,
        "numeric": numeric,
        "categorical": categorical,
        "datetime": datetime_info,
        "correlations": correlations,
        "alerts": alerts,
    }
    result["quality_score"] = quality_score(overview, findings)
    result["quality_dims"] = quality_dims(overview, findings, has_date_col)
    return result
