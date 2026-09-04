"""MCP 服务端：工具直调 + Streamable HTTP 协议烟雾测试。"""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import mcpserver
from backend.app.main import app

client = TestClient(app, base_url="http://127.0.0.1:8765")  # mcp 2.x 校验 Host（防 DNS 重绑定），须用本机地址

pytest.importorskip("mcp", reason="未安装 mcp 库时跳过 MCP 测试")


@pytest.fixture(scope="module")
def ds():
    df = pd.DataFrame({
        "客户": [f"u{i % 4}" for i in range(12)],
        "日期": pd.date_range("2026-01-01", periods=12, freq="D").strftime("%Y-%m-%d"),
        "金额": [100, 250, 80, 300, 120, 500, 90, 40, 60, 700, 30, 10],
    })
    from backend.app import storage

    ds_id = storage.create_dataset("mcp测试", df, "mcp.csv", df.to_csv(index=False).encode("utf-8-sig"))
    yield ds_id
    storage.delete_dataset(ds_id)


# ---------- 工具直调 ----------


def test_list_and_profile(ds):
    out = json.loads(mcpserver.tool_list_datasets())
    ids = [d["dataset_id"] for d in out["datasets"]]
    assert ds in ids
    prof = json.loads(mcpserver.tool_column_profile(ds))
    assert {c["name"] for c in prof["columns"]} == {"客户", "日期", "金额"}
    assert prof["rows"] == 12


def test_sql_tool_readonly_and_aliases(ds):
    out = json.loads(mcpserver.tool_sql_query("SELECT 客户, SUM(金额) AS s FROM df GROUP BY 1 ORDER BY s DESC", dataset_id=ds))
    assert out["total"] == 4
    from backend.app import storage
    expect = storage.load_df(ds).groupby("客户")["金额"].sum().max()
    assert out["rows"][0][1] == expect
    assert any(a["id"] == ds for a in out["aliases"])


def test_sql_tool_rejects_mutation(ds):
    from backend.app.sqlquery import SqlError

    with pytest.raises(SqlError):
        mcpserver.tool_sql_query("DELETE FROM df", dataset_id=ds)


def test_rfm_funnel_cohort_tools(ds):
    rfm = json.loads(mcpserver.tool_rfm(ds, id_column="客户", date_column="日期", value_column="金额"))
    assert rfm["rows"] and "分层" in json.dumps(rfm, ensure_ascii=False)
    # 漏斗需要独立事件表（用户列≠事件列）
    from backend.app import storage
    ev = pd.DataFrame({
        "uid": ["a", "a", "b", "b", "c"],
        "event": ["浏览", "下单", "浏览", "下单", "浏览"],
    })
    ev_id = storage.create_dataset("mcp事件", ev, "ev.csv", ev.to_csv(index=False).encode("utf-8-sig"))
    try:
        funnel = json.loads(mcpserver.tool_funnel(ev_id, user_column="uid", event_column="event", steps=["浏览", "下单"]))
        assert funnel["funnel"]["values"] == [3, 2]
        from backend.app.analysis import AnalysisError

        with pytest.raises(AnalysisError):
            mcpserver.tool_funnel(ev_id, user_column="uid", event_column="uid", steps=["浏览", "下单"])  # 同列防护
    finally:
        storage.delete_dataset(ev_id)
    cohort = json.loads(mcpserver.tool_cohort(ds, user_column="客户", date_column="日期", freq="W"))
    assert cohort["cohort"]["values"]


def test_ab_prop_test_count_mode():
    out = json.loads(mcpserver.tool_ab_prop_test(success_a=120, n_a=1000, success_b=150, n_b=1000))
    assert out["tests"][0]["p"] == pytest.approx(0.0496, abs=1e-3)


def test_rows_capped():
    df = pd.DataFrame({"g": [f"g{i}" for i in range(600)], "v": list(range(600))})
    from backend.app import storage

    ds_id = storage.create_dataset("mcp大表", df, "big.csv", b"g,v\n")
    try:
        # sql 无 top 截断，验证统一行数上限（200）与 truncated 标记
        out = json.loads(mcpserver.tool_sql_query("SELECT g, COUNT(*) AS n FROM df GROUP BY 1", dataset_id=ds_id))
        assert out["total"] == 600
        assert len(out["rows"]) == mcpserver.MAX_ROWS
        assert out["truncated"] is True
    finally:
        storage.delete_dataset(ds_id)


# ---------- Streamable HTTP 协议烟雾 ----------


def _mcp_initialize():
    import uuid as _uuid

    return {
        "jsonrpc": "2.0", "id": _uuid.uuid4().hex, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest-smoke", "version": "0"},
        },
    }


def test_mcp_endpoint_initialize_and_tools_list():
    """挂载在 /mcp/mcp 的 Streamable HTTP 端点应答 initialize 与 tools/list。"""
    with client:  # 进入 lifespan（MCP 会话管理器随应用启动）
        r = client.post(
            "/mcp/mcp", json=_mcp_initialize(),
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text[:300]
        body = r.text
        session_id = r.headers.get("mcp-session-id")
        assert session_id, "缺少会话头"
        assert "data-helper" in body

        # notifications/initialized + tools/list（带会话头）
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
             "mcp-session-id": session_id}
        client.post("/mcp/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
        r2 = client.post(
            "/mcp/mcp",
            json={"jsonrpc": "2.0", "id": "t1", "method": "tools/list", "params": {}},
            headers=h,
        )
        assert r2.status_code == 200, r2.text[:300]
        names = [t.get("name") for t in _extract_tools(r2.text)]
        assert {"list_datasets", "sql_query", "rfm", "funnel", "cohort", "cluster", "ab_prop_test", "forecast"} <= set(names)


def _extract_tools(text: str):
    """从 SSE 帧（data: {...}）或纯 JSON 中取 tools/list 结果。"""
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
    else:
        payload = None
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
    return (payload or {}).get("result", {}).get("tools", [])
