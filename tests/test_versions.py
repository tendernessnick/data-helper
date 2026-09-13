"""多步回溯：版本快照链、任意步跳转、分支保留与修剪、撤销/回滚、上限淘汰、旧数据懒迁移。"""
import json
import shutil

import pandas as pd
from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.main import app

client = TestClient(app)


def upload(rows="a\n1\n2\n3\n4\n5\n") -> str:
    r = client.post("/api/upload", files={"file": ("t.csv", rows.encode("utf-8"), "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def op_filter(ds, gt):
    """清洗操作：保留 a <= gt 的行（行数可预期地变化）。"""
    r = client.post(
        f"/api/datasets/{ds}/clean",
        json={"op": "filter_rows", "params": {"column": "a", "op": "le", "value": gt}},
    )
    assert r.status_code == 200, r.text


def rows_of(ds) -> list:
    return storage.load_df(ds)["a"].tolist()


def test_version_chain_created_by_ops():
    ds = upload()
    d = storage.DATASETS_DIR / ds
    assert storage.get_meta(ds)["version"] == 0
    assert (d / "versions" / "v0.parquet").exists()  # 初始快照

    op_filter(ds, 3)  # v1: [1,2,3]
    op_filter(ds, 2)  # v2: [1,2]
    meta = storage.get_meta(ds)
    assert meta["version"] == 2
    assert rows_of(ds) == [1, 2]
    snaps = sorted(storage.available_versions(ds)["snapshots"])
    assert snaps == [0, 1]
    # 历史条目带版本号
    vs = [h.get("v") for h in meta["history"]]
    assert vs == [0, 1, 2]


def test_restore_to_any_step():
    ds = upload()
    op_filter(ds, 3)  # v1
    op_filter(ds, 2)  # v2

    r = client.post(f"/api/datasets/{ds}/restore", json={"version": 1})
    assert r.status_code == 200
    assert rows_of(ds) == [1, 2, 3]
    assert storage.get_meta(ds)["version"] == 1

    # 直接跳回 v0（上传原始）
    client.post(f"/api/datasets/{ds}/restore", json={"version": 0})
    assert rows_of(ds) == [1, 2, 3, 4, 5]

    # 不存在的版本 → 400
    assert client.post(f"/api/datasets/{ds}/restore", json={"version": 9}).status_code == 400


def test_branch_preserved_and_forward_jump():
    """回错可以再跳回来：跳转前的状态被补快照，未来分支可再进入。"""
    ds = upload()
    op_filter(ds, 3)  # v1
    op_filter(ds, 1)  # v2: [1]

    client.post(f"/api/datasets/{ds}/restore", json={"version": 1})
    assert rows_of(ds) == [1, 2, 3]
    # v2 仍可跳回（分支被保留）
    r = client.post(f"/api/datasets/{ds}/restore", json={"version": 2})
    assert r.status_code == 200
    assert rows_of(ds) == [1]


def test_new_op_prunes_unvisited_branch():
    """回溯后做新操作：未走的分支被丢弃，版本号从当前位置续。"""
    ds = upload()
    op_filter(ds, 3)   # v1
    op_filter(ds, 2)   # v2: [1,2]
    client.post(f"/api/datasets/{ds}/restore", json={"version": 1})  # 跳回 v1
    op_filter(ds, 1)   # 新操作：v2 重写为 [1]，旧 v2 分支被修剪

    assert storage.get_meta(ds)["version"] == 2
    assert rows_of(ds) == [1]
    r = client.post(f"/api/datasets/{ds}/restore", json={"version": 2})
    assert r.status_code == 200  # 当前版本本身（幂等）
    # 旧分支状态 [1,2] 已不存在：v2 快照是 [1]
    client.post(f"/api/datasets/{ds}/restore", json={"version": 2})
    assert rows_of(ds) == [1]


def test_multi_level_undo():
    ds = upload()
    op_filter(ds, 3)   # v1
    op_filter(ds, 2)   # v2
    op_filter(ds, 1)   # v3

    assert client.post(f"/api/datasets/{ds}/undo").status_code == 200
    assert rows_of(ds) == [1, 2]
    assert client.post(f"/api/datasets/{ds}/undo").status_code == 200  # 连续撤销（旧版只有一级）
    assert rows_of(ds) == [1, 2, 3]
    assert client.post(f"/api/datasets/{ds}/undo").status_code == 200
    assert rows_of(ds) == [1, 2, 3, 4, 5]
    assert client.post(f"/api/datasets/{ds}/undo").status_code == 400  # 到 v0 为止


def test_undo_after_restore_and_reset():
    ds = upload()
    op_filter(ds, 2)  # v1
    # 跳回 v0 后撤销仍安全：reset 是可撤销的操作
    client.post(f"/api/datasets/{ds}/reset")
    assert rows_of(ds) == [1, 2, 3, 4, 5]
    assert client.post(f"/api/datasets/{ds}/undo").status_code == 200
    assert rows_of(ds) == [1, 2]
    # 回滚后再回滚再撤销
    client.post(f"/api/datasets/{ds}/reset")
    client.post(f"/api/datasets/{ds}/reset")
    assert client.post(f"/api/datasets/{ds}/undo").status_code == 200
    assert rows_of(ds) == [1, 2, 3, 4, 5]


def test_reset_keeps_v0_and_middle_versions():
    ds = upload()
    op_filter(ds, 3)  # v1
    client.post(f"/api/datasets/{ds}/reset")  # v2 = v0 数据副本
    snaps = sorted(storage.available_versions(ds)["snapshots"])
    assert 0 in snaps and 1 in snaps
    client.post(f"/api/datasets/{ds}/restore", json={"version": 1})
    assert rows_of(ds) == [1, 2, 3]


def test_history_not_truncated_by_restore():
    ds = upload()
    op_filter(ds, 3)
    op_filter(ds, 2)
    client.post(f"/api/datasets/{ds}/restore", json={"version": 0})
    actions = [h["action"] for h in storage.get_meta(ds)["history"]]
    assert "回溯" in actions
    assert len([a for a in actions if a.startswith("清洗")]) == 2  # 原操作记录仍在


def test_snapshot_cap_evicts_oldest():
    ds = upload()
    col = "a"
    for i in range(storage.MAX_VERSIONS + 4):
        new = f"a{i}"
        r = client.post(
            f"/api/datasets/{ds}/clean",
            json={"op": "rename_columns", "params": {"mapping": {col: new}}},
        )
        assert r.status_code == 200, r.text
        col = new
    snaps = storage.available_versions(ds)["snapshots"]
    assert len(snaps) <= storage.MAX_VERSIONS
    assert 0 not in snaps  # 最旧的 v0 被淘汰
    # 被淘汰的版本回跳报 400 而不是崩溃
    assert client.post(f"/api/datasets/{ds}/restore", json={"version": 0}).status_code == 400
    # 回滚原始有 original.* 兜底
    r = client.post(f"/api/datasets/{ds}/reset")
    assert r.status_code == 200
    assert storage.load_df(ds).shape[1] == 1
    assert storage.load_df(ds).columns.tolist()[-1].startswith("a")


def test_legacy_prev_parquet_migrated_to_v0():
    """旧版数据集（meta 无 version，存在 prev.parquet）懒迁移：保住一级撤销。"""
    ds = upload()
    d = storage.DATASETS_DIR / ds
    # 先做一次正常操作产生 v0/v1
    op_filter(ds, 3)
    # 人工构造 legacy：去掉 version 字段，把快照伪装成 prev.parquet
    meta = storage.get_meta(ds)
    del meta["version"]
    for h in meta["history"]:
        h.pop("v", None)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(d / "versions")
    # 旧机制的 prev.parquet = 最近一次操作前的状态（即上传原始数据）
    pd.read_csv(d / "original.csv").to_parquet(d / "prev.parquet")

    # 旧版一级撤销语义仍可用（prev 存的是操作前状态 → v0）
    r = client.post(f"/api/datasets/{ds}/undo")
    assert r.status_code == 200, r.text
    assert rows_of(ds) == [1, 2, 3, 4, 5]
    assert not (d / "prev.parquet").exists()
    assert storage.available_versions(ds)["current"] == 0


def test_hardlink_snapshot_saves_space():
    """快照与 current 同 inode（NTFS 硬链接）时不占额外空间，且互不影响。"""
    ds = upload()
    d = storage.DATASETS_DIR / ds
    before = (d / "versions" / "v0.parquet").stat()
    cur = (d / "current.parquet").stat()
    if before.st_ino:  # Windows 上 st_ino 在 py3.5+ 可用
        assert before.st_ino == cur.st_ino
    # 改 current 不影响快照
    op_filter(ds, 2)
    assert storage.load_df(ds)["a"].tolist() == [1, 2]
    v0 = pd.read_parquet(d / "versions" / "v0.parquet")
    assert v0["a"].tolist() == [1, 2, 3, 4, 5]
