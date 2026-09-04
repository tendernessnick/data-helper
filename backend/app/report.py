"""自包含 HTML 分析报告：洞察全文 + 自动标准图表（内嵌 echarts，离线可看）。"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .insights import _detect_date_col, run_insights
from .paths import EXPORT_DIR, FRONTEND_DIR

BASE_COLORS = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7e22ce", "#0891b2"]


def _esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num(x, nd=2):
    if x is None:
        return "—"
    return f"{x:,.{nd}f}".rstrip("0").rstrip(".") if isinstance(x, (int, float)) else str(x)


def _table(headers, rows, cls=""):
    th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = "".join(f"<td>{_esc(v)}</td>" for v in r)
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def _hist_option(s: pd.Series, title: str) -> dict:
    counts, edges = np.histogram(s.dropna(), bins=min(20, max(5, int(s.nunique() / 5) or 5)))
    labels = [f"{edges[i]:.3g}~{edges[i + 1]:.3g}" for i in range(len(counts))]
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {},
        "grid": {"left": 50, "right": 16, "bottom": 60, "top": 40},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 45, "fontSize": 10}},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [int(c) for c in counts], "itemStyle": {"color": "#2563eb"}}],
    }


def _cat_option(s: pd.Series, title: str) -> dict:
    vc = s.value_counts(dropna=True).head(10)
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 50, "right": 16, "bottom": 60, "top": 40},
        "xAxis": {"type": "category", "data": [str(i) for i in vc.index], "axisLabel": {"rotate": 30, "fontSize": 10}},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [int(v) for v in vc.values], "itemStyle": {"color": "#16a34a"}}],
    }


def _trend_option(dates: pd.Series, values: pd.Series, title: str) -> dict:
    tmp = pd.DataFrame({"日期": dates, "值": values}).dropna()
    monthly = tmp.set_index("日期").resample("MS")["值"].sum().dropna()
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 60, "right": 20, "bottom": 40, "top": 40},
        "xAxis": {"type": "category", "data": [d.strftime("%Y-%m") for d in monthly.index]},
        "yAxis": {"type": "value", "scale": True},
        "series": [{"type": "line", "smooth": True, "data": [round(float(v), 2) for v in monthly.values], "areaStyle": {"opacity": 0.12}}],
    }


def _corr_option(df: pd.DataFrame, num_cols: list, title: str) -> dict:
    corr = df[num_cols].corr(numeric_only=True).round(3)
    data = []
    for i in range(len(num_cols)):
        for j in range(len(num_cols)):
            v = corr.iloc[i, j]
            if pd.notna(v):
                data.append([j, i, float(v)])
    return {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"position": "top"},
        "grid": {"left": 90, "bottom": 90, "right": 30, "top": 40},
        "xAxis": {"type": "category", "data": num_cols, "axisLabel": {"rotate": 40}},
        "yAxis": {"type": "category", "data": num_cols},
        "visualMap": {"min": -1, "max": 1, "calculable": True, "orient": "horizontal", "left": "center", "bottom": 0,
                       "inRange": {"color": ["#3b82f6", "#fbbf24", "#ef4444"]}},
        "series": [{"type": "heatmap", "data": data, "label": {"show": len(num_cols) <= 8, "fontSize": 9}}],
    }


def build_charts(df: pd.DataFrame) -> list:
    charts = []
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    cat_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c])]
    for c in num_cols[:6]:
        if df[c].nunique(dropna=True) > 3:
            charts.append({"id": f"hist_{len(charts)}", "title": f"{c} 分布", "option": _hist_option(df[c], f"{c} 分布")})
    for c in cat_cols[:3]:
        if df[c].nunique(dropna=True) > 1 and df[c].nunique(dropna=True) < 100:
            charts.append({"id": f"cat_{len(charts)}", "title": f"{c} Top10", "option": _cat_option(df[c], f"{c} Top10")})
    date_col, dates = _detect_date_col(df)
    if date_col and num_cols:
        charts.append({"id": "trend", "title": f"{num_cols[0]} 月度趋势", "option": _trend_option(dates, pd.to_numeric(df[num_cols[0]], errors="coerce"), f"{num_cols[0]} 月度趋势")})
    if len(num_cols) >= 3:
        charts.append({"id": "corr", "title": "相关性热力图", "option": _corr_option(df, num_cols[:10], "相关性热力图")})
    return charts


def build_report_html(meta: dict, df: pd.DataFrame, insights: dict) -> str:
    charts = build_charts(df)
    echarts_js = (FRONTEND_DIR / "vendor" / "echarts.min.js").read_text(encoding="utf-8")

    ov = insights["overview"]
    parts = []
    parts.append(
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        f"<title>{_esc(meta['name'])} · 分析报告</title><script>{echarts_js}</script>"
        "<style>"
        "body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;margin:0;background:#f3f4f6;color:#1f2937}"
        ".wrap{max-width:1080px;margin:0 auto;padding:32px 24px}"
        "h1{font-size:24px} .muted{color:#6b7280;font-size:13px}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}"
        ".kcard{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}"
        ".kcard b{font-size:22px;display:block;margin-top:4px}"
        "h2{font-size:17px;margin:30px 0 10px;border-left:4px solid #2563eb;padding-left:10px}"
        ".alerts{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:6px 18px;list-style:none}"
        ".alerts li{padding:8px 0;border-bottom:1px dashed #e5e7eb;font-size:14px}"
        ".alerts li:last-child{border:none}"
        "table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;border-radius:8px;overflow:hidden}"
        "th,td{padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:left}"
        "th{background:#f9fafb} td.num{text-align:right}"
        ".charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:14px}"
        ".chart{background:#fff;border:1px solid #e5e7eb;border-radius:10px;height:340px}"
        ".qlist{list-style:none} .qlist li{padding:6px 0;font-size:14px}"
        ".warn{color:#b45309}.info{color:#6b7280} footer{margin:34px 0;text-align:center;color:#9ca3af;font-size:12px}"
        "</style></head><body><div class='wrap'>"
    )
    parts.append(
        f"<h1>📊 {_esc(meta['name'])} · 数据分析报告</h1>"
        f"<div class='muted'>源文件 {_esc(meta.get('original_filename', ''))} · 报告生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据分析小助手（本地生成）</div>"
    )
    # 概览
    parts.append(
        "<div class='cards'>"
        f"<div class='kcard'>数据行<b>{ov['rows']:,}</b></div>"
        f"<div class='kcard'>数据列<b>{ov['cols']}</b></div>"
        f"<div class='kcard'>重复行<b>{ov['duplicates']:,}</b></div>"
        f"<div class='kcard'>缺失占比<b>{ov['missing_pct']}%</b></div>"
        f"<div class='kcard'>内存占用<b>{ov['mem_mb']} MB</b></div>"
        "</div>"
    )
    # 要点
    parts.append("<h2>🔎 关键发现</h2><ul class='alerts'>")
    for a in insights["alerts"]:
        parts.append(f"<li>{a}</li>")
    parts.append("</ul>")
    # 质量
    if insights["quality"]:
        parts.append("<h2>🧪 数据质量</h2><ul class='qlist'>")
        for q in insights["quality"]:
            parts.append(f"<li class='{q['level']}'>• {q['msg']}</li>")
        parts.append("</ul>")
    # 数值列
    if insights["numeric"]:
        rows = [
            [x["name"], _num(x["min"]), _num(x["max"]), _num(x["mean"]), _num(x["median"]),
             _num(x["std"]), x["shape"], x["zeros"], x["negatives"], f"{x['outliers']}（{x['outlier_pct']}%）"]
            for x in insights["numeric"]
        ]
        parts.append("<h2>🔢 数值列概览</h2>")
        parts.append(_table(["列", "最小", "最大", "均值", "中位数", "标准差", "分布形态", "零值", "负值", "离群值"], rows))
    # 类别列
    if insights["categorical"]:
        rows = [
            [x["name"], x["nunique"], x["top_value"], f"{x['top_count']}（{x['top_share']}%）", x["rare"]]
            for x in insights["categorical"]
        ]
        parts.append("<h2>🏷️ 类别列概览</h2>")
        parts.append(_table(["列", "唯一值数", "最高频值", "次数（占比）", "仅出现1次的值"], rows))
    # 时间
    dt = insights["datetime"]
    if dt:
        parts.append("<h2>📅 时间维度</h2>")
        parts.append(_table(
            ["日期列", "数值列", "范围", "跨度", "月度趋势", "首末变化", "最大环比突变"],
            [[dt["column"], dt["value_column"], f"{dt['min']} ~ {dt['max']}", f"{dt['span_days']} 天",
              dt["direction"], f"{dt['change_pct']}%" if dt["change_pct"] is not None else "—",
              f"{dt['big_shift']['period']}（{dt['big_shift']['pct']}%）" if dt["big_shift"] else "—"]],
        ))
    # 相关性
    if insights["correlations"]:
        rows = [[p["a"], p["b"], p["r"], "强正相关" if p["r"] > 0 else "强负相关"] for p in insights["correlations"]]
        parts.append("<h2>🔗 强相关列对（|r| ≥ 0.6）</h2>")
        parts.append(_table(["列A", "列B", "相关系数", "含义"], rows))
    # 图表
    if charts:
        parts.append("<h2>📈 自动图表</h2><div class='charts'>")
        for ch in charts:
            parts.append(f"<div class='chart' id='{ch['id']}'></div>")
        parts.append("</div><script>")
        for ch in charts:
            option_json = json.dumps(ch["option"], ensure_ascii=False).replace("</", "<\\/")
            parts.append(f"echarts.init(document.getElementById('{ch['id']}')).setOption({option_json});")
        parts.append(
            "window.addEventListener('resize',function(){"
            "document.querySelectorAll('.chart').forEach(function(el){var c=echarts.getInstanceByDom(el);if(c)c.resize();})});"
        )
        parts.append("</script>")
    parts.append("<footer>本报告由 数据分析小助手 在本机生成 · 图表可交互 · 可直接分享给同事</footer></div></body></html>")
    return "".join(parts)


def save_report(meta: dict, df: pd.DataFrame) -> Path:
    insights = run_insights(df, meta)
    html = build_report_html(meta, df, insights)
    name = "".join("-" if ch in '<>:"/\\|?*' else ch for ch in (meta.get("name") or "数据集"))[:50]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{name}_分析报告.html"
    path.write_text(html, encoding="utf-8")
    return path
