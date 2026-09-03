"""阶段7（A包）：粘贴导入 / Excel 多 sheet / 撤销上一步。"""
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def upload(content=b"a,b\n1,2\n3,4\n", name="t.csv"):
    r = client.post(
        "/api/upload",
        files={"file": (name, content, "application/octet-stream")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- 粘贴导入 ----------


def test_paste_tab_separated():
    r = client.post(
        "/api/upload-paste",
        json={"text": "地区\t销售额\n华东\t100\n华南\t200\n", "name": "粘贴测试"},
    )
    assert r.status_code == 200
    ds = r.json()["id"]
    data = client.get(f"/api/datasets/{ds}/rows").json()
    assert data["total"] == 2
    assert [c["name"] for c in data["columns"]] == ["地区", "销售额"]


def test_paste_comma_and_empty():
    assert client.post("/api/upload-paste", json={"text": "", "name": ""}).status_code == 400
    r = client.post("/api/upload-paste", json={"text": "x,y\n1,2", "name": ""})
    assert r.status_code == 200
    assert client.get(f"/api/datasets/{r.json()['id']}/rows").json()["total"] == 1


# ---------- Excel 多 sheet ----------


def test_multi_sheet():
    import io

    bio = io.BytesIO()
    with pd.ExcelWriter(bio) as w:
        pd.DataFrame({"a": [1, 2]}).to_excel(w, index=False, sheet_name="一月")
        pd.DataFrame({"b": ["x", "y", "z"]}).to_excel(w, index=False, sheet_name="二月")
    raw = bio.getvalue()

    ds = upload(raw, "multi.xlsx")
    meta = client.get(f"/api/datasets/{ds}").json()
    assert meta["sheets"] == ["一月", "二月"]
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 2  # 默认第一个 sheet

    # 导入第二个 sheet 为新数据集
    r = client.post(f"/api/datasets/{ds}/import-sheet", json={"sheet": "二月"})
    assert r.status_code == 200
    ds2 = r.json()["id"]
    d2 = client.get(f"/api/datasets/{ds2}/rows").json()
    assert d2["total"] == 3
    assert [c["name"] for c in d2["columns"]] == ["b"]

    # 不存在的 sheet
    assert client.post(f"/api/datasets/{ds}/import-sheet", json={"sheet": "不存在"}).status_code == 400


# ---------- 撤销上一步 ----------


def test_undo_clean():
    ds = upload()
    client.post(f"/api/datasets/{ds}/clean", json={"op": "filter_rows", "params": {"column": "a", "op": "gt", "value": 1}})
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 1
    r = client.post(f"/api/datasets/{ds}/undo")
    assert r.status_code == 200
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 2
    actions = [h["action"] for h in r.json()["history"]]
    assert actions[-1] == "撤销"


def test_undo_twice_only_one_level():
    ds = upload()
    client.post(f"/api/datasets/{ds}/clean", json={"op": "drop_duplicates", "params": {}})
    r1 = client.post(f"/api/datasets/{ds}/undo")
    assert r1.status_code == 200
    # 只有一级撤销：再撤销应失败
    r2 = client.post(f"/api/datasets/{ds}/undo")
    assert r2.status_code == 400


def test_undo_after_reset():
    ds = upload()
    client.post(f"/api/datasets/{ds}/clean", json={"op": "filter_rows", "params": {"column": "a", "op": "gt", "value": 1}})
    client.post(f"/api/datasets/{ds}/reset")
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 2
    # 撤销"回滚"，恢复到回滚前（1行）的状态
    r = client.post(f"/api/datasets/{ds}/undo")
    assert r.status_code == 200
    assert client.get(f"/api/datasets/{ds}/rows").json()["total"] == 1
