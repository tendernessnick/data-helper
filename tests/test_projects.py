"""项目化管理：数据集按项目分组、派生表归组、移动与项目 CRUD。"""
from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.main import app

client = TestClient(app)


def upload_csv(content: str, name="t.csv", project="") -> str:
    r = client.post(
        "/api/upload",
        files={"file": (name, content.encode("utf-8"), "text/csv")},
        data={"name": "", "project": project},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_project(name: str) -> str:
    r = client.post("/api/projects", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_project_crud_and_validation():
    prj = make_project("电商清洗")
    assert prj.startswith("prj-")

    r = client.get("/api/projects")
    assert any(p["id"] == prj and p["name"] == "电商清洗" and p["count"] == 0 for p in r.json())

    # 重名拒绝 / 空名拒绝
    assert client.post("/api/projects", json={"name": "电商清洗"}).status_code == 400
    assert client.post("/api/projects", json={"name": "  "}).status_code == 400

    # 重命名 + 唯一性
    assert client.patch(f"/api/projects/{prj}", json={"name": "电商项目"}).status_code == 200
    prj2 = make_project("占位")
    assert client.patch(f"/api/projects/{prj2}", json={"name": "电商项目"}).status_code == 400

    # 删除不存在 → 404
    assert client.delete("/api/projects/prj-not-exist").status_code == 404


def test_upload_with_project_and_list_grouping():
    prj = make_project("分组A")
    ds = upload_csv("a,b\n1,x\n2,y\n", project=prj)
    meta = storage.get_meta(ds)
    assert meta["project"] == prj and meta["parent"] == ""

    names = [m["id"] for m in client.get("/api/datasets").json()]
    assert ds in names

    counts = {p["id"]: p["count"] for p in client.get("/api/projects").json()}
    assert counts[prj] == 1

    # 未指定项目的数据集 project 为空（归入未分组）
    ds2 = upload_csv("a\n1\n")
    assert storage.get_meta(ds2)["project"] == ""


def test_derived_datasets_inherit_project():
    """核心诉求：采样 / SQL 建集 / 导入工作表生成的派生表留在源数据集的项目里。"""
    prj = make_project("派生项目")
    ds = upload_csv("a,cat\n1,x\n2,x\n3,y\n4,y\n", name="src.csv", project=prj)

    # 采样派生
    r = client.post(f"/api/datasets/{ds}/sample-create", json={"method": "random", "n": 2})
    assert r.status_code == 200
    samp_id = r.json()["id"]
    samp = storage.get_meta(samp_id)
    assert samp["project"] == prj and samp["parent"] == ds
    assert samp["history"][0]["action"] == "采样"

    # SQL 建集派生
    r = client.post("/api/sql", json={"query": "SELECT * FROM df WHERE a > 1", "save_as": "sql结果", "current_id": ds})
    assert r.status_code == 200, r.text
    sql_id = r.json()["new_dataset"]["id"]
    sql_meta = storage.get_meta(sql_id)
    assert sql_meta["project"] == prj and sql_meta["parent"] == ds

    counts = {p["id"]: p["count"] for p in client.get("/api/projects").json()}
    assert counts[prj] == 3  # 源 + 采样 + SQL


def test_move_dataset_between_projects():
    prj1 = make_project("移动源")
    prj2 = make_project("移动目标")
    ds = upload_csv("a\n1\n", project=prj1)

    r = client.post(f"/api/datasets/{ds}/move", json={"project": prj2})
    assert r.status_code == 200
    assert storage.get_meta(ds)["project"] == prj2

    # 移回未分组
    client.post(f"/api/datasets/{ds}/move", json={"project": ""})
    assert storage.get_meta(ds)["project"] == ""

    # 目标项目不存在
    assert client.post(f"/api/datasets/{ds}/move", json={"project": "prj-nope"}).status_code == 404


def test_delete_project_moves_members_to_ungrouped():
    prj = make_project("待删项目")
    ds = upload_csv("a\n1\n", project=prj)
    assert client.delete(f"/api/projects/{prj}").status_code == 200
    meta = storage.get_meta(ds)  # 数据集本身不动
    assert meta["project"] == ""
    assert storage.load_df(ds)["a"].tolist() == [1]
    assert all(p["id"] != prj for p in storage.list_projects())


def test_paste_and_sample_endpoint_with_project():
    prj = make_project("入口项目")
    r = client.post("/api/upload-paste", json={"text": "a,b\n1,x\n", "name": "粘贴表", "project": prj})
    assert r.status_code == 200
    assert storage.get_meta(r.json()["id"])["project"] == prj

    r = client.post(f"/api/sample?project={prj}")
    assert r.status_code == 200
    assert storage.get_meta(r.json()["id"])["project"] == prj


def test_projects_file_atomic_and_survives_reload():
    make_project("持久化")
    # 注册表就是普通 json 文件，损坏时按空表处理不崩溃
    storage.PROJECTS_FILE.write_text("not-json", encoding="utf-8")
    assert storage.list_projects() == []
    # 写入后恢复
    make_project("恢复后")
    names = [p["name"] for p in storage.list_projects()]
    assert "恢复后" in names and "持久化" not in names


def test_rename_project_conflict_and_meta_keep():
    prj1 = make_project("甲")
    make_project("乙")
    ds = upload_csv("a\n5\n", project=prj1)
    assert client.patch(f"/api/projects/{prj1}", json={"name": "乙"}).status_code == 400  # 与乙重名
    assert client.patch(f"/api/projects/{prj1}", json={"name": "甲改"}).status_code == 200
    assert storage.get_meta(ds)["project"] == prj1  # 改名不动成员归属


def test_import_sheet_inherits_project():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "订单"
    ws1.append(["a"])
    ws1.append([1])
    ws2 = wb.create_sheet("用户")
    ws2.append(["u"])
    ws2.append(["x"])
    bio = io.BytesIO()
    wb.save(bio)

    prj = make_project("xlsx项目")
    r = client.post(
        "/api/upload",
        files={"file": ("two.xlsx", bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"name": "", "project": prj},
    )
    assert r.status_code == 200, r.text
    ds = r.json()["id"]

    r = client.post(f"/api/datasets/{ds}/import-sheet", json={"sheet": "用户"})
    assert r.status_code == 200, r.text
    sheet_meta = storage.get_meta(r.json()["id"])
    assert sheet_meta["project"] == prj
    assert sheet_meta["parent"] == ds
    assert sheet_meta["history"][0]["action"] == "导入工作表"
