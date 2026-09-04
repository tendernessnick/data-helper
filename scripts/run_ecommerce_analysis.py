"""端到端电商案例：上传百万行 UCI Online Retail II → 通过本工具 HTTP API 跑完整分析。

数据文件不进 git：先运行 scripts/fetch_dataset.py 下载数据，再运行本脚本：
    .venv/Scripts/python.exe scripts/run_ecommerce_analysis.py

流程：启动临时后端 → 流式上传 CSV（>16MB 自动走分块 Parquet 路径）→
SQL 清洗/派生 → RFM / 同期群留存 / K-means 聚类 / 生命周期漏斗 / 复购与 LTV / 退货与地理
→ 全部响应 JSON 存 examples/ecommerce/results/，控制台输出关键结论数字。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSV_PATH = ROOT / "data" / "online_retail_ii.csv"
PORT = 8901
BASE = f"http://127.0.0.1:{PORT}"
SCRATCH = ROOT / "data" / "ecommerce_demo"
RESULTS = ROOT / "examples" / "ecommerce" / "results"

_obs_end = "2011-12-10"  # 观测终点：数据集最大日期(2011-12-09) + 1 天，计算 R 用的基准日


def main() -> int:
    if not CSV_PATH.exists():
        print("缺少数据文件，请先运行 scripts/fetch_dataset.py")
        return 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True)

    env = dict(os.environ, DATA_HELPER_DATA=str(SCRATCH))
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_up()
        run_analysis()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def _wait_up(timeout=60):
    for _ in range(timeout * 2):
        try:
            if requests.get(BASE + "/", timeout=3).status_code == 200:
                print("[ok] 后端已启动")
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError("后端启动超时")


_ds = {}
_table_cache = None


def _alias(ds_id: str) -> str:
    global _table_cache
    if _table_cache is None:
        _table_cache = requests.get(BASE + "/api/sql/tables", timeout=60).json()
    for t in _table_cache:
        if t["id"] == ds_id:
            return t["alias"]
    raise KeyError(ds_id)


def save(name: str, obj):
    (RESULTS / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def sql(query: str, current_id: str = "", save_as: str = "") -> dict:
    r = requests.post(BASE + "/api/sql", timeout=300, json={"query": query, "current_id": current_id, "save_as": save_as})
    if r.status_code != 200:
        raise RuntimeError(f"SQL 失败（{r.status_code}）：{r.text[:300]}\n查询：{query[:200]}")
    return r.json()


def sql_df(result: dict):
    """把 /api/sql 响应转成 [{列: 值}]，便于打印与存档。"""
    names = [c["name"] for c in result["columns"]]
    return [dict(zip(names, row)) for row in result["rows"]]


def new_dataset_from_sql(name: str, query: str, base_id: str) -> str:
    res = sql(query, current_id=base_id, save_as=name)
    ds = res["new_dataset"]["id"]
    _ds[name] = ds
    global _table_cache  # 新数据集会改变别名排序
    _table_cache = None
    print(f"  [sql建集] {name}：{res['new_dataset']['meta']['rows']} 行")
    return ds


def analyze(ds_id: str, kind: str, params: dict) -> dict:
    r = requests.post(BASE + f"/api/datasets/{ds_id}/analyze", timeout=300, json={"kind": kind, "params": params})
    r.raise_for_status()
    return r.json()


def biz_run(ds_id: str, tool: str, params: dict) -> dict:
    r = requests.post(BASE + f"/api/datasets/{ds_id}/{tool}", timeout=300, json={"params": params})
    r.raise_for_status()
    return r.json()


def run_analysis():
    print("[1/6] 流式上传 CSV（92MB，分块直写 Parquet）…")
    t0 = time.time()
    with open(CSV_PATH, "rb") as f:
        r = requests.post(BASE + "/api/upload", files={"file": ("online_retail_ii.csv", f)}, timeout=600)
    r.raise_for_status()
    raw_id = r.json()["id"]
    meta = r.json()["meta"]
    print(f"  数据集 {raw_id}：{meta['rows']} 行 × {meta['cols']} 列，耗时 {time.time() - t0:.1f}s（{meta['history'][0]['action']}）")
    save("00_upload_meta", meta)
    a = _alias(raw_id)

    print("[2/6] SQL 清洗与派生…")
    # 有效销售（排除取消单/退货行/无客户ID）
    clean = f'''
    SELECT "InvoiceNo", "CustomerID", "InvoiceDate", "Quantity", "Price", "Country",
           ROUND("Quantity" * "Price", 2) AS "Amount"
    FROM {a}
    WHERE "CustomerID" IS NOT NULL AND "Quantity" > 0 AND "InvoiceNo" NOT LIKE 'C%' AND "Price" > 0
    '''
    clean_id = new_dataset_from_sql("有效销售明细", clean, raw_id)

    print("[3/6] RFM 客户分层…")
    rfm = analyze(clean_id, "rfm", {"id_column": "CustomerID", "date_column": "InvoiceDate", "value_column": "Amount"})
    save("01_rfm", rfm)
    seg_rows = rfm["rows"]
    print("  RFM 分层（前 8 段）:")
    for row in seg_rows[:8]:
        print("   ", row[0], row[1])
    print("  ", rfm.get("note", ""))

    print("[4/6] 同期群留存…")
    cohort = biz_run(clean_id, "cohort", {"user_column": "CustomerID", "date_column": "InvoiceDate", "freq": "M", "periods": 12})
    save("02_cohort", cohort)
    print("  ", cohort.get("note", ""))

    print("[5/6] K-means 聚类（RFM 三指标）× 生命周期漏斗…")
    cust_sql = f'''
    WITH s AS (SELECT * FROM {_alias(clean_id)}),
    percust AS (
      SELECT "CustomerID" AS uid,
             COUNT(DISTINCT "InvoiceNo") AS frequency,
             SUM("Amount") AS monetary,
             CAST(date_diff('day', CAST(MAX("InvoiceDate") AS TIMESTAMP), DATE '{_obs_end}') AS INT) AS recency_days
      FROM s GROUP BY 1
    )
    SELECT * FROM percust
    '''
    cust_id = new_dataset_from_sql("客户RFM指标", cust_sql, clean_id)
    cluster = biz_run(cust_id, "cluster", {"columns": ["recency_days", "frequency", "monetary"], "standardize": True})
    save("03_cluster", cluster)
    print("  ", cluster.get("note", ""))

    events_sql = f'''
    WITH s AS (SELECT * FROM {_alias(clean_id)}),
    percust AS (
      SELECT "CustomerID" AS uid,
             COUNT(DISTINCT "InvoiceNo") AS orders_cnt,
             SUM("Amount") AS total_amt
      FROM s GROUP BY 1
    ),
    q75 AS (SELECT quantile_cont(total_amt, 0.75) AS t75 FROM percust)
    SELECT uid, '首购' AS event FROM percust
    UNION ALL
    SELECT uid, '复购' FROM percust WHERE orders_cnt >= 2
    UNION ALL
    SELECT uid, '高价值' FROM percust CROSS JOIN q75 WHERE total_amt >= t75
    '''
    events_id = new_dataset_from_sql("客户生命周期事件", events_sql, clean_id)
    funnel = biz_run(events_id, "funnel", {"user_column": "uid", "event_column": "event", "steps": ["首购", "复购", "高价值"]})
    save("04_funnel", funnel)
    print("  ", funnel.get("note", ""))

    print("[6/6] 复购率 / LTV / 退货与地理…")
    ltv = sql(f'''
    WITH s AS (SELECT * FROM {_alias(clean_id)}),
    percust AS (
      SELECT "CustomerID" AS uid, COUNT(DISTINCT "InvoiceNo") AS orders_cnt, SUM("Amount") AS total_amt
      FROM s GROUP BY 1
    )
    SELECT COUNT(*) AS 客户数,
           SUM(CASE WHEN orders_cnt >= 2 THEN 1 ELSE 0 END) AS 复购客户数,
           ROUND(100.0 * SUM(CASE WHEN orders_cnt >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS 复购率pct,
           ROUND(AVG(total_amt), 2) AS 平均LTV,
           ROUND(MEDIAN(total_amt), 2) AS 中位LTV,
           ROUND(MAX(total_amt), 2) AS 最高LTV
    FROM percust
    ''', current_id=clean_id)
    save("05_ltv", ltv)
    print("  ", sql_df(ltv)[0])

    geo = sql(f'''
    SELECT "Country" AS 国家,
           COUNT(DISTINCT "InvoiceNo") AS 订单数,
           ROUND(SUM(CASE WHEN "Quantity" > 0 AND "InvoiceNo" NOT LIKE 'C%' THEN "Quantity" * "Price" ELSE 0 END), 0) AS 销售额,
           ROUND(SUM(CASE WHEN "Quantity" < 0 OR "InvoiceNo" LIKE 'C%' THEN -"Quantity" * "Price" ELSE 0 END), 0) AS 退货额
    FROM {_alias(raw_id)}
    WHERE "CustomerID" IS NOT NULL
    GROUP BY 1 HAVING COUNT(DISTINCT "InvoiceNo") > 200
    ORDER BY 销售额 DESC LIMIT 12
    ''', current_id=raw_id)
    save("06_geo", geo)
    for row in sql_df(geo):
        print("  ", row)

    ret = sql(f'''
    SELECT ROUND(100.0 * SUM(CASE WHEN "Quantity" < 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS 退货行占比pct,
           ROUND(SUM(CASE WHEN "Quantity" < 0 THEN -"Quantity" * "Price" ELSE 0 END) / 1000.0, 1) AS 退货金额k,
           COUNT(DISTINCT "CustomerID") AS 客户数
    FROM {_alias(raw_id)} WHERE "CustomerID" IS NOT NULL
    ''', current_id=raw_id)
    save("07_return_overall", ret)
    print("  ", sql_df(ret)[0])

    extra = sql(f'''
    WITH s AS (SELECT * FROM {_alias(clean_id)}),
    cust AS (SELECT "CustomerID" AS uid, SUM("Amount") AS amt FROM s GROUP BY 1),
    ranked AS (SELECT uid, amt, ntile(10) OVER (ORDER BY amt) AS decile FROM cust),
    share AS (SELECT ROUND(100.0 * SUM(CASE WHEN decile = 10 THEN amt ELSE 0 END) / SUM(amt), 1) AS top10_share
              FROM ranked),
    inv AS (SELECT COUNT(DISTINCT "InvoiceNo") AS n_inv, ROUND(SUM("Amount"), 0) AS total_amt FROM s)
    SELECT n_inv AS 订单数, ROUND(total_amt / n_inv, 2) AS 客单价, top10_share AS 头部10pct客户金额占比pct
    FROM inv CROSS JOIN share
    ''', current_id=clean_id)
    save("08_overview", extra)
    print("  ", sql_df(extra)[0])

    print("[补] 强制 k=4 聚类（对照 RFM 规则分层）…")
    cluster4 = biz_run(cust_id, "cluster", {"columns": ["recency_days", "frequency", "monetary"], "k": 4, "standardize": True})
    save("03b_cluster_k4", cluster4)
    print("  ", cluster4.get("note", ""))

    print(f"\n全部结果已存 {RESULTS}")


if __name__ == "__main__":
    sys.exit(main())
