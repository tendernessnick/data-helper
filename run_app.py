"""exe / 开发环境统一启动入口：起本地服务并自动打开浏览器。"""
import socket
import threading
import webbrowser

import uvicorn

from backend.app.main import app


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 46)
    print("  数据分析小助手 已启动")
    print(f"  访问地址: {url}")
    print("  浏览器将自动打开；关闭本窗口即可退出")
    print("=" * 46)
    threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
