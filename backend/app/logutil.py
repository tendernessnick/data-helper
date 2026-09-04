"""日志基建：控制台 + 文件双通道（data/logs/app.log，按大小轮转）。

约定：
- 业务模块一律 logging.getLogger(__name__) 取 logger，不允许自行挂 handler
- 只有 setup_logging() 负责初始化（main.py 启动时调用一次），保证测试环境
  可通过不调用它来关闭文件句柄（conftest 清理沙箱目录前需 logging.shutdown()）
"""
import logging
from logging.handlers import RotatingFileHandler

from .paths import DATA_DIR

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_h = RotatingFileHandler(
        log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_h)
    root.addHandler(console)
    _configured = True
