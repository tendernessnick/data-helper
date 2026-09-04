"""用户自定义 Python 代码变换。

约定：代码中可直接使用变量 df（pandas DataFrame，已复制），
执行完毕后命名空间里的 df 即为新数据。pd/np 已预先注入。
注意：这是本地单人工具，代码以当前用户权限执行。
"""
import concurrent.futures
import io
import sys
import threading

import numpy as np
import pandas as pd

TIMEOUT_SECONDS = 30


class TransformError(ValueError):
    pass


class _ThreadRoutedStdout:
    """按线程分流的 stdout 包装器。

    redirect_stdout 是进程级的：用户代码死循环超时后工作线程永远停在
    with 块内，整个进程的 stdout 会被永久劫持。这里只有"注册过缓冲的
    线程"（正在执行用户代码的工作线程）的输出进缓冲，其他线程直通
    真实 stdout；父线程在超时/完成路径都能立即恢复 sys.stdout。
    """

    def __init__(self, fallback):
        self._fallback = fallback
        self._buffers = {}

    def register(self, buf) -> None:
        self._buffers[threading.get_ident()] = buf

    def unregister(self) -> None:
        self._buffers.pop(threading.get_ident(), None)

    def write(self, s):
        buf = self._buffers.get(threading.get_ident())
        if buf is not None:
            return buf.write(s)
        return self._fallback.write(s)

    def flush(self):
        buf = self._buffers.get(threading.get_ident())
        (buf if buf is not None else self._fallback).flush()

    @property
    def encoding(self):
        return getattr(self._fallback, "encoding", "utf-8")


def run_code(df: pd.DataFrame, code: str, timeout: int = TIMEOUT_SECONDS):
    """返回 (新df, stdout输出)。超时或代码异常抛 TransformError。"""
    if not code or not code.strip():
        raise TransformError("代码不能为空")
    ns = {"df": df.copy(), "pd": pd, "np": np, "__builtins__": __builtins__}
    buf = io.StringIO()
    router = _ThreadRoutedStdout(sys.stdout)
    sys.stdout = router
    try:
        # worker 只注册缓冲，不碰 sys.stdout（属性替换必须始终发生在父线程，
        # 这样超时后即使 worker 卡死，父线程也能原子地恢复全局 stdout）
        def _run():
            router.register(buf)
            try:
                exec(code, ns)
            finally:
                router.unregister()

        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(_run)
        try:
            fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TransformError(f"代码执行超过 {timeout} 秒，已放弃本次执行")
        except BaseException as e:  # 用户代码抛出的任意异常
            raise TransformError(f"{type(e).__name__}: {e}")
        finally:
            # 不等待仍卡住的线程（本地工具的务实取舍；路由器已保证其输出不影响进程）
            ex.shutdown(wait=False, cancel_futures=True)
    finally:
        sys.stdout = router._fallback

    result = ns.get("df")
    if not isinstance(result, pd.DataFrame):
        raise TransformError("执行后 df 不是 DataFrame——请始终对变量 df 进行操作")
    if result.empty:
        raise TransformError("执行后数据为 0 行，已放弃")
    return result, buf.getvalue().strip()
