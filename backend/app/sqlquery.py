"""SQL 查询引擎：基于 DuckDB，直接对数据集跑 SQL。

- 所有数据集以 ds1 / ds2 ... 注册（UI 显示别名与真实名称对应关系）
- 当前数据集额外注册为 df，方便快速引用
- 仅允许 SELECT / WITH 开头的查询；结果超过上限自动截断
"""
import re

import duckdb
import pandas as pd

MAX_ROWS = 100_000

# 修改类语句的关键字（用于第二级检查：分号后拼第二条语句）
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|create|drop|alter|attach|detach|copy|export|import|pragma|set|call|vacuum|checkpoint)\b",
    re.IGNORECASE,
)


class SqlError(ValueError):
    pass


def _sanitize(df: pd.DataFrame) -> pd.DataFrame:
    """duckdb 对 object 列里的混合类型较敏感，做一层保守转换。"""
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype) == "str" or out[c].dtype == object:
            out[c] = out[c].astype(str).mask(out[c].isna(), None)
    return out


def run_sql(query: str, datasets: list, current_id: str = "") -> dict:
    """datasets: [{id, name, df}]；current_id 对应的表额外注册为 df。"""
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
            con.register(alias, _sanitize(item["df"]))
            aliases.append({"alias": alias, "id": item["id"], "name": item["name"]})
            if item["id"] == current_id:
                con.register("df", _sanitize(item["df"]))
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
