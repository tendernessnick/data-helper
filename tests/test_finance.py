"""金融模块：列识别 / 收益风险 / 技术指标 / K线 / CAPM / 组合 / ADF / LB。"""
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.app import finance
from backend.app.main import app

client = TestClient(app)


def make_stock_df(n=200, seed=7, start=100.0, drift=0.001, vol=0.02):
    rng = np.random.default_rng(seed)
    close = start * (1 + rng.normal(drift, vol, n)).cumprod()
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({
        "日期": pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
        "开盘": open_.round(3), "最高": high.round(3), "最低": low.round(3),
        "收盘": close.round(3), "成交量": rng.integers(1_000_000, 9_000_000, n),
    })


def upload_df(df, name="stock.csv"):
    r = client.post(
        "/api/upload",
        files={"file": (name, df.to_csv(index=False).encode("utf-8-sig"), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- 列识别 ----------


def test_detect_ohlcv_chinese_and_english():
    df_cn = make_stock_df(10)
    oh = finance.detect_ohlcv(df_cn)
    assert oh == {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"}
    df_en = pd.DataFrame({"Date": ["2025-01-01"], "Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
    oh_en = finance.detect_ohlcv(df_en)
    assert oh_en["close"] == "Close" and oh_en["date"] == "Date"
    # 非金融数据返回空
    assert finance.detect_ohlcv(pd.DataFrame({"姓名": ["a"], "年龄": [1]})) == {}


# ---------- 收益风险指标 ----------


def test_metrics_known_series():
    # 构造 3 期已知收益：+10%, -5%, +20% → 总收益 1.1*0.95*1.2-1 = 25.4%
    df = pd.DataFrame({
        "日期": ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
        "收盘": [100.0, 110.0, 104.5, 125.4],
    })
    m = finance.metrics_report(df, {"rf": 0.0})
    assert abs(m["groups"][0]["items"][0]["value"] == "25.40%") or "25.4" in m["groups"][0]["items"][0]["value"]
    # 最大回撤：110 → 104.5 = -5%
    dd_item = m["groups"][1]["items"][1]["value"]
    assert "-5.00%" in dd_item


def test_metrics_max_drawdown_and_curve():
    df = make_stock_df(300, seed=3)
    m = finance.metrics_report(df, {})
    assert len(m["curve"]["values"]) == 299
    assert m["groups"][2]["items"][0]["value"] is not None  # Sharpe 有值


# ---------- 技术指标 ----------


def test_tech_indicators_columns():
    df = make_stock_df(80)
    out, msg = finance.apply_tech_indicator(df, {"indicator": "ma", "n": 5})
    assert "收盘_MA5" in out.columns
    out2, _ = finance.apply_tech_indicator(df, {"indicator": "macd"})
    for c in ("收盘_DIF", "收盘_DEA", "收盘_MACD"):
        assert c in out2.columns
    out3, _ = finance.apply_tech_indicator(df, {"indicator": "rsi"})
    rsi = out3["收盘_RSI14"].dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()
    out4, _ = finance.apply_tech_indicator(df, {"indicator": "boll"})
    assert out4["收盘_BOLL上轨"].dropna().ge(out4["收盘_BOLL下轨"].dropna()).all()
    out5, _ = finance.apply_tech_indicator(df, {"indicator": "kdj"})
    assert {"收盘_K", "收盘_D", "收盘_J"} <= set(out5.columns)
    out6, _ = finance.apply_tech_indicator(df, {"indicator": "obv"})
    assert "收盘_OBV" in out6.columns


def test_tech_indicator_needs_columns():
    df = pd.DataFrame({"日期": ["2025-01-01"], "收盘": [1.0]})
    try:
        finance.apply_tech_indicator(df, {"indicator": "kdj"})
        assert False, "应抛错"
    except finance.FinanceError as e:
        assert "最高价" in str(e)


def test_ma_precision():
    df = pd.DataFrame({"收盘": [1.0, 2.0, 3.0, 4.0]})
    out, _ = finance.apply_tech_indicator(df, {"indicator": "ma", "n": 2})
    assert out["收盘_MA2"].tolist()[1:] == [1.5, 2.5, 3.5]


# ---------- K线 ----------


def test_kline_payload():
    df = make_stock_df(50)
    k = finance.kline_payload(df, {})
    assert len(k["dates"]) == 50
    assert len(k["kdata"]) == 50 and len(k["kdata"][0]) == 4
    assert k["volumes"] is not None
    assert set(k["ma"].keys()) == {"MA5", "MA10", "MA20", "MA60"}


# ---------- CAPM / 基准 ----------


def test_benchmark_beta_known():
    n = 150
    rng = np.random.default_rng(5)
    bench = 100 * (1 + rng.normal(0.0, 0.01, n)).cumprod()
    noise = rng.normal(0, 0.005, n)
    # 构造 beta=1.5：资产收益 = 1.5*基准收益 + 噪声
    br = pd.Series(bench).pct_change().dropna()
    ar = 1.5 * br + noise[1:]
    dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d")
    df_a = pd.DataFrame({"日期": dates[1:], "收盘": (1 + ar).cumprod() * 100})
    df_b = pd.DataFrame({"日期": dates[1:], "收盘": bench[1:]})
    res = finance.benchmark_compare(df_a, df_b, {})
    assert 1.2 < res["beta"] < 1.8  # 回归还原 beta≈1.5
    assert res["correlation"] > 0.9


# ---------- 组合 ----------


def test_portfolio_two_assets():
    n = 120
    dates = pd.bdate_range("2025-01-01", periods=n).strftime("%Y-%m-%d")
    df1 = pd.DataFrame({"日期": dates, "收盘": 100 * (1 + np.random.default_rng(1).normal(0.001, 0.02, n)).cumprod()})
    df2 = pd.DataFrame({"日期": dates, "收盘": 100 * (1 + np.random.default_rng(2).normal(0.0005, 0.03, n)).cumprod()})
    res = finance.portfolio_analysis(
        [{"name": "A", "df": df1}, {"name": "B", "df": df2}], {"rf": 0.02}
    )
    assert len(res["assets"]) == 2
    assert abs(sum(res["weights"]) - 1) < 1e-6  # 等权 0.5/0.5
    assert len(res["frontier"]["vols"]) == 2000
    assert res["corr_matrix"]["values"][0][1] == res["corr_matrix"]["values"][1][0]


def test_portfolio_needs_two():
    df = make_stock_df(60)
    try:
        finance.portfolio_analysis([{"name": "A", "df": df}], {})
        assert False
    except finance.FinanceError:
        pass


# ---------- ADF / LB ----------


def test_adf_random_walk_vs_stationary():
    n = 300
    rw = pd.Series(np.random.default_rng(9).normal(0, 1, n).cumsum())  # 随机游走：非平稳
    stat = pd.Series(np.random.default_rng(10).normal(0, 1, n))        # 白噪声：平稳
    r1 = finance.adf_test(pd.DataFrame({"y": rw}), {"column": "y"})
    r2 = finance.adf_test(pd.DataFrame({"y": stat}), {"column": "y"})
    assert r1["tests"][0]["significant"] is False   # 随机游走 → 非平稳
    assert r2["tests"][0]["significant"] is True    # 白噪声 → 平稳
    assert r2["tests"][0]["stat"] < r2["critical_values"]["1%"]


def test_adf_trend_option():
    n = 200
    t = np.arange(n, dtype=float)
    y = pd.Series(0.5 * t + np.random.default_rng(11).normal(0, 5, n))  # 趋势项
    r = finance.adf_test(pd.DataFrame({"y": y}), {"column": "y", "trend": True})
    assert "趋势" in r["tests"][0]["name"]


def test_ljung_box_ar1_detected():
    n = 300
    rng = np.random.default_rng(12)
    e = rng.normal(0, 1, n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.8 * x[i - 1] + e[i]  # AR(1) 强自相关
    r = finance.ljung_box_test(pd.DataFrame({"x": x}), {"column": "x", "lags": [1, 5]})
    assert all(t["significant"] for t in r["tests"])


def test_ljung_box_white_noise_mostly_insignificant():
    # 白噪声：多滞后阶中大多数应不显著（5% 假阳性允许个别显著）
    n = 400
    x = pd.Series(np.random.default_rng(77).normal(0, 1, n))
    r = finance.ljung_box_test(pd.DataFrame({"x": x}), {"column": "x", "lags": [1, 2, 3, 4, 5]})
    sig = sum(1 for t in r["tests"] if t["significant"])
    assert sig <= 2
