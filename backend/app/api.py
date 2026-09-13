"""全部 HTTP API 路由（挂在 /api 前缀下）。"""
import json
import logging
import os
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import (
    agent,
    ai,
    analysis,
    cleaning,
    deepprofile,
    exporter,
    sqlquery,
    storage,
    transform,
)
from . import compare as compare_mod
from . import insights as insights_mod
from . import profile as prof
from . import sample as sample_mod
from . import suggest as suggest_mod
from .paths import DATA_DIR
from .serialize import rows_payload
from .storage import DatasetNotFound

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health():
    """存活探针（容器平台健康检查用）：进程在且能响应即返回 ok，不触碰数据层。"""
    return {"ok": True}

# 上传大小上限（MB），可用环境变量覆盖；原始文件先落盘临时文件，大 CSV 分块流式读入
MAX_UPLOAD_MB = int(os.environ.get("DATA_HELPER_MAX_UPLOAD_MB", "500"))


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
async def upload(file: UploadFile = File(...), name: str = Form(None), sheet: str = Form(None), project: str = Form("")):
    # 先落盘临时文件（8MB 分块），大 CSV 再分块流式读回，内存不驻留整文件
    tmp = DATA_DIR / f"upload-{uuid.uuid4().hex}.part"
    size = 0
    try:
        with tmp.open("wb") as spool:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"文件超过大小上限（{MAX_UPLOAD_MB} MB），可调整环境变量 DATA_HELPER_MAX_UPLOAD_MB")
                spool.write(chunk)
        if size == 0:
            raise HTTPException(400, "上传的文件为空")
        filename = file.filename or "data.csv"

        def _build():
            # 同步重活（xlsx 解析可达数十秒）放线程池，避免阻塞事件循环殃及 SSE 等其他请求
            ext = Path(filename).suffix.lower()
            if ext in (".csv", ".txt") and size > storage.STREAM_THRESHOLD_BYTES:
                return storage.create_dataset_stream(name, tmp, filename, project=project)
            raw = tmp.read_bytes()  # 读一次复用：解析与 original 存档共用
            try:
                df = storage.parse_upload(filename, raw, sheet_name=sheet)
            except ValueError as e:
                raise HTTPException(400, str(e))
            except Exception as e:  # 解析器抛出的其他异常（结构错误等）
                logger.warning("文件解析失败 %s：%s", filename, e)
                raise HTTPException(400, f"文件解析失败：{e}")
            return storage.create_dataset(name, df, filename, raw, project=project)

        ds_id = await run_in_threadpool(_build)
    finally:
        tmp.unlink(missing_ok=True)
    logger.info("上传完成 file=%s size=%.1fMB", file.filename, size / 1048576)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


class PasteBody(BaseModel):
    text: str
    name: str = ""
    project: str = ""


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
    ds_id = storage.create_dataset(body.name or "粘贴数据", df, "粘贴数据.csv", raw, project=body.project)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


@router.post("/sample")
def create_sample(project: str = Query("")):
    df = sample_mod.make_sample()
    raw = df.to_csv(index=False).encode("utf-8-sig")
    ds_id = storage.create_dataset("示例-销售数据（含缺失/重复）", df, "示例销售数据.csv", raw, project=project)
    return {"id": ds_id, "meta": storage.get_meta(ds_id)}


# ---------- 项目（数据集分组） ----------


class ProjectBody(BaseModel):
    name: str


@router.get("/projects")
def projects():
    return storage.list_projects()


