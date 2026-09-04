# 数据分析小助手 · 功能清单

> 按模块组织的完整功能面。本清单同时是代码审计/优化的验收基准：每个功能点在改动后必须仍然可用。
> 更新时间：2026-09（v2.0 · 152+ 测试）。

## 一、数据导入与管理

| 功能 | 说明 | 入口 |
|---|---|---|
| 文件导入 | CSV / XLSX / JSON / TXT；自动识别中文编码（utf-8-sig/gbk）与分隔符；8MB 分块落盘，上限默认 500MB（`DATA_HELPER_MAX_UPLOAD_MB` 可调） | 顶栏「导入文件」 |
| 大 CSV 流式建集 | >16MB 的 CSV 分块（20 万行/块）直写 Parquet，内存只驻留单块；类型漂移/分隔符误判自动回退全量解析 | 上传自动分流 |
| 粘贴导入 | 直接粘贴 Excel 复制内容（Tab 自动转逗号） | 顶栏「粘贴数据」 |
| 示例数据 | 内置含缺失/重复的 370 行销售数据，一键体验全流程 | 顶栏「示例数据」 |
| Excel 多工作表 | xlsx 内多 sheet 一键导入为新数据集 | 数据集操作条 chips |
| 数据集管理 | 重命名 / 删除 / 回滚原始 / 一级撤销（撤销快照 prev.parquet）/ 操作历史时间线（200 条） | 左栏 + 操作条 |
| 存储 | `data/datasets/{id}/`：original.* + current.parquet（原子写）+ prev.parquet + meta.json；旧 pickle 数据加载时自动迁移 | — |

## 二、数据预览与画像

| 功能 | 说明 |
|---|---|
| 分页预览 | 20/50/100/200 每页；列头点击快捷菜单（该列画像 / 填入清洗筛选 / SQL 预览此列） |
| 列画像 | 每列类型/缺失/唯一值/数值统计（min/max/mean/median/std/p25/p75）/类别高频值 |
| 一键洞察 | 本地规则引擎：质量评分（0-100 环形 + 加权扣分明细）、质量体检（重复/缺失/常量列/疑似数值列/ID 列）、数值分布形态、类别集中度、月度趋势与环比突变、强相关列对 → 中文要点清单 |
| 深度画像 | 多方法相关矩阵（Pearson/Spearman/Kendall）、缺失值矩阵热力图（1/40 行分段 × 列）、重复行明细、文本列长度统计、两列交互散点（降采样 ≤1000） |

## 三、清洗与列变换（14 种操作）

- 行级：去重（可按列）、删缺失行（any/all）、12 种条件筛选（比较/包含/开头/between/isin/空值）、IQR/Z-score 异常值剔除
- 列级：重命名、类型转换（int/float/str/datetime）、分箱（等宽/等频 + 自定义标签）、独热编码（≤30 类）、Z-score/Min-Max 标准化、log(1+x) 变换、日期成分提取（年月日/季度/星期/小时）、正则提取新列

## 四、统计分析（13 种）

分组聚合（10 种函数）· 透视表 · 相关性（三方法卡片内切换 + 矩阵热力图）· 直方图 · 箱线图（五数概括）· 频次统计 · describe 汇总 · 时间趋势（D/W/M/Q/Y 重采样）· 同比/环比/累计 · 移动平均 · RFM · 帕累托 ABC · 异常值检测

## 五、业务模板

| 模板 | 要点 |
|---|---|
| RFM 客户分层 | 五分位打分 → 8 层客户群 + 分层汇总表 + 明细（前 500）+ 饼图 |
| 转化漏斗 | 到达制口径（不校验事件顺序）；各步去重人数/单步转化/整体转化/流失明细 + ECharts 漏斗图 |
| 同期群留存 | 按首活跃月/周分群，N 期（2-12）留存率矩阵 + 群规模 + 热力图 |
| K-means 聚类 | 手写 k-means++ + 多重启；肘部法 SSE + 轮廓系数自动推荐 k；Z-score 标准化；簇画像表 + 散点着色 + 中心点 |
| ABC/帕累托 | 双轴累计曲线 + 80%/95% 分级 |
| 异常值检测 | IQR 1.5×四分位距 / Z-score \|z\|>3，可一键转入清洗剔除 |

## 六、统计检验与 A/B 套件

- 正态性：Shapiro-Wilk（n≤5000）+ Jarque-Bera，偏度/峰度
- 组间比较：2 组 Welch t + Mann-Whitney U + Cohen's d（效应量分级）；3+ 组 ANOVA + Kruskal-Wallis + Levene
- 卡方独立性：Cramér's V + 交叉表（类别 >10 自动合并"其他"）
- 相关显著性：Pearson / Spearman
- **两比例 z 检验**（A/B 转化）：数据集模式 / 直接计数模式；合并标准误检验 + 非合并标准误差值 95% CI + 相对提升
- **样本量计算器**：α/power/基线/MDE（绝对或相对）→ 每组 n（正态近似）

## 七、时序与预测

趋势/同比环比/移动平均；**预测**：线性趋势 / Holt 双参数指数平滑（网格搜索 α/β）/ 季节朴素三方法，20% 留出回测按 MAPE 自动选优，95% 置信区间带状图，horizon 1-36 期。

## 八、SQL 控制台（DuckDB）

