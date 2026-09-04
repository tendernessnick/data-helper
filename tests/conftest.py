"""测试配置：在导入 backend 之前把数据目录指向测试沙箱。"""
import logging
import os
import shutil
from pathlib import Path

_TMP = Path(__file__).resolve().parent / "_tmpdata"
os.environ["DATA_HELPER_DATA"] = str(_TMP)


def pytest_sessionfinish(session, exitstatus):
    # 关闭日志文件句柄，否则 Windows 上 RotatingFileHandler 占用文件导致沙箱删不干净
    logging.shutdown()
    shutil.rmtree(_TMP, ignore_errors=True)
