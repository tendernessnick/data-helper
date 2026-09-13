"""数据表交互：/rows 的排序与按值筛选（电子表格式列头交互的后端支撑）。"""
import json

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def upload_df(df, name="交互"):
    raw = df.to_csv(index=False).encode("utf-8-sig")
    r = client.post("/api/upload", files={"file": (f"{name}.csv", raw, "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


DF = pd.DataFrame({
    "id": range(1, 11),
    "cat": ["b", "a", "b", "a", "c", "b", "a", None, "c", "a"],
    "num": [10, 5, 8, 1, 9, 2, 7, 3, 6, 4],
})


def rows(ds, **params):
    r = client.get(f"/api/datasets/{ds}/rows", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def col_vals(body, col):
    idx = [c["name"] for c in body["columns"]].index(col)
    return [row[idx] for row in body["rows"]]


def test_sort_numeric_asc_desc():
    ds = upload_df(DF)
    up = rows(ds, page=1, page_size=10, sort="num", order="asc")
    assert col_vals(up, "num") == sorted(DF["num"].tolist())
    down = rows(ds, page=1, page_size=10, sort="num", order="desc")
    assert col_vals(down, "num") == sorted(DF["num"].tolist(), reverse=True)


def test_sort_string_and_nulls_last():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=10, sort="cat", order="asc")
    vals = col_vals(body, "cat")
    assert vals[-1] is None  # 缺失排最后
    non_null = [v for v in vals if v is not None]
    assert non_null == sorted(non_null)


def test_sort_unknown_column_400():
    ds = upload_df(DF)
    r = client.get(f"/api/datasets/{ds}/rows", params={"sort": "不存在"})
    assert r.status_code == 400


def test_filter_by_string_values():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=50, filters=json.dumps({"cat": ["a"]}))
    assert body["total"] == 4 and body["unfiltered_total"] == 10
    assert set(col_vals(body, "cat")) == {"a"}


def test_filter_multiple_values_and_columns():
    ds = upload_df(DF)
    flt = {"cat": ["a", "b"], "num": [10, 5, 8, 1]}
    body = rows(ds, page=1, page_size=50, filters=json.dumps(flt))
    # cat∈{a,b} 且 num∈{10,5,8,1} → 行 (b,10),(a,5),(b,8),(a,1)
    assert body["total"] == 4


def test_filter_null_sentinel():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=50, filters=json.dumps({"cat": ["__NULL__"]}))
    assert body["total"] == 1
    assert col_vals(body, "cat") == [None]


def test_filter_with_value_plus_null():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=50, filters=json.dumps({"cat": ["c", "__NULL__"]}))
    assert body["total"] == 3


def test_filter_then_sort_combined():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=50, sort="num", order="desc",
                filters=json.dumps({"cat": ["a", "b"]}))
    nums = col_vals(body, "num")
    assert nums == sorted(nums, reverse=True)
    assert body["unfiltered_total"] == 10 and body["total"] == 7


def test_filter_bad_json_or_unknown_col_400():
    ds = upload_df(DF)
    r = client.get(f"/api/datasets/{ds}/rows", params={"filters": "{bad"})
    assert r.status_code == 400
    r2 = client.get(f"/api/datasets/{ds}/rows", params={"filters": json.dumps({"无此列": [1]})})
    assert r2.status_code == 400


def test_filter_numeric_values_match_dtype():
    ds = upload_df(DF)
    body = rows(ds, page=1, page_size=50, filters=json.dumps({"num": [10, 5]}))
    assert body["total"] == 2
