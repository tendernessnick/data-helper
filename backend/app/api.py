"""全部 HTTP API 路由（挂在 /api 前缀下）。"""
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import analysis
from . import ai
from . import cleaning
from . import compare as compare_mod
from . import datafeed
from . import finance
from . import deepprofile
from . import exporter
from . import forecast as forecast_mod
from . import insights as insights_mod
from . import profile as prof
from . import report as report_mod
from . import sample as sample_mod
from . import sqlquery
from . import stats_tests
from . import storage
from . import suggest as suggest_mod
from . import transform
from .serialize import rows_payload
from .storage import DatasetNotFound

router = APIRouter()


def _load(ds_id: str) -> pd.DataFrame:
    try:
        return storage.load_df(ds_id)
    except DatasetNotFound:
        raise HTTPException(404, "数据集不存在或已删除")


def _meta_or_404(ds_id: str) -> dict:
    try:
        return storage.get_meta(ds_id)
    except DatasetNotFound:
        raise HTTPException(404, "数据集不存在或已删除")


# ---------- 数据集管理 ----------


@router.post("/upload")
async def upload(file: UploadFile = File(...), name: str = Form(None), sheet: str = Form(None)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "上传的文件为空")
    try:
        df = storage.parse_upload(file.filename or "", raw, sheet_name=sheet)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 解析器抛出的其他异常（结构错误等）
        raise HTTPException(400, f"文件解析失败：{e}")
    ds_id = storage.create_dataset(name, df, file.filename or "data.csv", raw)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


class PasteBody(BaseModel):
    text: str
    name: str = ""


