"""金融数据分析核心：列识别 / 收益风险指标 / 技术指标 / CAPM / 组合 / 回测。

设计约定：
- 列识别支持中英文常见命名（日期/开盘/最高/最低/收盘/成交量…）
- 指标计算纯 pandas/numpy/scipy，无额外依赖
- 所有输出可直接 JSON 化（原生类型）
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


class FinanceError(ValueError):
    pass


# ---------------- 列识别 ----------------

COLUMN_ALIASES = {
    "date": ["日期", "date", "time", "交易日", "trade_date", "day"],
    "open": ["开盘", "开盘价", "open", "开盘价(元)", "openprice"],
    "high": ["最高", "最高价", "high", "最高价(元)"],
    "low": ["最低", "最低价", "low", "最低价(元)"],
    "close": ["收盘", "收盘价", "close", "收盘价(元)", "closeprice", "adjclose", "前收盘" ],
    "volume": ["成交量", "volume", "vol", "成交量(股)", "volumeoriginal", "成交数量"],
    "amount": ["成交额", "amount", "成交金额", "turnover", "成交额(元)"],
}


def _map_roles(df: pd.DataFrame) -> dict:
    """按别名逐角色映射列名（不要求齐全）。"""
    cols = {str(c).strip().lower(): c for c in df.columns}
    found = {}
    for role, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in cols:
                found[role] = cols[alias.lower()]
                break
    return found


def detect_ohlcv(df: pd.DataFrame) -> dict:
    """识别 OHLCV 列名。至少需要 date+close 才算金融数据。返回 {角色: 列名}。"""
    found = _map_roles(df)
    if "date" in found and "close" in found:
        return found
    return {}


def _date_series(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, errors="coerce")
    return s


def _sorted_prices(df: pd.DataFrame, ohlcv: dict) -> pd.DataFrame:
    """按日期升序、去停牌空值的 OHLCV 子表。"""
    out = df[list(set(ohlcv.values()))].copy()
    out["__date"] = _date_series(df, ohlcv["date"])
    out = out.dropna(subset=["__date", ohlcv["close"]]).sort_values("__date").reset_index(drop=True)
    if len(out) < 3:
        raise FinanceError("有效行情数据不足 3 行（检查日期与收盘列）")
    return out


# ---------------- 收益与风险指标 ----------------


def _max_drawdown(prices: pd.Series, dates: pd.Series):
    """返回 (回撤值, 峰值日, 谷底日, 恢复期天数或None)。"""
    cummax = prices.cummax()
    dd = prices / cummax - 1
    trough_idx = int(dd.idxmin())
    dd_val = float(dd.iloc[trough_idx])
    peak_idx = int(prices.iloc[: trough_idx + 1].idxmax())
    # 恢复：谷底之后首次回到峰值
    peak_val = prices.iloc[peak_idx]
    after = prices.iloc[trough_idx:]
    rec = after[after >= peak_val]
    rec_idx = int(rec.index[0]) if len(rec) else None
    def _d(i):
        d = dates.iloc[int(i)]
        return "第{}期".format(int(i) + 1) if pd.isna(d) else str(d)[:10]

    return {
        "drawdown": round(dd_val, 6),
        "peak_date": _d(peak_idx),
        "trough_date": _d(trough_idx),
        "recovered": rec_idx is not None,
        "duration_days": (trough_idx - peak_idx),
    }


def metrics_report(df: pd.DataFrame, params: dict) -> dict:
    """收益风险指标总览。params: close(可选，默认识别), rf(年化无风险利率,默认0.02), freq(D/W/M)。"""
    ohlcv = _map_roles(df)  # 宽松映射：只要能找到收盘列即可（日期可选）
    close_col = params.get("close") or (ohlcv.get("close") if ohlcv else "")
    if close_col not in df.columns:
        raise FinanceError("请选择收盘价列（或数据中包含可识别的 收盘/Close 列）")
    # 输出的 ohlcv 仅供前端参考；无日期时指标照常计算（日期显示为序号）
    if not ("date" in ohlcv and "close" in ohlcv):
        ohlcv = {}
    rf = float(params.get("rf", 0.02))
    freq = params.get("freq", "D")
    ann_factor = {"D": TRADING_DAYS, "W": 52, "M": 12, "Q": 4, "Y": 1}.get(freq, TRADING_DAYS)

    date_col = ohlcv.get("date") if ohlcv else ""
    if date_col:
        tmp = pd.DataFrame({"date": _date_series(df, date_col), "close": pd.to_numeric(df[close_col], errors="coerce")}).dropna().sort_values("date").reset_index(drop=True)
    else:
        tmp = pd.DataFrame({"close": pd.to_numeric(df[close_col], errors="coerce").dropna().reset_index(drop=True)})
        tmp["date"] = pd.Series([pd.NaT] * len(tmp))
    if len(tmp) < 3:
        raise FinanceError("有效收盘价不足 3 行")
    prices = tmp["close"]
    dates = tmp["date"]
    rets = prices.pct_change().dropna()

    n = len(prices)
    total_return = float(prices.iloc[-1] / prices.iloc[0] - 1)
    years = n / ann_factor
    ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else None
    ann_vol = float(rets.std(ddof=1) * np.sqrt(ann_factor))
    mdd = _max_drawdown(prices, dates)
    downside = rets[rets < 0]
    downside_vol = float(downside.std(ddof=1) * np.sqrt(ann_factor)) if len(downside) > 1 else 0.0
    var95 = float(np.percentile(rets, 5))
    var99 = float(np.percentile(rets, 1))
    cvar95 = float(rets[rets <= var95].mean())
    sharpe = (ann_return - rf) / ann_vol if ann_vol > 0 else None
    sortino = (ann_return - rf) / downside_vol if downside_vol > 0 else None
    calmar = ann_return / abs(mdd["drawdown"]) if mdd["drawdown"] < 0 else None

    # 累计收益曲线（按日）
    cum = (1 + rets).cumprod() - 1
    curve_dates = [str(d)[:10] if pd.notna(d) else str(i) for i, d in zip(rets.index, dates.iloc[1:])]
    curve = {
        "labels": curve_dates,
        "values": [round(float(v) * 100, 4) for v in cum],
    }

    def _r(x, nd=4):
        return None if x is None else round(float(x), nd)

    groups = [
        {"name": "收益", "items": [
            {"label": "区间总收益", "value": f"{total_return * 100:.2f}%"},
            {"label": "年化收益", "value": f"{_r(ann_return) * 100:.2f}%" if ann_return is not None else "—"},
            {"label": "样本数", "value": f"{n} 根{ {'D': '日K', 'W': '周K', 'M': '月K'}.get(freq, 'K线') }"},
        ]},
        {"name": "风险", "items": [
            {"label": "年化波动率", "value": f"{ann_vol * 100:.2f}%"},
            {"label": "最大回撤", "value": f"{mdd['drawdown'] * 100:.2f}%（{mdd['peak_date']} → {mdd['trough_date']}）"},
            {"label": "下行波动率", "value": f"{downside_vol * 100:.2f}%"},
            {"label": "VaR 95% / 99%（单期）", "value": f"{var95 * 100:.2f}% / {var99 * 100:.2f}%"},
            {"label": "CVaR 95%", "value": f"{cvar95 * 100:.2f}%"},
        ]},
        {"name": "风险调整比率（rf={:.0%}）".format(rf), "items": [
            {"label": "Sharpe", "value": _r(sharpe, 3) if sharpe is not None else "—"},
            {"label": "Sortino", "value": _r(sortino, 3) if sortino is not None else "—"},
            {"label": "Calmar", "value": _r(calmar, 3) if calmar is not None else "—"},
        ]},
        {"name": "收益分布", "items": [
            {"label": "偏度", "value": _r(float(rets.skew()), 3)},
            {"label": "峰度", "value": _r(float(rets.kurt()), 3)},
            {"label": "最佳/最差单期", "value": f"{rets.max() * 100:.2f}% / {rets.min() * 100:.2f}%"},
        ]},
    ]
    return {
        "kind": "finance_metrics",
        "groups": groups,
        "curve": curve,
        "note": f"基于收盘列 [{close_col}]，{n} 期，年化因子 {ann_factor}",
        "ohlcv": ohlcv,
    }


# ---------------- 技术指标（生成新列） ----------------


def _mk_col(base: str, suffix: str) -> str:
    return f"{base}_{suffix}"


def add_ma(df: pd.DataFrame, col: str, n: int, kind: str = "ma") -> pd.DataFrame:
    out = df.copy()
    if kind == "ema":
        out[_mk_col(col, f"EMA{n}")] = out[col].ewm(span=n, adjust=False).mean().round(4)
    else:
        out[_mk_col(col, f"MA{n}")] = out[col].rolling(n).mean().round(4)
    return out


def add_macd(df: pd.DataFrame, col: str, fast=12, slow=26, signal=9) -> pd.DataFrame:
    out = df.copy()
    ef = out[col].ewm(span=fast, adjust=False).mean()
    es = out[col].ewm(span=slow, adjust=False).mean()
    dif = (ef - es).round(4)
    dea = dif.ewm(span=signal, adjust=False).mean().round(4)
    out[_mk_col(col, "DIF")] = dif
    out[_mk_col(col, "DEA")] = dea
    out[_mk_col(col, "MACD")] = ((dif - dea) * 2).round(4)
    return out


def add_rsi(df: pd.DataFrame, col: str, n=14) -> pd.DataFrame:
    out = df.copy()
    diff = out[col].diff()
    up = diff.clip(lower=0)
    down = (-diff).clip(lower=0)
    avg_up = up.ewm(alpha=1 / n, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_up / avg_down.replace(0, np.nan)
    out[_mk_col(col, f"RSI{n}")] = (100 - 100 / (1 + rs)).round(2)
    return out


def add_boll(df: pd.DataFrame, col: str, n=20, k=2.0) -> pd.DataFrame:
    out = df.copy()
    mid = out[col].rolling(n).mean()
    std = out[col].rolling(n).std(ddof=1)
    out[_mk_col(col, "BOLL中轨")] = mid.round(4)
    out[_mk_col(col, "BOLL上轨")] = (mid + k * std).round(4)
    out[_mk_col(col, "BOLL下轨")] = (mid - k * std).round(4)
    return out


def add_kdj(df: pd.DataFrame, ohlcv: dict, n=9, m1=3, m2=3) -> pd.DataFrame:
    out = df.copy()
    low_n = out[ohlcv["low"]].rolling(n, min_periods=1).min()
    high_n = out[ohlcv["high"]].rolling(n, min_periods=1).max()
    rsv = ((out[ohlcv["close"]] - low_n) / (high_n - low_n).replace(0, np.nan) * 100).fillna(50)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    base = ohlcv["close"]
    out[_mk_col(base, "K")] = k.round(2)
    out[_mk_col(base, "D")] = d.round(2)
    out[_mk_col(base, "J")] = (3 * k - 2 * d).round(2)
    return out


def add_atr(df: pd.DataFrame, ohlcv: dict, n=14) -> pd.DataFrame:
    out = df.copy()
    h, l, c = out[ohlcv["high"]], out[ohlcv["low"]], out[ohlcv["close"]]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    out[_mk_col(ohlcv["close"], f"ATR{n}")] = tr.ewm(alpha=1 / n, adjust=False).mean().round(4)
    return out


def add_obv(df: pd.DataFrame, ohlcv: dict) -> pd.DataFrame:
    out = df.copy()
    c, v = out[ohlcv["close"]], out[ohlcv["volume"]]
    direction = np.sign(c.diff()).fillna(0)
    obv = (direction * v).cumsum()
    out[_mk_col(ohlcv["close"], "OBV")] = obv.round(2)
    return out


def apply_tech_indicator(df: pd.DataFrame, params: dict):
    """统一入口：给 df 追加技术指标新列，返回 (新df, 摘要)。"""
    indicator = params.get("indicator", "")
    ohlcv = _map_roles(df)
    close_col = params.get("close") or ohlcv.get("close", "")
    if close_col not in df.columns:
        raise FinanceError("需要收盘价列（自动识别失败时请先在清洗中重命名列）")
    needs_hl = indicator in ("kdj", "atr")
    if needs_hl and ("high" not in ohlcv or "low" not in ohlcv):
        raise FinanceError(f"{indicator.upper()} 需要最高价与最低价列")
    if indicator == "obv" and "volume" not in ohlcv:
        raise FinanceError("OBV 需要成交量列")

    if indicator == "ma":
        n = int(params.get("n", 5))
        out = add_ma(df, close_col, n, "ma")
        msg = f"生成 {close_col}_MA{n}"
    elif indicator == "ema":
        n = int(params.get("n", 12))
        out = add_ma(df, close_col, n, "ema")
        msg = f"生成 {close_col}_EMA{n}"
    elif indicator == "macd":
        out = add_macd(df, close_col)
        msg = f"生成 DIF / DEA / MACD 三列（12,26,9）"
    elif indicator == "rsi":
        n = int(params.get("n", 14))
        out = add_rsi(df, close_col, n)
        msg = f"生成 {close_col}_RSI{n}"
    elif indicator == "boll":
        out = add_boll(df, close_col)
        msg = "生成 BOLL 上/中/下轨三列（20,2）"
    elif indicator == "kdj":
        out = add_kdj(df, ohlcv)
        msg = "生成 K / D / J 三列（9,3,3）"
    elif indicator == "atr":
        n = int(params.get("n", 14))
        out = add_atr(df, ohlcv, n)
        msg = f"生成 ATR{n}"
    elif indicator == "obv":
        out = add_obv(df, ohlcv)
        msg = "生成 OBV 能量潮"
    else:
        raise FinanceError(f"未知指标: {indicator}")
    return out, msg


# ---------------- K线图数据 ----------------


def kline_payload(df: pd.DataFrame, params: dict) -> dict:
    """输出 ECharts candlestick 数据：[日期, 开, 收, 低, 高, 成交量] + MA 线。"""
    ohlcv = detect_ohlcv(df)
    if not ohlcv:
        raise FinanceError("未识别到 K 线所需的 日期+开盘+最高+最低+收盘 列（可检查列名）")
    for role in ("open", "high", "low"):
        if role not in ohlcv:
            raise FinanceError(f"缺少{ {'open': '开盘', 'high': '最高', 'low': '最低'}[role] }列，无法绘制K线")
    tmp = _sorted_prices(df, ohlcv)
    dates = [str(d)[:10] for d in tmp["__date"]]
    o = pd.to_numeric(tmp[ohlcv["open"]], errors="coerce")
    h = pd.to_numeric(tmp[ohlcv["high"]], errors="coerce")
    l = pd.to_numeric(tmp[ohlcv["low"]], errors="coerce")
    c = pd.to_numeric(tmp[ohlcv["close"]], errors="coerce")
    v = pd.to_numeric(tmp[ohlcv["volume"]], errors="coerce") if "volume" in ohlcv else None
    kdata = [[round(float(a), 4), round(float(b), 4), round(float(d), 4), round(float(e), 4)]
             for a, b, d, e in zip(o, c, l, h)]
    ma_lines = {}
    for n in (5, 10, 20, 60):
        ma_lines[f"MA{n}"] = [None if pd.isna(x) else round(float(x), 4) for x in c.rolling(n).mean()]
    return {
        "kind": "kline",
        "dates": dates,
        "kdata": kdata,
        "ma": ma_lines,
        "volumes": None if v is None else [None if pd.isna(x) else float(x) for x in v],
        "note": f"K线图：{len(dates)} 根，MA5/10/20/60" + ("，含成交量" if v is not None else ""),
        "columns": [], "rows": [],
    }


# ---------------- 基准对比 / CAPM ----------------


def _returns_by_date(df: pd.DataFrame, close_col: str, date_col: str) -> pd.Series:
    tmp = pd.DataFrame({
        "date": _date_series(df, date_col),
        "close": pd.to_numeric(df[close_col], errors="coerce"),
    }).dropna().sort_values("date").drop_duplicates("date").set_index("date")["close"]
    return tmp.pct_change().dropna()


def benchmark_compare(df: pd.DataFrame, bdf: pd.DataFrame, params: dict) -> dict:
    """CAPM：资产 vs 基准。params: close, bclose, (bdate), rf。"""
    ohlcv = detect_ohlcv(df)
    bohlcv = detect_ohlcv(bdf)
    close_col = params.get("close") or ohlcv.get("close", "")
    bclose_col = params.get("bclose") or bohlcv.get("close", "")
    if close_col not in df.columns or bclose_col not in bdf.columns:
        raise FinanceError("资产或基准缺少收盘价列")
    date_col = params.get("date") or ohlcv.get("date", "")
    bdate_col = params.get("bdate") or bohlcv.get("date", "")
    if not date_col or not bdate_col:
        raise FinanceError("资产与基准都需要日期列用于对齐")
    rf_daily = float(params.get("rf", 0.02)) / TRADING_DAYS

    ra = _returns_by_date(df, close_col, date_col)
    rb = _returns_by_date(bdf, bclose_col, bdate_col)
    aligned = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(aligned) < 20:
        raise FinanceError(f"资产与基准按日期对齐后仅 {len(aligned)} 个共同交易日（至少 20）")
    ra, rb = aligned.iloc[:, 0], aligned.iloc[:, 1]

    cov = float(np.cov(ra, rb, ddof=1)[0][1])
    var_b = float(np.var(rb, ddof=1))
    beta = cov / var_b if var_b > 0 else None
    alpha_daily = float(np.mean(ra) - beta * np.mean(rb)) if beta is not None else None
    alpha_ann = alpha_daily * TRADING_DAYS if alpha_daily is not None else None
    excess = ra - rb
    tracking_err = float(np.std(excess, ddof=1) * np.sqrt(TRADING_DAYS))
    info_ratio = float(np.mean(excess) * TRADING_DAYS / tracking_err) if tracking_err > 0 else None
    corr = float(np.corrcoef(ra, rb)[0][1])
    ann_ret = float(np.mean(ra) * TRADING_DAYS)
    cum_asset = float((1 + ra).prod() - 1)
    cum_bench = float((1 + rb).prod() - 1)

    def _r(x, nd=4):
        return None if x is None else round(float(x), nd)

    # 回归散点（抽样≤800）
    step = max(1, len(ra) // 800)
    xs = [round(float(x), 6) for x in rb.iloc[::step]]
    ys = [round(float(x), 6) for x in ra.iloc[::step]]
    reg_x = [min(xs), max(xs)]
    reg_y = [alpha_daily + beta * x for x in reg_x] if beta is not None else []

    return {
        "kind": "capm",
        "beta": _r(beta, 4),
        "alpha_annual": _r(alpha_ann, 4),
        "correlation": _r(corr, 4),
        "r_squared": _r(corr * corr, 4),
        "tracking_error": _r(tracking_err, 4),
        "info_ratio": _r(info_ratio, 3),
        "cum_return": _r(cum_asset, 4),
        "cum_benchmark": _r(cum_bench, 4),
        "excess_annual": _r(ann_ret - float(np.mean(rb)) * TRADING_DAYS, 4),
        "n_days": int(len(aligned)),
        "scatter": {"x": xs, "y": ys, "reg_x": reg_x, "reg_y": reg_y,
                     "xlabel": "基准收益率", "ylabel": "资产收益率"},
        "groups": [
            {"name": "CAPM 回归", "items": [
                {"label": "Beta（系统性风险）", "value": _r(beta, 4)},
                {"label": "Alpha（年化超额）", "value": _r(alpha_ann, 4)},
                {"label": "相关系数 / R²", "value": f"{_r(corr, 4)} / {_r(corr * corr, 4)}"},
            ]},
            {"name": "相对表现", "items": [
                {"label": "区间收益（资产 vs 基准）", "value": f"{cum_asset * 100:.2f}% vs {cum_bench * 100:.2f}%"},
                {"label": "跟踪误差（年化）", "value": _r(tracking_err, 4)},
                {"label": "信息比率 IR", "value": _r(info_ratio, 3)},
                {"label": "共同交易日", "value": len(aligned)},
            ]},
        ],
        "note": "CAPM：R资产 = α + β·R基准 + ε（日频对齐，α 年化×252）",
        "columns": [], "rows": [],
    }


# ---------------- 投资组合 ----------------


def portfolio_analysis(dfs: list, params: dict) -> dict:
    """dfs: [{name, df, close, date}]。权重等权或自定义；输出组合指标+有效前沿。"""
    if not (2 <= len(dfs) <= 5):
        raise FinanceError("组合需要 2~5 个资产（各选一个收盘列）")
    rf = float(params.get("rf", 0.02))
    weights_in = params.get("weights") or []
    rets = {}
    for item in dfs:
        ohlcv = detect_ohlcv(item["df"])
        close = item.get("close") or ohlcv.get("close", "")
        date = item.get("date") or ohlcv.get("date", "")
        if close not in item["df"].columns or not date:
            raise FinanceError(f"资产 [{item['name']}] 缺少收盘或日期列")
        rets[item["name"]] = _returns_by_date(item["df"], close, date)
    R = pd.DataFrame(rets).dropna()
    if len(R) < 30:
        raise FinanceError(f"各资产按日期对齐后仅 {len(R)} 个共同交易日（至少 30）")

    n = R.shape[1]
    mean_ann = R.mean() * TRADING_DAYS
    cov_ann = R.cov() * TRADING_DAYS

    if weights_in and len(weights_in) == n:
        w = np.array(weights_in, dtype=float)
        if np.any(w < 0) or abs(w.sum()) < 1e-9:
            raise FinanceError("权重需为非负数")
        w = w / w.sum()
        w_label = "自定义"
    else:
        w = np.ones(n) / n
        w_label = "等权"

    def port_stats(w):
        ret = float(w @ mean_ann)
        vol = float(np.sqrt(w @ cov_ann.values @ w))
        return ret, vol

    port_ret, port_vol = port_stats(w)
    sharpe = (port_ret - rf) / port_vol if port_vol > 0 else None

    # 有效前沿：随机权重（Dirichlet 保证和为1且非负）
    rng = np.random.default_rng(42)
    W = rng.dirichlet(np.ones(n) * 2.0, size=2000)
    frontier = []
    for wi in W:
        r, v = port_stats(wi)
        frontier.append((v, r, (r - rf) / v if v > 0 else 0))
    min_var = min(frontier, key=lambda t: t[0])
    max_sharpe = max(frontier, key=lambda t: t[2])

    def _r(x, nd=4):
        return None if x is None else round(float(x), nd)

    corr = R.corr().round(3)
    return {
        "kind": "portfolio",
        "assets": list(R.columns),
        "weights": [round(float(x), 4) for x in w],
        "weights_label": w_label,
        "n_days": int(len(R)),
        "groups": [
            {"name": "组合（{}）".format(w_label), "items": [
                {"label": "年化收益", "value": "{:.2%}".format(port_ret)},
                {"label": "年化波动", "value": "{:.2%}".format(port_vol)},
                {"label": "Sharpe", "value": _r(sharpe, 3)},
            ]},
            {"name": "有效前沿关键点", "items": [
                {"label": "最小方差组合", "value": "波动 {:.2%} · 收益 {:.2%}".format(min_var[0], min_var[1])},
                {"label": "最大Sharpe组合", "value": "波动 {:.2%} · 收益 {:.2%} · S={:.2f}".format(max_sharpe[0], max_sharpe[1], max_sharpe[2])},
            ]},
        ],
        "frontier": {
            "vols": [round(float(v), 5) for v, _, _ in frontier],
            "rets": [round(float(r), 5) for _, r, _ in frontier],
            "min_var": [min_var[0], min_var[1]],
            "max_sharpe": [max_sharpe[0], max_sharpe[1]],
            "current": [port_vol, port_ret],
        },
        "corr_matrix": {
            "columns": list(corr.columns),
            "values": [[None if pd.isna(v) else float(v) for v in row] for row in corr.values],
        },
        "note": "{} 资产组合 · {} 个共同交易日 · 前沿为 2000 组随机权重".format(n, len(R)),
        "columns": [], "rows": [],
    }


# ---------------- 金融计量检验 ----------------


def adf_test(df: pd.DataFrame, params: dict) -> dict:
    """ADF 单位根检验（自实现 OLS）。params: column, trend(bool), max_lag。"""
    column = params.get("column", "")
    if column not in df.columns:
        raise FinanceError("列不存在: {}".format(column))
    y = pd.to_numeric(df[column], errors="coerce").dropna()
    n = len(y)
    if n < 25:
        raise FinanceError("样本过少（ADF 至少需要 25 个观测）")
    trend = bool(params.get("trend", False))
    max_lag = int(params.get("max_lag", 1))
    lags = max(0, min(max_lag, max(1, (n - 25) // 10)))

    dy = y.diff().dropna()          # Δy_t, 长度 n-1
    y_lag = y.shift(1).dropna()     # y_{t-1}, 长度 n-1
    # 对齐：去掉前 lags 行
    y_dep = dy.values[lags:]
    y_lag_v = y_lag.values[lags:]
    parts = [np.ones(len(y_dep))]
    if trend:
        parts.append(np.arange(1, len(y_dep) + 1, dtype=float))
    for i in range(1, lags + 1):
        parts.append(dy.shift(i).values[lags:])
    Xm = np.column_stack(parts + [y_lag_v])  # γ 是最后一个系数

    beta, _, _, _ = np.linalg.lstsq(Xm, y_dep, rcond=None)
    resid = y_dep - Xm @ beta
    dof = len(y_dep) - Xm.shape[1]
    if dof <= 0:
        raise FinanceError("自由度不足")
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(Xm.T @ Xm)
    se_gamma = float(np.sqrt(sigma2 * XtX_inv[-1, -1]))
    gamma = float(beta[-1])
    t_stat = gamma / se_gamma

    if trend:
        crit = {"1%": -3.96, "5%": -3.41, "10%": -3.12}
        case = "含常数与趋势"
    else:
        crit = {"1%": -3.43, "5%": -2.86, "10%": -2.57}
        case = "含常数"
    level = next((k for k in ("1%", "5%", "10%") if t_stat < crit[k]), None)
    stationary = t_stat < crit["5%"]

    return {
        "kind": "adf",
        "column": str(column),
        "tests": [{
            "name": "ADF（{}，滞后 {}）".format(case, lags),
            "stat": round(t_stat, 4),
            "p": None,
            "significant": stationary,
            "verdict": ("拒绝单位根 → 序列平稳" if stationary else "不能拒绝单位根 → 序列非平稳")
                       + ("（{}显著）".format(level) if level else ""),
        }],
        "critical_values": crit,
        "n": n,
        "note": "ADF 检验：t 统计量与 MacKinnon 近似临界值比较（教学用近似，非精确 p 值）",
        "columns": [], "rows": [],
    }


def ljung_box_test(df: pd.DataFrame, params: dict) -> dict:
    """Ljung-Box 自相关检验。params: column, lags(list|int)。"""
    from scipy import stats as sps

    column = params.get("column", "")
    if column not in df.columns:
        raise FinanceError("列不存在: {}".format(column))
    x = pd.to_numeric(df[column], errors="coerce").dropna()
    n = len(x)
    if n < 20:
        raise FinanceError("样本过少（至少 20 个观测）")
    lags_in = params.get("lags", [1, 5, 10, 20])
    if isinstance(lags_in, int):
        lags_in = [lags_in]
    lags = sorted({int(l) for l in lags_in if 1 <= int(l) <= min(30, n // 3)})
    if not lags:
        raise FinanceError("滞后阶无效")

    tests = []
    for k in lags:
        q = n * (n + 2) * sum(
            float(x.autocorr(lag=j)) ** 2 / (n - j) for j in range(1, k + 1)
        )
        p = float(1 - sps.chi2.cdf(q, k))
        tests.append({
            "name": "滞后 {} 阶".format(k),
            "stat": round(q, 3),
            "p": round(p, 6),
            "significant": p < 0.05,
            "verdict": "存在自相关" if p < 0.05 else "无显著自相关",
        })
    return {
        "kind": "ljung_box",
        "column": str(column),
        "tests": tests,
        "n": n,
        "note": "Ljung-Box Q 检验：H0=序列无自相关（白噪声）",
        "columns": [], "rows": [],
    }



def make_stock_sample(n: int = 250, seed: int = 7) -> pd.DataFrame:
    """生成示例股票日线（几何布朗运动+阶段性趋势），离线体验金融功能。"""
    rng = np.random.default_rng(seed)
    # 三段趋势：上涨→回撤→震荡上行
    drift = np.concatenate([
        np.full(n // 3, 0.0015), np.full(n // 3, -0.0012), np.full(n - 2 * (n // 3), 0.0009),
    ])[:n]
    rets = drift + rng.normal(0, 0.018, n)
    close = 20.0 * np.exp(np.cumsum(rets))
    open_ = close * np.exp(rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.007, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.007, n)))
    vol = rng.integers(800_000, 6_000_000, n) * (1 + np.abs(rets) * 20)
    return pd.DataFrame({
        "日期": pd.bdate_range("2024-01-02", periods=n).strftime("%Y-%m-%d"),
        "开盘": open_.round(3), "最高": high.round(3), "最低": low.round(3),
        "收盘": close.round(3),
        "成交量": (vol // 100).astype("int64") * 100,
        "成交额": (vol * close).round(0),
    })
