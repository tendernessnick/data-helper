"""增强版：SQL 控制台 / 深度画像 / 统计检验 / 预测 / 列变换 / 对比 / 采样 / 图表推荐。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def upload_df(df, name="t.csv"):
    r = client.post(
        "/api/upload",
        files={"file": (name, df.to_csv(index=False).encode("utf-8-sig"), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def sales_df(n=120):
    rng = np.random.default_rng(7)
    rows = []
    for i in range(n):
        rows.append({
            "日期": (date(2025, 1, 1) + timedelta(days=i)).isoformat(),
            "地区": ["华东", "华南", "华北"][i % 3],
            "渠道": ["线上", "线下"][i % 2],
            "销售额": float(1000 + i * 10 + rng.normal(0, 50)),
            "数量": int(1 + i % 9),
            "利润": float(100 + i * 2 + rng.normal(0, 10)),
        })
    return pd.DataFrame(rows)


# ---------- SQL ----------


def test_sql_basic_and_tables():
    ds = upload_df(sales_df())
    tables = client.get("/api/sql/tables").json()
    assert any(t["id"] == ds for t in tables)
    alias = next(t["alias"] for t in tables if t["id"] == ds)
    r = client.post("/api/sql", json={"query": f"SELECT 地区, COUNT(*) AS n FROM {alias} GROUP BY 地区 ORDER BY n"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert {row[0] for row in body["rows"]} == {"华东", "华南", "华北"}


def test_sql_df_alias_and_save():
    ds = upload_df(sales_df())  # 最新上传的会成为 df
    r = client.post("/api/sql", json={"query": "SELECT COUNT(*) AS c FROM df", "save_as": "SQL结果", "current_id": ds})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"][0][0] == 120
    # 保存的是查询结果表（COUNT 查询结果为 1 行）
    assert body["new_dataset"]["meta"]["rows"] == 1


def test_sql_rejects_mutation():
    upload_df(sales_df())
    for q in ["DELETE FROM df", "INSERT INTO df VALUES (1)", "CREATE TABLE x(a int)", "PRAGMA foo"]:
        r = client.post("/api/sql", json={"query": q})
        assert r.status_code == 400, q


def test_sql_syntax_error_400():
    upload_df(sales_df())
    r = client.post("/api/sql", json={"query": "SELECT FROM df WHERE"})
    assert r.status_code == 400
    assert "SQL 执行出错" in r.json()["detail"]


# ---------- 深度画像 ----------


def test_corr_methods():
    ds = upload_df(sales_df())
    for m in ("pearson", "spearman", "kendall"):
        r = client.get(f"/api/datasets/{ds}/corr?method={m}")
        assert r.status_code == 200, m
        body = r.json()
        assert "销售额" in body["columns"]
    assert client.get(f"/api/datasets/{ds}/corr?method=nope").status_code == 400


def test_missing_matrix_and_duplicates():
    df = sales_df(50)
    df.loc[0:9, "销售额"] = None
    df = pd.concat([df, df.head(3)], ignore_index=True)
    ds = upload_df(df)
    mm = client.get(f"/api/datasets/{ds}/missing-matrix").json()
    assert len(mm["values"]) == 40 and any(any(v > 0 for v in row) for row in mm["values"])
    dup = client.get(f"/api/datasets/{ds}/duplicates").json()
    assert dup["total_dup_rows"] >= 6  # 3行×2次


def test_interactions():
    ds = upload_df(sales_df())
    r = client.get(f"/api/datasets/{ds}/interactions", params={"x": "销售额", "y": "利润"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) <= 1000
    assert abs(body["spearman"]) > 0.5  # 构造数据强相关


def test_text_stats_endpoint_via_insights():
    ds = upload_df(sales_df(30))
    ins = client.get(f"/api/datasets/{ds}/insights").json()
    assert ins["overview"]["rows"] == 30










def _clean(ds, op, params):
    return client.post(f"/api/datasets/{ds}/clean", json={"op": op, "params": params})


def test_bin_and_onehot():
    df = pd.DataFrame({"分数": range(10, 101, 10), "等级": (["低", "中", "高"] * 4)[:10]})
    ds = upload_df(df)
    r = _clean(ds, "bin_column", {"column": "分数", "method": "equal_width", "bins": 3, "labels": ["低", "中", "高"]})
    assert r.status_code == 200, r.text
    cols = [c["name"] for c in client.get(f"/api/datasets/{ds}/rows").json()["columns"]]
    assert "分数_箱" in cols
    r2 = _clean(ds, "one_hot_encode", {"column": "等级"})
    assert r2.status_code == 200
    cols2 = [c["name"] for c in client.get(f"/api/datasets/{ds}/rows").json()["columns"]]
    assert any(c.startswith("等级_") for c in cols2)


def test_standardize_log():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    ds = upload_df(df)
    r = _clean(ds, "standardize_column", {"column": "x", "method": "zscore"})
    assert r.status_code == 200
    rows = client.get(f"/api/datasets/{ds}/rows").json()["rows"]
    zs = [row[1] for row in rows]
    assert abs(sum(zs)) < 1e-6
    r2 = _clean(ds, "log_transform", {"column": "x"})
    assert r2.status_code == 200
    # 负值拒绝
    ds2 = upload_df(pd.DataFrame({"x": [-1.0, 2.0]}))
    assert _clean(ds2, "log_transform", {"column": "x"}).status_code == 400


def test_date_parts_and_regex():
    df = pd.DataFrame({"日期": ["2025-03-15", "2024-12-01"], "单号": ["SO-001", "SO-002"]})
    ds = upload_df(df)
    r = _clean(ds, "extract_date_parts", {"column": "日期", "parts": ["year", "month", "weekday"]})
    assert r.status_code == 200
    cols = [c["name"] for c in client.get(f"/api/datasets/{ds}/rows").json()["columns"]]
    assert "日期_年" in cols and "日期_星期" in cols
    r2 = _clean(ds, "regex_extract", {"column": "单号", "pattern": r"SO-(\d+)", "new_column": "编号"})
    assert r2.status_code == 200
    rows = client.get(f"/api/datasets/{ds}/rows").json()["rows"]
    assert rows[0][-1] == "001"
    assert _clean(ds, "regex_extract", {"column": "单号", "pattern": "("}).status_code == 400


# ---------- 对比 / 采样 / 图表推荐 ----------



def test_sample_create():
    ds = upload_df(sales_df(200))
    r = client.post(f"/api/datasets/{ds}/sample-create", json={"method": "random", "n": 50, "name": "随机样本"})
    assert r.status_code == 200
    assert r.json()["meta"]["rows"] == 50
    r2 = client.post(f"/api/datasets/{ds}/sample-create", json={"method": "stratified", "n": 2, "by": "地区"})
    assert r2.status_code == 200
    assert r2.json()["meta"]["rows"] == 6  # 3组 × 2


def test_chart_suggest_and_cross_heat():
    ds = upload_df(sales_df(100))
    r = client.get(f"/api/datasets/{ds}/chart-suggest")
    assert r.status_code == 200
    kinds = {s["kind"] for s in r.json()}
    assert "trend" in kinds and "groupby" in kinds and "scatter" in kinds
    r2 = client.post(f"/api/datasets/{ds}/cross-heat", json={"params": {"row": "地区", "col": "渠道"}})
    assert r2.status_code == 200
    body = r2.json()
    assert body["heatmap"]["values"][0][0] >= 0


# ---------- AI 自然语言出图 ----------


def test_ai_chart_spec_to_card():
    from unittest import mock
    ds = upload_df(sales_df(100))
    client.put("/api/ai/settings", json={"api_key": "sk-x", "base_url": "https://fake/v4", "model": "m"})
    fake = mock.Mock()
    fake.status_code = 200
    fake.json.return_value = {"choices": [{"message": {"content": '```json\n{"kind": "groupby", "params": {"by": ["地区"], "metrics": [{"column": "销售额", "agg": "sum"}]}, "title": "各地区销售额"}\n```'}}]}
    with mock.patch.object(__import__("backend.app.ai", fromlist=["requests"]).requests, "post", return_value=fake):
        r = client.post("/api/ai/chart", json={"dataset_id": ds, "prompt": "各地区的销售额"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_spec"]["title"] == "各地区销售额"
    assert {row[0] for row in body["rows"]} == {"华东", "华南", "华北"}
    client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})


def test_ai_chart_bad_json_400():
    from unittest import mock
    ds = upload_df(sales_df(50))
    client.put("/api/ai/settings", json={"api_key": "sk-x", "base_url": "https://fake/v4", "model": "m"})
    fake = mock.Mock()
    fake.status_code = 200
    fake.json.return_value = {"choices": [{"message": {"content": "我觉得画个图挺好的"}}]}
    with mock.patch.object(__import__("backend.app.ai", fromlist=["requests"]).requests, "post", return_value=fake):
        r = client.post("/api/ai/chart", json={"dataset_id": ds, "prompt": "画图"})
    assert r.status_code == 400
    assert "图表配置" in r.json()["detail"]
    client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})


def test_quality_score_in_insights():
    ds = upload_df(sales_df(80))
    ins = client.get(f"/api/datasets/{ds}/insights").json()
    qs = ins["quality_score"]
    assert 0 <= qs["score"] <= 100
    assert qs["level"] in ("优秀", "良好", "一般", "较差")
    assert qs["color"].startswith("#")


def test_sql_save_as_not_truncated_by_preview_cap(monkeypatch):
    """回归：SQL 建集保存完整结果，预览行数封顶只影响响应里的 rows。"""
    from backend.app import sqlquery as sq

    big = pd.DataFrame({"v": range(37)})
    monkeypatch.setattr(sq, "MAX_ROWS", 10)
    ds = upload_df(big, "big.csv")
    r = client.post("/api/sql", json={"query": f"SELECT v FROM {_alias_of(ds)} WHERE v >= 0", "save_as": "全量建集"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 37 and body["truncated"] is True
    assert len(body["rows"]) == 10  # 预览封顶
    assert body["new_dataset"]["meta"]["rows"] == 37  # 建集不截断


def _alias_of(ds_id: str) -> str:
    return next(t["alias"] for t in client.get("/api/sql/tables").json() if t["id"] == ds_id)
