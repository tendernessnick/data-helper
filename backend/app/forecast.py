"""时间序列预测：线性趋势 / Holt 指数平滑 / 季节朴素法，留出回测自动选优。

纯 numpy 实现，无需 statsmodels。输出历史 + 预测区间。
"""
import numpy as np
import pandas as pd

from .analysis import AnalysisError, FREQ_MAP, FREQ_LABEL, _resample_series

SEASON_M = {"D": 7, "W": 4, "M": 12, "Q": 4, "Y": 1}


def _linear_fit(series: pd.Series):
    t = np.arange(len(series), dtype=float)
    coef = np.polyfit(t, series.values, 1)
    return lambda tt: coef[0] * tt + coef[1]


def _holt_fit(series: pd.Series):
    """Holt 线性趋势指数平滑，网格搜索 alpha/beta。"""
    y = series.values.astype(float)
    n = len(y)
    best = None
    for alpha in (0.2, 0.4, 0.6, 0.8, 0.9):
        for beta in (0.05, 0.1, 0.2, 0.3):
            level, trend = y[0], y[1] - y[0]
            sse = 0.0
            for i in range(1, n):
                forecast = level + trend
                err = y[i] - forecast
                sse += err * err
                prev_level = level
                level = alpha * y[i] + (1 - alpha) * (level + trend)
                trend = beta * (level - prev_level) + (1 - beta) * trend
            if best is None or sse < best[0]:
                best = (sse, alpha, beta, level, trend)
    sse, alpha, beta, level, trend = best

    def predict(tt):
        h = np.asarray(tt, dtype=float) - (n - 1)  # 相对最后一个观测点的步数
        return level + h * trend

    return predict


def _seasonal_naive_fit(series: pd.Series, m: int):
    y = series.values.astype(float)
    pattern = y[-m:] if len(y) >= m else y

    def predict(tt):
        return np.array([pattern[(int(t) - len(y)) % len(pattern)] for t in np.asarray(tt, dtype=float)])

    return predict


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    mask = np.abs(actual) > 1e-9
    if not mask.any():
        return float("inf")
    return float((np.abs((actual[mask] - pred[mask]) / actual[mask])).mean() * 100)


def forecast(df: pd.DataFrame, params: dict) -> dict:
    date_col = params.get("date_column", "")
    value_col = params.get("value_column", "")
    freq = params.get("freq", "M")
    horizon = int(params.get("horizon", 6))
    horizon = max(1, min(horizon, 36))
    if not date_col or not value_col:
        raise AnalysisError("预测需要日期列与数值列")
    series = _resample_series(df, date_col, value_col, freq, "sum")
    if len(series) < 8:
        raise AnalysisError(f"历史数据点过少（{len(series)} 个，按当前粒度至少需要 8 个期间）")

    m = SEASON_M.get(freq, 1)
    holdout = max(2, min(int(round(len(series) * 0.2)), len(series) - 5, 8))
    train, test = series.iloc[:-holdout], series.iloc[-holdout:]

    candidates = {
        "线性趋势": _linear_fit(train),
        "指数平滑(Holt)": _holt_fit(train),
    }
    if m >= 2 and len(train) >= m + 2:
        candidates[f"季节朴素(m={m})"] = _seasonal_naive_fit(train, m)

    backtest = []
    test_t = np.arange(len(train), len(series), dtype=float)
    test_pred = {}
    for name, fit in candidates.items():
        pred = fit(test_t)
        test_pred[name] = pred
        backtest.append({"name": name, "mape": round(_mape(test.values, pred), 2)})

    backtest.sort(key=lambda b: b["mape"])
    best_name = backtest[0]["name"]

    # 用全量数据重训最优方法
    full_fit = {"线性趋势": _linear_fit, "指数平滑(Holt)": _holt_fit}.get(best_name)
    if full_fit is not None:
        predict = full_fit(series)
    else:
        predict = _seasonal_naive_fit(series, m)
    last_t = len(series) - 1
    future_t = np.arange(last_t + 1, last_t + 1 + horizon, dtype=float)
    point = predict(future_t)
    point = np.maximum(point, 0)

    # 预测区间：用最优方法回测残差 std
    resid_std = float(np.std(test.values - test_pred[best_name], ddof=1)) if len(test) > 1 else 0.0
    freq_lbl = FREQ_LABEL.get(freq, freq)
    rule = FREQ_MAP.get(freq, "MS")
    if rule == "W":
        future_idx = pd.date_range(series.index[-1] + pd.Timedelta(weeks=1), periods=horizon, freq="W")
    else:
        future_idx = pd.date_range(series.index[-1] + pd.tseries.frequencies.to_offset(rule), periods=horizon, freq=rule)

    history_rows = [[idx.strftime("%Y-%m-%d"), round(float(v), 4), None, False] for idx, v in series.items()]
    future_rows = [
        [
            idx.strftime("%Y-%m-%d"),
            None,
            {
                "value": round(float(v), 4),
                "lower": round(float(max(v - 1.96 * resid_std, 0)), 4),
                "upper": round(float(v + 1.96 * resid_std), 4),
            },
            True,
        ]
        for idx, v in zip(future_idx, point)
    ]
    return {
        "columns": [
            {"name": "期间", "numeric": False},
            {"name": f"实际值", "numeric": True},
            {"name": f"预测值（{best_name}）", "numeric": True},
            {"name": "is_forecast", "numeric": False, "hidden": True},
        ],
        "rows": history_rows + future_rows,
        "backtest": backtest,
        "best": best_name,
        "horizon": horizon,
        "band": round(1.96 * resid_std, 4),
        "note": f"预测 {horizon} 个{freq_lbl}期间：最优方法「{best_name}」（回测 MAPE {backtest[0]['mape']}%），区间=±1.96×回测残差标准差",
        "forecast_meta": {
            "labels": [r[0] for r in future_rows],
            "values": [r[2]["value"] for r in future_rows],
            "lower": [r[2]["lower"] for r in future_rows],
            "upper": [r[2]["upper"] for r in future_rows],
            "history_labels": [r[0] for r in history_rows],
            "history_values": [r[1] for r in history_rows],
        },
        "chart": {"type": "line", "label_col": "期间"},
    }
