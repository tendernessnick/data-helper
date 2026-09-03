"""阶段10（D包）：一键本地洞察 / HTML 报告。"""
from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def setup_sales():
    rows = []
    for i in range(120):
        month = 1 + i % 12
        rows.append(
            {
                "日期": (date(2025, month, 1 + i % 27)).isoformat(),
                "地区": ["华东", "华南", "华北"][i % 3],
                "销售额": 1000 + i * 10 + (5000 if i == 119 else 0),  # 末尾放一个离群值
                "数量": i + 1,
            }
        )
    # 加重复行
    rows.append(dict(rows[0]))
    csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
    r = client.post("/api/upload", files={"file": ("t.csv", csv, "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_insights_structure_and_rules():
    ds = setup_sales()
    r = client.get(f"/api/datasets/{ds}/insights")
    assert r.status_code == 200
    body = r.json()
    ov = body["overview"]
    assert ov["rows"] == 121 and ov["duplicates"] == 1
    # 数值列画像：销售额有离群
    sales = next(x for x in body["numeric"] if x["name"] == "销售额")
    assert sales["outliers"] >= 1
    # 类别列：地区 top 占比约 1/3
    region = next(x for x in body["categorical"] if x["name"] == "地区")
    assert 20 < region["top_share"] < 50
    # 时间趋势存在且方向合理（销售额随 i 增长 → 上行）
    assert body["datetime"] is not None
    assert body["datetime"]["value_column"] == "销售额"
    assert body["datetime"]["direction"] in ("上升", "下降", "波动")
    # 相关性：销售额 与 数量 强相关
    pairs = {(p["a"], p["b"]) for p in body["correlations"]}
    assert ("数量", "销售额") in pairs or ("销售额", "数量") in pairs
    # 告警里提到重复
    assert any("重复" in a for a in body["alerts"])


def test_insights_empty_quality_ok():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
    r = client.post("/api/upload", files={"file": ("t.csv", df.to_csv(index=False).encode(), "text/csv")}, data={"name": ""})
    ds = r.json()["id"]
    body = client.get(f"/api/datasets/{ds}/insights").json()
    assert any("未发现明显数据质量问题" in a for a in body["alerts"])


def test_report_html():
    ds = setup_sales()
    r = client.post(f"/api/datasets/{ds}/report")
    assert r.status_code == 200
    html = r.content.decode("utf-8")
    # 自包含：内嵌 echarts、包含洞察与图表容器
    assert "echarts" in html
    assert "关键发现" in html and "数值列概览" in html
    assert "id='hist_" in html  # 数值分布图存在
    assert "setOption" in html
    # 恶意字符转义安全（数据集名注入）
    assert "<script>alert" not in html
