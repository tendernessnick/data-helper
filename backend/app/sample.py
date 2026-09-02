"""生成示例销售数据（含缺失值与重复行，用于演示清洗功能）。"""
import random
from datetime import date, timedelta

import pandas as pd


def make_sample(n: int = 360) -> pd.DataFrame:
    rng = random.Random(42)
    regions = ["华东", "华南", "华北", "西南", "东北"]
    cats = {
        "办公用品": ["打印纸", "签字笔", "文件夹", "订书机"],
        "电子产品": ["键盘", "鼠标", "显示器", "U盘"],
        "家具": ["办公椅", "书桌", "文件柜", "会议桌"],
    }
    managers = ["张伟", "李娜", "王强", "刘洋", "陈静", "赵磊"]
    start = date(2025, 1, 1)
    rows = []
    for i in range(n):
        cat = rng.choice(list(cats))
        product = rng.choice(cats[cat])
        qty = rng.randint(1, 20)
        price = round(rng.uniform(20, 800), 2)
        d = start + timedelta(days=rng.randint(0, 600))
        rows.append(
            {
                "订单编号": f"SO-{i:05d}",
                "日期": d.isoformat(),
                "地区": rng.choice(regions),
                "产品类别": cat,
                "产品": product,
                "单价": price,
                "数量": qty,
                "销售额": round(price * qty, 2),
                "利润": round(price * qty * rng.uniform(0.05, 0.35), 2),
                "客户经理": rng.choice(managers),
            }
        )
    df = pd.DataFrame(rows)
    # 注入数据质量问题，方便演示清洗能力
    for idx in rng.sample(range(n), 12):
        df.loc[idx, "销售额"] = None
    for idx in rng.sample(range(n), 8):
        df.loc[idx, "地区"] = None
    dup = df.sample(10, random_state=7)
    df = pd.concat([df, dup], ignore_index=True)
    return df.sample(frac=1, random_state=7).reset_index(drop=True)
