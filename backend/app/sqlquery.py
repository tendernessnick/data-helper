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


def _split_statements(q: str) -> list:
    """按分号切分语句，但跳过字符串字面量与注释内的分号。

    q.split(";") 会把 WHERE x='a;b' 误判成两条语句而拒绝合法查询。
    """
    segs, buf = [], []
    i, n = 0, len(q)
    while i < n:
        ch = q[i]
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(q[i])
                if q[i] == quote and (i + 1 >= n or q[i + 1] != quote):
                    i += 1
                    break
                if q[i] == quote:  # 转义的引号 '' / ""
                    i += 1
                    if i < n:
                        buf.append(q[i])
                i += 1
            continue
        if ch == "-" and i + 1 < n and q[i + 1] == "-":  # 行注释
            while i < n and q[i] != "\n":
                buf.append(q[i])
                i += 1
            continue
        if ch == "/" and i + 1 < n and q[i + 1] == "*":  # 块注释
            buf.append(q[i])
            i += 1
            while i + 1 < n and not (q[i] == "*" and q[i + 1] == "/"):
                buf.append(q[i])
                i += 1
            if i + 1 < n:
                buf.append(q[i : i + 2])
                i += 2
            continue
        if ch == ";":
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segs.append("".join(buf))
    return segs


def run_sql(query: str, datasets: list, current_id: str = "", save_as: str = "") -> dict:
    """datasets: [{id, name, path}]，path 指向数据集 current.parquet；current_id 对应的表额外注册为 df。"""
    q = (query or "").strip().rstrip(";")
    if not q:
        raise SqlError("SQL 不能为空")
    # 两级只读防护：
    # 1) 语句必须以 SELECT/WITH 开头（覆盖主查询）
    # 2) 分号拼接的每一段都必须是查询（拦截 "SELECT 1; DROP TABLE x"）
    # 不做全文关键字扫描：避免误伤列名/字符串里恰好含 update 等词的合法查询
    for i, seg in enumerate(_split_statements(q)):
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
        if save_as:
            # 建集需要完整结果，只能全量物化（用户显式动作）
            df = con.execute(q).df()
        else:
            # 预览路径：外层包 LIMIT，避免笛卡尔积/巨型聚合把内存打爆
            try:
                df = con.execute(f"SELECT * FROM ({q}) AS _preview LIMIT {MAX_ROWS + 1}").df()
            except duckdb.Error:
                df = con.execute(q).df()  # 极少数语法不支持子查询包装时回退
    except duckdb.Error as e:
        raise SqlError(f"SQL 执行出错：{e}")
    finally:
        con.close()

    from .serialize import cell

    total = len(df)
    # 预览行数封顶（前端表格展示用）；完整结果通过 result["df"] 交给调用方（如 SQL 建集）
    preview = df if total <= MAX_ROWS else df.head(MAX_ROWS)
    logger.info("SQL 执行完成 rows=%d truncated=%s query=%.80s", total, total > MAX_ROWS, q)
    return {
        "columns": [
            {"name": str(c), "numeric": pd.api.types.is_numeric_dtype(preview[c])}
            for c in preview.columns
        ],
        "rows": [[cell(v) for v in row] for row in preview.itertuples(index=False, name=None)],
        "total": total,
        "truncated": total > MAX_ROWS,
        "aliases": aliases,
        "df": df,
    }
