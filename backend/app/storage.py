"""数据集本地存储。

每个数据集位于 data/datasets/{id}/，包含：
- meta.json       元信息（名称、行列数、列类型、操作历史）
- original.*      用户上传的原始文件（用于回滚）
- current.pkl     当前工作副本（pandas pickle，仅由本程序写入和读取）
"""
import io
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from .paths import DATA_DIR

DATASETS_DIR = DATA_DIR / "datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

MAX_HISTORY = 200
_lock = threading.RLock()


class DatasetNotFound(KeyError):
    pass


def _ds_dir(ds_id: str) -> Path:
    d = DATASETS_DIR / str(ds_id)
    if not d.is_dir():
        raise DatasetNotFound(ds_id)
    return d


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _write_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _columns_info(df: pd.DataFrame) -> list:
    return [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_csv_any(src) -> pd.DataFrame:
    """自动尝试常见编码和分隔符读取 CSV（src 为 bytes 或路径）。"""
    raw = src if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
    text = _decode_bytes(bytes(raw))
    try:
        return pd.read_csv(io.StringIO(text), sep=None, engine="python")
    except pd.errors.ParserError:
        # 分隔符嗅探失败时按标准逗号解析
        return pd.read_csv(io.StringIO(text))


def _parse_json(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return pd.read_json(io.StringIO(text))
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            return pd.json_normalize(data)
        return pd.DataFrame(data)
    if isinstance(data, dict):
        for key in ("data", "rows", "records", "items", "list"):
            if isinstance(data.get(key), list):
                inner = data[key]
                if inner and all(isinstance(x, dict) for x in inner):
                    return pd.json_normalize(inner)
                return pd.DataFrame(inner)
        return pd.DataFrame(data)
    raise ValueError("JSON 顶层必须是数组或对象")


def parse_upload(filename: str, raw: bytes) -> pd.DataFrame:
    ext = Path(filename or "").suffix.lower()
    if ext in (".csv", ".txt"):
        df = read_csv_any(raw)
    elif ext == ".xlsx":
        df = pd.read_excel(io.BytesIO(raw), sheet_name=0)
    elif ext == ".json":
        df = _parse_json(raw)
    else:
        raise ValueError(f"不支持的文件类型 {ext or '(无后缀)'}，请上传 CSV / XLSX / JSON")
    if df.empty:
        raise ValueError("文件解析后没有任何数据行")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(x) for x in tup if str(x) != "nan") for tup in df.columns]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def create_dataset(name, df: pd.DataFrame, original_filename: str, original_bytes: bytes) -> str:
    ds_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    with _lock:
        d = DATASETS_DIR / ds_id
        d.mkdir(parents=True)
        ext = Path(original_filename or "").suffix.lower() or ".bin"
        (d / f"original{ext}").write_bytes(original_bytes)
        df.to_pickle(d / "current.pkl")
        meta = {
            "id": ds_id,
            "name": (name or "").strip() or Path(original_filename or "").stem or "未命名数据集",
            "original_filename": original_filename or "",
            "created_at": _now(),
            "updated_at": _now(),
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "columns": _columns_info(df),
            "history": [
                {
                    "time": _now(),
                    "action": "上传",
                    "detail": f"{original_filename}（{len(df)} 行 × {df.shape[1]} 列）",
                }
            ],
        }
        _write_meta(d, meta)
    return ds_id


def list_datasets() -> list:
    out = []
    if DATASETS_DIR.is_dir():
        for d in DATASETS_DIR.iterdir():
            if d.is_dir() and (d / "meta.json").exists():
                try:
                    out.append(_read_meta(d))
                except (json.JSONDecodeError, OSError):
                    continue
    out.sort(key=lambda m: (m.get("updated_at", ""), m.get("id", "")), reverse=True)
    return out


def get_meta(ds_id: str) -> dict:
    with _lock:
        return _read_meta(_ds_dir(ds_id))


def load_df(ds_id: str) -> pd.DataFrame:
    p = _ds_dir(ds_id) / "current.pkl"
    if not p.exists():
        raise DatasetNotFound(ds_id)
    return pd.read_pickle(p)


def save_df(ds_id: str, df: pd.DataFrame, action: str, detail: str = "") -> dict:
    with _lock:
        d = _ds_dir(ds_id)
        df.to_pickle(d / "current.pkl")
        meta = _read_meta(d)
        meta["rows"] = int(len(df))
        meta["cols"] = int(df.shape[1])
        meta["columns"] = _columns_info(df)
        meta["updated_at"] = _now()
        meta["history"].append({"time": _now(), "action": action, "detail": detail})
        meta["history"] = meta["history"][-MAX_HISTORY:]
        _write_meta(d, meta)
        return meta


def rename_dataset(ds_id: str, name: str) -> dict:
    with _lock:
        d = _ds_dir(ds_id)
        meta = _read_meta(d)
        meta["name"] = name.strip() or meta["name"]
        _write_meta(d, meta)
        return meta


def delete_dataset(ds_id: str) -> None:
    with _lock:
        import shutil

        shutil.rmtree(_ds_dir(ds_id))


def reset_dataset(ds_id: str) -> dict:
    """回滚：用原始上传文件重建当前工作副本。"""
    with _lock:
        d = _ds_dir(ds_id)
        originals = [p for p in d.glob("original.*")]
        if not originals:
            raise DatasetNotFound(ds_id)
        p = originals[0]
        df = parse_upload(p.name, p.read_bytes())
        return save_df(ds_id, df, "回滚", "恢复到上传时的原始数据")


def find_original_file(ds_id: str) -> Path:
    d = _ds_dir(ds_id)
    originals = [p for p in d.glob("original.*")]
    if not originals:
        raise DatasetNotFound(ds_id)
    return originals[0]
