# MCP 外接 AI 使用指南

> 不用内置对话页：在 **Cherry Studio / ChatWise** 等成熟聊天客户端里填你自己的 API Key，把本软件添加为 MCP 工具源——客户端里的 AI 就能直接调用本软件的分析能力（RFM / 漏斗 / 留存 / 聚类 / A-B 检验 / SQL / 预测等 15 个工具）。
>
> 隐私边界与内置 AI 一致：**LLM 在客户端侧（你的 Key），工具调用回本机执行，原始数据不出本机**。

## 一、开启 MCP

1. 软件启动后 MCP 自动可用（依赖 `mcp` 库，`requirements.txt` 已包含；老环境执行 `pip install mcp` 后重启应用）。
2. 查看地址：内置 AI 页 → ⚙️ 连接设置 → 「🔌 外接聊天客户端（MCP）」一键复制。地址形如：

```
http://127.0.0.1:8765/mcp/mcp      ← Streamable HTTP（推荐，新客户端）
http://127.0.0.1:8765/sse/sse      ← SSE（旧版客户端兼容）
```

端口以你启动时黑窗口打印的为准。

## 二、Cherry Studio 配置（免费，推荐）

1. [下载 Cherry Studio](https://cherry-ai.com/)（Windows/Mac/Linux）。
2. **配置模型服务**：设置 → 模型服务 → 添加（或选已有服务商）：
   - 智谱：API 地址 `https://open.bigmodel.cn/api/paas/v4`，填你的 Key，模型如 `glm-4.6`
   - DeepSeek：API 地址 `https://api.deepseek.com/v1`，模型如 `deepseek-chat`
   - 任何 OpenAI 兼容服务均可
3. **添加 MCP 服务器**：设置 → MCP 服务器 → 添加：
   - 类型选 **Streamable HTTP**（旧版本选 SSE）
   - URL 粘贴上面的 MCP 地址
   - 保存后确认工具列表出现 `data-helper` 的 15 个工具（list_datasets / sql_query / rfm / funnel / cohort / cluster / ab_prop_test / forecast …）
4. **使用**：先在数据小助手里导入/生成数据集，然后到 Cherry Studio 对话：
   > "看看我本机有哪些数据集，对销售数据做一次 RFM 分层，并解读结果"

   AI 会自动调用 list_datasets → column_profile → rfm 并基于真实结果回答。

## 三、其他客户端

| 客户端 | 配置位置 | 传输选择 |
|---|---|---|
| ChatWise | Settings → MCP → Add Server | Streamable HTTP |
| 5ire / 其他 MCP 面板 | MCP 服务器 → 添加 URL | Streamable HTTP 或 SSE |
| 自研脚本 | `mcp` Python/TS SDK `streamablehttp_client(url)` | Streamable HTTP |

## 四、工具清单（15 个）

| 工具 | 用途 |
|---|---|
| `list_datasets` | 列出本机数据集（id/名称/行列/列名）——分析的第一步 |
| `column_profile` | 每列类型/缺失/唯一值/统计量/高频值——选列依据 |
| `read_rows` | 分页预览原始行 |
| `sql_query` | 只读 SQL（DuckDB；跨数据集 JOIN 用 ds1/ds2…别名） |
| `describe` / `groupby` / `correlation` / `value_counts` / `trend` | 描述统计/分组聚合/相关矩阵/频次/时间趋势 |
| `rfm` | RFM 客户分层（五分位 8 层 + 金额占比） |
| `funnel` | 转化漏斗（到达制口径） |
| `cohort` | 同期群留存矩阵（月/周） |
| `cluster` | K-means 聚类（肘部法+轮廓系数自动选 k） |
| `ab_prop_test` | A/B 两比例 z 检验（p 值/差值 CI/相对提升） |
| `forecast` | 时序预测（三方法回测选优 + 区间） |

返回给 AI 的结果统一做了行数裁剪（默认 200 行），避免撑爆上下文。

## 五、安全边界

- MCP 工具**全部只读**：分析类计算不改数据；SQL 与内置控制台同一套 SELECT/WITH 只读防护。
- 服务只应监听本机（默认 127.0.0.1）。**不要把端口暴露到公网**——任何能访问该端口的 MCP 客户端都能读取你的数据集。
- API Key 只存在于你的聊天客户端与本软件配置中，两者都只在本机。

## 六、常见问题

- **客户端连不上**：确认软件正在运行、端口与地址一致；浏览器直接访问 MCP 地址返回 406/400 是正常现象（它要求特定的 MCP 协议头），不代表服务挂了。
- **AI 说找不到工具**：在客户端里确认 MCP 服务器已启用、工具列表已加载。
- **exe 版**：内置 `mcp` 依赖；若使用精简打包导致不可用，界面设置弹窗仍会显示地址但工具列表为空——用源码方式启动即可。
