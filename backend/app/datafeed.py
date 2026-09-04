"""在线行情数据源（akshare，可选依赖）。

懒导入：未安装/断网时返回友好错误而非崩溃。
所有 akshare 返回统一做列名归一化 + 日期升序。
"""
import concurrent.futures
import logging

import pandas as pd

logger = logging.getLogger(__name__)

AK_TIMEOUT_SECONDS = 60  # akshare 内部 requests 多数无超时，挂起会占死 worker 线程

# 常用指数（akshare index_zh_a_hist 的 symbol）
INDEX_SOURCES = [
    {"symbol": "000001", "name": "上证指数"},
    {"symbol": "399001", "name": "深证成指"},
    {"symbol": "399006", "name": "创业板指"},
    {"symbol": "000300", "name": "沪深300"},
    {"symbol": "000905", "name": "中证500"},
    {"symbol": "000852", "name": "中证1000"},
]

FREQ_MAP = {"D": "daily", "W": "weekly", "M": "monthly"}


class FeedError(ValueError):
    pass


class _TimeoutExceeded(Exception):
    pass


def _with_timeout(fn):
    """akshare 内部 requests 多无超时：用独立线程 + 等待超时兜底。

    超时后底层线程无法被杀（Python 线程限制），会随进程退出回收；
    至少 API 请求能及时返回错误，不再无限占用 worker。
    """
    def wrapper(*args, **kwargs):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(fn, *args, **kwargs)
            try:
                return fut.result(timeout=AK_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                raise _TimeoutExceeded(fn.__name__)
    return wrapper


def _import_ak():
    try:
        import akshare as ak

        return ak
    except ImportError:
        raise FeedError(
            "未安装 akshare（开源财经数据库）。开发模式请在虚拟环境执行: "
            "pip install akshare；exe 版本如未内置则该功能不可用，可用「导入文件」上传老师提供的数据"
        )


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # 只保留行情相关列，避免接口附加列（换手率等）干扰识别
    keep = [c for c in df.columns if c in ("日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "股票代码")]
    if keep:
        df = df[keep]
    if "日期" in df.columns:
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df.dropna(subset=["日期"]).sort_values("日期").reset_index(drop=True)
        df["日期"] = df["日期"].dt.strftime("%Y-%m-%d")
    for c in df.columns:
        if c != "日期" and c != "股票代码":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _sina_symbol(symbol: str) -> str:
    if symbol.startswith(("0", "2", "3")):
        return f"sz{symbol}"
    if symbol.startswith(("4", "8")):  # 北交所（新浪不支持时由上层报错兜底）
        return f"bj{symbol}"
    return f"sh{symbol}"  # 6/9 开头（含科创板 688/689）


def fetch_stock(symbol: str, start: str, end: str, period: str = "D", adjust: str = "qfq") -> pd.DataFrame:
    """A 股个股历史行情。symbol 如 600519；period D/W/M；adjust qfq/hfq/none。
    主源东方财富，失败时自动降级新浪。"""
    ak = _import_ak()
    symbol = "".join(ch for ch in str(symbol) if ch.isdigit())
    if not (6 >= len(symbol) >= 4):
        raise FeedError("股票代码格式不对，示例：600519 / 000001 / 300750")
    df = None
    try:
        df = _with_timeout(ak.stock_zh_a_hist)(
            symbol=symbol,
            period=FREQ_MAP.get(period, "daily"),
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="" if adjust == "none" else adjust,
        )
    except _TimeoutExceeded:
        raise FeedError(f"行情源响应超过 {AK_TIMEOUT_SECONDS} 秒（东财），请稍后重试")
    except Exception as e:
        logger.warning("东财行情源失败，降级新浪：%s", e)
        df = None  # 东财不可达 → 试新浪
    if df is not None and not df.empty:
        return _normalize(df)
    # 降级：新浪源（英文列名，仅日线）
    try:
        sina = _with_timeout(ak.stock_zh_a_daily)(
            symbol=_sina_symbol(symbol),
            start_date=pd.to_datetime(start),
            end_date=pd.to_datetime(end),
            adjust=adjust if adjust != "none" else "",
        )
        if sina is None or sina.empty:
            raise FeedError(f"未取到 {symbol} 在该区间的行情（检查代码与日期）")
        rename = {"date": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量", "amount": "成交额"}
        sina = sina.rename(columns={k: v for k, v in rename.items() if k in sina.columns})
        return _normalize(sina)
    except FeedError:
        raise
    except Exception as e:
        raise FeedError(f"获取个股行情失败（东财与新浪均不可用）：{str(e)[:120]}（检查网络或代码）")


def fetch_index(symbol: str, start: str, end: str, period: str = "D") -> pd.DataFrame:
    """A 股指数历史行情。symbol 如 000001(上证)/000300(沪深300)。"""
    ak = _import_ak()
    symbol = "".join(ch for ch in str(symbol) if ch.isdigit())
    try:
        df = _with_timeout(ak.index_zh_a_hist)(
            symbol=symbol,
            period=FREQ_MAP.get(period, "daily"),
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
    except _TimeoutExceeded:
        raise FeedError(f"行情源响应超过 {AK_TIMEOUT_SECONDS} 秒，请稍后重试")
    except Exception as e:
        raise FeedError(f"获取指数行情失败：{str(e)[:150]}（检查代码或网络）")
    if df is None or df.empty:
        raise FeedError(f"未取到指数 {symbol} 的行情数据")
    return _normalize(df)


def search_hot(search: str) -> list:
    """按关键字搜股票代码（本地热门表 + akshare spot 实时表兜底）。"""
    ak = _import_ak()
    kw = (search or "").strip()
    if not kw:
        return []
    try:
        spot = _with_timeout(ak.stock_zh_a_spot_em)()
        if spot is None or spot.empty:
            return []
        col_code = next((c for c in spot.columns if "代码" in str(c)), None)
        col_name = next((c for c in spot.columns if "名称" in str(c)), None)
        if not col_code or not col_name:
            return []
        hit = spot[spot[col_code].astype(str).str.contains(kw, regex=False) | spot[col_name].astype(str).str.contains(kw, case=False, regex=False)]  # 关键字按字面匹配，元字符不当正则
        return [{"code": str(r[col_code]), "name": str(r[col_name])} for _, r in hit.head(15).iterrows()]
    except _TimeoutExceeded:
        raise FeedError(f"实时行情表响应超过 {AK_TIMEOUT_SECONDS} 秒，请稍后重试")
    except Exception as e:
        raise FeedError(f"搜索失败：{str(e)[:120]}")
