"""数据清洗操作。每个函数接收 (df, params)，返回 (新df, 摘要)。失败抛 CleanError。"""
import math
import re

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
            elif method == "interpolate":
                # 时序插值：按现有值线性内插，两端向外延伸；仅数值/日期列适用
                out[c] = out[c].interpolate(limit_direction="both")
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
            # 先数值化（无法解析→空），再四舍五入取整（小数 3.5→4），避免 pandas "cannot safely cast"
            out[column] = pd.to_numeric(df[column], errors="coerce").round().astype("Int64")
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


# ---------------- 列级变换（新增列为主，便于对比与回退） ----------------


def bin_column(df, params):
    """分箱：等宽 / 等频，可自定义标签。默认生成新列 <列>_箱。"""
    column = params.get("column", "")
    method = params.get("method", "equal_width")
    n = int(params.get("bins", 5))
    labels = params.get("labels")
    new_col = (params.get("new_column") or f"{column}_箱").strip()
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if new_col in df.columns:
        raise CleanError(f"新列名 [{new_col}] 已存在")
    if not (2 <= n <= 50):
        raise CleanError("箱数需在 2~50 之间")
    s = pd.to_numeric(df[column], errors="coerce")
    try:
        if method == "equal_freq":
            binned = pd.qcut(s, n, duplicates="drop")
        elif method == "equal_width":
            binned = pd.cut(s, n)
        else:
            raise CleanError("method 仅支持 equal_width / equal_freq")
    except (ValueError, TypeError) as e:
        raise CleanError(f"分箱失败: {e}")
    out = df.copy()
    if labels:
        cats = sorted(binned.dropna().unique(), key=lambda x: x.left if hasattr(x, "left") else x)
        label_map = {cat: str(labels[i]) if i < len(labels) else str(cat) for i, cat in enumerate(cats)}
        out[new_col] = binned.map(label_map)
    else:
        out[new_col] = binned.astype(str).replace("nan", None)
    return out, f"列 [{column}] 分箱为新列 [{new_col}]（{'等频' if method == 'equal_freq' else '等宽'} {n} 箱）"


def one_hot_encode(df, params):
    """独热编码：类别列展开为 0/1 列。"""
    column = params.get("column", "")
    prefix = (params.get("prefix") or column)[:20]
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    vc = df[column].value_counts(dropna=True)
    max_cols = int(params.get("max_columns", 30))
    keep = vc.head(max_cols).index
    out = df.copy()
    made = []
    for v in keep:
        name = f"{prefix}_{v}"[:60]
        if name in out.columns:
            continue
        out[name] = (df[column] == v).astype(int)
        made.append(name)
    if not made:
        raise CleanError("未能生成任何独热列（类别列全为空？）")
    return out, f"列 [{column}] 独热编码生成 {len(made)} 列（超出 {max_cols} 类的值合并忽略）"


def standardize_column(df, params):
    """标准化：Z-score 或 Min-Max，生成新列。"""
    column = params.get("column", "")
    method = params.get("method", "zscore")
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise CleanError(f"列 [{column}] 不是数值列")
    suffix = {"zscore": "_z", "minmax": "_归一"}.get(method)
    if suffix is None:
        raise CleanError("method 仅支持 zscore / minmax")
    new_col = f"{column}{suffix}"
    out = df.copy()
    s = out[column]
    if method == "zscore":
        std = s.std()
        if not std or pd.isna(std):
            raise CleanError("标准差为 0，无法 Z-score 标准化")
        out[new_col] = ((s - s.mean()) / std).round(6)
    else:
        rng = s.max() - s.min()
        if not rng or pd.isna(rng):
            raise CleanError("极差为 0，无法 Min-Max 归一化")
        out[new_col] = ((s - s.min()) / rng).round(6)
    return out, f"列 [{column}] {'Z-score 标准化' if method == 'zscore' else 'Min-Max 归一化'}为新列 [{new_col}]"


def log_transform(df, params):
    """对数变换 log(1+x)，压缩右偏分布；负值列拒绝（可先 shift）。"""
    column = params.get("column", "")
    base = params.get("base", "ln")
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise CleanError(f"列 [{column}] 不是数值列")
    s = pd.to_numeric(df[column], errors="coerce")
    if (s < 0).any():
        raise CleanError("列中存在负值，无法直接对数变换（请先筛选或平移）")
    import numpy as np

    out = df.copy()
    new_col = f"{column}_log"
    if base == "log10":
        out[new_col] = np.log10(s + 1).round(6)
        note = "log10(1+x)"
    else:
        out[new_col] = np.log1p(s).round(6)
        note = "ln(1+x)"
    return out, f"列 [{column}] 对数变换（{note}）为新列 [{new_col}]"


