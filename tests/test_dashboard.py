"""运营看板（nio）：KPI 指标（含环比）/ 转化漏斗 / 钉卡配置持久化。"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.analysis import AnalysisError, funnel, kpi, run
from backend.app.main import app

client = TestClient(app)


def upload_csv(content: str, name="t.csv") -> str:
    r = client.post("/api/upload", files={"file": (name, content.encode("utf-8"), "text/csv")},
                    data={"name": "", "project": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- KPI ----------


def test_kpi_sum_without_date():
    df = __import__("pandas").DataFrame({"销售额": [100.0, 250.5, 49.5]})
    r = kpi(df, {"value_column": "销售额", "agg": "sum"})
    assert r["kind"] == "kpi" and r["value"] == 400.0
    assert r.get("delta_pct") is None and r.get("span_note") is None


def test_kpi_count_and_mean():

    df = pd.DataFrame({"销售额": [10.0, 20.0, 30.0]})
    assert kpi(df, {"agg": "count"})["value"] == 3
    assert kpi(df, {"value_column": "销售额", "agg": "mean"})["value"] == 20.0


def test_kpi_delta_with_date_column():
    # 近 2 天合计 30，前 2 天合计 10 → 环比 +200%

    df = pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "销售额": [5.0, 5.0, 15.0, 15.0],
    })
    r = kpi(df, {"value_column": "销售额", "agg": "sum", "date_column": "日期"})
    assert r["prev"] == 10.0 and r["value"] == 30.0
    assert r["delta_pct"] == 200.0
    assert "vs" in r["span_note"]


def test_kpi_delta_negative_and_zero_prev():

    df = pd.DataFrame({
        "日期": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "销售额": [10.0, 10.0, 5.0, 5.0],
    })
    r = kpi(df, {"value_column": "销售额", "agg": "sum", "date_column": "日期"})
    assert r["delta_pct"] == -50.0

    df0 = df.copy()
    df0.loc[df0.index[:2], "销售额"] = 0.0
    r0 = kpi(df0, {"value_column": "销售额", "agg": "sum", "date_column": "日期"})
    assert r0["delta_pct"] is None  # 上期为 0 时无法计算百分比


def test_kpi_unknown_column_rejected():

    df = pd.DataFrame({"a": [1]})
    with pytest.raises(AnalysisError):
        kpi(df, {"value_column": "不存在", "agg": "sum"})
    with pytest.raises(AnalysisError):
        run(df, "kpi", {"value_column": "a", "agg": "median"})  # 不支持的聚合


# ---------- 漏斗 ----------


def test_funnel_events_mode_with_user_dedup():

    df = pd.DataFrame({
        "事件": ["浏览", "浏览", "加购", "下单", "加购", "浏览", "下单"],
        "用户": ["u1", "u2", "u1", "u1", "u2", "u3", "u1"],
    })
    r = funnel(df, {"mode": "events", "column": "事件", "steps": ["浏览", "加购", "下单"], "user_column": "用户"})
    counts = [s["count"] for s in r["steps"]]
    assert counts == [3, 2, 1]  # 浏览 u1/u2/u3，加购 u1/u2，下单 u1（去重）
    assert r["steps"][1]["conv_from_prev"] == round(2 / 3 * 100, 1)
    assert r["total"] == 3
    assert "用户" in r["note"]


def test_funnel_events_row_mode_and_unknown_step():

    df = pd.DataFrame({"事件": ["浏览", "浏览", "下单", "退货"]})
    r = funnel(df, {"mode": "events", "column": "事件", "steps": ["浏览", "下单", "支付"]})
    assert [s["count"] for s in r["steps"]] == [2, 1, 0]
    assert r["steps"][2]["conv_from_prev"] == 0.0


def test_funnel_columns_mode_nonempty_as_reached():

    df = pd.DataFrame({
        "注册日期": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "首单日期": ["2026-01-05", None, None],
        "复购日期": [None, None, None],
    })
    r = funnel(df, {"mode": "columns", "columns": ["注册日期", "首单日期", "复购日期"]})
    assert [s["count"] for s in r["steps"]] == [3, 1, 0]
    assert r["steps"][1]["conv_from_prev"] == round(1 / 3 * 100, 1)


def test_funnel_validation():

    df = pd.DataFrame({"事件": ["a"]})
    with pytest.raises(AnalysisError):
        funnel(df, {"mode": "events", "column": "事件", "steps": ["a"]})  # 少于 2 步
    with pytest.raises(AnalysisError):
        funnel(df, {"mode": "columns", "columns": ["事件"]})
    with pytest.raises(AnalysisError):
        funnel(df, {"mode": "events", "column": "不存在", "steps": ["a", "b"]})


# ---------- 看板钉卡持久化 API ----------


def test_dashboard_crud_and_replay_contract():
    ds = upload_csv("日期,销售额,事件\n2026-01-01,10,浏览\n2026-01-02,20,下单\n")
    cfg = [
        {"kind": "kpi", "params": {"value_column": "销售额", "agg": "sum", "date_column": "日期"},
         "title": "KPI 指标", "icon": "🎯", "span2": False},
        {"kind": "funnel", "params": {"mode": "events", "column": "事件", "steps": ["浏览", "下单"]},
         "title": "转化漏斗", "icon": "⏬", "span2": True},
    ]
    assert client.put(f"/api/datasets/{ds}/dashboard", json={"cards": cfg}).status_code == 200
    r = client.get(f"/api/datasets/{ds}/dashboard")
    assert r.status_code == 200 and len(r.json()["cards"]) == 2

    # 重放契约：每条配置都能被 analyze/insights 真实执行
    for c in r.json()["cards"]:
        rr = client.post(f"/api/datasets/{ds}/analyze", json={"kind": c["kind"], "params": c["params"]})
        assert rr.status_code == 200, rr.text

    # 覆盖保存 + 越界拒绝 + 清空
    assert client.put(f"/api/datasets/{ds}/dashboard", json={"cards": cfg[:1]}).status_code == 200
    assert len(client.get(f"/api/datasets/{ds}/dashboard").json()["cards"]) == 1
    assert client.put(f"/api/datasets/{ds}/dashboard", json={"cards": [{"kind": "kpi"}] * 13}).status_code == 400
    assert client.delete(f"/api/datasets/{ds}/dashboard").status_code == 200
    assert client.get(f"/api/datasets/{ds}/dashboard").json()["cards"] == []


def test_dashboard_cleanup_on_dataset_delete():
    ds = upload_csv("a\n1\n")
    cfg = [{"kind": "kpi", "params": {"agg": "count"}, "title": "行数", "icon": "🎯", "span2": False}]
    client.put(f"/api/datasets/{ds}/dashboard", json={"cards": cfg})
    assert client.delete(f"/api/datasets/{ds}").status_code == 200
    assert storage._read_dashboards().get(ds) is None  # 删数据集连带清配置


def test_dashboard_requires_existing_dataset():
    assert client.get("/api/datasets/nope/dashboard").status_code == 404
    assert client.put("/api/datasets/nope/dashboard", json={"cards": []}).status_code == 404
