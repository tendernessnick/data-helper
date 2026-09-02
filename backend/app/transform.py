"""用户自定义 Python 代码变换。

约定：代码中可直接使用变量 df（pandas DataFrame，已复制），
执行完毕后命名空间里的 df 即为新数据。pd/np 已预先注入。
注意：这是本地单人工具，代码以当前用户权限执行。
"""
import concurrent.futures
import contextlib
import io

import numpy as np
import pandas as pd

TIMEOUT_SECONDS = 30


class TransformError(ValueError):
    pass


def run_code(df: pd.DataFrame, code: str, timeout: int = TIMEOUT_SECONDS):
    """返回 (新df, stdout输出)。超时或代码异常抛 TransformError。"""
    if not code or not code.strip():
        raise TransformError("代码不能为空")
    ns = {"df": df.copy(), "pd": pd, "np": np, "__builtins__": __builtins__}
    buf = io.StringIO()

    def _run():
        with contextlib.redirect_stdout(buf):
            exec(code, ns)

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_run)
    try:
        fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TransformError(f"代码执行超过 {timeout} 秒，已放弃本次执行")
    except TransformError:
        raise
    except BaseException as e:  # 用户代码抛出的任意异常
        raise TransformError(f"{type(e).__name__}: {e}")
    finally:
        # 不等待仍卡住的线程（本地工具的务实取舍）
        ex.shutdown(wait=False, cancel_futures=True)

    result = ns.get("df")
    if not isinstance(result, pd.DataFrame):
        raise TransformError("执行后 df 不是 DataFrame——请始终对变量 df 进行操作")
    if result.empty:
        raise TransformError("执行后数据为 0 行，已放弃")
    return result, buf.getvalue().strip()