- 全部数据集注册为 `ds1/ds2…` 视图（当前数据集额外 `df`），直接 `read_parquet` 惰性读取
- 标准 SQL：GROUP BY / JOIN / 窗口函数 / ntile / quantile 等
- 只读防护两级：语句必须 SELECT/WITH 开头 + 分号逐段校验（引号感知切分，字符串里的分号不误杀）
- 预览自动外层 LIMIT 10 万行；结果可另存为新数据集（完整不截断）

## 九、AI Agent（可选，OpenAI 兼容）

- **SSE 流式对话**：逐字渲染、光标动画、停止按钮、会话历史（内存级 24 条 × 50 会话）
- **Function calling 工具循环**：12 个工具（汇总/分组/趋势/相关/直方图/频次/RFM/漏斗/留存/聚类/两比例 z/预测）JSON Schema 注册；LLM 出意图 → 后端本地 DataFrame 真实执行 → 统计结果回填 → 结果卡自动进数据页；工具失败自动回填错误供 LLM 重试；≤6 轮防失控
- 隐私边界：仅列结构摘要（列名/类型/统计量）发送给模型服务；API Key 掩码存储不回传
- 端点不支持 tools 自动降级纯文本流式
- 自然语言出图（图表 spec 生成 + 直接执行）
- 「解读洞察」：一键把本地洞察结果交给 AI 做业务解读

## 十、MCP 服务端（外接 AI）

外部聊天客户端（Cherry Studio / ChatWise 等）填用户自己的 API Key，把本软件加为 MCP 工具源（Streamable HTTP `/mcp/mcp`、SSE `/sse/sse`），客户端 AI 可调用 15 个只读工具：list_datasets / column_profile / read_rows / sql_query / describe / groupby / correlation / value_counts / trend / rfm / funnel / cohort / cluster / ab_prop_test / forecast（结果 200 行封顶）。接入指南见 docs/MCP.md。

## 十一、在线行情与金融分析

- **在线行情**（akshare，可选）：A 股个股（东财主源 + 新浪降级，日/周/月线，前/后复权）与常用指数；60s 超时防护；热门股票搜索（代码/名称，字面匹配）；离线示例股票数据生成
- **收益风险指标**：区间总收益/年化（几何）、年化波动、最大回撤（峰值/谷底日期）、下行波动、VaR/CVaR 95%/99%、Sharpe/Sortino/Calmar、偏度峰度、累计收益曲线
- **K 线图**：candlestick + MA5/10/20/60 + 成交量 + dataZoom 缩放
- **8 类技术指标**（生成新列）：MA/EMA/MACD(DIF,DEA,MACD)/RSI(Wilder)/BOLL(20,2)/KDJ(9,3,3)/ATR(14)/OBV
- **CAPM 基准对比**：Beta/年化 Alpha/R²/跟踪误差/信息比率 + 回归散点（日期对齐 ≥20 共同交易日）
- **投资组合**：2-5 资产，年化收益/协方差，2000 组 Dirichlet 随机权重的有效前沿 + 最小方差/最大 Sharpe 点 + 相关矩阵
- **计量检验**：ADF 单位根（手写 OLS，含常数/趋势两种，MacKinnon 近似临界值）、Ljung-Box 自相关（经典 ACF）

## 十二、对比 / 采样 / 变换 / 导出

- 数据集对比：列增删/类型变化/行数/共同数值列统计差异/按键匹配
- 采样：随机/分层/前 N → 新数据集（分层保留分层列）
- Python 变换：内置 pd/np，8 个代码模板，先预览后应用，30s 超时（线程路由式 stdout 捕获，不劫持进程输出）
- 导出：数据集与任意结果卡 → CSV（utf-8-sig）/ XLSX（超 104 万行给出明确提示改用 CSV）
- HTML 报告：洞察全文 + 自动图表（直方图/Top10/月度趋势/相关热力）内嵌 echarts，自包含离线可看（用户内容全部转义）

## 十三、工程与基建

- 测试：150+ 项 pytest（上传/存储/SQL/业务模板/检验/Agent mock LLM/金融/报告导出）
- CI：GitHub Actions（ruff + pytest，Python 3.12/3.14）；ruff 零告警
- 日志：控制台 + `data/logs/app.log` RotatingFileHandler，关键路径落日志
- 打包：PyInstaller onefile exe（含 akshare collect-data 修复）
- 端到端案例：`scripts/fetch_dataset.py`（UCI Online Retail II 106 万行）+ `scripts/run_ecommerce_analysis.py`（一键复跑全部分析），叙事见 `examples/ecommerce/`

## 前端界面结构

顶栏（导入/粘贴/示例/AI 对话/主题）· 左侧数据集栏（搜索/相对时间）· AI 对话主视图（欢迎页/流式气泡/工具进度/连接设置弹窗）· 数据画布（操作条/推荐 chips/分页预览/结果卡片网格 7 种形态）· 右侧工具坞 11 节 · 状态栏 · 明暗双主题（ECharts 自适应）

## 结果卡片形态

通用表格卡（6 种图表切换/导出/排序）· 洞察卡（质量环/KPI/下钻）· 检验卡（p 值结论 pill）· RFM 卡 · 对比卡 · 金融卡（K线/CAPM/前沿）· 变换卡 · 漏斗/留存/聚类专用卡
