"""阶段9（C包）：RFM / 帕累托ABC / 异常值检测与剔除。"""

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