@router.post("/upload-paste")
def upload_paste(body: PasteBody):
    text = (body.text or "").lstrip("\ufeff").strip()
    if not text:
        raise HTTPException(400, "粘贴内容为空")
    # Excel 复制默认 Tab 分隔；统一转成 CSV 文本走既有解析
    first_line = text.splitlines()[0]
    if "\t" in first_line and "," not in first_line:
        text = text.replace("\t", ",")
    raw = text.encode("utf-8-sig")
    try:
        df = storage.parse_upload("paste.csv", raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ds_id = storage.create_dataset(body.name or "粘贴数据", df, "粘贴数据.csv", raw)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


@router.post("/sample")
def create_sample():
    df = sample_mod.make_sample()
    raw = df.to_csv(index=False).encode("utf-8-sig")
    ds_id = storage.create_dataset("示例-销售数据（含缺失/重复）", df, "示例销售数据.csv", raw)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


@router.get("/datasets")
def datasets():
    return storage.list_datasets()


@router.get("/datasets/{ds_id}")
def dataset(ds_id: str):
    return _meta_or_404(ds_id)


class RenameBody(BaseModel):
    name: str


@router.post("/datasets/{ds_id}/rename")
def rename(ds_id: str, body: RenameBody):
    _meta_or_404(ds_id)
    return storage.rename_dataset(ds_id, body.name)


@router.delete("/datasets/{ds_id}")
def remove(ds_id: str):
    _meta_or_404(ds_id)
    storage.delete_dataset(ds_id)
    return {"ok": True}


@router.post("/datasets/{ds_id}/reset")
def reset(ds_id: str):
    _meta_or_404(ds_id)
    return storage.reset_dataset(ds_id)


@router.post("/datasets/{ds_id}/undo")
def undo(ds_id: str):
    _meta_or_404(ds_id)
    try:
        return storage.undo_dataset(ds_id)
    except DatasetNotFound:
        raise HTTPException(400, "没有可撤销的操作（仅支持撤销最近一次清洗/变换/回滚）")


class ImportSheetBody(BaseModel):
    sheet: str


@router.post("/datasets/{ds_id}/import-sheet")
def import_sheet(ds_id: str, body: ImportSheetBody):
    _meta_or_404(ds_id)
    try:
        ds_id2 = storage.import_sheet(ds_id, body.sheet)
    except DatasetNotFound:
        raise HTTPException(400, f"工作表 [{body.sheet}] 不存在或源文件不是 xlsx")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": ds_id2, "meta": storage.get_meta(ds_id2)}


# ---------- 预览与画像 ----------


@router.get("/datasets/{ds_id}/rows")
def rows(ds_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
    df = _load(ds_id)
    return rows_payload(df, page, page_size)


@router.get("/datasets/{ds_id}/profile")
def get_profile(ds_id: str):
    df = _load(ds_id)
    return {"rows": len(df), "columns": prof.profile_columns(df)}


# ---------- 清洗 ----------


class CleanBody(BaseModel):
    op: str
    params: dict = {}


@router.post("/datasets/{ds_id}/clean")
def clean(ds_id: str, body: CleanBody):
    df = _load(ds_id)
    try:
        out, message = cleaning.apply_op(df, body.op, body.params)
    except cleaning.CleanError as e:
        raise HTTPException(400, str(e))
    meta = storage.save_df(ds_id, out, "清洗-" + body.op, message)
    return {"message": message, "meta": meta}


# ---------- Python 变换 ----------


class TransformBody(BaseModel):
    code: str
    apply: bool = False


@router.post("/datasets/{ds_id}/transform")
def do_transform(ds_id: str, body: TransformBody):
    df = _load(ds_id)
    try:
        result, stdout = transform.run_code(df, body.code)
    except transform.TransformError as e:
        raise HTTPException(400, str(e))
    payload = {
        "stdout": stdout,
        "shape": {"rows": int(len(result)), "cols": int(result.shape[1])},
        "old_shape": {"rows": int(len(df)), "cols": int(df.shape[1])},
        "preview": rows_payload(result, 1, 20),
    }
    if body.apply:
        first_line = body.code.strip().splitlines()[0][:80]
        meta = storage.save_df(
            ds_id, result, "Python变换",
            f"{first_line}（{len(df)} 行 → {len(result)} 行）",
        )
        payload["meta"] = meta
    return payload


# ---------- 分析 ----------


class AnalyzeBody(BaseModel):
    kind: str
    params: dict = {}


@router.post("/datasets/{ds_id}/analyze")
def analyze(ds_id: str, body: AnalyzeBody):
    df = _load(ds_id)
    try:
        return analysis.run(df, body.kind, body.params)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


# ---------- 一键洞察 / 报告 ----------


@router.get("/datasets/{ds_id}/insights")
def get_insights(ds_id: str):
    df = _load(ds_id)
    return insights_mod.run_insights(df, storage.get_meta(ds_id))


@router.post("/datasets/{ds_id}/report")
def make_report(ds_id: str):
    _meta_or_404(ds_id)
    df = _load(ds_id)
    path = report_mod.save_report(storage.get_meta(ds_id), df)
    return FileResponse(path, filename=path.name, media_type="text/html")


# ---------- SQL 控制台（DuckDB） ----------


@router.get("/sql/tables")
def sql_tables():
    """返回全部数据集的 SQL 表别名（ds1/ds2...）。"""
    metas = storage.list_datasets()
    return [{"alias": f"ds{i}", "id": m["id"], "name": m["name"], "rows": m["rows"]}
            for i, m in enumerate(metas, start=1)]


class SqlBody(BaseModel):
    query: str
    save_as: str = ""
    current_id: str = ""  # 注册为 df 的数据集；留空取最新更新的数据集


@router.post("/sql")
def run_sql(body: SqlBody):
    metas = storage.list_datasets()
    if body.current_id and not any(m["id"] == body.current_id for m in metas):
        raise HTTPException(404, "当前数据集不存在或已删除")
    items = [{"id": m["id"], "name": m["name"], "df": storage.load_df(m["id"])} for m in metas]
    current = body.current_id or (metas[0]["id"] if metas else "")
    try:
        result = sqlquery.run_sql(body.query, items, current_id=current)
    except sqlquery.SqlError as e:
        raise HTTPException(400, str(e))

    payload = {k: v for k, v in result.items() if k != "df"}
    if body.save_as:
        ds_id = storage.create_dataset(body.save_as, result["df"], "SQL查询结果.csv",
                                       result["df"].to_csv(index=False).encode("utf-8-sig"))
        storage.save_df(ds_id, result["df"], "SQL建集",
                        f"{body.query.strip().splitlines()[0][:60]}...（{len(result['df'])} 行）")
        payload["new_dataset"] = {"id": ds_id, "meta": storage.get_meta(ds_id)}
    return payload


# ---------- 深度画像 ----------


@router.get("/datasets/{ds_id}/corr")
def corr_deep(ds_id: str, method: str = Query("pearson")):
    df = _load(ds_id)
    try:
        return deepprofile.corr_matrix(df, method)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


@router.get("/datasets/{ds_id}/missing-matrix")
def missing_matrix(ds_id: str):
    df = _load(ds_id)
    try:
        return deepprofile.missing_matrix(df)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


@router.get("/datasets/{ds_id}/duplicates")
def duplicates(ds_id: str):
    df = _load(ds_id)
    return deepprofile.duplicates_detail(df)


@router.get("/datasets/{ds_id}/interactions")
def interactions(ds_id: str, x: str = Query(...), y: str = Query(...)):
    df = _load(ds_id)
    try:
        return deepprofile.interactions(df, x, y)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


# ---------- 统计检验 ----------


class TestBody(BaseModel):
    test: str
    params: dict = {}


@router.post("/datasets/{ds_id}/test")
def run_test(ds_id: str, body: TestBody):
    df = _load(ds_id)
    try:
        return stats_tests.run_test(df, body.test, body.params)
    except stats_tests.TestError as e:
        raise HTTPException(400, str(e))


# ---------- 预测 ----------


class ForecastBody(BaseModel):
    params: dict = {}


@router.post("/datasets/{ds_id}/forecast")
def forecast(ds_id: str, body: ForecastBody):
    df = _load(ds_id)
    try:
        return forecast_mod.forecast(df, body.params)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


# ---------- 交叉热力 / 对比 / 采样 / 图表推荐 ----------


@router.post("/datasets/{ds_id}/cross-heat")
def cross_heat(ds_id: str, body: ForecastBody):

    df = _load(ds_id)
    try:
        return suggest_mod.cross_heat(df, body.params)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


@router.get("/datasets/{ds_id}/chart-suggest")
def chart_suggest(ds_id: str):
    df = _load(ds_id)
    return suggest_mod.suggest(df)


class CompareBody(BaseModel):
    other_id: str
    key: str = ""


@router.post("/datasets/{ds_id}/compare")
def compare(ds_id: str, body: CompareBody):
    _meta_or_404(body.other_id)
    try:
        return compare_mod.compare(
            _load(ds_id), _load(body.other_id),
            storage.get_meta(ds_id)["name"], storage.get_meta(body.other_id)["name"],
            body.key,
        )
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


class SampleBody(BaseModel):
    method: str = "random"
    n: int = 100
    by: str = ""
    name: str = ""


@router.post("/datasets/{ds_id}/sample-create")
def sample_create(ds_id: str, body: SampleBody):
    _meta_or_404(ds_id)
    try:
        out = compare_mod.sample_create(_load(ds_id), body.method, body.n, body.by)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))
    name = body.name or f"{storage.get_meta(ds_id)['name']}-采样"
    ds_id2 = storage.create_dataset(name, out, "采样数据.csv", out.to_csv(index=False).encode("utf-8-sig"))
    return {"id": ds_id2, "meta": storage.get_meta(ds_id2)}



