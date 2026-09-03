# 📊 数据分析小助手（Data Helper）

一个本地运行的轻量数据分析工作台：导入数据 → 一键洞察 → 清洗 → 统计/时序/业务模板分析 → 可视化 → Python 变换 → 导出与 HTML 报告。面向商业/业务数据，**所有数据处理都在本机完成，数据不出本机**。

![技术栈](https://img.shields.io/badge/Python-3.12%2B-blue) ![后端](https://img.shields.io/badge/FastAPI-uvicorn-green) ![前端](https://img.shields.io/badge/Vue3%20%2B%20ECharts-无构建-orange)

---

## 🚀 快速开始（普通用户）

1. 拿到 `数据分析小助手.exe`（约 42 MB，单文件，无需安装 Python）
2. 双击运行，会自动打开浏览器进入界面（如未自动打开，看黑窗口里打印的地址手动访问）
3. 点击「生成示例数据」可立即体验全部功能；或导入自己的数据
4. **关闭黑窗口即退出程序**；数据保存在 exe 同目录的 `data/` 文件夹里

> 首次启动 exe 需要几秒钟解压运行库，属正常现象。

## 🖥️ 工作台布局

```
+-----------------------------------------------------------+
| 顶栏：品牌 | 导入文件 / 粘贴数据 / 示例数据                    |
+------+----------------------------------------+------------+
| 数据集 | 画布：                                  | 工具坞(330px) |
| 列表   |  · 数据集操作条（撤销/回滚/洞察/报告/导出）  | ▼ 数据清洗    |
|       |  · 数据预览（可折叠）                      | ▼ 统计分析    |
|       |  · 结果画布：每次分析生成一张卡片，           | ▼ 时间序列    |
|       |    多卡并存、可单独关闭、图表可切换与导出      | ▼ 业务模板    |
|       |                                        | ▼ Python变换 |
|       |                                        | ▼ AI 问答    |
|       |                                        | ▼ 操作历史    |
+------+----------------------------------------+------------+
```

## ✨ 功能一览

| 模块 | 能力 |
|---|---|
| 📥 数据导入 | CSV / XLSX / JSON / **直接粘贴**（Excel 复制即用）；自动识别中文编码与分隔符；**Excel 多工作表**一键导入；示例数据生成 |
| 🔍 一键洞察 | **纯本地规则引擎（无需AI）**：数据质量体检（重复/缺失/常量列/疑似数值列）、数值列分布形态与离群值、类别集中度、时间范围与月度趋势方向、最大环比突变、强相关列对，输出中文要点清单 |
| 🧹 数据清洗 | 去重、缺失值 6 种处理、重命名、类型转换、12 种条件筛选、删列、**异常值剔除（IQR/Z-score）**；**撤销上一步** + 一键回滚原始数据 + 全程操作历史 |
| 📈 统计分析 | 分组聚合（10 种函数）、透视表、相关性热力图、直方图、箱线图、频次统计、describe 汇总 |
| 📉 时间序列 | 基础趋势、**同比/环比增长率/累计值**（按天/周/月/季/年自动对齐同口径周期）、**移动平均**（滚动平滑） |
| 🎯 业务模板 | **RFM 客户价值分层**（R/F/M 五分位打分 → 8 层客户群 + 明细）、**ABC/帕累托分析**（80/20 关键少数，双轴累计曲线）、**异常值检测** |
| 🐍 Python 变换 | 直接写 pandas 代码处理数据（内置 pd / np），先预览后应用，30 秒超时保护 |
| 📤 导出 | 数据集与任意结果卡片导出 CSV / Excel（UTF-8 BOM，Excel 打开不乱码） |
| 📄 HTML 报告 | 一键生成**自包含 HTML 分析报告**（内嵌图表与洞察全文，离线可看、可直接发同事） |
| 🤖 AI 问答（可选） | 配置 OpenAI 兼容接口（智谱 GLM / DeepSeek / OpenAI 等）后自然语言提问；支持「让 AI 解读洞察结果」；模型给出的 pandas 代码经你确认才会执行 |

## 🤖 AI 配置（可选）

在右侧工具坞「AI 问答」中填写：

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

# 2b. 或开发模式
.venv\Scripts\python -m uvicorn backend.app.main:app --port 8765 --reload

# 3. 运行测试（64 项）
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
│   ├── storage.py        # 数据集存储（原始文件 + 工作副本 + 撤销快照 + meta）
│   ├── profile.py        # 列画像
│   ├── cleaning.py       # 清洗操作（含异常值剔除）
│   ├── analysis.py       # 统计/时序/业务模板分析
│   ├── insights.py       # 一键本地洞察（规则引擎）
│   ├── report.py         # 自包含 HTML 报告生成
│   ├── transform.py      # Python 代码变换
│   ├── ai.py             # 可选 LLM 问答（OpenAI 兼容）
│   ├── exporter.py       # CSV/XLSX 导出
│   ├── sample.py         # 示例数据生成
│   └── paths.py          # 路径（开发/exe 双模式）
├── frontend/             # 无构建前端（Vue3 + ECharts 本地 vendor，离线可用）
├── tests/                # pytest 测试（64 项）
├── run_app.py            # 启动入口
├── requirements.txt      # 运行依赖
└── requirements-dev.txt  # 开发依赖（含 pytest / pyinstaller）
```

## ⚠️ 说明与边界

- **内存级处理**：基于 pandas，适合百万行以内的表格数据；更大的数据建议先抽样或分块。
- **Python 变换以当前用户权限执行**：这是本地单人工具的设计取舍，请不要运行来路不明的代码。
- **数据安全**：默认全本地。AI 问答开启后，会把数据集的**结构摘要**（列名/类型/统计量，不含明细行）发送给你配置的模型服务。
- 数据目录：开发模式在项目 `data/`，exe 模式在 exe 同目录 `data/`。
- 撤销为一级撤销（恢复最近一次操作）；更早的状态可用「回滚原始数据」。

## 🧪 测试

64 项 pytest 覆盖：上传解析（含 GBK/JSON/XLSX/单列/分页/粘贴/多 sheet）、数据集管理（含撤销/回滚）、9 种清洗操作、Python 变换（含超时/异常路径）、13 种分析（含同比环比/移动平均/RFM/帕累托/异常值）、导出、AI 模块、洞察规则与 HTML 报告结构。前端工作台已通过浏览器 GUI 全流程实测。
