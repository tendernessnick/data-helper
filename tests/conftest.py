"""测试配置：在导入 backend 之前把数据目录指向测试沙箱。"""
import os
import shutil
from pathlib import Path

_TMP = Path(__file__).resolve().parent / "_tmpdata"
os.environ["DATA_HELPER_DATA"] = str(_TMP)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
