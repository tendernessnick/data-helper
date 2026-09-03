# 📊 数据分析小助手（Data Helper）

一个本地运行的轻量数据分析工作台：导入数据 → 一键洞察 → 清洗/列变换 → SQL / 统计 / 时序 / 业务模板分析 → 可视化 → Python 变换 → 导出与 HTML 报告。面向商业/业务数据，**所有数据处理都在本机完成，数据不出本机**。

![技术栈](https://img.shields.io/badge/Python-3.12%2B-blue) ![后端](https://img.shields.io/badge/FastAPI%20%2B%20DuckDB%20%2B%20SciPy-uvicorn-green) ![前端](https://img.shields.io/badge/Vue3%20%2B%20ECharts-无构建-orange) ![设计](https://img.shields.io/badge/设计语言-Apple%20HIG-9cf) ![主题](https://img.shields.io/badge/主题-明%20%2F%20暗-blueviolet)

---

## 🚀 快速开始（普通用户）

1. 拿到 `数据分析小助手.exe`（约 84 MB，单文件，无需安装 Python）
2. 双击运行，会自动打开浏览器进入界面（如未自动打开，看黑窗口里打印的地址手动访问）
3. 点击「生成示例数据」可立即体验全部功能；或导入自己的数据
4. **关闭黑窗口即退出程序**；数据保存在 exe 同目录的 `data/` 文件夹里

> 首次启动 exe 需要几秒钟解压运行库，属正常现象。

## 🖥️ 工作台布局（参考 Tableau / Hex 的三栏范式）

```
+-----------------------------------------------------------+
| 顶栏：品牌 | 导入文件 / 粘贴数据 / 示例数据 / 主题切换        |
+------+----------------------------------------+------------+
| 数据集 | 画布：                                 | 工具坞(336px)|
| 列表   |  · 数据集操作条（撤销/洞察/推荐/报告/导出） | ▼ 清洗与列变换|
|       |  · 🎯 图表推荐 chips（一键出图）           | ▼ 统计分析   |
|       |  · 数据预览（可折叠，点列名有快捷菜单）      | ▼ 时间序列与预测|
|       |  · 结果卡片画布：多卡并存、图表类型可切换     | ▼ 业务模板   |
|       |    单卡关闭/导出                          | ▼ 统计检验   |
|       |                                        | ▼ SQL 控制台 |
|       |                                        | ▼ 对比与采样 |
|       |                                        | ▼ Python变换 |
|       |                                        | ▼ AI 问答    |
|       |                                        | ▼ 操作历史   |
+------+----------------------------------------+------------+
| 状态栏：行×列 · 缺失% · 数值/类别列数 · 卡片数 · v3.0         |
+-----------------------------------------------------------+
```

明/暗双主题（右上角 🌙 切换，自动记住偏好），ECharts 图表文字颜色随主题自适应。

## ✨ 功能一览

| 模块 | 能力 |
|---|---|
| 📥 数据导入 | CSV / XLSX / JSON / **直接粘贴**（Excel 复制即用）；自动识别中文编码与分隔符；**Excel 多工作表**一键导入；示例数据生成 |
| 🔍 一键洞察 | **数据质量评分（0-100 环形进度 + 扣分明细）** + 纯本地规则引擎：数据质量体检（重复/缺失/常量列/疑似数值列）、数值列分布形态与离群值、类别集中度、时间范围与月度趋势、最大环比突变、强相关列对 → 中文要点清单 |
| 🧹 清洗与列变换 | 行级：去重、缺失值 6 种处理、12 种条件筛选、**异常值剔除**；列级：重命名、类型转换、**分箱（等宽/等频+自定义标签）、独热编码、Z-score/Min-Max 标准化、对数变换、日期成分提取（年月日/季度/星期/小时）、正则提取新列**；一级撤销 + 回滚原始 + 操作历史 |
| 📈 统计分析 | 分组聚合（10 种函数）、透视表、**相关性（Pearson/Spearman/Kendall 三方法卡片内切换）**、直方图、箱线图、频次统计、describe 汇总 |
| 📉 时间序列与预测 | 趋势、**同比/环比/累计**、移动平均、**🔮 预测**（线性趋势/指数平滑/季节朴素三法留出回测 MAPE 自动选优 + 95% 置信区间带状图） |
| 🎯 业务模板 | **RFM 客户价值分层**（五分位打分 → 8 层客户群）、**ABC/帕累托**（双轴累计曲线 + 80% 标线）、**异常值检测**（IQR/Z-score） |
| 🧪 统计检验 | **正态性（Shapiro-Wilk + Jarque-Bera）**、**组间比较（Welch t / ANOVA + Mann-Whitney U / Kruskal-Wallis / Levene）**、**卡方独立性（含 Cramér's V 与交叉表）**、**相关性显著性检验**——自动输出 p 值与「是否显著」业务结论 |
| 🗄️ SQL 控制台 | **DuckDB 引擎**：数据集注册为 `ds1/ds2…`（当前数据集亦可用 `df`），支持 GROUP BY / JOIN / 窗口函数等标准 SQL；只读防护；结果可存为新数据集 |
| ⚖️ 对比与采样 | **数据集对比**（列增删/类型变化/数值统计差异/键匹配）+ **采样**（随机/分层/前 N → 新数据集） |
| 🐍 Python 变换 | 直接写 pandas 代码处理数据（内置 pd / np），先预览后应用，30 秒超时保护 |
| 📤 导出 | 数据集与任意结果卡片导出 CSV / Excel（UTF-8 BOM） |
| 📡 在线行情 | **akshare 开源数据库**（东方财富主源+新浪自动降级）：A 股个股（日/周/月线，前/后复权）与常用指数（上证/深证/创业板/沪深300/中证500/1000）一键拉取建数据集；含离线示例股票数据生成 |
| 💰 金融分析 | **行情列智能识别**（中英文）→ 收益与风险指标（年化收益/波动/最大回撤/Sharpe/Sortino/Calmar/VaR/CVaR + 累计收益曲线）；**K线图**（candlestick+MA5/10/20/60+成交量+缩放）；**8 类技术指标**生成新列（MA/EMA/MACD/RSI/BOLL/KDJ/ATR/OBV）；**CAPM 基准对比**（Beta/Alpha/跟踪误差/信息比率+回归散点）；**投资组合**（2~5 资产有效前沿+最小方差/最大Sharpe点+相关矩阵）；**ADF 平稳性**与 **Ljung-Box 自相关**检验 |
| 📄 HTML 报告 | 一键生成**自包含 HTML 分析报告**（内嵌图表与洞察全文，离线可看、可直接发同事） |
| 🎯 图表推荐 | 根据列类型组合自动推荐 10 种以内可视化（Tableau "Show Me" 思路），一键生成结果卡片 |
| 🖱️ 列头快捷菜单 | 预览表格点任意列名 → 该列画像 / 填充到清洗筛选 / SQL 预览此列 |
| 🤖 AI 问答（可选） | 配置 OpenAI 兼容接口（智谱 GLM / DeepSeek / OpenAI 等）后：自然语言提问；**📊 按描述出图**（说「各月销售额趋势」直接生成图表卡）；「AI 解读洞察」；模型给的 pandas 代码经你确认才执行 |

## 🤖 AI 配置（可选）

在工具坞「AI 问答」中填写 API Base URL、模型名称、API Key（仅保存在本机 `data/config.json`）。不配置时其余功能完全不受影响。

## 🛠️ 从源码运行（开发者）

```bash
# 1. 创建虚拟环境并安装依赖（首次）
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

# 2a. 启动（推荐，与 exe 相同入口）
.venv\Scripts\python run_app.py

# 2b. 或开发模式
.venv\Scripts\python -m uvicorn backend.app.main:app --port 8765 --reload

# 3. 运行测试（104 项）
.venv\Scripts\python -m pytest tests/ -q
```

## 📦 构建 exe

```bash
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --name "数据分析小助手" --add-data "frontend;frontend" --collect-submodules akshare --collect-data akshare --collect-data py_mini_racer run_app.py
```

产物在 `dist/数据分析小助手.exe`（约 103 MB，含 scipy/duckdb/akshare）。注意 `--collect-data` 两个参数不可省：akshare 需要内置日历数据文件，py_mini_racer 需要内置原生库，缺了会导致在线行情在 exe 中不可用。构建环境：Python 3.14 + PyInstaller 6.x（已在 Windows 10/11 验证）。

## 📁 目录结构

```
data_helper/
├── backend/app/          # FastAPI 后端
│   ├── finance.py        # 金融核心（收益风险/技术指标/K线/CAPM/组合/ADF/LB）
│   ├── datafeed.py       # akshare 在线行情（东财+新浪双源降级）
│   ├── main.py           # 应用入口（路由 + 静态托管）
│   ├── api.py            # 全部 HTTP 路由
│   ├── storage.py        # 数据集存储（原始文件 + 工作副本 + 撤销快照）
│   ├── profile.py        # 列画像
│   ├── cleaning.py       # 清洗 + 列级变换（14 种操作）
│   ├── analysis.py       # 统计/时序/业务模板分析（13 种）
│   ├── stats_tests.py    # 统计检验套件（SciPy）
│   ├── forecast.py       # 时序预测（三方法回测选优 + 置信区间）
│   ├── deepprofile.py    # 深度画像（多方法相关/缺失矩阵/重复明细/交互散点）
│   ├── sqlquery.py       # SQL 查询引擎（DuckDB）
│   ├── compare.py        # 数据对比 + 采样
│   ├── suggest.py        # 自动图表推荐 + 交叉热力
│   ├── insights.py       # 一键本地洞察（规则引擎）
│   ├── report.py         # 自包含 HTML 报告生成
│   ├── transform.py      # Python 代码变换
│   ├── ai.py             # 可选 LLM 问答（OpenAI 兼容）
│   ├── exporter.py       # CSV/XLSX 导出
│   ├── sample.py         # 示例数据生成
│   └── paths.py          # 路径（开发/exe 双模式）
├── frontend/             # 无构建前端（Vue3 + ECharts 本地 vendor，明暗双主题）
├── tests/                # pytest 测试（104 项）
├── run_app.py            # 启动入口
├── requirements.txt      # 运行依赖（含 scipy / duckdb）
└── requirements-dev.txt  # 开发依赖（含 pytest / pyinstaller）
```

## ⚠️ 说明与边界

- **内存级处理**：基于 pandas，适合百万行以内的表格数据；更大的数据建议先抽样（内置采样功能）。
- **Python 变换以当前用户权限执行**：本地单人工具的设计取舍，请不要运行来路不明的代码。
- **SQL 只读防护**：仅允许 SELECT/WITH，检测并拒绝修改类关键字；结果超 10 万行自动截断。
- **数据安全**：默认全本地。AI 问答开启后，只会把数据集的**结构摘要**（列名/类型/统计量，不含明细行）发送给你配置的模型服务。
- 撤销为一级撤销；更早的状态用「回滚原始数据」。

## 🧪 测试

104 项 pytest 覆盖：上传解析（含 GBK/JSON/XLSX/单列/分页/粘贴/多 sheet）、数据集管理（撤销/回滚）、14 种清洗与列变换、13 种分析、统计检验（4 类）、预测（趋势/数据不足路径）、SQL（正常/拒绝变更/建集）、深度画像（三方法相关/缺失矩阵/重复/交互）、对比/采样/图表推荐、导出、AI 模块、洞察规则与 HTML 报告。前端工作台已通过浏览器 GUI 全流程实测（明/暗主题）。

## 🎨 设计语言

界面遵循 [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines)：清晰、遵从内容、深度三原则——毛玻璃材质（backdrop blur + 饱和度提升）、系统色板（亮 #007AFF / 暗 #0A84FF 系）、#f5f5f7 / #161617 灰阶层次、大标题、胶囊按钮与分段控件、连续大圆角、8pt 间距网格、柔和多层阴影与微交互动效。

## 🙏 功能与思路参考

[ydata-profiling](https://github.com/ydataai/ydata-profiling)（自动化画像与告警）、[DuckDB SQL on Pandas](https://duckdb.org/docs/lts/guides/python/sql_on_pandas.html)（DataFrame 上的 SQL）、[Tableau Workspace](https://help.tableau.com/current/pro/desktop/en-us/environment_workspace.htm)（数据栏/画布/属性栏三栏范式与 Show Me 推荐）、[Hex](https://learn.hex.tech/docs/explore-data/projects/projects-introduction)（卡片式分析画布）。