DATE_PARTS = {
    "year": ("年", lambda s: s.dt.year),
    "month": ("月", lambda s: s.dt.month),
    "day": ("日", lambda s: s.dt.day),
    "quarter": ("季度", lambda s: s.dt.quarter),
    "weekday": ("星期", lambda s: s.dt.dayofweek + 1),
    "hour": ("小时", lambda s: s.dt.hour),
}


def extract_date_parts(df, params):
    """从日期列提取 年/月/日/季度/星期/小时 为新列。"""
    column = params.get("column", "")
    parts = params.get("parts") or ["year", "month", "day"]
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    s = df[column]
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, errors="coerce")
    if s.isna().all():
        raise CleanError(f"列 [{column}] 无法解析为日期（请先做类型转换）")
    out = df.copy()
    made = []
    for p in parts:
        if p not in DATE_PARTS:
            continue
        label, fn = DATE_PARTS[p]
        new_col = f"{column}_{label}"
        out[new_col] = fn(s).astype("Int64")
        made.append(new_col)
    if not made:
        raise CleanError("未选择任何要提取的部分")
    return out, f"从列 [{column}] 提取 {len(made)} 个新列: {', '.join(made)}"


def regex_extract(df, params):
    """正则提取：把列中匹配的部分抽为新列。"""
    column = params.get("column", "")
    pattern = params.get("pattern", "")
    new_col = (params.get("new_column") or f"{column}_提取").strip()
    group = int(params.get("group", 0))
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not pattern:
        raise CleanError("正则表达式不能为空")
    if new_col in df.columns:
        raise CleanError(f"新列名 [{new_col}] 已存在")
    import re as _re

    try:
        rx = _re.compile(pattern)
    except _re.error as e:
        raise CleanError(f"正则表达式无效: {e}")
    if group > rx.groups:
        raise CleanError(f"捕获组编号 {group} 超出范围（表达式共 {rx.groups} 组）")
    out = df.copy()
    extracted = out[column].astype(str).str.extract(pattern, expand=False)
    if isinstance(extracted, pd.DataFrame):
        extracted = extracted.iloc[:, min(group, extracted.shape[1] - 1)]
    out[new_col] = extracted
    matched = int(extracted.notna().sum())
    return out, f"列 [{column}] 正则提取为新列 [{new_col}]（匹配 {matched}/{len(out)} 行）"


# ---------------- 文本与格式清洗 ----------------

# 首尾空白字符集合：半角/全角空格、制表符、零宽字符、BOM
_WS_CHARS = " \t\r\n\u3000\u00a0\u200b\u200c\u200d\ufeff"
# 控制字符 + 乱码替换符
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")
# 千分位整数/小数（严格分组建组，避免把 "12,34" 误当数字）
_THOUSAND_RE = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?")
_NUM_RE = re.compile(r"[+-]?(\d+(\.\d+)?|\.\d+)")
_UNIT_MUL = (("亿", 1e8), ("万", 1e4), ("W", 1e4), ("w", 1e4), ("K", 1e3), ("k", 1e3))
_CUR_RE = re.compile(r"[¥￥$€£\s]")
_TRUE_SET = {"是", "true", "yes", "y", "1"}
_FALSE_SET = {"否", "false", "no", "n", "0"}


def to_halfwidth(s: str) -> str:
    """全角转半角：全角空格→空格，FF01-FF5E 区段平移。"""
    out = []
    for ch in s:
        o = ord(ch)
        if o == 0x3000:
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def parse_number_value(v, percent_scale: bool = False) -> float:
    """把单个值智能解析为数字：支持千分位/货币符号/百分号/中文单位(万·亿)/全角数字。
    解析失败返回 nan。体检检测与 parse_number 操作共用此函数，保证口径一致。"""
    nan = float("nan")
    if v is None:
        return nan
    if isinstance(v, bool):
        return nan
    if isinstance(v, str):
        s = to_halfwidth(v).strip()
        if not s:
            return nan
        mult = 1.0
        for unit, m in _UNIT_MUL:
            if s.endswith(unit):
                mult = m
                s = s[: -len(unit)]
                break
        s = _CUR_RE.sub("", s)
        if s.endswith("%"):
            s = s[:-1]
            if percent_scale:
                mult /= 100.0
        if "," in s:
            if not _THOUSAND_RE.fullmatch(s):
                return nan
            s = s.replace(",", "")
        if not _NUM_RE.fullmatch(s):
            return nan
        try:
            return float(s) * mult
        except ValueError:
            return nan
    try:
        f = float(v)
        return f if math.isfinite(f) else nan
    except (TypeError, ValueError):
        return nan


