"""可选的大模型问答模块。

- 配置（API Key / Base URL / 模型名）保存在本机 data/config.json
- 走 OpenAI 兼容 /chat/completions 接口（支持智谱 GLM / OpenAI / DeepSeek 等）
- 未配置时主流程完全不受影响
"""
import json

import requests

from .paths import CONFIG_PATH

TIMEOUT_SECONDS = 90

DEFAULT_SYSTEM_PROMPT = (
    "你是「数据分析小助手」里的AI分析员。用户正在查看一个 pandas DataFrame 数据集，"
    "下面会提供该数据集的结构摘要。\n"
    "回答要求：\n"
    "1. 用中文，简洁专业，面向业务人员。\n"
    "2. 涉及计算结论时说明依据（哪一列、什么聚合）。\n"
    "3. 如果适合用代码进一步分析或处理数据，给出一段 Python 代码块（```python ... ```），"
    "代码中直接操作变量 df（pandas DataFrame），pd 和 np 已可用，不要使用 print 之外的外部库。\n"
    "4. 不要编造摘要里没有的数据结论；信息不足时先说明。"
)

CHART_SPEC_PROMPT = (
    "你是图表配置生成器。根据用户的自然语言需求和数据集摘要，输出一个 JSON 对象（只输出 JSON，不要任何其他文字）：\n"
    '{"kind": "<分析类型>", "params": {<参数>}, "title": "<简短中文标题>"}\n'
    "可选 kind 与必填参数：\n"
    '- groupby: {"by": ["分组列"], "metrics": [{"column": "数值列", "agg": "sum|mean|count|min|max|median|std|nunique"}]}\n'
    '- pivot: {"index": "行维度", "columns": "列维度或null", "values": "数值列", "aggfunc": "sum"}\n'
    "- trend / growth / moving_avg: {\"date_column\": \"日期列\", \"value_column\": \"数值列\", \"freq\": \"D|W|M|Q|Y\""
    "（moving_avg 额外 \"window\": 整数≥2）}\n"
    '- corr: {"columns": ["数值列"...] 或省略}\n'
    '- histogram: {"column": "数值列", "bins": 整数}\n'
    "- boxplot: {\"columns\": [\"数值列\"...] 或省略}\n"
    '- value_counts: {"column": "列", "top": 整数}\n'
    "- describe: {}\n"
    '- rfm: {"id_column": "客户列", "date_column": "日期列", "value_column": "金额列"}\n'
    '- pareto: {"category_column": "类别列", "value_column": "数值列", "top_n": 整数}\n'
    "- outliers: {\"columns\": [\"数值列\"] 或省略, \"method\": \"iqr|zscore\"}\n"
    '- scatter: {"x": "数值列", "y": "数值列"}\n'
    "- cross_heat: {\"row\": \"类别列\", \"col\": \"类别列\"}\n"
    "要求：列名必须与摘要中的列名完全一致；日期列若是文本日期也可以直接用于 trend/growth；"
    "不确定时选择最贴近用户意图的类型。"
)


def chart_spec(messages: list, context: str, timeout: int = TIMEOUT_SECONDS) -> dict:
    """自然语言 → 图表配置 JSON。返回 {kind, params, title}。"""
    cfg = load_config()
    api_key = cfg.get("api_key", "")
    base_url = (cfg.get("base_url") or "").rstrip("/")
    model = cfg.get("model", "")
    if not (api_key and base_url and model):
        raise ValueError("请先在设置中填写 API Key、接口地址和模型名称")
    url = base_url + "/chat/completions"
    user_text = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")[-1500:]
    payload_messages = [
        {"role": "system", "content": CHART_SPEC_PROMPT + "\n\n【数据集摘要】\n" + context},
        {"role": "user", "content": user_text},
    ]
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": payload_messages, "temperature": 0.1},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise ValueError(f"无法连接模型服务：{e}")
    if resp.status_code != 200:
        raise ValueError(f"模型服务返回 {resp.status_code}：{resp.text[:200]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"模型响应格式异常：{e}")
    # 容错解析：剥掉 markdown 代码块
    text = content.strip()
    if "```" in text:
        import re as _re

        m = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    import json as _json

    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"模型未返回有效的图表配置：{content[:120]}")
    try:
        spec = _json.loads(text[start : end + 1])
    except _json.JSONDecodeError as e:
        raise ValueError(f"图表配置解析失败：{e}")
    if not isinstance(spec, dict) or "kind" not in spec:
        raise ValueError(f"图表配置缺少 kind 字段：{content[:120]}")
    spec.setdefault("params", {})
    spec.setdefault("title", "AI 图表")
    return spec



def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(cfg: dict) -> dict:
    merged = load_config()
    merged.update({k: v for k, v in cfg.items() if k in ("api_key", "base_url", "model")})
    CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged


def public_config() -> dict:
    cfg = load_config()
    return {
        "api_key": cfg.get("api_key", ""),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "configured": bool(cfg.get("api_key") and cfg.get("base_url") and cfg.get("model")),
    }


def build_context(meta: dict, profile: list) -> str:
    lines = [
        f"数据集名称：{meta.get('name', '')}",
        f"规模：{meta.get('rows', 0)} 行 × {meta.get('cols', 0)} 列",
        "列结构（名称 | 类型 | 缺失% | 唯一值数 | 概要）：",
    ]
    for c in profile:
        brief = ""
        if c.get("kind") == "numeric":
            brief = f"min={c.get('min')}, max={c.get('max')}, mean={round(c.get('mean'), 2) if c.get('mean') is not None else None}"
        elif c.get("top_values"):
            tops = ", ".join(f"{t['value']}×{t['count']}" for t in c["top_values"][:3])
            brief = f"高频值: {tops}"
        lines.append(
            f"- {c['name']} | {c['dtype']} | 缺失{c['missing_pct']}% | {c['nunique']}个唯一值 | {brief}"
        )
    return "\n".join(lines)


def chat(messages: list, context: str, timeout: int = TIMEOUT_SECONDS) -> str:
    cfg = load_config()
    api_key = cfg.get("api_key", "")
    base_url = (cfg.get("base_url") or "").rstrip("/")
    model = cfg.get("model", "")
    if not (api_key and base_url and model):
        raise ValueError("请先在设置中填写 API Key、接口地址和模型名称")
    url = base_url + "/chat/completions"
    payload_messages = [
        {"role": "system", "content": DEFAULT_SYSTEM_PROMPT + "\n\n【数据集摘要】\n" + context}
    ] + [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": payload_messages, "temperature": 0.3},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise ValueError(f"无法连接模型服务：{e}")
    if resp.status_code != 200:
        detail = ""
        try:
            j = resp.json()
            detail = j.get("error", {}).get("message") or resp.text[:200]
        except (ValueError, AttributeError):
            detail = resp.text[:200]
        raise ValueError(f"模型服务返回 {resp.status_code}：{detail}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"模型响应格式异常：{e}")
