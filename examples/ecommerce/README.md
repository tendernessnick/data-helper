# 百万行真实电商数据集端到端预处理

> 用「数据分析小助手」对 **UCI Online Retail II**（1,067,371 行真实在线零售交易，CC BY 4.0）完成的一次完整**数据预处理**：从原始 CSV 上传、体检发现问题、SQL 清洗、复检对比到导出可交付的干净数据。所有结论均由本工具后端真实计算产出，原始结果 JSON 见 [results/](results/)。

## 为什么只做预处理

深度分析（客户分层、留存、建模）有更专业的工具去做。本软件的定位是**把前置问题在最早阶段暴露并修掉**：格式脏污、类型混乱、缺失、重复、异常值——让交给主力分析软件的数据是干净可信的。

## 流水线与真实结果

| 步骤 | 操作 | 结果 |
|---|---|---|
| 1. 上传 | 92MB CSV 流式导入（分块直写 Parquet） | **1,067,371 行 × 8 列，2.9 秒** |
| 2. 体检 | 一键数据体检（质量评分 + 问题清单） | 评分 **83.4**，发现 **15 项**问题 |
| 3. 清洗 | SQL 建新集：排除取消单/退货行/无客户ID散单 | 有效销售 **805,549 行** |
| 4. 复检 | 再次体检对比 | 评分 77.5，问题 11 项（重复行占比上升属业务特性，见下） |
| 5. 快查 | 月度趋势 + 金额异常值 | 25 个月趋势；Amount 离群 8.24% |
| 6. 导出 | 清洗后数据导出 CSV | **46.5MB** 干净数据，交给你的主力工具 |

## 体检都发现了什么（原始数据）

- 🔴 **34,335 行完全重复**——真实交易流水中的重复录入（一键去重可修）
- 🟡 `StockCode` **混合类型**：87.35% 是数字、其余是文本（如礼品码 POST）——数值解析可提取
- 🟡 `Description` **20.04% 的值带首尾空格**（213,035 个）——去除首尾空格一键修复
- 🟡 `Quantity` **22,950 个负值**——退货/取消单（本次用 SQL 排除）
- 🟡 `Quantity` 离群值 10.91%——批发场景的大额订单属真实极端值，适合盖帽而非删除

清洗后复检：负值与散单已消失，但\「完全重复行\」上升到 314,891 行——这是**业务特性而非脏数据**（同一发票同一商品允许多行），体现了体检结果需要结合业务判断的价值。

## 清洗 SQL（DuckDB 直读 Parquet 视图）

```sql
SELECT "InvoiceNo", CAST(CAST("CustomerID" AS BIGINT) AS VARCHAR) AS "CustomerID", "InvoiceDate",
       "Quantity", "Price", "Country",
       ROUND("Quantity" * "Price", 2) AS "Amount"
FROM ds1
WHERE "CustomerID" IS NOT NULL AND "Quantity" > 0 AND "InvoiceNo" NOT LIKE 'C%' AND "Price" > 0
```

## 复现

```bash
.venv/Scripts/python.exe scripts/fetch_dataset.py            # 下载数据（约 43MB，一次性）
.venv/Scripts/python.exe scripts/run_ecommerce_analysis.py   # 一键重跑体检→清洗→复检→导出
```

结果文件：`00_upload_meta` / `01_health_check_raw` / `02_health_check_clean` / `03_monthly_trend` / `04_outliers`。
