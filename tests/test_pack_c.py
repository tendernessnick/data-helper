"""阶段9（C包）：RFM / 帕累托ABC / 异常值检测与剔除。"""
import random
from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def _to_csv(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def upload_df(df, name="t.csv"):
    r = client.post(
        "/api/upload",
        files={"file": (name, _to_csv(df), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_rfm_df():
    rng = random.Random(7)
    rows = []
    start = date(2025, 1, 1)
    # 甲：高频高额新客；乙：低频老客；丙：中频
    plans = {
        "客户甲": (30, 500, 5),   # 30笔、最近、单笔500
        "客户乙": (3, 100, 300),  # 3笔、很早、单笔100
        "客户丙": (12, 300, 60),  # 12笔、较近
    }
    for cust, (n, amount, days_ago) in plans.items():
        for i in range(n):
            rows.append(
                {
                    "客户": cust,
                    "日期": (start + timedelta(days=rng.randint(0, 400))).isoformat(),
                    "金额": amount + rng.randint(0, 10),
                }
            )
    # 强制最近消费时间差
    rows.append({"客户": "客户甲", "日期": date(2026, 8, 20).isoformat(), "金额": 600})
    rows.append({"客户": "客户乙", "日期": date(2025, 1, 5).isoformat(), "金额": 90})
    rng.shuffle(rows)
    return pd.DataFrame(rows)


# ---------- RFM ----------


def test_rfm_segments():
    ds = upload_df(make_rfm_df())
    r = client.post(
        f"/api/datasets/{ds}/analyze",
        json={"kind": "rfm", "params": {"id_column": "客户", "date_column": "日期", "value_column": "金额"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    seg = {row[0]: row for row in body["rows"]}
    assert "客户甲" not in seg  # 甲是分层名不是客户名
    # 明细中客户甲金额最高
    detail = {row[0]: row for row in body["detail"]["rows"]}
    assert detail["客户甲"][8] in ("重要价值客户", "重要发展客户", "重要保持客户")
    assert detail["客户甲"][4] > detail["客户乙"][4]
    assert detail["客户乙"][8] in ("一般挽留客户", "一般客户", "一般保持客户", "重要挽留客户")
    # 汇总占比合计 ≈ 100
    assert abs(sum(row[3] for row in body["rows"]) - 100) < 0.5
    assert body["chart"]["type"] == "pie"


def test_rfm_missing_params():
    ds = upload_df(make_rfm_df())
    r = client.post(f"/api/datasets/{ds}/analyze", json={"kind": "rfm", "params": {}})
    assert r.status_code == 400


def test_rfm_small_sample_no_crash():
    df = pd.DataFrame(
        {"客户": ["a", "b"], "日期": ["2025-01-01", "2025-06-01"], "金额": [10, 20]}
    )
    ds = upload_df(df)
    r = client.post(
        f"/api/datasets/{ds}/analyze",
        json={"kind": "rfm", "params": {"id_column": "客户", "date_column": "日期", "value_column": "金额"}},
    )
    assert r.status_code == 200
    assert len(r.json()["rows"]) >= 1


# ---------- 帕累托 / ABC ----------


def test_pareto_abc():
    df = pd.DataFrame(
        {
            "产品": ["A品", "B品", "C品", "D品", "E品"],
            "销售额": [700, 200, 60, 30, 10],
        }
    )
    ds = upload_df(df)
    r = client.post(
        f"/api/datasets/{ds}/analyze",
        json={"kind": "pareto", "params": {"category_column": "产品", "value_column": "销售额"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pareto"] is True
    rows = body["rows"]
    assert rows[0][0] == "A品" and rows[0][1] == 700
    assert rows[0][2] == 70.0  # 700/1000
    assert rows[0][3] == 70.0  # 累计
    assert rows[0][4] == "A"
    assert abs(rows[1][3] - 90.0) < 0.01  # 700+200=900
    assert rows[1][4] == "A"  # 前期累计70<80
    assert rows[2][4] == "B"  # 前期累计90在80~95
    assert rows[4][4] == "C"


# ---------- 异常值 ----------


def test_outliers_detect_and_drop():
    vals = [10, 11, 12, 10, 11, 13, 12, 11, 10, 12, 1000]  # 1000 是明显离群
    df = pd.DataFrame({"销售额": vals, "地区": ["华东"] * 11})
    ds = upload_df(df)
    r = client.post(
        f"/api/datasets/{ds}/analyze",
        json={"kind": "outliers", "params": {"columns": ["销售额"], "method": "iqr"}},
    )
    assert r.status_code == 200
    body = r.json()
    row = body["rows"][0]
    assert row[0] == "销售额" and row[3] == 1  # 检出1个离群
    # 清洗剔除
    r2 = client.post(
        f"/api/datasets/{ds}/clean",
        json={"op": "drop_outliers", "params": {"columns": ["销售额"], "method": "iqr"}},
    )
    assert r2.status_code == 200
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 10


def test_drop_outliers_non_numeric_400():
    df = pd.DataFrame({"销售额": [1, 2, 3], "地区": ["a", "b", "c"]})
    ds = upload_df(df)
    r = client.post(
        f"/api/datasets/{ds}/clean",
        json={"op": "drop_outliers", "params": {"columns": ["地区"]}},
    )
    assert r.status_code == 400
