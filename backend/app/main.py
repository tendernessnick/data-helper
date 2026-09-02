"""FastAPI 应用入口：API 路由 + 前端静态资源托管。"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .paths import FRONTEND_DIR

app = FastAPI(title="数据分析小助手", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router, prefix="/api")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
