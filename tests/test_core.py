"""阶段1：上传解析 / 数据集管理 / 分页预览 / 列画像。"""
import json

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

CSV = "地区,产品,销售额,数量\n华东,键盘,1200,3\n华南,鼠标,300,2\n华东,键盘,900,2\n华北,显示器,3500,1\n"
CSV_GBK = "地区,销售额\n华东,100\n华南,200\n".encode("gbk")


def upload(name="t.csv", content=CSV):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    r = client.post(
        "/api/upload",
        files={"file": (name, raw, "application/octet-stream")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- 上传与解析 ----------


def test_upload_csv_and_rows():
    ds = upload()
    r = client.get(f"/api/datasets/{ds}/rows")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 4
    assert [c["name"] for c in data["columns"]] == ["地区", "产品", "销售额", "数量"]
    assert data["rows"][0][0] in ("华东", "华南", "华北")
    assert isinstance(data["rows"][0][2], (int, float))


def test_upload_csv_gbk_encoding():
    ds = upload("gbk.csv", CSV_GBK)
    data = client.get(f"/api/datasets/{ds}/rows").json()
    assert data["rows"][0][0] == "华东"


def test_upload_json_records():
    payload = json.dumps(
        [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], ensure_ascii=False
    ).encode("utf-8")
    ds = upload("t.json", payload)
    data = client.get(f"/api/datasets/{ds}/rows").json()
    assert data["total"] == 2
    assert [c["name"] for c in data["columns"]] == ["a", "b"]


def test_upload_xlsx(tmp_path):
    p = tmp_path / "t.xlsx"
    pd.DataFrame({"x": [1, 2], "y": ["a", "b"]}).to_excel(p, index=False)
    ds = upload("t.xlsx", p.read_bytes())
    data = client.get(f"/api/datasets/{ds}/rows").json()
    assert data["total"] == 2


def test_upload_unsupported_type():
    r = client.post(
        "/api/upload",
        files={"file": ("t.zip", b"1234", "application/octet-stream")},
        data={"name": ""},
    )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_pagination():
    csv = "a\n" + "\n".join(str(i) for i in range(105)) + "\n"
    ds = upload("big.csv", csv)
    d1 = client.get(f"/api/datasets/{ds}/rows?page=1&page_size=50").json()
    d3 = client.get(f"/api/datasets/{ds}/rows?page=3&page_size=50").json()
    assert d1["total"] == 105 and len(d1["rows"]) == 50
    assert len(d3["rows"]) == 5


# ---------- 数据集管理 ----------


def test_list_rename_delete():
    ds = upload()
    lst = client.get("/api/datasets").json()
    assert any(m["id"] == ds for m in lst)
    r = client.post(f"/api/datasets/{ds}/rename", json={"name": "我的测试集"})
    assert r.json()["name"] == "我的测试集"
    assert client.delete(f"/api/datasets/{ds}").json()["ok"] is True
    assert client.get(f"/api/datasets/{ds}").status_code == 404


def test_missing_dataset_404():
    assert client.get("/api/datasets/not-exist/rows").status_code == 404


# ---------- 画像 ----------


def test_profile():
    ds = upload()
    cols = {c["name"]: c for c in client.get(f"/api/datasets/{ds}/profile").json()["columns"]}
    assert cols["销售额"]["kind"] == "numeric"
    assert cols["销售额"]["mean"] == 1475.0
    assert cols["地区"]["kind"] == "categorical"
    assert cols["地区"]["nunique"] == 3
    tv = cols["地区"]["top_values"]
    assert tv[0]["value"] == "华东" and tv[0]["count"] == 2


def test_sample_dataset():
    r = client.post("/api/sample")
    assert r.status_code == 200
    ds = r.json()["id"]
    meta = client.get(f"/api/datasets/{ds}").json()
    assert meta["rows"] == 370  # 360 + 10 条重复
    assert meta["history"][0]["action"] == "上传"
    # 回滚原始数据
    r2 = client.post(f"/api/datasets/{ds}/reset")
    assert r2.status_code == 200