# ---------- 导出 ----------


@router.get("/datasets/{ds_id}/export")
def export_dataset(ds_id: str, format: str = Query("csv"), filename: str = Query("")):
    _meta_or_404(ds_id)
    df = _load(ds_id)
    name = filename or f"{storage.get_meta(ds_id)['name']}_导出"
    try:
        path = exporter.export_df(df, name, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


class ExportTableBody(BaseModel):
    columns: list
    rows: list
    filename: str = "分析结果"
    format: str = "csv"


@router.post("/export-table")
def export_table(body: ExportTableBody):
    try:
        path = exporter.export_table(body.columns, body.rows, body.filename, body.format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


# ---------- AI（可选） ----------


@router.get("/ai/settings")
def get_ai_settings():
    return ai.public_config()


class AiSettingsBody(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@router.put("/ai/settings")
def put_ai_settings(body: AiSettingsBody):
    ai.save_config(body.model_dump())
    return ai.public_config()


class AiChatBody(BaseModel):
    dataset_id: str
    messages: list


@router.post("/ai/chat")
def ai_chat(body: AiChatBody):
    _meta_or_404(body.dataset_id)
    if not body.messages:
        raise HTTPException(400, "消息为空")
    df = _load(body.dataset_id)
    context = ai.build_context(storage.get_meta(body.dataset_id), prof.profile_columns(df))
    try:
        reply = ai.chat(body.messages, context)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"reply": reply}


class AiChartBody(BaseModel):
    dataset_id: str
    prompt: str


@router.post("/ai/chart")
def ai_chart(body: AiChartBody):
    """自然语言 → 图表配置 → 直接执行分析，返回 spec + 结果。"""
    _meta_or_404(body.dataset_id)
    if not body.prompt.strip():
        raise HTTPException(400, "请描述你想要的图表")
    df = _load(body.dataset_id)
    meta = storage.get_meta(body.dataset_id)
    context = ai.build_context(meta, prof.profile_columns(df))
    try:
        spec = ai.chart_spec([{"role": "user", "content": body.prompt}], context)
    except ValueError as e:
        raise HTTPException(400, str(e))
    kind, params = spec["kind"], spec.get("params") or {}
    # 分派执行：分析类走 analysis，特殊类型走各自端点逻辑
    try:
        if kind == "scatter":
            result = deepprofile.interactions(df, params.get("x", ""), params.get("y", ""))
        elif kind == "cross_heat":
            result = suggest_mod.cross_heat(df, params)
        elif kind == "forecast":
            result = forecast_mod.forecast(df, params)
        else:
            result = analysis.run(df, kind, params)
    except (analysis.AnalysisError,) as e:
        raise HTTPException(400, f"AI 配置执行失败（{spec.get('title', kind)}）：{e}")
    result["ai_spec"] = {"title": str(spec.get("title", "AI 图表"))[:40], "prompt": body.prompt[:120]}
    return result


# ---------- 金融分析 ----------


@router.get("/datasets/{ds_id}/finance/detect")
def finance_detect(ds_id: str):
    df = _load(ds_id)
    return finance.detect_ohlcv(df)


class FinanceMetricsBody(BaseModel):
    close: str = ""
    rf: float = 0.02
    freq: str = "D"


@router.post("/datasets/{ds_id}/finance/metrics")
def finance_metrics(ds_id: str, body: FinanceMetricsBody):
    df = _load(ds_id)
    try:
        return finance.metrics_report(df, body.model_dump())
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))


