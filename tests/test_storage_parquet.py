"""Phase 3 存储：Parquet 主存储 / 旧 pickle 自动迁移 / 大 CSV 流式建集 / SQL 直读 Parquet。"""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.main import app

client = TestClient(app)

CSV = "地区,产品,销售额\n华东,键盘,1200\n华南,鼠标,300\n"


def upload(name="t.csv", content=CSV):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    r = client.post(
        "/api/upload",
        files={"file": (name, raw, "application/octet-stream")},
        data={"name": ""},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _legacy_pkl_dataset(df: pd.DataFrame, with_prev=False) -> str:
    """手工构造一个旧版 pickle 存储的数据集（模拟升级前的存量数据）。"""
    ds = upload()
    d = storage.DATASETS_DIR / ds
    for p in d.glob("current.parquet"):
        p.unlink()
    df.to_pickle(d / "current.pkl")
    if with_prev:
        (df.head(1)).to_pickle(d / "prev.pkl")
    return ds


# ---------- Parquet 主存储 ----------


def test_create_and_load_parquet_roundtrip():
    ds = upload()
    d = storage.DATASETS_DIR / ds
    assert (d / "current.parquet").exists()
    assert not (d / "current.pkl").exists()
    df = storage.load_df(ds)
    assert list(df.columns) == ["地区", "产品", "销售额"]
    assert len(df) == 2
    assert df["销售额"].sum() == 1500


def test_save_and_undo_uses_parquet_snapshot():
    ds = upload()
    df2 = pd.DataFrame({"a": [1, 2, 3]})
    storage.save_df(ds, df2, "测试修改")
    d = storage.DATASETS_DIR / ds
    assert (d / "prev.parquet").exists()
    assert len(storage.load_df(ds)) == 3
    meta = storage.undo_dataset(ds)
    assert meta["rows"] == 2
    assert len(storage.load_df(ds)) == 2


def test_legacy_pkl_auto_migrate_on_load():
    legacy = pd.DataFrame({"城市": ["北京", "上海"], "销量": [10, 20]})
    ds = _legacy_pkl_dataset(legacy)
    d = storage.DATASETS_DIR / ds
    df = storage.load_df(ds)  # 读取时自动迁移
    assert (d / "current.parquet").exists()
    assert not (d / "current.pkl").exists()
    assert df["销量"].sum() == 30


def test_legacy_pkl_snapshot_undo():
    legacy = pd.DataFrame({"x": [1, 2]})
    ds = _legacy_pkl_dataset(legacy)
    storage.save_df(ds, pd.DataFrame({"x": [9]}), "覆盖")
    meta = storage.undo_dataset(ds)  # 旧 pickle 快照也能撤销
    assert meta["rows"] == 2
    assert storage.load_df(ds)["x"].tolist() == [1, 2]


def test_mixed_type_object_column_stringify_fallback():
    df = pd.DataFrame({"v": ["a", 1.5, "b", None]})  # 病态混合类型列
    ds = storage.create_dataset("mixed", df, "mixed.csv", b"v\na\n1.5\nb\n\n")
    out = storage.load_df(ds)
    assert len(out) == 4
    assert out["v"].astype(str).str.contains("1.5|a|b").sum() == 3


# ---------- 大 CSV 流式建集 ----------


@pytest.fixture()
def force_stream(monkeypatch):
    monkeypatch.setattr(storage, "STREAM_THRESHOLD_BYTES", 10)  # 强制任何 CSV 走流式


def test_stream_upload_basic(force_stream):
    rows = 5000
    content = "id,城市,金额\n" + "\n".join(f"{i},城市{i % 7},{i * 3}" for i in range(rows)) + "\n"
    ds = upload("big.csv", content)
    meta = storage.get_meta(ds)
    assert meta["rows"] == rows and meta["cols"] == 3
    assert meta["history"][0]["action"] == "上传（流式）"
    df = storage.load_df(ds)
    assert len(df) == rows
    assert int(df["金额"].sum()) == sum(i * 3 for i in range(rows))
    assert (storage.DATASETS_DIR / ds / "original.csv").exists()


def test_stream_upload_gbk(force_stream):
    body = "城市,销量\n" + "\n".join(f"城市{i},{i}" for i in range(300))
    ds = upload("gbk.csv", body.encode("gbk"))
    df = storage.load_df(ds)
    assert len(df) == 300
    assert df["销量"].sum() == sum(range(300))


def test_stream_fallback_on_dtype_drift(monkeypatch):
    monkeypatch.setattr(storage, "STREAM_THRESHOLD_BYTES", 10)
    monkeypatch.setattr(storage, "STREAM_CHUNK_ROWS", 10)  # 每 10 行一块，制造跨块类型漂移
    lines = [f"{i}" for i in range(25)] + ["oops"]  # 前 25 行数值，末尾混入文本
    content = "v\n" + "\n".join(lines) + "\n"
    ds = upload("drift.csv", content)
    df = storage.load_df(ds)  # 回退全量解析后数据完整
    assert len(df) == 26
    assert "oops" in df["v"].astype(str).tolist()


def test_stream_sep_misdetect_fallback(force_stream):
    # 表头含逗号引号场景 + 分号分隔：分隔符计数应选中分号；若误判则必须回退且数据正确
    content = "a;b\n1;2\n3;4\n"
    ds = upload("semi.csv", content)
    df = storage.load_df(ds)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


# ---------- SQL 直读 Parquet ----------


def test_sql_over_parquet_views():
    upload("a.csv", "k,v\nx,1\ny,2\n")
    upload("b.csv", "k,w\nx,10\ny,20\n")
    tables = client.get("/api/sql/tables").json()  # 别名编号覆盖全部数据集，按 updated_at 排序
    a = next(t["alias"] for t in tables if t["name"] == "a")
    b = next(t["alias"] for t in tables if t["name"] == "b")
    r = client.post("/api/sql", json={"query": f"SELECT {a}.k AS k, v + w AS s FROM {a} JOIN {b} ON {a}.k = {b}.k"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 2
    assert dict(zip([row[0] for row in data["rows"]], [row[1] for row in data["rows"]])) == {"x": 11, "y": 22}


def test_sql_df_alias_and_readonly():
    ds = upload("a.csv", "k,v\nx,1\n")
    r = client.post("/api/sql", json={"query": "SELECT * FROM df", "current_id": ds})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    r2 = client.post("/api/sql", json={"query": "SELECT 1; DROP TABLE df", "current_id": ds})
    assert r2.status_code == 400


def test_meta_columns_dtype_serializable(force_stream):
    ds = upload("t.csv", "a,b\n1,x\n2,y\n")
    meta = json.loads((storage.DATASETS_DIR / ds / "meta.json").read_text(encoding="utf-8"))
    assert meta["columns"][0]["dtype"].startswith("int")


def test_reset_dataset_rebuilds_parquet_from_original():
    ds = upload("r.csv", "a,b\n1,x\n2,y\n")
    storage.save_df(ds, pd.DataFrame({"a": [9]}), "覆盖")
    meta = storage.reset_dataset(ds)
    assert meta["rows"] == 2
    assert storage.load_df(ds)["a"].tolist() == [1, 2]


def test_delete_dataset_removes_dir():
    ds = upload("d.csv", "a\n1\n")
    d = storage.DATASETS_DIR / ds
    assert d.exists()
    storage.delete_dataset(ds)
    assert not d.exists()
