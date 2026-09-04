"""AI Agent：LLM 出意图、本地执行工具、数据不出本机。

- 工具注册表：把汇总/分组/相关/趋势/RFM/漏斗/同期群留存/A-B/聚类/预测等分析能力
  以 JSON Schema 声明为 function calling 工具
- 工具循环：LLM 多轮发起 tool_calls，后端在本地 DataFrame 上真实执行并回填结果，
  LLM 只看到列结构摘要与工具返回的统计结果，原始数据永不上传
- SSE 流式：正文增量实时下发；工具调用下发进度事件，前端展示"正在执行 …"
- 端点不支持 tools 时自动回退纯文本流式对话
"""
import json
import logging
import threading
import time

import requests

from . import analysis, biz, stats_tests
from . import forecast as forecast_mod
from .ai import TIMEOUT_SECONDS, load_config

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
TOOL_MSG_MAX_CHARS = 3500
CARD_MAX_ROWS = 500
SESSION_LIMIT = 50  # 内存级会话数上限（LRU），防长驻进程慢泄漏


class LlmError(ValueError):
    pass


class ToolsUnsupported(LlmError):
    pass


# ---------------- 工具注册表 ----------------
# runner 在本地 DataFrame 上执行；card 描述前端结果卡如何渲染（addCard 参数）


def _t_describe(df, p):
    return analysis.describe(df, {})


def _t_prop_z(df, p):
    if "success_a" in p:
        return stats_tests.prop_z_test(None, p)
    return stats_tests.prop_z_test(df, p)


