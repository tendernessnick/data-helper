"""全部 HTTP API 路由（挂在 /api 前缀下）。"""
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from . import profile as prof
from . import sample as sample_mod
from . import storage
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
async def upload(file: UploadFile = File(...), name: str = Form(None)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "上传的文件为空")
    try:
        df = storage.parse_upload(file.filename or "", raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 解析器抛出的其他异常（结构错误等）
        raise HTTPException(400, f"文件解析失败：{e}")
    ds_id = storage.create_dataset(name, df, file.filename or "data.csv", raw)
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


# ---------- 预览与画像 ----------


@router.get("/datasets/{ds_id}/rows")
def rows(ds_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500)):
    df = _load(ds_id)
    return rows_payload(df, page, page_size)


@router.get("/datasets/{ds_id}/profile")
def get_profile(ds_id: str):
    df = _load(ds_id)
    return {"rows": len(df), "columns": prof.profile_columns(df)}
