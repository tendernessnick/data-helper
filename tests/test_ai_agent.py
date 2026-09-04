"""Phase 4 AI Agent：SSE 流式 + function calling 工具循环（mock LLM，工具本地真实执行）。"""
import json

import pandas as pd
from fastapi.testclient import TestClient

from backend.app import agent
from backend.app.main import app

client = TestClient(app)

# ---------- mock LLM 基建 ----------


class FakeResp:
    def __init__(self, lines, status=200, body=""):
        self.status_code = status
        self._lines = lines
        self._body = body

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    @property
    def text(self):
        return self._body

    def close(self):
        pass


def chunk(delta=None, tool_calls=None):
    d = {}
    if delta is not None:
        d["content"] = delta
    if tool_calls is not None:
        d["tool_calls"] = tool_calls
    return "data: " + json.dumps({"choices": [{"delta": d}]}, ensure_ascii=False)


def tool_call(idx=0, call_id="call_1", name="rfm", arguments="{}"):
    return [{"index": idx, "id": call_id, "function": {"name": name, "arguments": arguments}}]


DF = pd.DataFrame({
    "订单ID": [f"o{i}" for i in range(6)],
    "客户": ["u1", "u1", "u2", "u3", "u3", "u3"],
    "日期": ["2026-01-05", "2026-02-10", "2026-02-20", "2026-03-01", "2026-03-15", "2026-04-02"],
    "金额": [100, 250, 80, 300, 120, 500],
})


def run_agent(monkeypatch, scripted, msg="帮我分析", sid=""):
    """按脚本依次返回 LLM 响应；返回 (事件列表, 捕获的请求 payload)。"""
    monkeypatch.setattr(agent, "load_config", lambda: {"api_key": "k", "base_url": "http://x", "model": "m"})
    calls = {"payloads": []}

    def fake_post(cfg, payload, timeout):
        calls["payloads"].append(payload)
        return FakeResp(scripted[len(calls["payloads"]) - 1])

    monkeypatch.setattr(agent, "_post_llm", fake_post)
    events = list(agent.stream_agent("数据集摘要", msg, DF, sid=sid))
    return events, calls["payloads"]


# ---------- 工具循环 ----------


def test_tool_roundtrip_executes_locally(monkeypatch):
    args1 = json.dumps({"id_column": "客户", "date_column": "日期", "value_column": "金额"})
    scripted = [
        [chunk(tool_calls=tool_call(name="rfm", arguments=args1[:8])), chunk(tool_calls=tool_call(name="rfm", arguments=args1[8:])), "data: [DONE]"],
        [chunk("RFM"), chunk("分析完成，"), chunk("高价值客户 1 人。"), "data: [DONE]"],
    ]
    events, payloads = run_agent(monkeypatch, scripted)

    types = [e["type"] for e in events]
    assert "tool_start" in types and "tool_result" in types and "done" in types
    start = next(e for e in events if e["type"] == "tool_start")
    assert start["name"] == "rfm" and "RFM" in start["label"]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["card"]["type"] == "rfm"
    assert result["card"]["payload"]["rows"], "本地真实执行的 RFM 应有结果行"
    text = "".join(e.get("text", "") for e in events if e["type"] == "delta")
    assert text == "RFM分析完成，高价值客户 1 人。"
    # 第二轮请求应包含 tool 消息回填
    second = payloads[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-2]["role"] == "assistant"
    assert any("金额" in m.get("content", "") or "error" in m.get("content", "") for m in second if m["role"] == "tool")


def test_tool_error_feeds_back_and_recovers(monkeypatch):
    scripted = [
        [chunk(tool_calls=tool_call(name="rfm", arguments='{"id_column": "客户", "date_column": "不存在列"}')), "data: [DONE]"],
        [chunk(tool_calls=tool_call(call_id="call_2", name="rfm", arguments='{"id_column": "客户", "date_column": "日期", "value_column": "金额"}')), "data: [DONE]"],
        [chunk("已修正参数并完成分析。"), "data: [DONE]"],
    ]
    events, payloads = run_agent(monkeypatch, scripted)
    tool_msgs = [m for p in payloads for m in p["messages"] if m["role"] == "tool"]
    assert "不存在列" in tool_msgs[0]["content"]  # 错误回填给 LLM
    assert next(e for e in events if e["type"] == "done")["text"] == "已修正参数并完成分析。"