def _text_like(s: pd.Series) -> bool:
    return s.dtype == object or str(s.dtype) in ("str", "string")


def _map_text(s: pd.Series, fn):
    """对文本列逐值变换：保留非字符串值与缺失，仅处理 str 实例。"""
    return s.map(lambda v: fn(v) if isinstance(v, str) else v, na_action="ignore")


def trim_whitespace(df, params):
    """去首尾空白（含全角空格、零宽字符等），列内其他内容不动。"""
    columns = params.get("columns") or []
    if not columns:
        raise CleanError("请选择要去空格的列")
    _check_columns(df, columns)
    out = df.copy()
    n = 0
    for c in columns:
        if not _text_like(out[c]):
            continue
        before = out[c]
        after = _map_text(before, lambda v: v.strip(_WS_CHARS))
        n += int((before.astype("string") != after.astype("string")).sum())
        out[c] = after
    return out, f"去除 {len(columns)} 列的首尾空白（改动 {n} 个值）"


def normalize_text(df, params):
    """文本规范化：全角转半角、去控制/零宽/乱码字符、压缩连续空白为单个空格。
    可选把空字符串转为缺失（empty_to_na）。"""
    columns = params.get("columns") or []
    empty_to_na = bool(params.get("empty_to_na", False))

    def _fn(v: str):
        t = to_halfwidth(v)
        t = _CTRL_RE.sub("", t)
        t = re.sub(r"\s+", " ", t).strip(_WS_CHARS)
        if empty_to_na and t == "":
            return None
        return t

    if not columns:
        raise CleanError("请选择要规范化的列")
    _check_columns(df, columns)
    out = df.copy()
    for c in columns:
        if not _text_like(out[c]):
            continue
        out[c] = _map_text(out[c], _fn)
    return out, (
        f"规范化 {len(columns)} 列文本（全角→半角、去控制字符、压缩空白"
        + ("、空字符串→缺失" if empty_to_na else "")
        + "）"
    )


def parse_number(df, params):
    """智能数值解析：把 '1,234' / '¥100' / '12%' / '1.5万' / 全角数字等解析为数值列。"""
    column = params.get("column", "")
    percent_scale = bool(params.get("percent_scale", False))
    new_col = (params.get("new_column") or f"{column}_数值").strip()
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not new_col:
        new_col = column
    out = df.copy()
    parsed = out[column].map(lambda v: parse_number_value(v, percent_scale))
    out[new_col] = parsed.astype("float64")
    ok = int(parsed.notna().sum())
    total = int(out[column].notna().sum())
    if ok == 0:
        raise CleanError(f"列 [{column}] 没有任何值能解析为数字")
    target = f"新列 [{new_col}]" if new_col != column else "原列（覆盖）"
    return out, f"列 [{column}] 数值解析 → {target}（成功 {ok}/{total}）"


def map_values(df, params):
    """值映射：按字典替换列中的取值（类别标准化），未命中的值可保留或置为缺失。"""
    column = params.get("column", "")
    mapping = params.get("mapping") or {}
    keep_original = bool(params.get("keep_original", True))
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not mapping:
        raise CleanError("映射字典为空")
    out = df.copy()
    keys = {k: v for k, v in mapping.items()}

    def _fn(v):
        try:
            if v in keys:
                return keys[v]
            if str(v) in keys:
                return keys[str(v)]
        except TypeError:  # 不可哈希单元格（list 等）直接走未命中分支
            pass
        return v if keep_original else None

    before = out[column]
    after = before.map(_fn, na_action="ignore")
    hits = before.astype("string").ne(after.astype("string")).sum()
    out[column] = after
    return out, f"列 [{column}] 值映射（命中 {int(hits)} 个，未命中{'保留原值' if keep_original else '置为缺失'}）"