TOOLS = [
    {
        "name": "describe",
        "label": "汇总统计",
        "description": "对数据集做汇总统计（各数值列计数/均值/标准差/分位数等）。无需参数。",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "runner": _t_describe,
        "card": {"type": "table", "icon": "📋", "title": "汇总统计", "span2": False},
    },
    {
        "name": "groupby",
        "label": "分组聚合",
        "description": "按类别列分组聚合数值列。",
        "parameters": {
            "type": "object",
            "properties": {
                "by": {"type": "array", "items": {"type": "string"}, "description": "分组列（1-2 个）"},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "agg": {"type": "string", "enum": ["sum", "mean", "count", "min", "max", "median", "std", "nunique"]},
                        },
                        "required": ["column", "agg"],
                    },
                },
                "top": {"type": "integer", "description": "只返回前 N 组，默认 20"},
            },
            "required": ["by", "metrics"],
        },
        "runner": analysis.groupby,
        "card": {"type": "table", "icon": "📈", "title": "分组聚合", "span2": False},
    },
    {
        "name": "trend",
        "label": "时间趋势",
        "description": "按日期列+数值列聚合出时间趋势（含同比/环比口径的时间序列）。",
        "parameters": {
            "type": "object",
            "properties": {
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "freq": {"type": "string", "enum": ["D", "W", "M", "Q", "Y"]},
            },
            "required": ["date_column", "value_column"],
        },
        "runner": analysis.trend,
        "card": {"type": "table", "icon": "📉", "title": "时间趋势", "span2": False},
    },
    {
        "name": "corr",
        "label": "相关性分析",
        "description": "数值列两两相关系数矩阵；可指定列，缺省用全部数值列。",
        "parameters": {
            "type": "object",
            "properties": {"columns": {"type": "array", "items": {"type": "string"}}},
            "required": [],
        },
        "runner": analysis.corr,
        "card": {"type": "table", "icon": "🔗", "title": "相关性分析", "span2": False},
    },
    {
        "name": "histogram",
        "label": "直方图分布",
        "description": "单个数值列的分布直方图。",
        "parameters": {
            "type": "object",
            "properties": {"column": {"type": "string"}, "bins": {"type": "integer"}},
            "required": ["column"],
        },
        "runner": analysis.histogram,
        "card": {"type": "table", "icon": "📊", "title": "直方图分布", "span2": False},
    },
    {
        "name": "value_counts",
        "label": "频次统计",
        "description": "类别列的取值频次与占比（Top N）。",
        "parameters": {
            "type": "object",
            "properties": {"column": {"type": "string"}, "top": {"type": "integer"}},
            "required": ["column"],
        },
        "runner": analysis.value_counts,
        "card": {"type": "table", "icon": "🥧", "title": "频次统计", "span2": False},
    },
    {
        "name": "rfm",
        "label": "RFM 客户分层",
        "description": "RFM 客户分层：按客户列+日期列+金额列计算最近消费/频次/金额并分层。",
        "parameters": {
            "type": "object",
            "properties": {
                "id_column": {"type": "string", "description": "客户ID列"},
                "date_column": {"type": "string", "description": "订单日期列"},
                "value_column": {"type": "string", "description": "金额列"},
            },
            "required": ["id_column", "date_column", "value_column"],
        },
        "runner": analysis.rfm,
        "card": {"type": "rfm", "icon": "💎", "title": "RFM 客户分层", "span2": True},
    },
    {
        "name": "funnel",
        "label": "转化漏斗",
        "description": "转化漏斗：用户列+事件列+有序步骤，输出各步到达人数与转化率。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_column": {"type": "string"},
                "event_column": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}, "description": "事件步骤值（按顺序，至少 2 个）"},
            },
            "required": ["user_column", "event_column", "steps"],
        },
        "runner": biz.funnel,
        "card": {"type": "funnel", "icon": "🎯", "title": "转化漏斗", "span2": False},
    },
    {
        "name": "cohort",
        "label": "同期群留存",
        "description": "同期群留存：按用户首次活跃月/周分群，计算第 N 期留存率矩阵。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_column": {"type": "string"},
                "date_column": {"type": "string"},
                "freq": {"type": "string", "enum": ["M", "W"]},
                "periods": {"type": "integer", "description": "观察期数 2-12，默认 8"},
            },
            "required": ["user_column", "date_column"],
        },
        "runner": biz.cohort,
        "card": {"type": "cohort", "icon": "🗓️", "title": "同期群留存", "span2": True},
    },
    {
        "name": "cluster",
        "label": "K-means 聚类",
        "description": "K-means 聚类：选 2 个以上数值列，肘部法+轮廓系数自动推荐 k，输出各簇画像。",
        "parameters": {
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}, "description": "参与聚类的数值列"},
                "k": {"type": "integer", "description": "指定 k；缺省自动推荐"},
            },
            "required": ["columns"],
        },
        "runner": biz.cluster,
        "card": {"type": "cluster", "icon": "🧩", "title": "K-means 聚类", "span2": True},
    },
    {
        "name": "prop_z_test",
        "label": "A/B 两比例检验",
        "description": "A/B 实验两比例 z 检验：数据集模式给 group_column + success_column（+ success_value 转化取值）；"
        "或直接给 success_a/n_a/success_b/n_b 计数。",
        "parameters": {
            "type": "object",
            "properties": {
                "group_column": {"type": "string", "description": "实验分组列"},
                "success_column": {"type": "string", "description": "转化事件列"},
                "success_value": {"type": "string", "description": "代表转化的取值"},
                "success_a": {"type": "number"}, "n_a": {"type": "number"},
                "success_b": {"type": "number"}, "n_b": {"type": "number"},
            },
            "required": [],
        },
        "runner": _t_prop_z,
        "card": {"type": "test", "icon": "🔬", "title": "A/B 两比例 z 检验", "span2": False},
    },
    {
        "name": "forecast",
        "label": "时间序列预测",
        "description": "Holt 趋势/季节预测：日期列+数值列，按月/周粒度预测未来 N 期。",
        "parameters": {
            "type": "object",
            "properties": {
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "freq": {"type": "string", "enum": ["D", "W", "M", "Q", "Y"]},
                "horizon": {"type": "integer", "description": "预测期数 1-36，默认 6"},
            },
            "required": ["date_column", "value_column"],
        },
        "runner": forecast_mod.forecast,
        "card": {"type": "table", "icon": "🔮", "title": "时间序列预测", "span2": True},
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}
TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
    for t in TOOLS
]

