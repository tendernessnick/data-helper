"""下载 UCI Online Retail II（约 100 万行真实电商交易，CC BY 4.0）并转成工具可用的 CSV。

- 原始数据：https://archive.ics.uci.edu/dataset/502/online+retail+ii
- 一个 zip 内含 xlsx（2009-2010 / 2010-2011 两个 sheet），合并为单个 CSV
- 数据文件不进 git；删除后重跑本脚本即可复现

用法：
    .venv/Scripts/python.exe scripts/fetch_dataset.py [--out data/online_retail_ii.csv]
"""
import argparse
import io
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"

RENAME = {
    "Invoice": "InvoiceNo",
    "InvoiceDate": "InvoiceDate",
    "Customer ID": "CustomerID",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/online_retail_ii.csv", help="输出 CSV 路径")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print(f"[skip] 已存在 {out}（删除后可重新下载）")
        return 0

    import pandas as pd

    print(f"[1/3] 下载 {URL} …")
    with tempfile.TemporaryDirectory() as td:
        zpath = Path(td) / "retail.zip"
        with urllib.request.urlopen(URL, timeout=300) as resp, open(zpath, "wb") as f:
            total = 0
            while True:
                buf = resp.read(1 << 20)
                if not buf:
                    break
                total += len(buf)
                f.write(buf)
        print(f"      已下载 {total / 1048576:.1f} MB")

        print("[2/3] 解压并读取 xlsx（约 100 万行，需要 1-2 分钟）…")
        with zipfile.ZipFile(zpath) as z:
            xl_name = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
            with z.open(xl_name) as f:
                sheets = pd.read_excel(io.BytesIO(f.read()), sheet_name=None, engine="openpyxl")
        df = pd.concat(sheets.values(), ignore_index=True)
        df = df.rename(columns=RENAME)

    print(f"[3/3] 写出 {out} …")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"完成：{len(df)} 行 × {df.shape[1]} 列 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