@router.post("/datasets/{ds_id}/finance/kline")
def finance_kline(ds_id: str, body: dict = {}):
    df = _load(ds_id)
    try:
        return finance.kline_payload(df, body or {})
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))


class TechBody(BaseModel):
    indicator: str
    close: str = ""
    n: int = 0


@router.post("/datasets/{ds_id}/finance/tech-indicator")
def finance_tech(ds_id: str, body: TechBody):
    _meta_or_404(ds_id)
    df = _load(ds_id)
    try:
        params = {"indicator": body.indicator}
        if body.close:
            params["close"] = body.close
        if body.n:
            params["n"] = body.n
        out, msg = finance.apply_tech_indicator(df, params)
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))
    meta = storage.save_df(ds_id, out, "技术指标", msg)
    return {"message": msg, "meta": meta}


class BenchmarkBody(BaseModel):
    other_id: str
    close: str = ""
    bclose: str = ""
    rf: float = 0.02


@router.post("/datasets/{ds_id}/finance/benchmark")
def finance_benchmark(ds_id: str, body: BenchmarkBody):
    _meta_or_404(body.other_id)
    try:
        return finance.benchmark_compare(_load(ds_id), _load(body.other_id), body.model_dump())
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))


class PortfolioBody(BaseModel):
    assets: list  # [{id, close, date}]
    weights: list = []
    rf: float = 0.02


@router.post("/finance/portfolio")
def finance_portfolio(body: PortfolioBody):
    if len(body.assets) < 2:
        raise HTTPException(400, "请至少选择 2 个资产")
    dfs = []
    try:
        for a in body.assets:
            meta = storage.get_meta(a["id"])
            dfs.append({
                "name": meta["name"][:12],
                "df": storage.load_df(a["id"]),
                "close": a.get("close", ""),
                "date": a.get("date", ""),
            })
        return finance.portfolio_analysis(dfs, {"weights": body.weights, "rf": body.rf})
    except (finance.FinanceError, DatasetNotFound) as e:
        raise HTTPException(400, str(e))


class FeedBody(BaseModel):
    source: str = "stock"  # stock / index
    symbol: str
    start: str
    end: str
    period: str = "D"
    adjust: str = "qfq"


@router.post("/datafeed/fetch")
def datafeed_fetch(body: FeedBody):
    try:
        if body.source == "index":
            df = datafeed.fetch_index(body.symbol, body.start, body.end, body.period)
            name = f"指数{body.symbol}"
        else:
            df = datafeed.fetch_stock(body.symbol, body.start, body.end, body.period, body.adjust)
            name = f"股票{body.symbol}"
    except datafeed.FeedError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 打包环境缺模块等未知错误 → 友好暴露而非 500
        raise HTTPException(400, f"行情获取异常：{type(e).__name__}: {str(e)[:150]}")
    ds_id = storage.create_dataset(name, df, f"{name}.csv", df.to_csv(index=False).encode("utf-8-sig"))
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


@router.post("/finance/sample-stock")
def finance_sample_stock():
    df = finance.make_stock_sample()
    ds_id = storage.create_dataset("示例股票-日线(250日)", df, "示例股票.csv",
                                   df.to_csv(index=False).encode("utf-8-sig"))
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


@router.get("/datafeed/indexes")
def datafeed_indexes():
    return datafeed.INDEX_SOURCES


@router.get("/datafeed/search")
def datafeed_search(q: str = Query("")):
    try:
        return datafeed.search_hot(q)
    except datafeed.FeedError as e:
        raise HTTPException(400, str(e))


# 金融检验走通用 test 端点的扩展
class FinanceTestBody(BaseModel):
    test: str  # adf / ljung_box
    params: dict = {}


@router.post("/datasets/{ds_id}/finance/test")
def finance_test(ds_id: str, body: FinanceTestBody):
    df = _load(ds_id)
    try:
        if body.test == "adf":
            return finance.adf_test(df, body.params)
        if body.test == "ljung_box":
            return finance.ljung_box_test(df, body.params)
        raise HTTPException(400, f"未知金融检验: {body.test}")
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))



