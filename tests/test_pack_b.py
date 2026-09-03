"""阶段8（B包）：同比/环比/累计 与 移动平均。"""
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

# 两年按月数据：2024 与 2025，每月销售额
MONTHS = []
for y, base in ((2024, 100), (2025, 150)):
    for m in range(1, 13):
        MONTHS.append((f"{y}-{m:02d}-01", base + m))


def setup_ds():
    csv = "日期,销售额\n" + "\n".join(f"{d},{v}" for d, v in MONTHS) + "\n"
    r = client.post(
        "/api/upload",
        files={"file": ("t.csv", csv.encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def analyze(ds, kind, params):
    return client.post(f"/api/datasets/{ds}/analyze", json={"kind": kind, "params": params})


def test_growth_mom_yoy_cumsum():
    ds = setup_ds()
    r = analyze(ds, "growth", {"date_column": "日期", "value_column": "销售额", "freq": "M", "agg": "sum"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["rows"]) == 24
    by_period = {row[0]: row for row in body["rows"]}
    # 第一期：环比/同比为空
    assert by_period["2024-01-01"][2] is None
    # 2024-02: (102-101)/101 ≈ 0.99
    assert abs(by_period["2024-02-01"][2] - 0.99) < 0.05
    # 2025-01 同比 = (151-101)/101 ≈ 49.5（对比2024-01）
    assert abs(by_period["2025-01-01"][3] - 49.5) < 0.1
    # 累计：2024 前两月 101+102=203
    assert by_period["2024-02-01"][4] == 203
    # 图表建议折线
    assert body["chart"]["type"] == "line"


def test_growth_yearly_no_yoy():
    ds = setup_ds()
    r = analyze(ds, "growth", {"date_column": "日期", "value_column": "销售额", "freq": "Y"})
    body = r.json()
    assert len(body["rows"]) == 2
    assert body["rows"][0][3] is None  # 按年无法算同比


def test_moving_avg():
    ds = setup_ds()
    r = analyze(ds, "moving_avg", {"date_column": "日期", "value_column": "销售额", "freq": "M", "window": 3})
    assert r.status_code == 200
    body = r.json()
    by_period = {row[0]: row for row in body["rows"]}
    # 2024-03 的3期移动平均 = (101+102+103)/3 = 102
    assert abs(by_period["2024-03-01"][2] - 102.0) < 0.01
    # 第一期窗口不足时用可得数据
    assert by_period["2024-01-01"][2] == 101.0


def test_moving_avg_bad_window():
    ds = setup_ds()
    assert analyze(ds, "moving_avg", {"date_column": "日期", "value_column": "销售额", "window": 1}).status_code == 400


def test_growth_bad_date_column():
    csv = "地区,销售额\n华东,100\n华南,200\n"
    r = client.post(
        "/api/upload",
        files={"file": ("t2.csv", csv.encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    ds = r.json()["id"]
    rr = analyze(ds, "growth", {"date_column": "地区", "value_column": "销售额", "freq": "M"})
    assert rr.status_code == 400