@router.post("/projects")
def create_project(body: ProjectBody):
    try:
        return storage.create_project(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/projects/{prj_id}")
def rename_project(prj_id: str, body: ProjectBody):
    try:
        return storage.rename_project(prj_id, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except DatasetNotFound:
        raise HTTPException(404, "项目不存在")


@router.delete("/projects/{prj_id}")
def delete_project(prj_id: str):
    try:
        storage.delete_project(prj_id)
    except DatasetNotFound:
        raise HTTPException(404, "项目不存在")
    return {"ok": True}


class MoveBody(BaseModel):
    project: str = ""


@router.post("/datasets/{ds_id}/move")
def move_dataset(ds_id: str, body: MoveBody):
    _meta_or_404(ds_id)
    try:
        return storage.move_dataset(ds_id, body.project)
    except DatasetNotFound:
        raise HTTPException(404, "目标项目不存在")


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
        raise HTTPException(400, "没有可撤销的操作")


@router.get("/datasets/{ds_id}/versions")
def versions(ds_id: str):
    _meta_or_404(ds_id)
    return storage.available_versions(ds_id)


class RestoreBody(BaseModel):
    version: int


@router.post("/datasets/{ds_id}/restore")
def restore(ds_id: str, body: RestoreBody):
    _meta_or_404(ds_id)
    try:
        return storage.restore_version(ds_id, body.version)
    except DatasetNotFound:
        raise HTTPException(400, f"版本 v{body.version} 的快照不存在（可能已被清理）")


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
def rows(ds_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
         sort: str = Query(""), order: str = Query("asc"), filters: str = Query("")):
    """分页预览，支持列排序（sort/order）与按值筛选（filters = JSON {列: [值…]}）。

    "__NULL__" 哨兵值表示缺失；先过滤后排序再分页，total 为过滤后行数，另附 unfiltered_total。
    """
    df = _load(ds_id)
    unfiltered_total = len(df)
    if filters:
        try:
            flt = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(400, "filters 不是合法 JSON")
        if not isinstance(flt, dict):
            raise HTTPException(400, "filters 需为 {列: [值…]} 结构")
        for col, vals in flt.items():
            if col not in df.columns:
                raise HTTPException(400, f"筛选列不存在: {col}")
            if not isinstance(vals, list) or not vals:
                continue
            has_null = "__NULL__" in vals
            vs = [v for v in vals if v != "__NULL__"]
            mask = df[col].isin(vs)
            if has_null:
                mask = mask | df[col].isna()
            df = df[mask]
    if sort:
        if sort not in df.columns:
            raise HTTPException(400, f"排序列不存在: {sort}")
        df = df.sort_values(sort, ascending=order != "desc", na_position="last")
    payload = rows_payload(df, page, page_size)
    payload["unfiltered_total"] = unfiltered_total
    return payload


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


# ---------- 一键体检 ----------


@router.get("/datasets/{ds_id}/insights")
def get_insights(ds_id: str):
    df = _load(ds_id)
    return insights_mod.run_insights(df, storage.get_meta(ds_id))


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
    items = [{"id": m["id"], "name": m["name"], "path": str(storage.current_path(m["id"]))} for m in metas]
    current = body.current_id or (metas[0]["id"] if metas else "")
    try:
        result = sqlquery.run_sql(body.query, items, current_id=current, save_as=body.save_as)
    except sqlquery.SqlError as e:
        raise HTTPException(400, str(e))

    payload = {k: v for k, v in result.items() if k != "df"}
    if body.save_as:
        first_line = body.query.strip().splitlines()[0][:60]
        # 直接带初始 history 建集：此前 create_dataset+save_df 会把同一 parquet 写两遍
        # 并多出一份完全相同的撤销快照
        src_meta = next((m for m in metas if m["id"] == current), None)  # 派生表归入源数据集所在项目
        ds_id = storage.create_dataset(
            body.save_as, result["df"], "SQL查询结果.csv",
            result["df"].to_csv(index=False).encode("utf-8-sig"),
            action="SQL建集", detail=f"{first_line}…（{len(result['df'])} 行）",
            project=src_meta.get("project", "") if src_meta else "",
            parent=current,
        )
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
    try:
        return deepprofile.duplicates_detail(df)
    except analysis.AnalysisError as e:  # 含不可哈希单元格（list 列）等
        raise HTTPException(400, str(e))


@router.get("/datasets/{ds_id}/interactions")
def interactions(ds_id: str, x: str = Query(...), y: str = Query(...)):
    df = _load(ds_id)
    try:
        return deepprofile.interactions(df, x, y)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


# ---------- 交叉热力 / 采样 / 图表推荐 ----------


class ParamsBody(BaseModel):
    params: dict = {}


@router.post("/datasets/{ds_id}/cross-heat")
def cross_heat(ds_id: str, body: ParamsBody):
    df = _load(ds_id)
    try:
        return suggest_mod.cross_heat(df, body.params)
    except analysis.AnalysisError as e:
        raise HTTPException(400, str(e))


@router.get("/datasets/{ds_id}/chart-suggest")
def chart_suggest(ds_id: str):
    df = _load(ds_id)
    return suggest_mod.suggest(df)


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
    src_meta = storage.get_meta(ds_id)
    name = body.name or f"{src_meta['name']}-采样"
    ds_id2 = storage.create_dataset(
        name, out, "采样数据.csv", out.to_csv(index=False).encode("utf-8-sig"),
        action="采样", detail=f"从「{src_meta['name']}」{dict(random='随机', stratified='分层', top='前N行').get(body.method, body.method)}采样 {len(out)} 行",
        project=src_meta.get("project", ""), parent=ds_id,  # 派生表留在源数据集的项目里
    )
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
    except (ValueError, KeyError) as e:  # KeyError：前端表格单元格缺键（如区间 dict 缺 lower）
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


class AiStreamBody(BaseModel):
    dataset_id: str
    message: str
    session_id: str = ""


@router.post("/ai/chat/stream")
def ai_chat_stream(body: AiStreamBody):
    """AI Agent 流式对话（SSE）：delta 正文增量 / tool_start 工具进度 / tool_result 结果卡。"""

    _meta_or_404(body.dataset_id)
    if not body.message.strip():
        raise HTTPException(400, "消息为空")
    df = _load(body.dataset_id)
    context = ai.build_context(storage.get_meta(body.dataset_id), prof.profile_columns(df))
    sid = (body.session_id or "").strip() or uuid.uuid4().hex

    def gen():
        yield f"data: {json.dumps({'type': 'session', 'session_id': sid}, ensure_ascii=False)}\n\n"
        try:
            for evt in agent.stream_agent(context, body.message.strip(), df, sid=sid):
                yield f"data: {json.dumps(evt, ensure_ascii=False, default=str)}\n\n"
        except agent.LlmError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:  # 兜底：流已开始，只能以事件形式报错
            logger.exception("AI 流式对话异常")
            yield f"data: {json.dumps({'type': 'error', 'message': f'服务异常：{e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        else:
            result = analysis.run(df, kind, params)
    except analysis.AnalysisError as e:
        raise HTTPException(400, f"AI 配置执行失败（{spec.get('title', kind)}）：{e}")
    result["ai_spec"] = {"title": str(spec.get("title", "AI 图表"))[:40], "prompt": body.prompt[:120]}
    return result