def test_plain_text_stream_without_tools(monkeypatch):
    scripted = [[chunk("你好"), chunk("，我是分析助手。"), "data: [DONE]"]]
    events, _ = run_agent(monkeypatch, scripted)
    assert [e for e in events if e["type"] in ("tool_start", "tool_result")] == []
    assert next(e for e in events if e["type"] == "done")["text"] == "你好，我是分析助手。"


def test_tools_unsupported_falls_back(monkeypatch):
    monkeypatch.setattr(agent, "load_config", lambda: {"api_key": "k", "base_url": "http://x", "model": "m"})

    def fake_post(cfg, payload, timeout):
        if payload.get("tools"):
            raise agent.ToolsUnsupported("模型端点不支持 tools")
        return FakeResp([chunk("纯文本模式的回答。"), "data: [DONE]"])

    monkeypatch.setattr(agent, "_post_llm", fake_post)
    events = list(agent.stream_agent("摘要", "帮我看看", DF))
    notes = [e for e in events if e["type"] == "note"]
    assert notes and "纯文本" in notes[0]["text"]
    assert next(e for e in events if e["type"] == "done")["text"] == "纯文本模式的回答。"


def test_session_history_replay(monkeypatch):
    scripted = [
        FakeResp([chunk("第一次回答"), "data: [DONE]"]),
        FakeResp([chunk("第二次回答"), "data: [DONE]"]),
    ]
    holder = {"i": 0}
    seen = []

    def fake_post(cfg, payload, timeout):
        seen.append(payload)
        r = scripted[holder["i"]]
        holder["i"] += 1
        return r

    monkeypatch.setattr(agent, "load_config", lambda: {"api_key": "k", "base_url": "http://x", "model": "m"})
    monkeypatch.setattr(agent, "_post_llm", fake_post)
    list(agent.stream_agent("摘要", "第一问", DF, sid="sess-x"))
    list(agent.stream_agent("摘要", "第二问", DF, sid="sess-x"))
    hist = agent.session_history("sess-x")
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert hist[1]["content"] == "第一次回答"
    # 第二次请求应带上第一轮的问答历史
    second_msgs = seen[1]["messages"]
    assert any(m.get("content") == "第一次回答" for m in second_msgs)
    assert any(m.get("content") == "第一问" for m in second_msgs)


# ---------- SSE 端点 ----------


def test_stream_endpoint_sse_protocol(monkeypatch):
    from backend.app import storage as st

    ds = st.create_dataset("sse-demo", DF, "sse.csv", b"a,b\n1,2\n")
    monkeypatch.setattr(agent, "load_config", lambda: {"api_key": "k", "base_url": "http://x", "model": "m"})
    scripted = [[chunk(chunk_text) for chunk_text in ("结论：", "客单价上升。")] + ["data: [DONE]"]]
    monkeypatch.setattr(agent, "_post_llm", lambda cfg, payload, timeout: FakeResp(scripted[0]))
    r = client.post("/api/ai/chat/stream", json={"dataset_id": ds, "message": "看看客单价", "session_id": "sse-test"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
    evts = [json.loads(f) for f in frames]
    assert evts[0]["type"] == "session" and evts[0]["session_id"] == "sse-test"
    assert evts[-1]["type"] == "done" and evts[-1]["text"] == "结论：客单价上升。"
    st.delete_dataset(ds)


def test_stream_endpoint_without_config(monkeypatch):
    from backend.app import storage as st

    monkeypatch.setattr(agent, "load_config", lambda: {})
    ds = st.create_dataset("sse-nocfg", DF, "nc.csv", b"a\n1\n")
    r = client.post("/api/ai/chat/stream", json={"dataset_id": ds, "message": "hi"})
    assert r.status_code == 200
    evts = [json.loads(ln[5:].strip()) for ln in r.text.splitlines() if ln.startswith("data:")]
    assert evts[-1]["type"] == "error" and "API Key" in evts[-1]["message"]
    st.delete_dataset(ds)


def test_tools_schema_complete():
    names = {t["name"] for t in agent.TOOLS}
    assert {"describe", "groupby", "trend", "corr", "histogram", "value_counts", "rfm", "funnel", "cohort", "cluster", "prop_z_test", "forecast"} <= names
    for f in agent.TOOLS_SCHEMA:
        assert f["type"] == "function" and f["function"]["parameters"]["type"] == "object"
