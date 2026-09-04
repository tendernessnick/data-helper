"""MCP 服务端：把本软件的分析能力暴露给外部聊天客户端（Cherry Studio / ChatWise 等）。

架构与内置 AI Agent 相同的隐私边界：LLM 在客户端侧（用户自己的 API Key），
意图产生的工具调用回到本机执行，原始数据不出本机。

- 懒加载 mcp 依赖：未安装时其余功能不受影响（挂载返回 None）
- 传输：Streamable HTTP（/mcp/mcp）与 SSE（/sse/sse，兼容旧客户端）
- 工具全部只读（分析 + SELECT-only SQL），与 SQL 控制台同级别防护
"""
import json
import logging

from . import analysis, biz, sqlquery, stats_tests, storage
from . import forecast as forecast_mod
from .profile import profile_columns
from .serialize import cell

logger = logging.getLogger(__name__)

MAX_ROWS = 200  # 工具返回给 LLM 的行数上限（防上下文爆炸）

MCP_INSTRUCTIONS = (
    "这是本地数据分析工具集。请先调用 list_datasets 查看可用数据集，"
    "再用 column_profile 了解列结构（列名/类型/统计量），然后按需调用分析工具。"
    "列名必须与 column_profile 返回的完全一致。计算结论请引用工具返回的数字。"
)


def _cap_rows(result: dict, max_rows: int = MAX_ROWS) -> dict:
    """分析结果统一裁剪：行数封顶 + 附提示，其余结构保留。"""
    out = dict(result)
    rows = out.get("rows")
    if isinstance(rows, list) and len(rows) > max_rows:
        out["rows"] = rows[:max_rows]
        out["truncated"] = True
        out.setdefault("note", "")
        out["note"] = f"{out['note']}；仅返回前 {max_rows} 行（共 {len(rows)} 行）".lstrip("；")
    detail = out.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("rows"), list) and len(detail["rows"]) > max_rows:
        detail = dict(detail)
        detail["rows"] = detail["rows"][:max_rows]
        out["detail"] = detail
    return out


def _dumps(obj) -> str:
    """转 JSON 字符串（NaN/Timestamp/numpy 标量安全）。"""
    def _default(v):
        try:
            return cell(v)
        except Exception:  # noqa: BLE001
            return str(v)
    return json.dumps(obj, ensure_ascii=False, default=_default)


# ---------------- 工具实现（普通函数，可直接单测） ----------------


def tool_list_datasets() -> str:
    out = []
    for m in storage.list_datasets():
        out.append({
            "dataset_id": m["id"], "name": m["name"],
            "rows": m["rows"], "cols": m["cols"],
            "columns": [c["name"] for c in m.get("columns", [])],
        })
    return _dumps({"datasets": out, "hint": "后续工具用 dataset_id 引用"})


def tool_column_profile(dataset_id: str) -> str:
    df = storage.load_df(dataset_id)
    prof = profile_columns(df)
    slim = [{
        "name": c["name"], "dtype": c["dtype"], "kind": c["kind"],
        "missing_pct": c["missing_pct"], "nunique": c["nunique"],
        "min": c.get("min"), "max": c.get("max"), "mean": c.get("mean"),
        "top_values": [t["value"] for t in c.get("top_values", [])[:3]],
    } for c in prof]
    return _dumps({"dataset_id": dataset_id, "rows": len(df), "columns": slim})


def tool_read_rows(dataset_id: str, page: int = 1, page_size: int = 20) -> str:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), MAX_ROWS))
    df = storage.load_df(dataset_id)
    start = (page - 1) * page_size
    part = df.iloc[start:start + page_size]
    return _dumps({
        "total": len(df), "page": page, "page_size": page_size,
        "columns": [str(c) for c in part.columns],
        "rows": [[cell(v) for v in row] for row in part.itertuples(index=False, name=None)],
    })


def tool_sql_query(query: str, dataset_id: str = "") -> str:
    """只读 SQL（SELECT/WITH），跨数据集 JOIN 用别名 ds1/ds2…，当前集亦可用 df。"""
    metas = storage.list_datasets()
    datasets = [{"id": m["id"], "name": m["name"], "path": str(storage.current_path(m["id"]))} for m in metas]
    aliases = [{"alias": f"ds{i + 1}", "id": d["id"], "name": d["name"]} for i, d in enumerate(datasets)]
    result = sqlquery.run_sql(query, datasets, current_id=dataset_id)
    result.pop("df", None)
    result = _cap_rows(result)
    result["aliases"] = aliases
    return _dumps(result)


def _analyze(dataset_id: str, kind: str, params: dict) -> str:
    df = storage.load_df(dataset_id)
    result = analysis.run(df, kind, params)
    return _dumps(_cap_rows(result))


def tool_describe(dataset_id: str) -> str:
    return _analyze(dataset_id, "describe", {})


def tool_groupby(dataset_id: str, by: list[str], metrics: list[dict], top: int = 20) -> str:
    return _analyze(dataset_id, "groupby", {"by": by, "metrics": metrics, "top": max(1, min(int(top), MAX_ROWS))})


def tool_correlation(dataset_id: str, columns: list[str] | None = None, method: str = "pearson") -> str:
    return _analyze(dataset_id, "corr", {"columns": columns or [], "method": method})


def tool_value_counts(dataset_id: str, column: str, top: int = 15) -> str:
    return _analyze(dataset_id, "value_counts", {"column": column, "top": max(1, min(int(top), MAX_ROWS))})


def tool_trend(dataset_id: str, date_column: str, value_column: str, freq: str = "M") -> str:
    return _analyze(dataset_id, "trend", {"date_column": date_column, "value_column": value_column, "freq": freq})