AGENT_SYSTEM_PROMPT = (
    "你是「数据分析小助手」的 AI 分析员，帮助业务用户分析一个本地数据集。"
    "你可以调用工具在用户本机真实执行分析（RFM/漏斗/留存/聚类/A-B 检验/预测等），"
    "工具会返回统计结果，你据此给出业务解读。规则：\n"
    "1. 需要计算结论时优先调用合适的工具，不要凭空编造数字；\n"
    "2. 列名必须与数据集摘要完全一致，不确定先说明；\n"
    "3. 工具执行成功后，用简洁中文解读结果并给出业务建议（结论→依据→建议行动）；\n"
    "4. 一次需要多步分析时，可以连续多次调用工具。"
)


# ---------------- 会话历史（内存级） ----------------

_SESSIONS: dict = {}
_SESSION_LOCK = threading.Lock()
_SESSION_MAX_MSGS = 24


def session_history(sid: str) -> list:
    with _SESSION_LOCK:
        return [dict(m) for m in _SESSIONS.get(sid, [])]


def _session_append(sid: str, role: str, content: str) -> None:
    with _SESSION_LOCK:
        lst = _SESSIONS.setdefault(sid, [])
        if not lst:
            # 会话数超限时丢弃最久未活跃的（dict 保序：首个即最老）
            if len(_SESSIONS) > SESSION_LIMIT:
                _SESSIONS.pop(next(iter(_SESSIONS)), None)
        lst.append({"role": role, "content": content})
        del _SESSIONS[sid][:-_SESSION_MAX_MSGS]


# ---------------- LLM 调用（OpenAI 兼容，SSE 流式） ----------------


def _post_llm(cfg: dict, payload: dict, timeout: int):
    url = (cfg.get("base_url") or "").rstrip("/") + "/chat/completions"
    try:
        t0 = time.monotonic()
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {cfg.get('api_key', '')}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
            stream=True,
        )
        logger.info("LLM 请求完成 model=%s tools=%s 耗时=%.1fs", cfg.get("model"), bool(payload.get("tools")), time.monotonic() - t0)
    except requests.RequestException as e:
        logger.warning("LLM 请求失败：%s", e)
        raise LlmError(f"无法连接模型服务：{e}")
    if resp.status_code != 200:
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass
        low = body.lower()
        if resp.status_code in (400, 404, 422, 501) and ("tool" in low or "function" in low):
            raise ToolsUnsupported(f"模型端点不支持 tools：{body}")
        raise LlmError(f"模型服务返回 {resp.status_code}：{body[:200]}")
    return resp


def _iter_sse_json(resp):
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if not str(raw).startswith("data:"):
            continue
        data = str(raw)[5:].strip()
        if data == "[DONE]":
            return
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict) and chunk.get("error") and not chunk.get("choices"):
            # 供应商中途报错（无 choices 的 error 帧）：转成可读异常，不静默吞掉
            err = chunk["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise LlmError(f"模型服务流式返回错误：{msg}")
        yield chunk


def _stream_completion(cfg: dict, messages: list, tools: list | None):
    """流式请求一次补全：yield 文本增量；返回累计的 (content, tool_calls)。"""
    payload = {"model": cfg.get("model", ""), "messages": messages, "stream": True, "temperature": 0.3}
    if tools:
        payload["tools"] = tools
    resp = _post_llm(cfg, payload, TIMEOUT_SECONDS)
    content_parts, tool_calls = [], {}
    try:
        for chunk in _iter_sse_json(resp):
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)
                yield piece
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]  # 分片重发时整体替换，不做子串拼接
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
    finally:
        resp.close()
    calls = [tool_calls[i] for i in sorted(tool_calls)]
    for c in calls:
        if not c["id"]:
            c["id"] = f"call_{c['name']}_{int(time.time() * 1000)}"
    return "".join(content_parts), calls


