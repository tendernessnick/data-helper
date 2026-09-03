"""数据清洗操作。每个函数接收 (df, params)，返回 (新df, 摘要)。失败抛 CleanError。"""
import pandas as pd


class CleanError(ValueError):
    pass


def _check_columns(df, columns):
    unknown = [c for c in columns if c not in df.columns]
    if unknown:
        raise CleanError(f"列不存在: {unknown}")


def drop_duplicates(df, params):
    subset = params.get("columns") or None
    before = len(df)
    out = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
    n = before - len(out)
    label = f"（按列 {', '.join(subset)}）" if subset else ""
    return out, f"删除重复行 {n} 行{label}"


def drop_missing(df, params):
    columns = params.get("columns") or None
    how = params.get("how", "any")
    _check_columns(df, columns or [])
    before = len(df)
    out = df.dropna(axis=0, subset=columns, how=how).reset_index(drop=True)
    return out, f"删除含缺失值的行 {before - len(out)} 行（方式: {how}）"


def fill_missing(df, params):
    columns = params.get("columns") or list(df.columns)
    _check_columns(df, columns)
    method = params.get("method", "constant")
    value = params.get("value")
    out = df.copy()
    filled = 0
    for c in columns:
        na = int(out[c].isna().sum())
        if na == 0:
            continue
        try:
            if method == "constant":
                if value is None:
                    raise CleanError("常数填充需要提供填充值")
                out[c] = out[c].fillna(value)
            elif method == "mean":
                m = out[c].mean()
                out[c] = out[c].fillna(m)
            elif method == "median":
                m = out[c].median()
                out[c] = out[c].fillna(m)
            elif method == "mode":
                mode = out[c].mode()
                if len(mode) == 0:
                    continue
                out[c] = out[c].fillna(mode.iloc[0])
            elif method == "ffill":
                out[c] = out[c].ffill()
            elif method == "bfill":
                out[c] = out[c].bfill()
            else:
                raise CleanError(f"未知填充方式: {method}")
        except (TypeError, ValueError) as e:
            raise CleanError(f"列 [{c}] 无法用方式 [{method}] 填充: {e}")
        filled += na
    return out, f"填充缺失值 {filled} 个（方式: {method}，涉及 {len(columns)} 列）"


def rename_columns(df, params):
    mapping = params.get("mapping") or {}
    if not mapping:
        raise CleanError("重命名映射为空")
    _check_columns(df, list(mapping))
    targets = [str(v) for v in mapping.values()]
    if len(set(targets)) != len(targets):
        raise CleanError("目标列名存在重复")
    out = df.rename(columns=mapping)
    return out, f"重命名 {len(mapping)} 列"


def cast_type(df, params):
    column = params.get("column")
    to = params.get("to")
    fmt = params.get("format") or None
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    out = df.copy()
    try:
        if to == "int":
            out[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
        elif to == "float":
            out[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")
        elif to == "str":
            s = df[column]
            out[column] = s.astype(str).mask(s.isna(), None)
        elif to == "datetime":
            out[column] = pd.to_datetime(df[column], errors="coerce", format=fmt)
        else:
            raise CleanError(f"未知目标类型: {to}")
    except (ValueError, TypeError) as e:
        raise CleanError(f"列 [{column}] 转换失败: {e}")
    bad = int(out[column].isna().sum() - df[column].isna().sum())
    note = f"（{bad} 个无法解析的值变为空值）" if bad > 0 else ""
    return out, f"列 [{column}] 转为 {to}{note}"


def filter_rows(df, params):
    column, op, value = params.get("column"), params.get("op"), params.get("value")
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    s = df[column]
    if op not in ("isnull", "notnull"):
        # 数值列与字符串值比较前做一次宽容转换
        if pd.api.types.is_numeric_dtype(s) and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass
    if op == "isnull":
        mask = s.isna()
    elif op == "notnull":
        mask = s.notna()
    else:
        try:
            if op == "gt":
                mask = s > value
            elif op == "ge":
                mask = s >= value
            elif op == "lt":
                mask = s < value
            elif op == "le":
                mask = s <= value
            elif op == "eq":
                mask = s == value
            elif op == "ne":
                mask = s != value
            elif op == "contains":
                mask = s.astype(str).str.contains(str(value), case=False, na=False, regex=False)
            elif op == "startswith":
                mask = s.astype(str).str.startswith(str(value), na=False)
            elif op == "between":
                if not (isinstance(value, list) and len(value) == 2):
                    raise CleanError("between 需要 [最小值, 最大值] 两个参数")
                mask = s.between(value[0], value[1])
            elif op == "isin":
                values = value if isinstance(value, list) else [value]
                mask = s.isin(values)
            else:
                raise CleanError(f"未知筛选操作: {op}")
        except TypeError as e:
            raise CleanError(f"筛选值类型与列类型不匹配: {e}")
    out = df[mask].reset_index(drop=True)
    if out.empty:
        raise CleanError("筛选结果为 0 行，已取消操作（请调整条件）")
    return out, f"筛选 [{column} {op} {value}]，保留 {len(out)}/{len(df)} 行"


def drop_columns(df, params):
    columns = params.get("columns") or []
    if not columns:
        raise CleanError("未选择要删除的列")
    _check_columns(df, columns)
    out = df.drop(columns=columns)
    return out, f"删除列: {', '.join(map(str, columns))}"


def drop_outliers(df, params):
    """按 IQR 边界剔除数值列的异常值行。"""
    columns = params.get("columns") or []
    method = params.get("method", "iqr")
    if not columns:
        raise CleanError("请选择要检测异常值的数值列")
    _check_columns(df, columns)
    from .analysis import outlier_bounds

    mask = pd.Series(False, index=df.index)
    for c in columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise CleanError(f"列 [{c}] 不是数值列")
        _, _, m = outlier_bounds(df[c], method)
        mask |= m.fillna(False)
    before = len(df)
    out = df[~mask].reset_index(drop=True)
    if out.empty:
        raise CleanError("剔除异常值后结果为 0 行，已取消操作")
    removed = before - len(out)
    return out, f"剔除异常值行 {removed} 行（{ 'IQR' if method == 'iqr' else 'Z-score' }，涉及列: {', '.join(map(str, columns))}）"


OPS = {
    "drop_duplicates": drop_duplicates,
    "drop_missing": drop_missing,
    "fill_missing": fill_missing,
    "rename_columns": rename_columns,
    "cast_type": cast_type,
    "filter_rows": filter_rows,
    "drop_columns": drop_columns,
    "drop_outliers": drop_outliers,
}


def apply_op(df: pd.DataFrame, op: str, params: dict):
    if op not in OPS:
        raise CleanError(f"未知操作: {op}")
    return OPS[op](df, params or {})
