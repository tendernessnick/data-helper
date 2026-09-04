"""FastAPI 应用入口：API 路由 + 前端静态资源托管 + MCP 服务端（可选）。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .logutil import setup_logging
from .paths import FRONTEND_DIR

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app):
    # MCP streamable-http 会话管理器需要随应用启停（未启用 MCP 时直接放行）
    ctx = app.state.mcp_lifespan
    if ctx is not None:
        async with ctx(app):
            yield
    else:
        yield


app = FastAPI(
    title="数据分析小助手", docs_url=None, redoc_url=None, openapi_url=None,
    lifespan=_lifespan,
)
app.include_router(router, prefix="/api")
app.state.mcp_lifespan = None
logger.info("数据分析小助手启动")

# MCP 服务端（可选依赖）：外部聊天客户端（Cherry Studio / ChatWise 等）经它调用本机分析工具
try:
    from . import mcpserver

    if mcpserver.mcp_available():
        _server, _streamable, _sse = mcpserver.build_server()
        # Starlette 应用的 lifespan 藏在 router.lifespan_context（mcp 2.x 内部为 session_manager.run()）
        _ctx = getattr(_streamable.router, "lifespan_context", None)
        app.state.mcp_lifespan = _ctx if callable(_ctx) else None
        app.mount("/mcp", _streamable)  # 客户端填 http://127.0.0.1:{port}/mcp/mcp
        app.mount("/sse", _sse)  # 旧版 SSE 客户端：http://127.0.0.1:{port}/sse/sse
        logger.info("MCP 已挂载：Streamable HTTP /mcp/mcp；SSE /sse/sse")
    else:
        logger.info("未安装 mcp 库，MCP 服务端未启用（pip install mcp 后重启开启）")
except Exception as e:  # noqa: BLE001 — MCP 启用失败不影响主应用
    logger.warning("MCP 服务端启用失败：%s", e)


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