def split_column(df, params):
    """按分隔符拆分列：一列拆为多列（如 '省-市' → 两列）。"""
    column = params.get("column", "")
    sep = params.get("sep", "")
    into = params.get("into") or []
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")
    if not sep:
        raise CleanError("分隔符不能为空")
    out = df.copy()
    parts = out[column].astype("string").str.split(sep, expand=True, regex=False)
    if isinstance(parts, pd.Series):
        parts = parts.to_frame()
    n = parts.shape[1]
    names = [str(x) for x in into[:n]] or [f"{column}_{i + 1}" for i in range(n)]
    while len(names) < n:
        names.append(f"{column}_{len(names) + 1}")
    for nm in names:
        if nm in df.columns and nm != column:
            raise CleanError(f"新列名 [{nm}] 已存在")
    for i, nm in enumerate(names):
        out[nm] = parts[i]
    return out, f"列 [{column}] 按 [{sep}] 拆分为 {n} 列: {', '.join(names)}"


def cap_outliers(df, params):
    """异常值盖帽（不删行）：超出上下界的值截断到边界。"""
    columns = params.get("columns") or []
    method = params.get("method", "iqr")
    if not columns:
        raise CleanError("请选择要盖帽的数值列")
    _check_columns(df, columns)
    from .analysis import outlier_bounds

    out = df.copy()
    capped = 0
    for c in columns:
        if not pd.api.types.is_numeric_dtype(out[c]):
            raise CleanError(f"列 [{c}] 不是数值列")
        if method == "zscore":
            s2 = out[c].dropna()
            if s2.empty:
                continue
            mean, std = float(s2.mean()), float(s2.std(ddof=0))
            if std == 0:
                continue
            lower, upper = mean - 3 * std, mean + 3 * std
        elif method == "iqr":
            lower, upper, _ = outlier_bounds(out[c], "iqr")
            if lower is None:
                continue
        else:
            raise CleanError("method 仅支持 iqr / zscore")
        _, _, mask = outlier_bounds(out[c], method)
        capped += int(mask.fillna(False).sum())
        out[c] = out[c].clip(lower, upper)
    return out, f"盖帽 {len(columns)} 列异常值（共 {capped} 个值截断到边界，未删除任何行）"


def drop_high_missing(df, params):
    """按缺失率删除列（默认）或行：缺失率高于阈值的整列/整行删除。"""
    threshold = float(params.get("threshold", 0.5))
    axis = params.get("axis", "column")
    if not (0 < threshold <= 1):
        raise CleanError("阈值需在 (0, 1] 之间")
    if axis == "row":
        keep = df.isna().mean(axis=1) <= threshold
        removed = int((~keep).sum())
        out = df[keep].reset_index(drop=True)
        return out, f"删除缺失率超 {threshold:.0%} 的行 {removed} 行"
    cols = [c for c in df.columns if df[c].isna().mean() > threshold]
    if len(cols) == df.shape[1]:
        raise CleanError("所有列的缺失率都超过阈值，已取消操作")
    out = df.drop(columns=cols)
    return out, f"删除缺失率超 {threshold:.0%} 的列: {', '.join(map(str, cols)) or '无'}"


def unify_boolean_text(df, params):
    """布尔语义列统一：把 true/false/yes/no/1/0/是/否 等统一为 是/否。"""
    column = params.get("column", "")
    if column not in df.columns:
        raise CleanError(f"列不存在: {column}")

    def _fn(v):
        if isinstance(v, str):
            low = v.strip().lower()
            if low in _TRUE_SET:
                return "是"
            if low in _FALSE_SET:
                return "否"
        elif isinstance(v, bool):
            return "是" if v else "否"
        return v

    out = df.copy()
    before = out[column]
    out[column] = before.map(_fn, na_action="ignore")
    changed = int(before.astype("string").ne(out[column].astype("string")).sum())
    return out, f"列 [{column}] 布尔语义统一为 是/否（改动 {changed} 个值）"




OPS = {
    "drop_duplicates": drop_duplicates,
    "drop_missing": drop_missing,
    "fill_missing": fill_missing,
    "rename_columns": rename_columns,
    "cast_type": cast_type,
    "filter_rows": filter_rows,
    "drop_columns": drop_columns,
    "drop_outliers": drop_outliers,
    "bin_column": bin_column,
    "one_hot_encode": one_hot_encode,
    "standardize_column": standardize_column,
    "log_transform": log_transform,
    "extract_date_parts": extract_date_parts,
    "regex_extract": regex_extract,
    "trim_whitespace": trim_whitespace,
    "normalize_text": normalize_text,
    "parse_number": parse_number,
    "map_values": map_values,
    "split_column": split_column,
    "cap_outliers": cap_outliers,
    "drop_high_missing": drop_high_missing,
    "unify_boolean_text": unify_boolean_text,
}



def apply_op(df: pd.DataFrame, op: str, params: dict):
    if op not in OPS:
        raise CleanError(f"未知操作: {op}")
    return OPS[op](df, params or {})
