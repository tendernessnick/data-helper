# 数据分析小助手 — CloudBase 云托管（容器型）镜像
# 平台会把服务端口注入 PORT 环境变量，应用必须监听它；数据目录经 DATA_HELPER_DATA 指到容器可写层
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_HELPER_DATA=/app/data

WORKDIR /app

# 先装依赖再拷代码：代码改动不触发依赖重装，充分利用构建层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 数据集/导出/配置的落盘目录（容器临时盘，重新部署会清空；见 docs/DEPLOY_CLOUDBASE.md）
RUN mkdir -p /app/data

EXPOSE 8080

# 云托管注入 PORT；本地 docker run 未注入时回退 8080
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