def _run_tool(df, call: dict):
    """本地执行一次工具调用。返回 (card, summary_str, brief)；失败时 card 为 None。"""
    tool = TOOLS_BY_NAME.get(call["name"])
    if tool is None:
        return None, f"未知工具 {call['name']}", ""
    try:
        args = json.loads(call["arguments"] or "{}")
        if not isinstance(args, dict):
            raise ValueError("参数必须是 JSON 对象")
    except json.JSONDecodeError as e:
        return None, f"参数不是合法 JSON：{e}", ""
    try:
        result = tool["runner"](df, args)
    except (ValueError, KeyError) as e:
        logger.info("工具 %s 执行失败：%s", call["name"], e)
        return None, f"执行失败：{e}", ""
    except Exception as e:  # 未预期异常也回给 LLM，让它调整参数重试
        logger.warning("工具 %s 异常：%s", call["name"], e)
        return None, f"执行异常：{e}", ""
    # 先截断再返回：巨大结果在 JSON 化阶段就会撑爆内存，不能等调用方再截
    try:
        summary = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        summary = str(result)
    if len(summary) > TOOL_MSG_MAX_CHARS:
        summary = summary[:TOOL_MSG_MAX_CHARS] + "…（截断）"
    card = dict(tool["card"])
    payload = result
    rows = result.get("rows") if isinstance(result, dict) else None
    if isinstance(rows, list) and len(rows) > CARD_MAX_ROWS:
        # 卡片只做展示：高基数分组（几十万行）不进 SSE / 前端内存
        payload = dict(result)
        total = len(rows)
        payload["rows"] = rows[:CARD_MAX_ROWS]
        base_note = str(payload.get("note") or "").strip()
        payload["note"] = (base_note + "；" if base_note else "") + f"卡片仅显示前 {CARD_MAX_ROWS} 行（共 {total} 行）"
    card["payload"] = payload
    return card, summary, _brief(result)


def _as_events(sub):
    """把一次补全的文本增量包装成 delta 事件流，最后带回 (content, tool_calls)。"""
    try:
        while True:
            piece = next(sub)
            yield {"type": "delta", "text": piece}
    except StopIteration as e:
        return e.value


def stream_agent(context: str, user_message: str, df, sid: str = ""):
    """Agent 主循环：流式 yield 事件 dict。

    事件：delta{text} / tool_start{name,label} / tool_result{name,card,summary}
         / note{text} / error{message} / done{text}
    """
    cfg = load_config()
    if not (cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")):
        raise LlmError("请先在设置中填写 API Key、接口地址和模型名称")

    history = session_history(sid) if sid else []
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT + "\n\n【数据集摘要】\n" + context},
        *history,
        {"role": "user", "content": user_message},
    ]

    use_tools = True
    final_text = ""
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            try:
                content, calls = yield from _as_events(_stream_completion(cfg, messages, TOOLS_SCHEMA if use_tools else None))
            except ToolsUnsupported:
                if not use_tools:
                    raise
                use_tools = False
                yield {"type": "note", "text": "当前模型端点不支持工具调用，已切换为纯文本对话模式"}
                continue

            if not calls:
                final_text = content
                break

            messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for c in calls
                ],
            })
            for c in calls:
                tool = TOOLS_BY_NAME.get(c["name"])
                label = tool["label"] if tool else c["name"]
                yield {"type": "tool_start", "name": c["name"], "label": f"正在执行 {label}…"}
                card, summary, brief = _run_tool(df, c)
                # 失败也发 tool_result（card=None）：前端据此撤掉 spinner 并显示原因
                yield ({"type": "tool_result", "name": c["name"], "card": card, "summary": brief}
                       if card is not None else
                       {"type": "tool_result", "name": c["name"], "card": None, "error": summary})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": summary[:TOOL_MSG_MAX_CHARS]})
        else:
            # 轮次耗尽：不再给工具，强制总结
            content, _ = yield from _as_events(_stream_completion(cfg, messages, None))
            final_text = content
    except LlmError as e:
        yield {"type": "error", "message": str(e)}
        return

    if not final_text.strip():
        final_text = "（模型没有返回内容）"
    if sid:
        _session_append(sid, "user", user_message)
        _session_append(sid, "assistant", final_text)
    yield {"type": "done", "text": final_text}


def _brief(summary) -> str:
    """给前端的一行结果摘要。"""
    try:
        if isinstance(summary, dict):
            note = summary.get("note") or ""
            if note:
                return str(note)[:120]
            rows = summary.get("rows")
            if isinstance(rows, list):
                return f"共 {len(rows)} 行结果"
    except Exception:
        pass
    return ""
