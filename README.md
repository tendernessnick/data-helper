# 📊 数据分析小助手（Data Helper）

一个本地运行的轻量数据分析工具：导入数据 → 预览画像 → 清洗 → 统计分析 → 可视化 → Python 变换 → 导出。面向商业/业务数据，**所有数据处理都在本机完成，数据不出本机**。

![技术栈](https://img.shields.io/badge/Python-3.12%2B-blue) ![后端](https://img.shields.io/badge/FastAPI-uvicorn-green) ![前端](https://img.shields.io/badge/Vue3%20%2B%20ECharts-无构建-orange)

---

## 🚀 快速开始（普通用户）

1. 拿到 `数据分析小助手.exe`（约 42 MB，单文件，无需安装 Python）
2. 双击运行，会自动打开浏览器进入界面（如未自动打开，看黑窗口里打印的地址手动访问）
3. 点击「生成示例数据」可立即体验全部功能；或导入自己的 CSV / Excel / JSON
4. **关闭黑窗口即退出程序**；数据保存在 exe 同目录的 `data/` 文件夹里

> 首次启动 exe 需要几秒钟解压运行库，属正常现象。

## ✨ 功能一览

| 模块 | 能力 |
|---|---|
| 📥 数据导入 | CSV / XLSX / JSON；自动识别中文编码（UTF-8 / GBK）与分隔符；示例数据一键生成 |
| 🔍 数据预览 | 分页表格、列类型标注、数字格式化 |
| 🧬 列画像 | 每列类型、缺失率、唯一值数、数值统计量（min/max/均值/中位数/标准差/四分位）、类别高频值 |
| 🧹 数据清洗 | 去重、缺失值处理（常数/均值/中位数/众数/前后值）、列重命名、类型转换（int/float/文本/日期）、条件筛选（12种）、删列；**一键回滚原始数据**；全程操作历史 |
| 📈 统计分析 | 分组聚合（10种聚合函数）、透视表、时间趋势（天/周/月/季/年）、相关性矩阵、直方图、箱线图、频次统计、describe 汇总 |
| 📊 可视化 | ECharts 柱状图 / 折线图 / 饼图 / 热力图 / 箱线图，图表可保存为 PNG |
| 🐍 Python 变换 | 直接写 pandas 代码处理数据（内置 pd / np），先预览后应用，30 秒超时保护 |
| 📤 导出 | 数据集与分析结果一键导出 CSV / Excel（UTF-8 BOM，Excel 直接打开不乱码） |
| 🤖 AI 问答（可选） | 配置 OpenAI 兼容接口（智谱 GLM / DeepSeek / OpenAI 等）后，可对当前数据集自然语言提问；模型给出的 pandas 代码经你确认后才会执行 |

## 🤖 AI 配置（可选）

进入「AI 问答」标签页填写：

- **API Base URL**：如智谱 `https://open.bigmodel.cn/api/paas/v4`
- **模型名称**：如 `glm-4.5-flash`
- **API Key**：你的密钥（仅保存在本机 `data/config.json`）

不配置时其余功能完全不受影响。

## 🛠️ 从源码运行（开发者）

```bash
# 1. 创建虚拟环境并安装依赖（首次）
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

# 2a. 启动（推荐，与 exe 相同入口）
.venv\Scripts\python run_app.py

# 2b. 或开发模式（自动选端口）
.venv\Scripts\python -m uvicorn backend.app.main:app --port 8765 --reload

# 3. 运行测试（44 项）
.venv\Scripts\python -m pytest tests/ -q
```

## 📦 构建 exe

```bash
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --name "数据分析小助手" --add-data "frontend;frontend" run_app.py
```

产物在 `dist/数据分析小助手.exe`。构建环境：Python 3.14 + PyInstaller 6.x（已在 Windows 10/11 验证）。

## 📁 目录结构

```
data_helper/
├── backend/app/          # FastAPI 后端
│   ├── main.py           # 应用入口（路由 + 静态托管）
│   ├── api.py            # 全部 HTTP 路由
│   ├── storage.py        # 数据集存储（原始文件 + pickle 工作副本 + meta.json）
│   ├── profile.py        # 列画像
│   ├── cleaning.py       # 清洗操作
│   ├── analysis.py       # 统计分析
│   ├── transform.py      # Python 代码变换
│   ├── ai.py             # 可选 LLM 问答（OpenAI 兼容）
│   ├── exporter.py       # CSV/XLSX 导出
│   ├── sample.py         # 示例数据生成
│   └── paths.py          # 路径（开发/exe 双模式）
├── frontend/             # 无构建步骤的前端（Vue3 + ECharts 本地 vendor，离线可用）
├── tests/                # pytest 测试（44 项）
├── run_app.py            # 启动入口
├── requirements.txt      # 运行依赖
└── requirements-dev.txt  # 开发依赖（含 pytest / pyinstaller）
```

## ⚠️ 说明与边界

- **内存级处理**：基于 pandas，适合百万行以内的表格数据；更大的数据建议先抽样或分块。
- **Python 变换以当前用户权限执行**：这是本地单人工具的设计取舍，请不要运行来路不明的代码。
- **数据安全**：默认全本地。AI 问答开启后，会把数据集的**结构摘要**（列名/类型/统计量，不含明细行）发送给你配置的模型服务。
- 数据目录：开发模式在项目 `data/`，exe 模式在 exe 同目录 `data/`。

## 🧪 测试

44 项 pytest 覆盖：上传解析（含 GBK/JSON/XLSX/分页）、数据集管理、7 种清洗操作、Python 变换（含超时/异常路径）、8 种分析、导出、AI 模块（配置/上下文/错误路径）。前端已通过浏览器 GUI 全流程实测。
