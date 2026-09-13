"""分模块代码审计修复的回归测试（v2.0 第二轮：工程质量）。"""
import shutil
import threading
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import exporter, serialize, storage, transform
from backend.app.main import app

client = TestClient(app)


def upload_csv(content: str, name="t.csv") -> str:
    r = client.post("/api/upload", files={"file": (name, content.encode("utf-8"), "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- storage：undo legacy pickle 破坏路径 ----------


def test_undo_with_legacy_pkl_snapshot_does_not_corrupt():
    """P1 回归：旧版 pkl 数据集在新版本机制下不损坏。

    旧版 prev.pkl 快照已不再被撤销消费；current.pkl 读取时照常迁移为 Parquet，
    撤销报告"无可撤销"而不是把 pickle 字节当 parquet 用（修复前会损坏数据集）。
    """
    ds = upload_csv("a\n1\n2\n")
    d = storage.DATASETS_DIR / ds
    # 构造 legacy 状态：current.pkl + prev.pkl（旧版本生成的快照）
    (d / "current.parquet").unlink()
    shutil.rmtree(d / "versions", ignore_errors=True)
    pd.DataFrame({"a": [9]}).to_pickle(d / "current.pkl")
    pd.DataFrame({"a": [1, 2]}).to_pickle(d / "prev.pkl")
    try:
        storage.undo_dataset(ds)
        raised = False
    except storage.DatasetNotFound:
        raised = True
    assert raised  # 新机制不再消费 pkl 快照：报告无可撤销
    df = storage.load_df(ds)  # current.pkl 迁移路径照常工作
    assert df["a"].tolist() == [9]
    assert not (d / "current.pkl").exists()
    assert (d / "current.parquet").exists()


def test_concurrent_load_and_save_no_crash():
    """P1 回归：读路径纳入全局锁——Windows 上 os.replace 正被读取的文件会 PermissionError。"""
    ds = upload_csv("v\n" + "\n".join(str(i) for i in range(500)) + "\n", name="cc.csv")
    errors = []

    def reader():
        for _ in range(15):
            try:
                storage.load_df(ds)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    def writer():
        for i in range(8):
            try:
                storage.save_df(ds, pd.DataFrame({"v": range(500)}), "并发写", str(i))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    t1, t2 = threading.Thread(target=reader), threading.Thread(target=writer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, errors


def test_stream_fallback_keeps_source_file(monkeypatch):
    """P1 回归：流式建集异常回退时原始文件必须还在（修复前 move 后异常 → 文件彻底丢失）。"""
    from pathlib import Path

    monkeypatch.setattr(storage, "STREAM_THRESHOLD_BYTES", 10)
    monkeypatch.setattr(storage, "STREAM_CHUNK_ROWS", 10)
    lines = [f"{i}" for i in range(25)] + ["oops"]  # 跨块类型漂移 → 触发回退
    src = Path(storage.DATA_DIR / "fallback-src.csv")
    src.write_text("v\n" + "\n".join(lines) + "\n", encoding="utf-8")
    ds = storage.create_dataset_stream("回退测试", src, "fallback.csv")
    assert len(storage.load_df(ds)) == 26  # 回退全量解析数据完整
    assert not src.exists()  # 建集成功（含回退路径）后临时文件由调用方/自身清理
    assert (storage.DATASETS_DIR / ds / "original.csv").exists()


# ---------- transform：线程路由式 stdout ----------


def test_transform_stdout_isolated_between_threads():
    """P0 回归：用户代码捕获 stdout 期间，其他线程的 print 不被劫持。"""
    import io as _io
    import sys

    probe = _io.StringIO()
    real = sys.stdout
    sys.stdout = probe
    try:
        df = pd.DataFrame({"v": [1, 2, 3]})
        out, stdout_text = transform.run_code(df, "print('from user code')\ndf", timeout=10)
    finally:
        sys.stdout = real
    assert "from user code" in stdout_text
    assert probe.getvalue() == ""  # 主线程（未注册）的输出没进用户缓冲


def test_transform_stdout_recovers_after_timeout():
    """P0 回归：死循环超时后进程 stdout 仍可用（修复前被永久劫持到孤儿缓冲）。

    循环用时间上限而非 while True：泄漏线程必须在 pytest 退出前自然结束，
    否则 ThreadPoolExecutor 的 atexit join 会挂起整个测试进程。
    """
    import sys

    df = pd.DataFrame({"v": [1]})
    code = "import time\nend = time.time() + 3\nwhile time.time() < end:\n    pass"
    with pytest.raises(transform.TransformError):
        transform.run_code(df, code, timeout=1)
    # 超时后：sys.stdout 必须已恢复（不再指向路由器）
    from backend.app.transform import _ThreadRoutedStdout
    assert not isinstance(sys.stdout, _ThreadRoutedStdout)
    time.sleep(2.5)  # 等泄漏的工作线程按时间上限自然退出，避免 atexit join 挂起


def test_transform_captures_user_print():
    df = pd.DataFrame({"v": [1, 2]})
    out, text = transform.run_code(df, "print('hello')\ndf['v'] = df['v'] * 2", timeout=10)
    assert "hello" in text
    assert out["v"].tolist() == [2, 4]


# ---------- sqlquery：引号感知切分 + 预览 LIMIT ----------


def test_sql_semicolon_inside_string_not_rejected():
    ds = upload_csv("k,v\na;b,1\nc,2\n", name="semi.csv")
    tables = client.get("/api/sql/tables").json()
    alias = next(t["alias"] for t in tables if t["id"] == ds)
    r = client.post("/api/sql", json={"query": f"SELECT * FROM {alias} WHERE k = 'a;b'"})
    assert r.status_code == 200, r.text  # 修复前被误判为多语句而 400
    assert r.json()["total"] == 1


def test_sql_mutation_still_rejected():
    upload_csv("k\nx\n", name="mut.csv")
    for q in ["SELECT 1; DROP TABLE df", "SELECT 1;DELETE FROM df", "WITH t AS (SELECT 1) SELECT * FROM t; UPDATE df SET k=1"]:
        r = client.post("/api/sql", json={"query": q})
        assert r.status_code == 400, q


def test_sql_preview_limit_wrap(monkeypatch):
    """P1 回归：预览路径外层 LIMIT，避免大结果全量物化。"""
    from backend.app import sqlquery as sq

    ds = upload_csv("v\n" + "\n".join(str(i) for i in range(50)) + "\n", name="big.csv")
    tables = client.get("/api/sql/tables").json()
    alias = next(t["alias"] for t in tables if t["id"] == ds)
    monkeypatch.setattr(sq, "MAX_ROWS", 10)
    r = client.post("/api/sql", json={"query": f"SELECT v FROM {alias}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 11 and body["truncated"] is True and len(body["rows"]) == 10


# ---------- serialize：np.bool_ ----------


def test_serialize_numpy_bool():
    assert serialize.cell(np.bool_(True)) is True
    assert serialize.cell(np.bool_(False)) is False
    assert isinstance(serialize.cell(np.bool_(True)), bool)  # 不是字符串 "True"


# ---------- exporter：dict 单元格容错 ----------


def test_export_table_dict_cell_without_bounds():
    path = exporter.export_table(
        [{"name": "期间"}, {"name": "预测"}],
        [["2026-01", {"value": 123}], ["2026-02", {"value": 45.6, "lower": 40, "upper": 51}]],
        "区间容错", "csv",
    )
    txt = path.read_text(encoding="utf-8-sig")
    assert "123" in txt and "45.6(下限40~上限51)" in txt  # 缺 lower/upper 不再 KeyError→500


def test_export_table_columns_missing_name_key():
    path = exporter.export_table([{"label": "x"}, "y"], [["1", "2"]], "列名容错", "csv")
    assert path.exists()


# ---------- report：XSS 转义 ----------



