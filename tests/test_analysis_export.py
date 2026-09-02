"""阶段3：统计分析 / 导出。"""
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

CSV = (
    "日期,地区,产品,销售额,数量,成本\n"
    "2025-01-05,华东,键盘,1200,3,800\n"
    "2025-02-10,华南,鼠标,300,2,200\n"
    "2025-03-15,华东,显示器,3500,1,2800\n"
    "2025-04-20,华北,键盘,900,2,600\n"
    "2025-05-25,华南,鼠标,300,2,200\n"
)


def setup_ds():
    r = client.post(
        "/api/upload",
        files={"file": ("t.csv", CSV.encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def analyze(ds, kind, params=None):
    return client.post(f"/api/datasets/{ds}/analyze", json={"kind": kind, "params": params or {}})


def test_describe():
    ds = setup_ds()
    r = analyze(ds, "describe")
    assert r.status_code == 200
    body = r.json()
    names = [c["name"] for c in body["columns"]]
    assert names[0] == "统计量" and "销售额" in names
    stat_names = [row[0] for row in body["rows"]]
    assert "count" in stat_names and "mean" in stat_names


def test_groupby_sum():
    ds = setup_ds()
    r = analyze(ds, "groupby", {"by": ["地区"], "metrics": [{"column": "销售额", "agg": "sum"}]})
    assert r.status_code == 200
    body = r.json()
    data = {row[0]: row[1] for row in body["rows"]}
    assert data["华东"] == 4700 and data["华南"] == 600 and data["华北"] == 900


def test_groupby_multi_metric():
    ds = setup_ds()
    r = analyze(
        ds,
        "groupby",
        {"by": ["产品"], "metrics": [
            {"column": "销售额", "agg": "sum"},
            {"column": "销售额", "agg": "mean"},
            {"column": "数量", "agg": "count"},
        ]},
    )
    assert r.status_code == 200
    cols = [c["name"] for c in r.json()["columns"]]
    assert "销售额 / sum" in cols and "数量 / count" in cols


def test_groupby_bad_agg():
    ds = setup_ds()
    r = analyze(ds, "groupby", {"by": ["地区"], "metrics": [{"column": "销售额", "agg": "sumx"}]})
    assert r.status_code == 400


def test_pivot():
    ds = setup_ds()
    r = analyze(
        ds,
        "pivot",
        {"index": "地区", "columns": "产品", "values": "销售额", "aggfunc": "sum"},
    )
    assert r.status_code == 200
    body = r.json()
    cols = [c["name"] for c in body["columns"]]
    assert "地区" in cols and "键盘" in cols and "鼠标" in cols


def test_corr():
    ds = setup_ds()
    r = analyze(ds, "corr")
    assert r.status_code == 200
    body = r.json()
    assert set(body["matrix"]["columns"]) >= {"销售额", "数量", "成本"}
    n = len(body["matrix"]["columns"])
    assert len(body["matrix"]["values"]) == n
    # 销售额与成本高度正相关
    di = body["matrix"]["columns"].index("销售额")
    dj = body["matrix"]["columns"].index("成本")
    assert body["matrix"]["values"][di][dj] > 0.9


def test_corr_with_non_numeric():
    ds = setup_ds()
    r = analyze(ds, "corr", {"columns": ["销售额", "地区"]})
    assert r.status_code == 400


def test_histogram_and_boxplot():
    ds = setup_ds()
    h = analyze(ds, "histogram", {"column": "销售额", "bins": 4})
    assert h.status_code == 200
    assert sum(row[1] for row in h.json()["rows"]) == 5
    b = analyze(ds, "boxplot", {"columns": ["销售额"]})
    assert b.status_code == 200
    stats = b.json()["box_stats"][0]
    assert stats["min"] == 300 and stats["max"] == 3500 and stats["name"] == "销售额"


def test_value_counts():
    ds = setup_ds()
    r = analyze(ds, "value_counts", {"column": "地区"})
    assert r.status_code == 200
    data = dict(r.json()["rows"])
    assert data["华南"] == 2 and data["华东"] == 2


def test_trend_monthly():
    ds = setup_ds()
    client.post(f"/api/datasets/{ds}/clean", json={"op": "cast_type", "params": {"column": "日期", "to": "datetime"}})
    r = analyze(ds, "trend", {"date_column": "日期", "value_column": "销售额", "freq": "M", "agg": "sum"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert len(rows) == 5  # 五个月各一条
    assert rows[0] == ["2025-01-01", 1200.0]


def test_unknown_kind():
    ds = setup_ds()
    assert analyze(ds, "nope").status_code == 400


# ---------- 导出 ----------


def test_export_dataset_csv_and_xlsx():
    ds = setup_ds()
    r = client.get(f"/api/datasets/{ds}/export?format=csv&filename=测试导出")
    assert r.status_code == 200
    # 中文文件名按 RFC5987 编码，浏览器会正确还原
    assert "filename" in r.headers.get("content-disposition", "")
    assert "地区" in r.content.decode("utf-8-sig")
    r2 = client.get(f"/api/datasets/{ds}/export?format=xlsx")
    assert r2.status_code == 200
    assert r2.content[:2] == b"PK"  # xlsx 是 zip 格式


def test_export_bad_format():
    ds = setup_ds()
    assert client.get(f"/api/datasets/{ds}/export?format=pdf").status_code == 400


def test_export_table():
    r = client.post(
        "/api/export-table",
        json={
            "columns": [{"name": "地区"}, {"name": "销售额"}],
            "rows": [["华东", 4700], ["华南", 600]],
            "filename": "分组结果",
            "format": "csv",
        },
    )
    assert r.status_code == 200
    assert "4700" in r.content.decode("utf-8-sig")
