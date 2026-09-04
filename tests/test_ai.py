"""阶段5：AI 模块（配置读写 / 上下文构建 / 未配置与网络失败的错误路径）。"""
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import ai as ai_mod
from backend.app.main import app

client = TestClient(app)


def _upload():
    r = client.post(
        "/api/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n".encode("utf-8"), "text/csv")},
        data={"name": ""},
    )
    return r.json()["id"]


def test_settings_roundtrip():
    r = client.get("/api/ai/settings")
    assert r.status_code == 200
    assert r.json()["configured"] is False
    r2 = client.put(
        "/api/ai/settings",
        json={"api_key": "sk-test", "base_url": "https://example.com/v4", "model": "glm-test"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["configured"] is True
    assert body["model"] == "glm-test"
    # 清空 key 后回到未配置状态
    r3 = client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})
    assert r3.json()["configured"] is False


def test_settings_key_masked_and_kept():
    """GET 不回传明文 key；把掩码值原样 PUT 回去不会破坏已保存的密钥。"""
    client.put(
        "/api/ai/settings",
        json={"api_key": "sk-secret-1234567890", "base_url": "https://example.com/v4", "model": "glm-test"},
    )
    got = client.get("/api/ai/settings").json()
    assert got["has_key"] is True
    assert "sk-secret-1234567890" not in got["api_key"]
    assert got["api_key"].startswith("sk-") and "****" in got["api_key"]
    # 掩码值回传 → 保留原 key，连接状态不变
    kept = client.put(
        "/api/ai/settings",
        json={"api_key": got["api_key"], "base_url": "https://example.com/v4", "model": "glm-test"},
    ).json()
    assert kept["configured"] is True
    client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})


def test_chat_without_config_400():
    ds = _upload()
    r = client.post(
        "/api/ai/chat",
        json={"dataset_id": ds, "messages": [{"role": "user", "content": "分析一下"}]},
    )
    assert r.status_code == 400
    assert "请先在设置中填写" in r.json()["detail"]


def test_chat_connection_error_400():
    ds = _upload()
    client.put(
        "/api/ai/settings",
        json={"api_key": "sk-x", "base_url": "http://127.0.0.1:1", "model": "m"},
    )
    r = client.post(
        "/api/ai/chat",
        json={"dataset_id": ds, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 400
    client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})


def test_build_context():
    meta = {"name": "销售", "rows": 10, "cols": 2}
    profile = [
        {"name": "地区", "dtype": "str", "missing_pct": 5.0, "nunique": 3,
         "top_values": [{"value": "华东", "count": 5}]},
        {"name": "销售额", "dtype": "float64", "missing_pct": 0.0, "nunique": 10,
         "kind": "numeric", "min": 1, "max": 9, "mean": 5.0},
    ]
    ctx = ai_mod.build_context(meta, profile)
    assert "数据集名称：销售" in ctx
    assert "地区 | str" in ctx
    assert "min=1, max=9" in ctx


def test_chat_ok_with_mocked_llm():
    ds = _upload()
    client.put(
        "/api/ai/settings",
        json={"api_key": "sk-x", "base_url": "https://fake/v4", "model": "m"},
    )
    fake = mock.Mock()
    fake.status_code = 200
    fake.json.return_value = {"choices": [{"message": {"content": "华东最高。```python\ndf = df.head()\n```"}}]}
    with mock.patch.object(ai_mod.requests, "post", return_value=fake) as p:
        r = client.post(
            "/api/ai/chat",
            json={"dataset_id": ds, "messages": [{"role": "user", "content": "哪个地区销售额最高"}]},
        )
    assert r.status_code == 200
    assert "华东最高" in r.json()["reply"]
    # 请求体包含数据集上下文
    sent = p.call_args.kwargs["json"]
    assert "数据集名称" in sent["messages"][0]["content"]
    client.put("/api/ai/settings", json={"api_key": "", "base_url": "", "model": ""})
