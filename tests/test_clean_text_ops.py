"""文本与格式清洗操作（8 个新 op + interpolate）走 /clean API 的行为测试。"""
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def upload_df(df, name="清洗"):
    raw = df.to_csv(index=False).encode("utf-8-sig")
    r = client.post("/api/upload", files={"file": (f"{name}.csv", raw, "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def clean(ds, op, params):
    r = client.post(f"/api/datasets/{ds}/clean", json={"op": op, "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def col_values(ds, column, page_size=500):
    r = client.get(f"/api/datasets/{ds}/rows?page=1&page_size={page_size}")
    body = r.json()
    idx = [c["name"] for c in body["columns"]].index(column)
    return [row[idx] for row in body["rows"]]


def test_trim_whitespace():
    ds = upload_df(pd.DataFrame({"id": range(6), "城市": ["北京 ", " 上海", "深圳", "广州　", "杭州", "成都"]}))
    clean(ds, "trim_whitespace", {"columns": ["城市"]})
    assert col_values(ds, "城市") == ["北京", "上海", "深圳", "广州", "杭州", "成都"]


def test_normalize_text():
    df = pd.DataFrame({"id": range(6), "v": ["１２３", "　a  b　", "x\x00y", "好", "", "z"]})
    ds = upload_df(df)
    clean(ds, "normalize_text", {"columns": ["v"], "empty_to_na": True})
    vals = col_values(ds, "v")
    assert vals[0] == "123"          # 全角转半角
    assert vals[1] == "a b"          # 全角空格 + 连续空白压缩
    assert vals[2] == "xy"           # 控制字符去除
    assert vals[4] is None           # 空字符串 → 缺失


def test_parse_number():
    df = pd.DataFrame({"id": range(7), "价格": ["¥1,200", "980", "1.5万", "12%", "８,８００", "abc", None]})
    ds = upload_df(df)
    clean(ds, "parse_number", {"column": "价格"})
    vals = col_values(ds, "价格_数值")
    assert vals[0] == 1200 and vals[1] == 980 and vals[2] == 15000
    assert vals[3] == 12 and vals[4] == 8800   # 全角数字 + 千分位
    assert vals[5] is None and vals[6] is None  # 不可解析与缺失


def test_parse_number_percent_scale():
    ds = upload_df(pd.DataFrame({"id": range(3), "比率": ["12%", "50%", "3%"]}))
    clean(ds, "parse_number", {"column": "比率", "percent_scale": True, "new_column": "比率值"})
    assert col_values(ds, "比率值") == [0.12, 0.5, 0.03]


def test_parse_number_all_fail_400():
    ds = upload_df(pd.DataFrame({"id": range(3), "v": ["abc", "def", "ghi"]}))
    r = client.post(f"/api/datasets/{ds}/clean", json={"op": "parse_number", "params": {"column": "v"}})
    assert r.status_code == 400 and "解析" in r.json()["detail"]


def test_map_values():
    ds = upload_df(pd.DataFrame({"id": range(6), "城市": ["北京市", "北京", "上海", "SH", "SH", "广州"]}))
    clean(ds, "map_values", {"column": "城市", "mapping": {"北京市": "北京", "SH": "上海"}})
    assert col_values(ds, "城市") == ["北京", "北京", "上海", "上海", "上海", "广州"]


def test_map_values_unmatched_to_na():
    ds = upload_df(pd.DataFrame({"id": range(4), "v": ["a", "b", "a", "c"]}))
    clean(ds, "map_values", {"column": "v", "mapping": {"a": "A"}, "keep_original": False})
    assert col_values(ds, "v") == ["A", None, "A", None]


def test_map_values_empty_mapping_400():
    ds = upload_df(pd.DataFrame({"id": range(1), "v": ["a"]}))
    r = client.post(f"/api/datasets/{ds}/clean", json={"op": "map_values", "params": {"column": "v", "mapping": {}}})
    assert r.status_code == 400


def test_split_column():
    ds = upload_df(pd.DataFrame({"id": range(3), "地区": ["广东省-深圳市", "浙江省-杭州市", "四川省-成都市"]}))
    clean(ds, "split_column", {"column": "地区", "sep": "-", "into": ["省", "市"]})
    assert col_values(ds, "省") == ["广东省", "浙江省", "四川省"]
    assert col_values(ds, "市") == ["深圳市", "杭州市", "成都市"]


def test_cap_outliers_keeps_rows():
    vals = [10.0] * 20 + [1000.0]   # 一个极端离群
    ds = upload_df(pd.DataFrame({"id": range(len(vals)), "v": vals}))
    clean(ds, "cap_outliers", {"columns": ["v"], "method": "iqr"})
    out = col_values(ds, "v")
    assert len(out) == 21                     # 不删行
    assert max(out) == 10.0                   # 极端值被盖帽到上界（q1=q3=10 → upper=10）


def test_drop_high_missing_columns():
    df = pd.DataFrame({"ok": [1, 2, 3, 4], "bad": [None, None, None, 1], "mid": [1, None, None, 1]})
    ds = upload_df(df)
    clean(ds, "drop_high_missing", {"threshold": 0.5})
    r = client.get(f"/api/datasets/{ds}/rows?page=1&page_size=10").json()
    names = [c["name"] for c in r["columns"]]
    assert names == ["ok", "mid"]


def test_fill_missing_interpolate():
    ds = upload_df(pd.DataFrame({"id": range(6), "v": [10.0, None, None, 40.0, None, 70.0]}))
    clean(ds, "fill_missing", {"columns": ["v"], "method": "interpolate"})
    assert col_values(ds, "v") == [10.0, 20.0, 30.0, 40.0, 55.0, 70.0]


def test_unify_boolean_text():
    ds = upload_df(pd.DataFrame({"id": range(6), "会员": ["是", "true", "0", "否", "yes", "N"]}))
    clean(ds, "unify_boolean_text", {"column": "会员"})
    assert col_values(ds, "会员") == ["是", "是", "否", "否", "是", "否"]


def test_ops_registry_contains_all_new():
    from backend.app import cleaning
    for op in ["trim_whitespace", "normalize_text", "parse_number", "map_values",
               "split_column", "cap_outliers", "drop_high_missing", "unify_boolean_text"]:
        assert op in cleaning.OPS, op
