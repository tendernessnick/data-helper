"""阶段2：清洗操作 / Python 变换 / 回滚与历史。"""
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

CSV = (
    "日期,地区,产品,销售额,数量\n"
    "2025-01-01,华东,键盘,1200,3\n"
    "2025-01-02,华南,鼠标,300,2\n"
    "2025-01-02,华南,鼠标,300,2\n"
    "2025-01-03,,显示器,3500,1\n"
    "2025-01-04,华北,,500,4\n"
)


def setup_ds():
    r = client.post(
        "/api/upload",
        files={"file": ("t.csv", CSV.encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def rows(ds):
    return client.get(f"/api/datasets/{ds}/rows").json()


def clean(ds, op, params=None):
    return client.post(f"/api/datasets/{ds}/clean", json={"op": op, "params": params or {}})


# ---------- 清洗 ----------


def test_drop_duplicates():
    ds = setup_ds()
    r = clean(ds, "drop_duplicates")
    assert r.status_code == 200
    assert rows(ds)["total"] == 4
    assert "1" in r.json()["message"]


def test_drop_missing_rows():
    ds = setup_ds()
    r = clean(ds, "drop_missing", {"columns": ["地区"], "how": "any"})
    assert r.status_code == 200
    assert rows(ds)["total"] == 4


def test_fill_missing_mean():
    ds = setup_ds()
    r = clean(ds, "fill_missing", {"columns": ["销售额"], "method": "mean"})
    assert r.status_code == 200
    data = rows(ds)
    assert data["total"] == 5
    vals = [row[3] for row in data["rows"]]
    assert None not in vals


def test_fill_missing_constant_and_ffill():
    ds = setup_ds()
    assert clean(ds, "fill_missing", {"columns": ["地区"], "method": "constant", "value": "未知"}).status_code == 200
    ds2 = setup_ds()
    assert clean(ds2, "fill_missing", {"columns": ["地区"], "method": "ffill"}).status_code == 200


def test_rename_and_drop_columns():
    ds = setup_ds()
    r = clean(ds, "rename_columns", {"mapping": {"销售额": "金额"}})
    assert r.status_code == 200
    cols = [c["name"] for c in rows(ds)["columns"]]
    assert "金额" in cols and "销售额" not in cols
    r2 = clean(ds, "drop_columns", {"columns": ["数量"]})
    assert r2.status_code == 200
    assert "数量" not in [c["name"] for c in rows(ds)["columns"]]


def test_cast_datetime_and_float():
    ds = setup_ds()
    r = clean(ds, "cast_type", {"column": "日期", "to": "datetime"})
    assert r.status_code == 200
    dtype = {c["name"]: c["dtype"] for c in rows(ds)["columns"]}
    assert "datetime" in dtype["日期"]
    r2 = clean(ds, "cast_type", {"column": "数量", "to": "float"})
    assert r2.status_code == 200
    dtype2 = {c["name"]: c["dtype"] for c in rows(ds)["columns"]}
    assert dtype2["数量"] == "float64"


def test_filter_rows():
    ds = setup_ds()
    r = clean(ds, "filter_rows", {"column": "销售额", "op": "ge", "value": 1000})
    assert r.status_code == 200
    assert rows(ds)["total"] == 2  # 1200 与 3500
    ds2 = setup_ds()
    r2 = clean(ds2, "filter_rows", {"column": "产品", "op": "contains", "value": "鼠"})
    assert r2.status_code == 200
    assert rows(ds2)["total"] == 2  # 含重复的两行鼠标


def test_filter_empty_returns_400():
    ds = setup_ds()
    r = clean(ds, "filter_rows", {"column": "销售额", "op": "gt", "value": 999999})
    assert r.status_code == 400
    assert "0 行" in r.json()["detail"]


def test_unknown_column_returns_400():
    ds = setup_ds()
    assert clean(ds, "filter_rows", {"column": "不存在", "op": "gt", "value": 1}).status_code == 400


def test_history_recorded_and_reset():
    ds = setup_ds()
    clean(ds, "drop_duplicates")
    clean(ds, "fill_missing", {"columns": ["地区"], "method": "constant", "value": "未知"})
    meta = client.get(f"/api/datasets/{ds}").json()
    actions = [h["action"] for h in meta["history"]]
    assert "清洗-drop_duplicates" in actions and "清洗-fill_missing" in actions
    r = client.post(f"/api/datasets/{ds}/reset")
    assert r.status_code == 200
    assert rows(ds)["total"] == 5


# ---------- Python 变换 ----------


def test_transform_preview_and_apply():
    ds = setup_ds()
    code = "df['单价'] = df['销售额'] / df['数量']\nprint('计算完成')"
    r = client.post(f"/api/datasets/{ds}/transform", json={"code": code, "apply": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stdout"] == "计算完成"
    assert body["shape"]["cols"] == 6
    # 仅预览不落盘
    assert len(rows(ds)["columns"]) == 5
    r2 = client.post(f"/api/datasets/{ds}/transform", json={"code": code, "apply": True})
    assert r2.status_code == 200
    assert "Python变换" in [h["action"] for h in client.get(f"/api/datasets/{ds}").json()["history"]]
    assert len(rows(ds)["columns"]) == 6


def test_transform_filter_df():
    ds = setup_ds()
    code = "df = df[df['销售额'] > 400]"
    r = client.post(f"/api/datasets/{ds}/transform", json={"code": code, "apply": True})
    assert r.status_code == 200
    assert rows(ds)["total"] == 3


def test_transform_syntax_error():
    ds = setup_ds()
    r = client.post(f"/api/datasets/{ds}/transform", json={"code": "df[", "apply": True})
    assert r.status_code == 400
    assert "SyntaxError" in r.json()["detail"]


def test_transform_runtime_error():
    ds = setup_ds()
    r = client.post(
        f"/api/datasets/{ds}/transform",
        json={"code": "df = df['不存在']", "apply": True},
    )
    assert r.status_code == 400


def test_transform_non_dataframe():
    ds = setup_ds()
    r = client.post(f"/api/datasets/{ds}/transform", json={"code": "df = 123", "apply": True})
    assert r.status_code == 400
    assert "DataFrame" in r.json()["detail"]


def test_regression_cast_int_with_decimals():
    """修复回归：小数浮点列转整数不再报错（四舍五入）。"""
    r = client.post(
        "/api/upload",
        files={"file": ("dec.csv", "x\n1.5\n2.7\n3.2\n".encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    ds = r.json()["id"]
    rr = client.post(f"/api/datasets/{ds}/clean", json={"op": "cast_type", "params": {"column": "x", "to": "int"}})
    assert rr.status_code == 200, rr.text
    vals = [row[0] for row in client.get(f"/api/datasets/{ds}/rows").json()["rows"]]
    assert vals == [2, 3, 3]


def test_regression_stratified_keeps_group_column():
    """修复回归：分层采样保留分层列。"""
    csv = "g,v\n" + "\n".join(f"A,{i}" for i in range(10)) + "\n" + "\n".join(f"B,{i}" for i in range(10)) + "\n"
    r = client.post("/api/upload", files={"file": ("s.csv", csv.encode(), "text/csv")}, data={"name": ""})
    ds = r.json()["id"]
    rr = client.post(f"/api/datasets/{ds}/clean", json={"op": "filter_rows", "params": {"column": "v", "op": "ge", "value": 0}})
    rr2 = client.post(f"/api/datasets/{ds}/sample-create", json={"method": "stratified", "n": 2, "by": "g"})
    assert rr2.status_code == 200
    cols = [c["name"] for c in rr2.json()["meta"]["columns"]]
    assert "g" in cols
