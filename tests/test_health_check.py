"""数据体检中心：规则命中 / 干净数据放行 / 修复建议可执行。"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import cleaning, insights
from backend.app.main import app

client = TestClient(app)

VALID_LEVELS = {"error", "warn", "info"}
VALID_CATEGORIES = {"structure", "missing", "type", "text", "category", "numeric", "datetime", "consistency"}


def upload_df(df, name="体检"):
    raw = df.to_csv(index=False).encode("utf-8-sig")
    r = client.post("/api/upload", files={"file": (f"{name}.csv", raw, "text/csv")}, data={"name": ""})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def dirty_df():
    """各行各业的典型脏数据：格式数字/空格/同义标签/日期混乱/未来日期/负值/离群/空列/重复行。"""
    return pd.DataFrame({
        "订单号": ["A001", "A002", "A003", "A004", "A005", "A006", "A007", "A008", "A009", "A010", "A011", "A012", "A001"],
        "日期": ["2024-01-01", "2024/01/15", "2024-02-01", "2024-02-20", "2024/03/05", "2024-03-15",
                "2024-04-01", "2024-04-15", "2024-05-01", "2024-05-20", "2024-06-01", "2099-01-01", "2024-01-01"],
        "金额": ["¥1,200", "980", "1.5万", "12%", "8,800", "2,300", "1,100", "950", "1,350", "1,080", "1,200", "1,000", "¥1,200"],
        "数量": [10, -5, 8, 6, 12, 9, 11, 7, 10, 8, 9, 1000, 10],
        "城市": ["北京", "北京 ", "SHANGHAI", "shanghai", "广州", "深圳", "杭州", "北京", "广州", "深圳", "杭州", "北京", "北京"],
        "是否会员": ["是", "true", "0", "否", "yes", "N", "false", "1", "是", "否", "Y", "no", "是"],
        "备注": ["正常", " 文", None, "OK", "　全角", "正常", "正常", "OK", "正常", "好", "正常", "复核", "正常"],
        "空列": [None] * 13,
    })


def msgs_of(result, category=None):
    return [f["msg"] for f in result["findings"] if category is None or f["category"] == category]


def test_dirty_data_rules_fire():
    r = insights.run_insights(dirty_df(), {})
    msgs = r["findings"] and [f["msg"] for f in r["findings"]]
    joined = " | ".join(msgs)
    # 结构：重复行 + 空列
    assert "完全重复" in joined and "整列为空" in joined
    # 类型：格式数字 + 混合日期格式 + 日期文本
    assert "带格式数字" in joined and "日期格式不统一" in joined and "日期列" in joined
    # 文本：首尾空格
    assert "首尾空格" in joined
    # 类别：同义标签 + 布尔语义
    assert "同义标签" in joined and "布尔语义" in joined
    # 数值：离群 + 负值
    assert "离群值" in joined and "负值" in joined
    # 日期：未来日期
    assert "未来日期" in joined


def test_finding_fields_valid():
    r = insights.run_insights(dirty_df(), {})
    assert r["findings"], "脏数据应有 findings"
    for f in r["findings"]:
        assert f["level"] in VALID_LEVELS, f
        assert f["category"] in VALID_CATEGORIES, f
        assert isinstance(f["msg"], str) and f["msg"]
        assert f["fix"] is None or (f["fix"]["op"] in cleaning.OPS and f["fix"]["label"])
    # error 优先于 warn/info 排序
    levels = [f["level"] for f in r["findings"]]
    order = {"error": 0, "warn": 1, "info": 2}
    assert levels == sorted(levels, key=lambda x: order[x])


def test_clean_data_passes():
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "b": ["x", "y", "z", "x", "y", "z"],
        "d": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01", "2024-06-01"]),
    })
    r = insights.run_insights(df, {})
    bad = [f for f in r["findings"] if f["level"] in ("error", "warn")]
    assert bad == [], f"干净数据不应有严重问题: {[f['msg'] for f in bad]}"
    assert r["quality_score"]["score"] == 100
    assert any("未发现明显数据质量问题" in a for a in r["alerts"])


def test_all_fix_suggestions_executable():
    """一键修复契约：体检给出的每个 fix 都能被清洗引擎真实执行。"""
    df = dirty_df()
    r = insights.run_insights(df, {})
    fixes = [f["fix"] for f in r["findings"] if f["fix"]]
    assert fixes, "脏数据应至少有一条带修复建议的问题"
    for fix in fixes:
        out, msg = cleaning.apply_op(df, fix["op"], fix["params"])
        assert out is not None and msg, fix


def test_quality_score_deductions():
    r = insights.run_insights(dirty_df(), {})
    assert r["quality_score"]["score"] < 100
    assert r["quality_score"]["deductions"], "脏数据应有扣分明细"
    assert r["quality_score"]["level"] in ("优秀", "良好", "一般", "较差")


def test_column_name_whitespace_and_rename_fix():
    df = pd.DataFrame({" 名字": ["a", "b", "c"], "年龄": [1, 2, 3]})
    r = insights.run_insights(df, {})
    assert any("列名含首尾空白" in f["msg"] for f in r["findings"])
    fix = next(f["fix"] for f in r["findings"] if f["fix"] and f["fix"]["op"] == "rename_columns")
    out, _ = cleaning.apply_op(df, fix["op"], fix["params"])
    assert list(out.columns) == ["名字", "年龄"]


def test_mixed_type_column_detected():
    df = pd.DataFrame({"v": ["10", "20", "abc", "30", "40", "def", "50", "60"]})
    r = insights.run_insights(df, {})
    assert any("混合类型" in f["msg"] for f in r["findings"])


def test_numeric_text_column_cast_suggestion():
    df = pd.DataFrame({"v": ["10", "20", "30", "40", "50", "60"]})
    r = insights.run_insights(df, {})
    fix = [f["fix"] for f in r["findings"] if f["fix"] and f["fix"]["op"] == "cast_type"]
    assert fix and fix[0]["params"]["to"] == "float"


def test_empty_string_vs_missing():
    df = pd.DataFrame({"v": ["a", "b", "", "  ", "c", "d"]})
    r = insights.run_insights(df, {})
    assert any("空字符串" in f["msg"] for f in r["findings"])


def test_synonym_mapping_fix_merges():
    df = pd.DataFrame({"城市": ["北京", "北京 ", "SH", "sh", "京", "沪"] * 2})
    r = insights.run_insights(df, {})
    fix = next((f["fix"] for f in r["findings"] if f["fix"] and f["fix"]["op"] == "map_values"), None)
    assert fix, "同义标签应给 map_values 修复"
    out, _ = cleaning.apply_op(df, "map_values", fix["params"])
    # 6 个写法（北京/北京 /SH/sh/京/沪）合并后只剩 4 个
    assert out["城市"].nunique() == 4
    assert "北京 " not in set(out["城市"])


def test_high_missing_column_suggests_drop():
    df = pd.DataFrame({"keep": [1, 2, 3, 4, 5, 6], "bad": [1, None, None, None, None, None]})
    r = insights.run_insights(df, {})
    assert any("缺失超 50%" in f["msg"] for f in r["findings"])


def test_api_endpoint_returns_findings():
    ds = upload_df(dirty_df())
    r = client.get(f"/api/datasets/{ds}/insights")
    assert r.status_code == 200
    body = r.json()
    assert body["findings"] and body["overview"]["rows"] == 13
    assert 0 <= body["quality_score"]["score"] <= 100


def test_fullwidth_digits_detected():
    df = pd.DataFrame({"v": ["１２３", "４５６", "abc", "def", "x", "y"]})
    r = insights.run_insights(df, {})
    assert any("全角" in f["msg"] for f in r["findings"])


def test_findings_capped_and_sorted():
    # 100 列各带一个首尾空格问题：超过上限触发截断，且排序保持 error→warn→info
    cols = {f"c{i:03d}": [" a", "b", "c", "d", "e", "f"] for i in range(100)}
    r = insights.run_insights(pd.DataFrame(cols), {})
    assert len(r["findings"]) <= insights.MAX_FINDINGS
    assert r["findings_truncated"] >= 1
    order = {"error": 0, "warn": 1, "info": 2}
    levels = [f["level"] for f in r["findings"]]
    assert levels == sorted(levels, key=lambda x: order[x])


@pytest.mark.parametrize("category,keyword", [
    ("type", "格式数字"),
    ("text", "空格"),
    ("category", "同义"),
    ("numeric", "离群"),
    ("datetime", "未来"),
    ("structure", "重复"),
])
def test_categories_covered(category, keyword):
    r = insights.run_insights(dirty_df(), {})
    assert any(f["category"] == category and keyword in f["msg"] for f in r["findings"]), category


# ---------------- v4.4 深化：列间关系 / 格式语义 / 数值粒度 / 时序 / 六维雷达 ----------------


def test_arithmetic_violation_rows_detected():
    """数量×单价≈金额 的关系发现 + 违反行报告（一致性类核心能力）。"""
    n = 100
    df = pd.DataFrame({
        "数量": [3] * n,
        "单价": [10.0] * n,
        "金额": [30.0] * n,
        "id": range(n),  # 第 4 个数值列参与组合但不构成关系
    })
    df.loc[0, "金额"] = 35.0
    df.loc[1, "金额"] = 13.0
    r = insights.run_insights(df, {})
    hits = [f for f in r["findings"] if "列间关系" in f["msg"]]
    assert hits, "应发现算术关系"
    assert any("2 行不满足" in f["msg"] for f in hits)
    assert all(f["category"] == "consistency" for f in hits)
    assert any(f["samples"] for f in hits), "违反行应有样本证据"


def test_arithmetic_consistent_reports_info_only():
    """关系成立且无违反：作为正面洞察（info），不产生 warn。"""
    n = 100
    df = pd.DataFrame({"数量": [2.0] * n, "单价": [5.0] * n, "金额": [10.0] * n})
    r = insights.run_insights(df, {})
    hits = [f for f in r["findings"] if "列间关系" in f["msg"]]
    assert hits and all(f["level"] == "info" for f in hits)


def test_functional_dependency_conflict():
    """同键不同值（订单号→城市）应报函数依赖冲突。"""
    n = 60
    df = pd.DataFrame({
        "订单号": [f"SO{i:03d}" for i in range(n)],
        "城市": ["北京"] * n,
        "金额": [10.0] * n,
    })
    df.loc[n - 1, "订单号"] = "SO000"  # 最后一行与第一行同单号但城市不同
    df.loc[n - 1, "城市"] = "上海"
    r = insights.run_insights(df, {})
    assert any("近似决定" in f["msg"] and "城市" in f["msg"] for f in r["findings"])
    hit = next(f for f in r["findings"] if "近似决定" in f["msg"])
    assert hit["category"] == "consistency" and hit["samples"]


def test_phone_format_violations():
    df = pd.DataFrame({
        "手机号": ["13812345678"] * 40 + ["1381234", "abc", "12345678901", "139001390009"],
        "v": range(44),
    })
    r = insights.run_insights(df, {})
    assert any("疑似手机号列" in f["msg"] and "不符合" in f["msg"] for f in r["findings"])


def test_email_format_column():
    df = pd.DataFrame({
        "邮箱": [f"user{i}@ex.com" for i in range(40)] + ["bad-email", "x@y@z", "no-at-sign"],
        "v": range(43),
    })
    r = insights.run_insights(df, {})
    assert any("疑似邮箱列" in f["msg"] for f in r["findings"])


def test_value_length_anomaly():
    df = pd.DataFrame({
        "编码": [f"AB{i:04d}" for i in range(60)] + ["AB0001-EXTRA-LONG-VALUE-PADDED", "AB"],
        "v": range(62),
    })
    r = insights.run_insights(df, {})
    assert any("长度显著偏离" in f["msg"] for f in r["findings"])


def test_decimal_granularity_anomaly():
    vals = [round(10.0 + i * 0.1, 2) for i in range(200)]  # 常见 1~2 位小数
    vals[0] = 10.123456
    vals[1] = 11.654321
    df = pd.DataFrame({"金额": vals})
    r = insights.run_insights(df, {})
    assert any("精度更高" in f["msg"] or "常见精度" in f["msg"] for f in r["findings"])


def test_magnitude_gap_detected():
    vals = [100.0 + i for i in range(200)]
    vals[0] = 5_000_000.0
    vals[1] = 8_000_000.0
    vals[2] = 0.001
    df = pd.DataFrame({"价格": vals})
    r = insights.run_insights(df, {})
    assert any("数量级" in f["msg"] for f in r["findings"])


def test_time_gap_detected_for_daily_series():
    dates = pd.date_range("2026-01-01", periods=60, freq="D").delete(range(20, 40))
    df = pd.DataFrame({"日期": dates, "值": range(len(dates))})
    r = insights.run_insights(df, {})
    assert any("时间覆盖有缺口" in f["msg"] for f in r["findings"])


def test_monthly_series_no_gap_false_positive():
    """月度数据不该被误报缺口（中位间隔守卫）。"""
    dates = pd.date_range("2024-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"日期": dates, "值": range(12)})
    r = insights.run_insights(df, {})
    assert not any("缺口" in f["msg"] for f in r["findings"])


def test_quality_dims_structure():
    r = insights.run_insights(dirty_df(), {})
    dims = r["quality_dims"]
    assert [d["key"] for d in dims] == ["completeness", "uniqueness", "consistency", "validity", "timeliness", "structure"]
    for d in dims:
        assert d["score"] is None or 0 <= d["score"] <= 100
    # 脏数据：完整性与唯一性应被扣分
    by = {d["key"]: d["score"] for d in dims}
    assert by["completeness"] < 100 and by["uniqueness"] < 100


def test_quality_dims_no_date_nulls_timeliness():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": ["x", "y", "z"]})
    r = insights.run_insights(df, {})
    t = next(d for d in r["quality_dims"] if d["key"] == "timeliness")
    assert t["score"] is None


def test_quality_dims_clean_all_full():
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "b": ["x", "y", "z", "x", "y", "z"],
        "d": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]),
    })
    r = insights.run_insights(df, {})
    assert all(d["score"] == 100 for d in r["quality_dims"] if d["score"] is not None)
