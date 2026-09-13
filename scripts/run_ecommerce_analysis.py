"""端到端预处理案例：上传百万行 UCI Online Retail II → 体检 → 清洗 → 复检 → 导出。

数据文件不进 git：先运行 scripts/fetch_dataset.py 下载数据，再运行本脚本：
    .venv/Scripts/python.exe scripts/run_ecommerce_analysis.py

流程：启动临时后端（仅本机回环）→ 流式上传 CSV（>16MB 自动走分块 Parquet 路径）→
数据体检（找问题）→ SQL 清洗建新集（排取消单/退货/散单）→ 再次体检对比评分 →
快速统计（月度趋势/异常值）→ 导出清洗后 CSV，全部响应 JSON 存 examples/ecommerce/results/。
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


def main() -> int:
    if not CSV_PATH.exists():
        print("缺少数据文件，请先运行 scripts/fetch_dataset.py")
        return 1
    RESULTS.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True)

    # 父进程同样指向 SCRATCH：health_check/export 走进程内直调时读到同一批数据集
    os.environ["DATA_HELPER_DATA"] = str(SCRATCH)
    env = dict(os.environ)
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


def health_check(ds_id: str) -> dict:
    """进程内直调体检引擎：数据集在同一 data 目录（DATA_HELPER_DATA 指向 SCRATCH）。"""
    from backend.app import insights as insights_mod
    from backend.app import storage as storage_mod

    return insights_mod.run_insights(storage_mod.load_df(ds_id), storage_mod.get_meta(ds_id))


def print_health(tag: str, h: dict):
    qs = h["quality_score"]
    print(f"  [{tag}] 质量评分 {qs['score']}（{qs['level']}），问题 {len(h['findings'])} 项：")
    for f in h["findings"][:6]:
        print(f"    {f['level']:5} {f['category']:9} {f['msg']}")
    if len(h["findings"]) > 6:
        print(f"    … 其余 {len(h['findings']) - 6} 项详见 JSON")


def export_clean_csv(ds_id: str) -> Path:
    """进程内导出清洗后的 CSV。"""
    from backend.app import exporter
    from backend.app import storage as storage_mod

    path = exporter.export_df(storage_mod.load_df(ds_id), "online_retail_clean", "csv")
    dest = SCRATCH / "online_retail_clean.csv"
    shutil.copyfile(path, dest)
    return dest


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

    print("[2/6] 原始数据体检…")
    h1 = health_check(raw_id)
    save("01_health_check_raw", h1)
    print_health("原始", h1)

    print("[3/6] SQL 清洗：排除取消单/退货行/无客户ID散单，派生金额列…")
    clean = f'''
    SELECT "InvoiceNo", CAST(CAST("CustomerID" AS BIGINT) AS VARCHAR) AS "CustomerID", "InvoiceDate",
           "Quantity", "Price", "Country",
           ROUND("Quantity" * "Price", 2) AS "Amount"
    FROM {a}
    WHERE "CustomerID" IS NOT NULL AND "Quantity" > 0 AND "InvoiceNo" NOT LIKE 'C%' AND "Price" > 0
    '''
    clean_id = new_dataset_from_sql("有效销售明细", clean, raw_id)

    print("[4/6] 清洗后复检（评分对比）…")
    h2 = health_check(clean_id)
    save("02_health_check_clean", h2)
    print_health("清洗后", h2)
    print(f"  评分变化：{h1['quality_score']['score']} → {h2['quality_score']['score']}，"
          f"问题数 {len(h1['findings'])} → {len(h2['findings'])}")

    print("[5/6] 快速统计：月度趋势与金额异常值…")
    trend = analyze(clean_id, "trend", {"date_column": "InvoiceDate", "value_column": "Amount", "freq": "M", "agg": "sum"})
    save("03_monthly_trend", trend)
    print(f"  月度趋势：{len(trend['rows'])} 个月，{trend['note']}")
    outliers = analyze(clean_id, "outliers", {"columns": ["Amount"], "method": "iqr"})
    save("04_outliers", outliers)
    print(f"  异常值：{outliers['rows'][0][3]} 个离群（{outliers['rows'][0][4]}%），可在清洗中盖帽处理")

    print("[6/6] 导出清洗后数据（CSV，交给专业分析软件）…")
    out = export_clean_csv(clean_id)
    print(f"  已导出 {out}（{out.stat().st_size / 1048576:.1f} MB）——清洗完成，后续深度分析交给你的主力工具")

    print(f"\n[done] 预处理流水线跑通：体检发现问题 → SQL 清洗 → 复检对比 → 导出。结果已存 {RESULTS}")


if __name__ == "__main__":
    sys.exit(main())
