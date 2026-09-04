"""业务模板：漏斗分析 / 同期群留存 / K-means 聚类 / A-B 实验（两比例 z、样本量、Cohen's d）。"""
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def _upload_df(df: pd.DataFrame, name="t") -> str:
    r = client.post(
        "/api/upload",
        files={"file": (f"{name}.csv", df.to_csv(index=False).encode("utf-8-sig"), "text/csv")},
        data={"name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _funnel_users() -> pd.DataFrame:
    rows = []
    # 10 人到达步骤1；其中 5 人到达步骤2；其中 2 人到达步骤3
    plans = {f"u{i}": (1 if i < 10 else 0, 1 if i < 5 else 0, 1 if i < 2 else 0) for i in range(10)}
    for uid, (s1, s2, s3) in plans.items():
        if s1:
            rows.append({"uid": uid, "event": "view"})
        if s2:
            rows.append({"uid": uid, "event": "cart"})
        if s3:
            rows.append({"uid": uid, "event": "buy"})
    return pd.DataFrame(rows)


def test_funnel_counts_and_rates():
    ds = _upload_df(_funnel_users())
    r = client.post(f"/api/datasets/{ds}/funnel", json={"params": {
        "user_column": "uid", "event_column": "event", "steps": ["view", "cart", "buy"]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row[1] for row in body["rows"]] == [10, 5, 2]
    assert body["rows"][1][2] == 50.0          # 单步转化率 5/10
    assert body["rows"][2][3] == 20.0          # 整体转化率 2/10
    assert body["funnel"]["values"] == [10, 5, 2]
    assert body["overall_rate"] == 20.0


def test_funnel_negative():
    ds = _upload_df(_funnel_users())
    r = client.post(f"/api/datasets/{ds}/funnel", json={"params": {
        "user_column": "uid", "event_column": "event", "steps": ["view"]}})
    assert r.status_code == 400
    r2 = client.post(f"/api/datasets/{ds}/funnel", json={"params": {
        "user_column": "nope", "event_column": "event", "steps": ["view", "cart"]}})
    assert r2.status_code == 400
    # 第一步事件不存在
    r3 = client.post(f"/api/datasets/{ds}/funnel", json={"params": {
        "user_column": "uid", "event_column": "event", "steps": ["pay", "view"]}})
    assert r3.status_code == 400


def _cohort_users() -> pd.DataFrame:
    # 2024-01 首次活跃：A（1月、2月活跃）、B（仅1月）→ 2月留存 50%
    # 2024-02 首次活跃：C（仅2月）
    return pd.DataFrame([
        {"uid": "A", "d": "2024-01-05"}, {"uid": "A", "d": "2024-02-10"},
        {"uid": "B", "d": "2024-01-20"},
        {"uid": "C", "d": "2024-02-01"},
    ])


def test_cohort_retention_matrix():
    ds = _upload_df(_cohort_users())
    r = client.post(f"/api/datasets/{ds}/cohort", json={"params": {
        "user_column": "uid", "date_column": "d", "freq": "M", "periods": 3}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cohort"]["row_labels"][0] == "2024-01"
    sizes = {row[0]: row[1] for row in body["rows"]}
    assert sizes["2024-01"] == 2 and sizes["2024-02"] == 1
    m = body["cohort"]["values"]
    assert m[0][0] == 100.0
    assert m[0][1] == 50.0   # A 留存，B 流失
    assert m[1][0] == 100.0


def test_cohort_bad_date_column():
    ds = _upload_df(pd.DataFrame({"uid": ["A"], "d": ["不是日期"]}))
    r = client.post(f"/api/datasets/{ds}/cohort", json={"params": {
        "user_column": "uid", "date_column": "d", "freq": "M"}})
    assert r.status_code == 400


def _blob_users() -> pd.DataFrame:
    """两个分离的高斯簇，k 自动选择应恢复 2。"""
    rng = np.random.default_rng(7)
    a = rng.normal(loc=[0, 0], scale=0.5, size=(60, 2))
    b = rng.normal(loc=[8, 8], scale=0.5, size=(60, 2))
    df = pd.DataFrame(np.vstack([a, b]), columns=["消费金额", "访问次数"])
    df["消费金额"] = df["消费金额"].round(3)
    df["访问次数"] = df["访问次数"].round(3)
    return df


def test_cluster_recovers_two_blobs():
    ds = _upload_df(_blob_users(), name="blobs")
    r = client.post(f"/api/datasets/{ds}/cluster", json={"params": {
        "columns": ["消费金额", "访问次数"], "seed": 42}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["best_k"] == 2
    assert body["silhouette"] > 0.5
    sizes = sorted(row[1] for row in body["rows"])
    assert sizes == [60, 60]
    assert len(body["cluster_points"]["x"]) == len(body["cluster_points"]["y"])
    assert body["elbow"]["ks"][0] == 2


def test_cluster_validations():
    ds = _upload_df(_blob_users(), name="blobs2")
    r = client.post(f"/api/datasets/{ds}/cluster", json={"params": {"columns": ["消费金额"]}})
    assert r.status_code == 400
    r2 = client.post(f"/api/datasets/{ds}/cluster", json={"params": {"columns": ["不存在1", "不存在2"]}})
    assert r2.status_code == 400
    # 常数列无区分度
    ds3 = _upload_df(pd.DataFrame({"x": [1.0, 2, 3, 4, 5, 6], "y": [5.0, 5, 5, 5, 5, 5]}))
    r3 = client.post(f"/api/datasets/{ds3}/cluster", json={"params": {"columns": ["x", "y"], "seed": 1}})
    assert r3.status_code == 400


def test_prop_z_significant_and_not():
    # 数据集模式：B 组转化率显著更高（100/1000 vs 150/1000）
    df = pd.DataFrame({
        "group": ["A"] * 1000 + ["B"] * 1000,
        "paid": [1] * 100 + [0] * 900 + [1] * 150 + [0] * 850,
    })
    ds = _upload_df(df)
    r = client.post(f"/api/datasets/{ds}/test", json={"test": "prop_z", "params": {
        "group_column": "group", "success_column": "paid", "success_value": 1}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tests"][0]["significant"] is True
    assert body["rate_a"] == 0.1 and body["rate_b"] == 0.15
    assert body["diff_ci95"][0] > 0        # 区间不含 0
    assert body["relative_lift"] == 0.5

    # 直接计数模式：无显著差异（100/1000 vs 110/1000）
    r2 = client.post(f"/api/datasets/{ds}/test", json={"test": "prop_z", "params": {
        "success_a": 100, "n_a": 1000, "success_b": 110, "n_b": 1000}})
    assert r2.status_code == 200
    assert r2.json()["tests"][0]["significant"] is False


def test_sample_size_known_value():
    ds = _upload_df(pd.DataFrame({"x": [1, 2]}))  # 样本量计算不依赖数据集，但端点需要合法 id
    # 经典教科书数值：基线 10%、绝对 MDE 2pp、α=0.05、效能 0.8 → 每组约 3830+
    r = client.post(f"/api/datasets/{ds}/test", json={"test": "sample_size", "params": {
        "baseline": 0.10, "mde": 0.02, "alpha": 0.05, "power": 0.8}})
    assert r.status_code == 200, r.text
    n = r.json()["n_per_group"]
    assert 3700 < n < 3950, n

    # 相对 MDE：10% 基线 + 20% 相对提升 = 2pp 绝对差，应与上面接近
    r2 = client.post(f"/api/datasets/{ds}/test", json={"test": "sample_size", "params": {
        "baseline": 0.10, "mde": 0.2, "relative": True, "alpha": 0.05, "power": 0.8}})
    assert r2.status_code == 200
    assert abs(r2.json()["n_per_group"] - n) <= 5

    # 非法参数
    r3 = client.post(f"/api/datasets/{ds}/test", json={"test": "sample_size", "params": {
        "baseline": 1.5, "mde": 0.02}})
    assert r3.status_code == 400


def test_compare_groups_has_cohens_d():
    df = pd.DataFrame({
        "g": ["ctl"] * 50 + ["treat"] * 50,
        "v": list(np.random.default_rng(3).normal(100, 10, 50)) + list(np.random.default_rng(4).normal(106, 10, 50)),
    })
    ds = _upload_df(df)
    r = client.post(f"/api/datasets/{ds}/test", json={"test": "compare_groups", "params": {
        "group_column": "g", "value_column": "v"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0.3 < abs(body["effect_size"]) < 1.6   # 偏大效应（均值差约 0.6σ）
    d_test = [t for t in body["tests"] if "Cohen" in t["name"]]
    assert d_test and ("中" in d_test[0]["verdict"] or "大" in d_test[0]["verdict"] or "小" in d_test[0]["verdict"])


# ---------- Phase 2 补充边界 ----------


def test_funnel_needs_at_least_two_steps():
    ds = _upload_df(pd.DataFrame({"u": ["a", "b"], "e": ["s1", "s2"]}))
    r = client.post(f"/api/datasets/{ds}/funnel", json={"params": {"user_column": "u", "event_column": "e", "steps": ["s1"]}})
    assert r.status_code == 400
    assert "至少需要 2 个步骤" in r.json()["detail"]


def test_cohort_rejects_invalid_freq():
    ds = _upload_df(pd.DataFrame({"u": ["a", "b"], "d": ["2026-01-01", "2026-02-01"]}))
    r = client.post(f"/api/datasets/{ds}/cohort", json={"params": {"user_column": "地区", "date_column": "地区", "freq": "Q"}})
    assert r.status_code == 400
    assert "粒度" in r.json()["detail"]


def test_cluster_rejects_single_column():
    ds = _upload_df(pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}))
    r = client.post(f"/api/datasets/{ds}/cluster", json={"params": {"columns": ["销售额"]}})
    assert r.status_code == 400
