"""集中管理路径：开发模式用仓库根目录，打包(exe)模式用 exe 所在目录存数据。"""
import os
import sys
from pathlib import Path

_frozen = getattr(sys, "frozen", False)

if os.environ.get("DATA_HELPER_DATA"):
    DATA_DIR = Path(os.environ["DATA_HELPER_DATA"])
elif _frozen:
    DATA_DIR = Path(sys.executable).parent / "data"
else:
    DATA_DIR = Path(__file__).resolve().parents[2] / "data"

if _frozen:
    # onefile 模式下静态资源解压在 _MEIPASS
    FRONTEND_DIR = Path(getattr(sys, "_MEIPASS")) / "frontend"
else:
    FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

EXPORT_DIR = DATA_DIR / "exports"
CONFIG_PATH = DATA_DIR / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