def tool_rfm(dataset_id: str, id_column: str, date_column: str, value_column: str) -> str:
    return _analyze(dataset_id, "rfm", {"id_column": id_column, "date_column": date_column, "value_column": value_column})


def tool_funnel(dataset_id: str, user_column: str, event_column: str, steps: list[str]) -> str:
    df = storage.load_df(dataset_id)
    return _dumps(_cap_rows(biz.funnel(df, {
        "user_column": user_column, "event_column": event_column, "steps": steps,
    })))


def tool_cohort(dataset_id: str, user_column: str, date_column: str, freq: str = "M", periods: int = 8) -> str:
    df = storage.load_df(dataset_id)
    return _dumps(_cap_rows(biz.cohort(df, {
        "user_column": user_column, "date_column": date_column, "freq": freq, "periods": periods,
    })))


def tool_cluster(dataset_id: str, columns: list[str], k: int = 0) -> str:
    df = storage.load_df(dataset_id)
    result = biz.cluster(df, {"columns": columns, "k": int(k)})
    result.pop("cluster_points", None)  # 散点原始数据对 LLM 无用且巨大
    return _dumps(_cap_rows(result))


def tool_ab_prop_test(dataset_id: str = "", group_column: str = "", success_column: str = "",
                      success_value: str = "", success_a: float | None = None, n_a: float | None = None,
                      success_b: float | None = None, n_b: float | None = None) -> str:
    if success_a is not None and n_a is not None:
        result = stats_tests.prop_z_test(None, {
            "success_a": success_a, "n_a": n_a, "success_b": success_b, "n_b": n_b,
        })
    else:
        df = storage.load_df(dataset_id) if dataset_id else None
        result = stats_tests.prop_z_test(df, {
            "group_column": group_column, "success_column": success_column, "success_value": success_value,
        })
    return _dumps(result)


def tool_forecast(dataset_id: str, date_column: str, value_column: str,
                  horizon: int = 6, freq: str = "M") -> str:
    df = storage.load_df(dataset_id)
    return _dumps(_cap_rows(forecast_mod.forecast(df, {
        "date_column": date_column, "value_column": value_column,
        "horizon": horizon, "freq": freq,
    }), max_rows=60))


# ---------------- 服务器构建与挂载 ----------------


def build_server():
    """构建 MCPServer 并注册全部工具。返回 (server, streamable_app)；未安装 mcp 时抛 ImportError。"""
    from mcp.server.mcpserver import MCPServer

    s = MCPServer(
        name="data-helper",
        title="数据分析小助手",
        description="本地数据分析工具集：数据集浏览 / SQL / RFM / 漏斗 / 留存 / 聚类 / A-B / 预测",
        instructions=MCP_INSTRUCTIONS,
    )

    s.add_tool(tool_list_datasets, name="list_datasets",
               description="列出本机全部数据集（dataset_id、名称、行列数、列名清单）。分析前先调用它。")
    s.add_tool(tool_column_profile, name="column_profile",
               description="查看指定数据集每列的类型/缺失率/唯一值数/数值统计/高频值。选列前必看。")
    s.add_tool(tool_read_rows, name="read_rows",
               description="分页预览数据集原始行（page/page_size）。")
    s.add_tool(tool_sql_query, name="sql_query",
               description="只读 SQL 查询（DuckDB 方言，仅 SELECT/WITH）。数据集别名 ds1/ds2…，指定 dataset_id 时亦可用 df；支持 JOIN/窗口函数。")
    s.add_tool(tool_describe, name="describe", description="数值列汇总统计（count/mean/std/分位数）。")
    s.add_tool(tool_groupby, name="groupby",
               description="分组聚合。metrics=[{column,agg}]，agg 可选 sum/mean/count/min/max/median/std/nunique；top 限制返回组数。")
    s.add_tool(tool_correlation, name="correlation",
               description="数值列相关矩阵。method 可选 pearson/spearman/kendall。")
    s.add_tool(tool_value_counts, name="value_counts", description="类别列取值频次 Top N。")
    s.add_tool(tool_trend, name="trend", description="时间趋势。freq 可选 D/W/M/Q/Y。")
    s.add_tool(tool_rfm, name="rfm",
               description="RFM 客户分层：id_column=客户列，date_column=日期列，value_column=金额列；输出 8 层分层与金额占比。")
    s.add_tool(tool_funnel, name="funnel",
               description="转化漏斗（到达制口径）：user_column=用户列，event_column=事件列，steps=有序事件值列表（≥2 步）。")
    s.add_tool(tool_cohort, name="cohort",
               description="同期群留存矩阵：按首次活跃分群。freq 可选 M/W；periods=观察期数(2-12)。")
    s.add_tool(tool_cluster, name="cluster",
               description="K-means 聚类（自动选 k）：columns=≥2 个数值列；k=0 自动推荐。输出各簇画像与轮廓系数。")
    s.add_tool(tool_ab_prop_test, name="ab_prop_test",
               description="A/B 两比例 z 检验。数据集模式：group_column+success_column+success_value；或直接计数：success_a/n_a/success_b/n_b。输出 p 值、差值 CI 与相对提升。")
    s.add_tool(tool_forecast, name="forecast",
               description="时序预测：三方法（线性/Holt/季节朴素）回测选优，输出未来 horizon 期点值与区间。")

    import asyncio as _a

    n_tools = len(_a.run(s.list_tools()))
    logger.info("MCP 服务器已构建（%d 个工具）", n_tools)
    return s, s.streamable_http_app(), s.sse_app()


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False
