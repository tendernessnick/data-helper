"""采样：随机 / 分层 / 前 N 行，采样结果可另建数据集。"""
import pandas as pd

from .analysis import AnalysisError


def sample_create(df: pd.DataFrame, method: str, n: int, by: str = "", seed: int = 42) -> pd.DataFrame:
    """采样：随机 / 分层 / 前 N 行。返回采样后的 df。"""
    n = max(1, int(n))
    if method == "top":
        return df.head(n)
    if method == "random":
        if n >= len(df):
            return df
        return df.sample(n=n, random_state=seed).reset_index(drop=True)
    if method == "stratified":
        if not by:
            raise AnalysisError("分层采样需要指定分层列")
        if by not in df.columns:
            raise AnalysisError(f"列不存在: {by}")
        # 显式按组采样后拼接（不用 groupby.apply：pandas3 默认丢弃分组列）
        picked = []
        for _, g in df.groupby(by, dropna=False, sort=False):
            picked.append(g.sample(n=min(n, len(g)), random_state=seed))
        out = pd.concat(picked).reset_index(drop=True)
        return out
    raise AnalysisError("method 仅支持 random / stratified / top")
