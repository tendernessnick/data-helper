"""SQL 查询引擎：基于 DuckDB，直接对数据集跑 SQL。

- 所有数据集以 ds1 / ds2 ... 注册（UI 显示别名与真实名称对应关系）
- 数据集以 Parquet 文件注册为视图，DuckDB 惰性读取，不整表载入 Python 内存
- 当前数据集额外注册为 df，方便快速引用
- 仅允许 SELECT / WITH 开头的查询；结果超过上限自动截断
"""
import logging
import re

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

MAX_ROWS = 100_000


class SqlError(ValueError):
    pass


def _parquet_view(con, alias: str, path: str) -> None:
    # DuckDB 的 CREATE VIEW 不支持参数绑定，路径来自本程序自身存储，做单引号转义后内联
    lit = "'" + str(path).replace("'", "''") + "'"
    con.execute(f"CREATE OR REPLACE VIEW {alias} AS SELECT * FROM read_parquet({lit})")


def run_sql(query: str, datasets: list, current_id: str = "") -> dict:
    """datasets: [{id, name, path}]，path 指向数据集 current.parquet；current_id 对应的表额外注册为 df。"""
    q = (query or "").strip().rstrip(";")
    if not q:
        raise SqlError("SQL 不能为空")
    # 两级只读防护：
    # 1) 语句必须以 SELECT/WITH 开头（覆盖主查询）
    # 2) 分号拼接的每一段都必须是查询（拦截 "SELECT 1; DROP TABLE x"）
    # 不做全文关键字扫描：避免误伤列名/字符串里恰好含 update 等词的合法查询
    for i, seg in enumerate(q.split(";")):
        seg = seg.strip()
        if not seg:
            continue
        if not re.match(r"(?is)^(select|with)\b", seg):
            raise SqlError("仅允许 SELECT / WITH 查询" + (f"（第 {i + 1} 段语句不是查询）" if i else ""))

    con = duckdb.connect(":memory:")
    aliases = []
    try:
        for i, item in enumerate(datasets, start=1):
            alias = f"ds{i}"
            _parquet_view(con, alias, item["path"])
            aliases.append({"alias": alias, "id": item["id"], "name": item["name"]})
            if item["id"] == current_id:
                _parquet_view(con, "df", item["path"])
        if current_id and not any(a["id"] == current_id for a in aliases):
            raise SqlError("当前数据集不在可查询列表中")
        result = con.execute(q)
        df = result.df()
    except duckdb.Error as e:
        raise SqlError(f"SQL 执行出错：{e}")
    finally:
        con.close()

    from .serialize import cell

    total = len(df)
    truncated = total > MAX_ROWS
    if truncated:
        df = df.head(MAX_ROWS)
    logger.info("SQL 执行完成 rows=%d truncated=%s query=%.80s", total, truncated, q)
    return {
        "columns": [
            {"name": str(c), "numeric": pd.api.types.is_numeric_dtype(df[c])}
            for c in df.columns
        ],
        "rows": [[cell(v) for v in row] for row in df.itertuples(index=False, name=None)],
        "total": total,
        "truncated": truncated,
        "aliases": aliases,
        "df": df,
    }
