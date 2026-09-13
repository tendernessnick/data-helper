# CloudBase 云托管部署指南（webview 分支）

本项目可完整部署到腾讯云 CloudBase **云托管（CloudRun，容器型）**，部署后浏览器直接访问，无需安装。本文说明可行性依据、部署步骤、与个人主页的链接协同，以及必须知道的边界。

## 为什么适合云托管

| 项目特性 | 云托管对应能力 |
| --- | --- |
| FastAPI 单体：`/api` 接口 + 前端静态页同源托管（`backend/app/main.py`） | 一个容器即可，前端用相对路径 `/api/...` 请求，**无跨域问题** |
| 流式建集 / SSE 推送 | 云托管容器模式支持长连接（这也是选云托管而非云函数的原因） |
| 自定义 Python 运行时（pandas / DuckDB / PyArrow） | 容器模式，仓库根目录 `Dockerfile` 自动构建 |
| 数据与配置落盘 `data/` | 容器内可写层（`DATA_HELPER_DATA=/app/data`），见下文「数据持久性」 |
| MCP 服务端（`/mcp/mcp`） | 部署后即为公网 MCP 地址，外接聊天客户端可远程调用 |

## 部署步骤（GitHub 来源，推荐）

> 前置：webview 分支已推送到 GitHub（`git push -u origin webview`）。

1. 打开 [CloudBase 控制台](https://tcb.cloud.tencent.com)，选择环境 → **云托管** → **创建服务**。
2. 代码上传方式选择 **代码仓库**，按提示授权并绑定 GitHub 账号，选择仓库 `tendernessnick/data-helper`、分支 `webview`。
3. 构建方式选 **容器**，平台自动识别仓库根目录的 `Dockerfile`（无需额外配置文件）。
4. 关键配置：
   - **监听端口**：本地开发端口填 8080（容器会优先读平台注入的 `PORT`，Dockerfile 已处理，此处仅为兜底）；
   - **规格**：1 核 2GB（云托管要求内存 ≥ 2×CPU；pandas 加载大表内存峰值高，1G 会偏紧）；
   - **实例副本数**：最小 1、最大 5。最小 1 可避免冷启动（本镜像含 pandas，缩容到 0 后首次拉起要十几秒甚至更久）；若想省成本接受冷启动，可设最小 0；
   - **公网访问**：开启（PUBLIC），否则浏览器无法访问。
5. （可选）健康检查路径填 `/api/health`，应用返回 `{"ok": true}`。
6. 点击部署，等待构建完成，获得形如 `https://<服务名>-<环境ID>.*.tcloudbase.com/` 的访问地址。

之后每次 `git push` 到 webview 分支，云托管可配置自动重新构建部署（服务设置里开启）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PORT` | 平台注入 | 监听端口，Dockerfile CMD 已适配，无需手工设置 |
| `DATA_HELPER_DATA` | `/app/data`（镜像内已设） | 数据集/导出/配置的落盘目录 |
| `DATA_HELPER_MAX_UPLOAD_MB` | `500` | 单文件上传上限（MB），可按规格调整 |

## 数据持久性（必读）

云托管实例使用**容器临时盘**：重新部署、实例重建、缩容后再扩容时，`/app/data` 下已上传的数据集、导出文件都会**丢失**。适合"上传 → 分析 → 下载结果"的会话式使用。

需要跨部署保留数据时，进阶方案是在云托管服务配置里**挂载 CFS 文件存储**到 `/app/data`（腾讯云托管原生支持挂载卷，无需改代码）。

## 与个人主页（my_homepage）的链接协同

应用支持**外部主页回跳**：访问链接带上 `?home=<主页地址>` 参数时，顶栏会出现「🏠 主页」按钮，左上角品牌区点击也会跳回主页：

```
https://<云托管域名>/?home=https://<你的个人主页地址>
```

在 my_homepage 的作品/项目页（如 `works.html`）放上述链接即可实现双向跳转。不带 `?home=` 参数时应用功能完全正常，只是不显示回跳按钮（本地 exe/源码运行不受影响）。

## MCP 外接（部署后的额外玩法）

部署后 MCP 地址变为公网地址：`https://<云托管域名>/mcp/mcp`（Streamable HTTP）。在 Cherry Studio / ChatWise 等客户端填入该地址，即可在聊天客户端里远程调用本应用的分析工具（接入细节见 [docs/MCP.md](MCP.md)）。若不想对公网暴露 MCP，可在服务设置中对该路径做访问鉴权，或从 Dockerfile 中去掉 mcp 依赖。

## 本地 Docker 验证（部署前自测）

```bash
docker build -t data-helper .
docker run --rm -p 8080:8080 -e PORT=8080 data-helper
# 打开 http://127.0.0.1:8080；curl http://127.0.0.1:8080/api/health 应返回 {"ok":true}
```

## 常见问题

- **首次访问慢**：最小实例数为 0 时触发冷启动（镜像拉起 + Python 进程 + pandas 导入），把最小副本设为 1 即可消除。
- **上传大文件失败 / 分析时 OOM**：调大实例规格（如 2 核 4GB），或调低 `DATA_HELPER_MAX_UPLOAD_MB`。
- **页面能开但接口 404**：确认访问的是云托管分配的域名根路径（前端由同一容器托管，不存在前后端分离部署问题）。
- **想改暴露内容**：`.dockerignore` 已排除 tests/docs/examples 等非运行时目录，镜像只含 `backend/`、`frontend/`、`requirements.txt`。
