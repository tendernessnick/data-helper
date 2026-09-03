"""全部 HTTP API 路由（挂在 /api 前缀下）。"""
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import analysis
from . import ai
from . import cleaning
from . import exporter
from . import insights as insights_mod
from . import profile as prof
from . import report as report_mod
from . import sample as sample_mod
from . import storage
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


