/* 数据分析小助手 - 前端逻辑（Vue3 全局构建 · 工具坞 + 结果画布工作台） */
const { createApp } = Vue;

let CARD_SEQ = 1;

const app = createApp({
  data() {
    return {
      datasets: [],
      currentId: null,
      meta: {},
      busy: false,
      busyRows: false,
      toasts: [],

      // 预览
      rowsData: { total: 0, columns: [], rows: [] },
      page: 1,
      pageSize: 50,
      previewOpen: true,

      // 结果画布
      cards: [],

      // 工具坞开合
      openSec: { cl: false, ana: true, ts: false, biz: false, stat: false, sql: false, cmp: false, tf: false, ai: false, hist: false },

      // 主题
      theme: "light",

      // 列头快捷菜单
      colMenu: { show: false, x: 0, y: 0, col: "" },

      // 图表推荐
      suggestions: [],

      // 图表类型（分段控件）
      chartTypes: [
        { v: "bar", l: "柱状" }, { v: "hbar", l: "条形" }, { v: "line", l: "折线" },
        { v: "area", l: "面积" }, { v: "pie", l: "饼图" }, { v: "treemap", l: "树图" },
      ],

      // 画像（列选择数据源）
      profile: { rows: 0, columns: [] },

      // 清洗
      cleanOp: "drop_duplicates",
      cleanSel: {
        columns: [], how: "any", method: "constant", value: "",
        column: "", to: "str", format: "", op: "eq",
        value1: "", value2: "", dropCols: [], outlierCols: [], outlierMethod: "iqr",
        binMethod: "equal_width", bins: 5, binLabels: "", maxCols: 30,
        stdMethod: "zscore", logBase: "ln", dateParts: ["year", "month"],
        pattern: "", newColumn: "",
      },
      dateParts: { year: "年", month: "月", day: "日", quarter: "季度", weekday: "星期", hour: "小时" },
      renameMap: {},

      // 统计分析
      aggs: ["count", "sum", "mean", "min", "max", "median", "std", "nunique"],
      anaKind: "groupby",
      ana: {
        by: [], metrics: [{ column: "", agg: "sum" }],
        index: "", columns: "", values: "", aggfunc: "sum",
        corrCols: [], corrMethod: "pearson", histCol: "", bins: 20, boxCols: [],
        vcCol: "", top: 20,
      },

      // 时序分析
      tsKind: "trend",
      ts: { dateCol: "", valCol: "", freq: "M", agg: "sum", window: 3, horizon: 6 },

      // 业务模板
      bizKind: "rfm",
      biz: { idCol: "", dateCol: "", valCol: "", catCol: "", topN: 30, outCols: [], outMethod: "iqr" },

      // 统计检验
      statKind: "normality",
      stat: { col: "", groupCol: "", valCol: "", colA: "", colB: "", colX: "", colY: "" },

      // SQL 控制台
      sqlQuery: "",
      sqlTables: [],

      // 对比与采样
      cmpKind: "compare",
      cmp: { otherId: "", key: "", sampleMethod: "random", n: 30, by: "", name: "" },

      // Python 变换
      code: "# 示例：新增一列\n# df['客单价'] = df['销售额'] / df['数量']\n",
      tfSample: "",
      tfSamples: [
        { name: "新增计算列", code: "df['新列'] = df['销售额'] / df['数量']" },
        { name: "条件筛选", code: "df = df[df['销售额'] > 1000]" },
        { name: "按列排序", code: "df = df.sort_values('销售额', ascending=False)" },
        { name: "删除缺失关键列的行", code: "df = df.dropna(subset=['销售额'])" },
        { name: "重命名列", code: "df = df.rename(columns={'旧列名': '新列名'})" },
        { name: "字符串处理", code: "df['地区'] = df['地区'].str.strip().str.replace('省', '', regex=False)" },
        { name: "日期列转类型", code: "df['日期'] = pd.to_datetime(df['日期'], errors='coerce')" },
        { name: "查看统计信息", code: "print(df.describe())\nprint(df['地区'].value_counts())" },
      ],

      // AI
      aiSettings: { api_key: "", base_url: "", model: "" },
      aiConfigured: false,
      aiMessages: [],
      aiInput: "",

      // 粘贴导入
      pasteOpen: false,
      pasteText: "",
      pasteName: "",
    };
  },

  computed: {
    ringTrack() {
      return this.theme === "dark" ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)";
    },
    totalPages() {
      return Math.max(1, Math.ceil((this.rowsData.total || 0) / this.pageSize));
    },
    numCols() {
      return (this.profile.columns || []).filter((c) => c.kind === "numeric");
    },
    catCols() {
      return (this.profile.columns || []).filter((c) => c.kind !== "numeric");
    },
    anaReady() {
      const a = this.ana, k = this.anaKind;
      if (k === "groupby") return a.by.length && a.metrics.every((m) => m.column);
      if (k === "pivot") return a.index && a.values;
      if (k === "histogram") return a.histCol;
      if (k === "value_counts") return a.vcCol;
      return true;
    },
    bizReady() {
      const b = this.biz, k = this.bizKind;
      if (k === "rfm") return b.idCol && b.dateCol && b.valCol;
      if (k === "pareto") return b.catCol && b.valCol;
      return true;
    },
    statReady() {
      const s = this.stat, k = this.statKind;
      if (k === "normality") return !!s.col;
      if (k === "compare_groups") return s.groupCol && s.valCol;
      if (k === "chi2") return s.colA && s.colB;
      if (k === "corr_test") return s.colX && s.colY;
      return false;
    },
    statusMissing() {
      const p = this.profile;
      if (!p.columns || !p.columns.length || !p.rows) return "0.00";
      const cells = p.columns.reduce((acc, c) => acc + (c.missing || 0), 0);
      return ((cells / (p.rows * p.columns.length)) * 100).toFixed(2);
    },
  },

  async mounted() {
    this.theme = localStorage.getItem("dh-theme") || "light";
    document.documentElement.dataset.theme = this.theme;
    await this.refreshDatasets();
    this.loadAiSettings();
    window.addEventListener("resize", () => {
      Object.values(this._charts || {}).forEach((c) => c && c.resize());
    });
    window.addEventListener("click", (e) => {
      if (this.colMenu.show && !e.target.closest(".col-menu") && !e.target.closest("th")) {
        this.colMenu.show = false;
      }
    });
  },

  methods: {
    // ---------- 基础 ----------
    async api(method, url, body) {
      const opt = { method, headers: {} };
      if (body !== undefined) {
        opt.headers["Content-Type"] = "application/json";
        opt.body = JSON.stringify(body);
      }
      const res = await fetch(url, opt);
      if (res.ok) return res.json();
      let msg = `请求失败 (${res.status})`;
      try { const j = await res.json(); if (j.detail) msg = String(j.detail); } catch (e) { /* ignore */ }
      throw new Error(msg);
    },

    toast(msg, type = "success") {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, msg, type });
      setTimeout(() => { this.toasts = this.toasts.filter((t) => t.id !== id); }, type === "error" ? 6000 : 3500);
    },

    fmtCell(v) {
      if (v === null || v === undefined) return "∅";
      if (typeof v === "object" && v !== null) {
        if ("value" in v) return `${this.fmtCell(v.value)} [${this.fmtCell(v.lower)} ~ ${this.fmtCell(v.upper)}]`;
        return JSON.stringify(v);
      }
      if (typeof v === "number") {
        if (!isFinite(v)) return "—";
        return v.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
      }
      return String(v);
    },

    isNumCol(j) {
      const c = this.rowsData.columns[j];
      return c && /^(int|uint|float|Int|Float)/.test(c.dtype);
    },

    aggLabel(a) {
      return { count: "计数", sum: "求和", mean: "平均", min: "最小", max: "最大", median: "中位数", std: "标准差", nunique: "去重计数" }[a] || a;
    },

    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = this.theme;
      localStorage.setItem("dh-theme", this.theme);
      // 重新渲染所有图表以应用文字颜色
      this.cards.forEach((c) => this.renderCardChart(c));
    },

    chartTheme() {
      const dark = this.theme === "dark";
      return {
        txt: dark ? "#98989d" : "#6e6e73",
        txtEm: dark ? "#f5f5f7" : "#1d1d1f",
        split: dark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.07)",
        // Apple 系统色板
        palette: dark
          ? ["#0a84ff", "#30d158", "#ff9f0a", "#ff453a", "#bf5af2", "#64d2ff", "#ffd60a", "#ff375f"]
          : ["#007aff", "#34c759", "#ff9500", "#ff3b30", "#af52ce", "#32ade6", "#ffcc00", "#ff2d55"],
        blue: dark ? "#0a84ff" : "#007aff",
        orange: dark ? "#ff9f0a" : "#ff9500",
        tipBg: dark ? "rgba(40,40,43,.92)" : "rgba(255,255,255,.92)",
      };
    },

    isGenericChart(card) {
      const R = card.payload;
      return !(R.matrix || R.box_stats || R.pareto || R.points || R.forecast_meta || R.heatmap || R.row_labels);
    },

    moveCard(idx, dir) {
      const j = idx + dir;
      if (j < 0 || j >= this.cards.length) return;
      const arr = this.cards;
      [arr[idx], arr[j]] = [arr[j], arr[idx]];
      this.cards = [...arr];
    },

    async askAiChart() {
      const prompt = this.aiInput.trim();
      if (!prompt) { this.toast("请先在输入框描述想要的图表，如：各月销售额趋势", "error"); return; }
      this.aiInput = "";
      this.aiMessages.push({ role: "user", content: "📊 出图指令：" + prompt });
      this.busy = true;
      this.scrollChat();
      try {
        const R = await this.api("POST", "/api/ai/chart", { dataset_id: this.currentId, prompt });
        const spec = R.ai_spec || {};
        delete R.ai_spec;
        this.addCard({
          type: R.matrix ? "table" : (R.backtest ? "table" : "table"),
          icon: "🤖", title: spec.title || "AI 图表", payload: R, span2: !!R.forecast_meta,
        });
        this.aiMessages.push({ role: "assistant", content: `已生成图表「${spec.title || "AI 图表"}」，见画布卡片。` });
      } catch (e) {
        this.aiMessages.push({ role: "assistant", content: "⚠ " + e.message });
        this.toast(e.message, "error");
      } finally { this.busy = false; this.scrollChat(); }
    },

    // ---------- 卡片系统 ----------
    addCard(card) {
      card.id = CARD_SEQ++;
      card.time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      if (card.chartType === undefined) card.chartType = "bar";
      if (card.showDetail === undefined) card.showDetail = false;
      // 是否需要图表容器
      const R = card.payload;
      card.chartDiv = !!(R.matrix || R.box_stats || R.pareto || R.points || R.forecast_meta || R.heatmap || R.row_labels
        || (R.rows && R.rows.length > 1 && R.columns && R.columns.some((c) => c.numeric)));
      if (card.type === "test") card.chartDiv = false;
      if (R.chart && R.chart.type && !R.matrix && !R.box_stats && !R.pareto) card.chartType = R.chart.type;
      this.cards.push(card);
      this.$nextTick(() => {
        this.renderCardChart(card);
        const el = document.querySelector(`.cards-grid .card-item:last-child`);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      if (this.cards.length > 12) this.removeCard(this.cards[0]);
      return card;
    },

    removeCard(card) {
      if (this._charts && this._charts[card.id]) {
        this._charts[card.id].dispose();
        delete this._charts[card.id];
      }
      this.cards = this.cards.filter((c) => c.id !== card.id);
    },

    setCardEl(card, el) {
      if (!this._charts) this._charts = {};
      this._cardEls = this._cardEls || {};
      this._cardEls[card.id] = el;
    },

    renderCardChart(card) {
      this.$nextTick(() => {
        const el = (this._cardEls || {})[card.id];
        if (!el || !card.chartDiv) return;
        if (!this._charts) this._charts = {};
        if (this._charts[card.id]) this._charts[card.id].dispose();
        const R = card.payload;
        const T = this.chartTheme();
        const chart = echarts.init(el);
        this._charts[card.id] = chart;

        // 热力图族：交叉表 / 缺失矩阵 / 相关矩阵
        let heat = null;
        if (R.heatmap) heat = { cols: R.heatmap.cols, rows: R.heatmap.rows, values: R.heatmap.values, min: 0, max: null };
        else if (R.row_labels && R.values) heat = { cols: R.columns, rows: R.row_labels, values: R.values, min: 0, max: 100 };
        if (heat) {
          const data = [];
          heat.values.forEach((row, i) => row.forEach((v, j) => {
            if (v !== null && v !== undefined) data.push([j, i, v]);
          }));
          const vmax = heat.max !== null ? heat.max : Math.max(1, ...data.map((d) => d[2]));
          chart.setOption({
            tooltip: { position: "top",
              formatter: (p) => `${heat.cols[p.value[0]]} × ${heat.rows[p.value[1]]}: ${p.value[2]}` },
            grid: { left: 80, bottom: 80, right: 20, top: 15 },
            xAxis: { type: "category", data: heat.cols, axisLabel: { rotate: 40, fontSize: 10, color: T.txt } },
            yAxis: { type: "category", data: heat.rows, axisLabel: { fontSize: 10, color: T.txt } },
            visualMap: { min: heat.min, max: vmax, calculable: true, orient: "horizontal", left: "center", bottom: 0,
              textStyle: { color: T.txt }, itemWidth: 12,
              inRange: { color: R.row_labels ? ["#ffffff", "#2563eb"] : ["#fbbf24", "#ef4444"] } },
            series: [{ type: "heatmap", data, label: { show: heat.rows.length <= 30 && heat.cols.length <= 12, fontSize: 9, color: T.txtEm } }],
          });
          return;
        }

        // 相关矩阵（对称）
        if (R.matrix) {
          const cols = R.matrix.columns;
          const data = [];
          R.matrix.values.forEach((row, i) => row.forEach((v, j) => { if (v !== null) data.push([j, i, v]); }));
          chart.setOption({
            tooltip: { position: "top", formatter: (p) => `${cols[p.value[0]]} × ${cols[p.value[1]]}: ${p.value[2]}` },
            grid: { left: 90, bottom: 80, right: 20, top: 20 },
            xAxis: { type: "category", data: cols, axisLabel: { rotate: 40, fontSize: 11, color: T.txt } },
            yAxis: { type: "category", data: cols, axisLabel: { color: T.txt } },
            visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#3b82f6", "#fbbf24", "#ef4444"] }, itemWidth: 12, textStyle: { color: T.txt } },
            series: [{ type: "heatmap", data, label: { show: true, fontSize: 10, color: T.txtEm, formatter: (p) => p.value[2].toFixed(2) } }],
          });
          return;
        }

        // 箱线图
        if (R.box_stats) {
          const stats = R.box_stats;
          chart.setOption({
            tooltip: { trigger: "item" },
            grid: { left: 55, right: 20, top: 20, bottom: 50 },
            xAxis: { type: "category", data: stats.map((s) => s.name), axisLabel: { rotate: 25, fontSize: 11, color: T.txt } },
            yAxis: { type: "value", scale: true, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } },
            series: [{ type: "boxplot", data: stats.map((s) => [Math.max(s.min, s.lower), s.q1, s.median, s.q3, Math.min(s.max, s.upper)]), itemStyle: { color: T.palette[0] + "33", borderColor: T.palette[0] } }],
          });
          return;
        }

        // 帕累托：柱(值) + 线(累计占比%) 双轴
        if (R.pareto) {
          const labels = R.rows.map((r) => String(r[0]));
          const values = R.rows.map((r) => r[1]);
          const cums = R.rows.map((r) => r[3]);
          chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { bottom: 0, textStyle: { color: T.txt } },
            grid: { left: 60, right: 55, top: 25, bottom: 70 },
            toolbox: { feature: { saveAsImage: { title: "保存" } }, right: 15 },
            xAxis: { type: "category", data: labels, axisLabel: { rotate: 35, fontSize: 11, color: T.txt } },
            yAxis: [
              { type: "value", scale: true, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } },
              { type: "value", max: 100, axisLabel: { formatter: "{value}%", color: T.txt }, splitLine: { show: false } },
            ],
            series: [
              { name: R.columns[1] ? R.columns[1].name : "数值", type: "bar", data: values, itemStyle: { color: T.palette[0], borderRadius: [4, 4, 0, 0] } },
              { name: "累计占比%", type: "line", yAxisIndex: 1, data: cums, smooth: true, itemStyle: { color: T.orange }, lineStyle: { color: T.orange }, markLine: { data: [{ yAxis: 80, name: "80%" }], lineStyle: { type: "dashed", color: T.palette[3] }, label: { formatter: "80%", color: T.txt } } },
            ],
          });
          return;
        }

        // 散点（交互分析）
        if (R.points) {
          chart.setOption({
            tooltip: { formatter: (p) => `${R.x}: ${p.value[0]}<br>${R.y}: ${p.value[1]}` },
            grid: { left: 60, right: 20, top: 25, bottom: 45 },
            xAxis: { type: "value", scale: true, name: R.x, nameTextStyle: { color: T.txt }, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } },
            yAxis: { type: "value", scale: true, name: R.y, nameTextStyle: { color: T.txt }, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } },
            series: [{ type: "scatter", data: R.points, symbolSize: 7, itemStyle: { color: T.palette[0], opacity: .6 } }],
          });
          return;
        }

        // 预测卡：历史线 + 预测线 + 置信带
        if (R.forecast_meta) {
          const fm = R.forecast_meta;
          const allLabels = [...fm.history_labels, ...fm.labels];
          const nHist = fm.history_labels.length;
          const histData = fm.history_values.map((v, i) => [i, v]);
          // 预测线从最后一个历史点衔接
          const fcData = [[nHist - 1, fm.history_values[nHist - 1]], ...fm.values.map((v, i) => [nHist + i, v])];
          const lowerData = Array(nHist - 1).fill(null)
            .concat([[nHist - 1, fm.history_values[nHist - 1]]])
            .concat(fm.lower.map((v, i) => [nHist + i, v]));
          const bandData = Array(nHist - 1).fill(null)
            .concat([[nHist - 1, 0]])
            .concat(fm.values.map((v, i) => [nHist + i, Math.max(fm.upper[i] - fm.lower[i], 0)]));
          chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { bottom: 0, textStyle: { color: T.txt } },
            grid: { left: 65, right: 20, top: 25, bottom: 65 },
            xAxis: { type: "category", data: allLabels, axisLabel: { rotate: 35, fontSize: 10, color: T.txt } },
            yAxis: { type: "value", scale: true, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } },
            series: [
              { name: "实际值", type: "line", data: histData, smooth: true, symbolSize: 3, itemStyle: { color: T.palette[0] }, lineStyle: { color: T.palette[0], width: 2.5 } },
              { name: `预测值（${R.best}）`, type: "line", data: fcData, smooth: true, lineStyle: { type: "dashed", color: T.orange, width: 2.5 }, itemStyle: { color: T.orange } },
              { name: "band-base", type: "line", data: lowerData, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
              { name: "95%区间", type: "line", data: bandData, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: T.orange + "26" }, tooltip: { show: false }, silent: true },
            ],
          });
          return;
        }

        // 通用表格 → 柱/条/折/面积/饼/树图
        if (!R.rows || !R.rows.length) return;
        const cols = R.columns;
        let labelIdx = cols.findIndex((c) => c.name === (R.chart && R.chart.label_col));
        if (labelIdx < 0) labelIdx = cols.findIndex((c) => !c.numeric);
        if (labelIdx < 0) labelIdx = 0;
        const valIdxs = cols.map((c, i) => (c.numeric && i !== labelIdx ? i : -1)).filter((i) => i >= 0).slice(0, 6);
        if (!valIdxs.length) return;
        const labels = R.rows.map((r) => String(r[labelIdx] ?? "空"));
        if (card.chartType === "pie") {
          chart.setOption({
            tooltip: { trigger: "item" },
            legend: { bottom: 0, type: "scroll", textStyle: { fontSize: 11, color: T.txt } },
            series: [{
              type: "pie", radius: ["28%", "62%"], center: ["50%", "46%"],
              data: R.rows.map((r, i) => ({ name: labels[i], value: r[valIdxs[0]] })),
              label: { fontSize: 11, color: T.txt },
              color: T.palette,
            }],
          });
          return;
        }
        if (card.chartType === "treemap") {
          chart.setOption({
            tooltip: { formatter: (p) => `${p.name}: ${p.value}` },
            series: [{
              type: "treemap", data: R.rows.map((r, i) => ({ name: labels[i], value: r[valIdxs[0]] })),
              label: { fontSize: 11, formatter: "{b}\n{c}" }, roam: false,
            }],
          });
          return;
        }
        const catAxis = { type: "category", data: labels, axisLabel: { rotate: 35, fontSize: 11, color: T.txt } };
        const valAxis = { type: "value", scale: true, axisLabel: { color: T.txt }, splitLine: { lineStyle: { color: T.split } } };
        const series = valIdxs.map((i, si) => {
          const s = { name: cols[i].name, type: card.chartType === "area" ? "line" : card.chartType, smooth: true, emphasis: { focus: "series" }, data: R.rows.map((r) => r[i]), color: T.palette[si % T.palette.length] };
          if (card.chartType === "bar") s.itemStyle = { borderRadius: [4, 4, 0, 0] };
          if (card.chartType === "area") s.areaStyle = { opacity: .15 };
          if (card.chartType === "hbar") { s.type = "bar"; }
          return s;
        });
        const grid = { left: 60, right: 20, top: 25, bottom: 70 };
        chart.setOption({
          tooltip: { trigger: "axis" },
          legend: { bottom: 0, type: "scroll", textStyle: { fontSize: 11, color: T.txt } },
          grid,
          toolbox: { feature: { saveAsImage: { title: "保存" } }, right: 15 },
          xAxis: card.chartType === "hbar" ? valAxis : catAxis,
          yAxis: card.chartType === "hbar" ? { ...catAxis, axisLabel: { fontSize: 10, color: T.txt } } : valAxis,
          series,
        });
      });
    },

    exportCardTable(card, fmt) {
      const R = card.payload;
      if (!R.rows || !R.rows.length) return;
      fetch("/api/export-table", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ columns: R.columns, rows: R.rows, filename: card.title.slice(0, 30), format: fmt }),
      })
        .then(async (res) => {
          if (!res.ok) throw new Error("导出失败");
          const blob = await res.blob();
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = (card.title.replace(/[^\w\u4e00-\u9fa5-]/g, "") || "结果") + (fmt === "csv" ? ".csv" : ".xlsx");
          a.click();
          URL.revokeObjectURL(a.href);
        })
        .catch((e) => this.toast(e.message, "error"));
    },

    // ---------- 数据集 ----------
    async refreshDatasets() {
      this.datasets = await this.api("GET", "/api/datasets");
    },

    async selectDataset(id) {
      if (this.currentId === id) return;
      this.currentId = id;
      this.meta = this.datasets.find((d) => d.id === id) || {};
      this.page = 1;
      this.cards = [];
      Object.values(this._charts || {}).forEach((c) => c && c.dispose());
      this._charts = {};
      this.cleanSel.columns = [];
      this.cleanSel.dropCols = [];
      this.cleanSel.outlierCols = [];
      await Promise.all([this.loadRows(), this.loadProfile(), this.initDefaults(), this.loadSqlTables()]);
      this.meta = await this.api("GET", `/api/datasets/${id}`);
    },

    async loadRows() {
      if (!this.currentId) return;
      this.busyRows = true;
      try {
        this.rowsData = await this.api("GET", `/api/datasets/${this.currentId}/rows?page=${this.page}&page_size=${this.pageSize}`);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busyRows = false; }
    },

    async loadProfile() {
      if (!this.currentId) return;
      try { this.profile = await this.api("GET", `/api/datasets/${this.currentId}/profile`); }
      catch (e) { this.toast(e.message, "error"); }
    },

    async afterDataChange(respMeta) {
      if (respMeta) this.meta = respMeta;
      await Promise.all([this.loadRows(), this.loadProfile(), this.refreshDatasets()]);
    },

    async uploadFile(ev) {
      const file = ev.target.files[0];
      ev.target.value = "";
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", "");
      this.busy = true;
      try {
        const r = await fetch("/api/upload", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || "上传失败");
        this.toast(`已导入「${j.meta.name}」：${j.meta.rows} 行 × ${j.meta.cols} 列`);
        await this.refreshDatasets();
        await this.selectDataset(j.id);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    openPaste() {
      this.pasteText = "";
      this.pasteName = "";
      this.pasteOpen = true;
    },

    async submitPaste() {
      this.busy = true;
      try {
        const j = await this.api("POST", "/api/upload-paste", { text: this.pasteText, name: this.pasteName });
        this.pasteOpen = false;
        this.toast(`已导入「${j.meta.name}」：${j.meta.rows} 行 × ${j.meta.cols} 列`);
        await this.refreshDatasets();
        await this.selectDataset(j.id);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async importSheet(sheet) {
      this.busy = true;
      try {
        const j = await this.api("POST", `/api/datasets/${this.currentId}/import-sheet`, { sheet });
        this.toast(`已导入工作表「${sheet}」为新数据集`);
        await this.refreshDatasets();
        await this.selectDataset(j.id);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async createSample() {
      this.busy = true;
      try {
        const j = await this.api("POST", "/api/sample");
        this.toast(`已生成示例数据：${j.meta.rows} 行（含缺失/重复，可体验清洗）`);
        await this.refreshDatasets();
        await this.selectDataset(j.id);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async renameDs() {
      const name = prompt("新的数据集名称：", this.meta.name);
      if (!name || name === this.meta.name) return;
      try { this.meta = await this.api("POST", `/api/datasets/${this.currentId}/rename`, { name }); await this.refreshDatasets(); }
      catch (e) { this.toast(e.message, "error"); }
    },

    async deleteDs() {
      if (!confirm(`确定删除数据集「${this.meta.name}」？原始文件将一并删除。`)) return;
      try {
        await this.api("DELETE", `/api/datasets/${this.currentId}`);
        this.currentId = null; this.meta = {}; this.cards = [];
        await this.refreshDatasets();
        this.toast("已删除");
      } catch (e) { this.toast(e.message, "error"); }
    },

    async undoDs() {
      this.busy = true;
      try {
        const meta = await this.api("POST", `/api/datasets/${this.currentId}/undo`);
        this.toast("已撤销上一步");
        await this.afterDataChange(meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async resetDs() {
      if (!confirm("回滚到上传时的原始数据？当前所有清洗与变换结果将丢弃。")) return;
      this.busy = true;
      try {
        const meta = await this.api("POST", `/api/datasets/${this.currentId}/reset`);
        this.toast("已回滚到原始数据");
        await this.afterDataChange(meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    exportDs(fmt) {
      const name = encodeURIComponent(this.meta.name || "数据集");
      window.location.href = `/api/datasets/${this.currentId}/export?format=${fmt}&filename=${name}`;
    },

    // ---------- 清洗 ----------
    buildCleanParams() {
      const s = this.cleanSel;
      const pick = (v) => (Array.isArray(v) && v.length ? v : undefined);
      switch (this.cleanOp) {
        case "drop_duplicates": return { columns: pick(s.columns) };
        case "drop_missing": return { columns: pick(s.columns), how: s.how };
        case "fill_missing": {
          const p = { columns: pick(s.columns), method: s.method };
          if (s.method === "constant") {
            if (s.value === "") throw new Error("请填写填充值");
            p.value = isNaN(Number(s.value)) ? s.value : Number(s.value);
          }
          return p;
        }
        case "rename_columns": {
          const mapping = {};
          for (const [k, v] of Object.entries(this.renameMap)) if (v && v !== k) mapping[k] = v;
          if (!Object.keys(mapping).length) throw new Error("没有修改任何列名");
          return { mapping };
        }
        case "cast_type": {
          if (!s.column) throw new Error("请选择列");
          const p = { column: s.column, to: s.to };
          if (s.to === "datetime" && s.format) p.format = s.format;
          return p;
        }
        case "filter_rows": {
          if (!s.column) throw new Error("请选择列");
          const p = { column: s.column, op: s.op };
          if (s.op === "between") {
            if (s.value1 === "" || s.value2 === "") throw new Error("请填写范围的两个值");
            p.value = [Number(s.value1), Number(s.value2)].map((v, i) => (isNaN(v) ? (i === 0 ? s.value1 : s.value2) : v));
          } else if (s.op === "isin") {
            if (s.value === "") throw new Error("请填写列表值");
            p.value = s.value.split(/[,，]/).map((x) => x.trim()).map((x) => (isNaN(Number(x)) || x === "" ? x : Number(x)));
          } else if (!["isnull", "notnull"].includes(s.op)) {
            if (s.value === "") throw new Error("请填写比较值");
            p.value = isNaN(Number(s.value)) ? s.value : Number(s.value);
          }
          return p;
        }
        case "drop_columns": {
          if (!s.dropCols.length) throw new Error("请勾选要删除的列");
          return { columns: s.dropCols };
        }
        case "drop_outliers": {
          if (!s.outlierCols.length) throw new Error("请选择要检测异常值的数值列");
          return { columns: s.outlierCols, method: s.outlierMethod };
        }
        case "bin_column": {
          if (!s.column) throw new Error("请选择列");
          const p = { column: s.column, method: s.binMethod, bins: s.bins };
          if (s.binLabels.trim()) p.labels = s.binLabels.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
          return p;
        }
        case "one_hot_encode": {
          if (!s.column) throw new Error("请选择列");
          return { column: s.column, max_columns: s.maxCols };
        }
        case "standardize_column": {
          if (!s.column) throw new Error("请选择列");
          return { column: s.column, method: s.stdMethod };
        }
        case "log_transform": {
          if (!s.column) throw new Error("请选择列");
          return { column: s.column, base: s.logBase };
        }
        case "extract_date_parts": {
          if (!s.column) throw new Error("请选择列");
          if (!s.dateParts.length) throw new Error("请勾选要提取的日期成分");
          return { column: s.column, parts: s.dateParts };
        }
        case "regex_extract": {
          if (!s.column || !s.pattern) throw new Error("请选择列并填写正则表达式");
          const p = { column: s.column, pattern: s.pattern };
          if (s.newColumn.trim()) p.new_column = s.newColumn.trim();
          return p;
        }
      }
      return {};
    },

    async runClean() {
      let params;
      try { params = this.buildCleanParams(); }
      catch (e) { this.toast(e.message, "error"); return; }
      this.busy = true;
      try {
        const r = await this.api("POST", `/api/datasets/${this.currentId}/clean`, { op: this.cleanOp, params });
        this.toast(r.message);
        await this.afterDataChange(r.meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- 分析 ----------
    async initDefaults() {
      const nums = this.numCols, cats = this.catCols;
      const a = this.ana;
      a.metrics = [{ column: nums[0] ? nums[0].name : "", agg: "sum" }];
      a.values = nums[0] ? nums[0].name : "";
      a.histCol = nums[0] ? nums[0].name : "";
      a.vcCol = cats[0] ? cats[0].name : "";
      a.index = cats[0] ? cats[0].name : "";
      const dt = (this.profile.columns || []).find((c) => c.kind === "datetime");
      const dateLike = dt ? dt.name : (cats || []).find((c) => /日期|时间|date/i.test(c.name))?.name || cats[0]?.name || "";
      this.ts.dateCol = dateLike;
      this.ts.valCol = nums[0] ? nums[0].name : "";
      const b = this.biz;
      b.valCol = nums[0] ? nums[0].name : "";
      b.dateCol = dateLike;
      b.idCol = cats.find((c) => /客户|用户|会员|id/i.test(c.name))?.name || (cats[0] ? cats[0].name : "");
      b.catCol = cats.find((c) => /产品|类别|地区|渠道|品类/i.test(c.name))?.name || (cats[0] ? cats[0].name : "");
      // 统计检验默认值
      this.stat.col = nums[0] ? nums[0].name : "";
      this.stat.groupCol = b.idCol;
      this.stat.valCol = nums[0] ? nums[0].name : "";
      this.stat.colA = cats[0] ? cats[0].name : "";
      this.stat.colB = cats[1] ? cats[1].name : "";
      this.stat.colX = nums[0] ? nums[0].name : "";
      this.stat.colY = nums[1] ? nums[1].name : "";
      this.cmp.otherId = this.datasets.find((d) => d.id !== this.currentId)?.id || "";
    },

    async runAnalyze() {
      const a = this.ana, k = this.anaKind;
      let params = {};
      if (k === "groupby") params = { by: a.by, metrics: a.metrics.filter((m) => m.column) };
      else if (k === "pivot") params = { index: a.index, columns: a.columns || null, values: a.values, aggfunc: a.aggfunc };
      else if (k === "corr") params = { columns: a.corrCols.length ? a.corrCols : undefined, method: a.corrMethod };
      else if (k === "histogram") params = { column: a.histCol, bins: a.bins };
      else if (k === "boxplot") params = { columns: a.boxCols.length ? a.boxCols : undefined };
      else if (k === "value_counts") params = { column: a.vcCol, top: a.top };
      await this.doAnalyze(k, params, "📈");
    },

    async runTs() {
      const t = this.ts;
      let params = { date_column: t.dateCol, value_column: t.valCol, freq: t.freq, agg: t.agg };
      if (this.tsKind === "moving_avg") params.window = t.window;
      if (this.tsKind === "forecast") {
        params = { date_column: t.dateCol, value_column: t.valCol, freq: t.freq, horizon: t.horizon };
        this.busy = true;
        try {
          const R = await this.api("POST", `/api/datasets/${this.currentId}/forecast`, { params });
          this.addCard({ type: "table", icon: "🔮", title: `预测（${R.best}）`, payload: R, span2: true });
        } catch (e) { this.toast(e.message, "error"); }
        finally { this.busy = false; }
        return;
      }
      await this.doAnalyze(this.tsKind, params, "📉");
    },

    async runBiz() {
      const b = this.biz, k = this.bizKind;
      let params;
      if (k === "rfm") params = { id_column: b.idCol, date_column: b.dateCol, value_column: b.valCol };
      else if (k === "pareto") params = { category_column: b.catCol, value_column: b.valCol, top_n: b.topN };
      else params = { columns: b.outCols.length ? b.outCols : undefined, method: b.outMethod };
      await this.doAnalyze(k, params, "🎯", k === "rfm");
    },

    async doAnalyze(kind, params, icon, span2 = false) {
      this.busy = true;
      try {
        const R = await this.api("POST", `/api/datasets/${this.currentId}/analyze`, { kind, params });
        const titleMap = {
          groupby: "分组聚合", pivot: "透视表", corr: "相关性分析", histogram: "直方图",
          boxplot: "箱线图", value_counts: "频次统计", describe: "汇总统计",
          trend: "时间趋势", growth: "同比环比与累计", moving_avg: "移动平均",
          rfm: "RFM 客户分层", pareto: "ABC 帕累托", outliers: "异常值检测",
        };
        this.addCard({ type: kind === "rfm" ? "rfm" : "table", icon, title: titleMap[kind] || kind, payload: R, span2 });
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async switchCorrMethod(card) {
      const cycle = { pearson: "spearman", spearman: "kendall", kendall: "pearson" };
      const next = cycle[card.payload.method || "pearson"];
      try {
        const R = await this.api("GET", `/api/datasets/${this.currentId}/corr?method=${next}`);
        card.payload = R;
        this.renderCardChart(card);
      } catch (e) { this.toast(e.message, "error"); }
    },

    // ---------- 列头快捷菜单 ----------
    openColMenu(ev, col) {
      this.colMenu = {
        show: true, col: col.name,
        x: Math.min(ev.clientX, window.innerWidth - 200),
        y: Math.min(ev.clientY, window.innerHeight - 200),
      };
    },

    colProfile() {
      const col = this.colMenu.col;
      this.colMenu.show = false;
      this.doAnalyze("value_counts", { column: col, top: 15 }, "📊");
    },

    colFilter() {
      this.cleanSel.column = this.colMenu.col;
      this.cleanOp = "filter_rows";
      this.openSec.cl = true;
      this.colMenu.show = false;
      this.toast(`已把「${this.colMenu.col}」填入清洗面板的筛选条件`);
    },

    colSql() {
      const col = this.colMenu.col;
      this.colMenu.show = false;
      this.sqlQuery = `SELECT "${col}", COUNT(*) AS n FROM df GROUP BY "${col}" ORDER BY n DESC LIMIT 20`;
      this.openSec.sql = true;
      this.runSql(false);
    },

    // ---------- 图表推荐 ----------
    async loadSuggestions() {
      this.busy = true;
      try {
        this.suggestions = await this.api("GET", `/api/datasets/${this.currentId}/chart-suggest`);
        if (!this.suggestions.length) this.toast("没有可推荐的可视化（列类型不足）", "error");
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async runSuggestion(s) {
      if (s.kind === "scatter") {
        this.busy = true;
        try {
          const R = await this.api("GET",
            `/api/datasets/${this.currentId}/interactions?x=${encodeURIComponent(s.params.x)}&y=${encodeURIComponent(s.params.y)}`);
          this.addCard({ type: "table", icon: "✳️", title: s.title, payload: R });
        } catch (e) { this.toast(e.message, "error"); }
        finally { this.busy = false; }
        return;
      }
      if (s.kind === "cross_heat") {
        this.busy = true;
        try {
          const R = await this.api("POST", `/api/datasets/${this.currentId}/cross-heat`, { params: s.params });
          this.addCard({ type: "table", icon: "🌡️", title: s.title, payload: R });
        } catch (e) { this.toast(e.message, "error"); }
        finally { this.busy = false; }
        return;
      }
      const iconMap = { trend: "📉", growth: "📉", groupby: "📈", value_counts: "🥧", histogram: "📊", boxplot: "📦", corr: "🔗" };
      await this.doAnalyze(s.kind, s.params, iconMap[s.kind] || "🎯");
    },

    // ---------- 统计检验 ----------
    async runStatTest() {
      const s = this.stat;
      let params = {};
      if (this.statKind === "normality") params = { column: s.col };
      else if (this.statKind === "compare_groups") params = { group_column: s.groupCol, value_column: s.valCol };
      else if (this.statKind === "chi2") params = { column_a: s.colA, column_b: s.colB };
      else params = { column_x: s.colX, column_y: s.colY };
      this.busy = true;
      try {
        const R = await this.api("POST", `/api/datasets/${this.currentId}/test`, { test: this.statKind, params });
        const titleMap = {
          normality: `正态性检验「${R.column}」`,
          compare_groups: `组间比较：${R.value_column} 按 ${R.group_column}`,
          chi2: `卡方独立性「${R.column_a} × ${R.column_b}」`,
          corr_test: `相关性检验「${R.column_x} × ${R.column_y}」`,
        };
        this.addCard({ type: "test", icon: "🧪", title: titleMap[this.statKind], payload: R });
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- SQL 控制台 ----------
    async loadSqlTables() {
      try { this.sqlTables = await this.api("GET", "/api/sql/tables"); }
      catch (e) { /* 静默 */ }
    },

    async runSql(saveAs) {
      if (!this.sqlQuery.trim()) { this.toast("请输入 SQL", "error"); return; }
      this.busy = true;
      try {
        const R = await this.api("POST", "/api/sql", {
          query: this.sqlQuery,
          save_as: saveAs ? (this.meta.name + "-SQL结果") : "",
          current_id: this.currentId,
        });
        this.addCard({
          type: "table", icon: "🗄️", span2: true,
          title: saveAs ? "SQL 结果（已存为新数据集）" : "SQL 查询结果",
          payload: { columns: R.columns, rows: R.rows, note: `共 ${R.total} 行${R.truncated ? "（超过上限已截断）" : ""}` },
        });
        if (R.new_dataset) {
          await this.refreshDatasets();
          this.toast(`已保存为新数据集「${R.new_dataset.meta.name}」`);
        } else {
          this.toast(`查询完成：${R.total} 行`);
        }
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- 对比与采样 ----------
    async runCompare() {
      if (!this.cmp.otherId) { this.toast("请选择对比的数据集", "error"); return; }
      this.busy = true;
      try {
        const R = await this.api("POST", `/api/datasets/${this.currentId}/compare`, { other_id: this.cmp.otherId, key: this.cmp.key });
        this.addCard({ type: "compare", icon: "⚖️", title: "数据集对比", payload: R, span2: true });
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async runSample() {
      this.busy = true;
      try {
        const j = await this.api("POST", `/api/datasets/${this.currentId}/sample-create`, {
          method: this.cmp.sampleMethod, n: this.cmp.n, by: this.cmp.by, name: this.cmp.name,
        });
        this.toast(`已生成采样数据集「${j.meta.name}」：${j.meta.rows} 行`);
        await this.refreshDatasets();
        await this.selectDataset(j.id);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async runInsights() {
      this.busy = true;
      try {
        const R = await this.api("GET", `/api/datasets/${this.currentId}/insights`);
        this.addCard({ type: "insight", icon: "🔍", title: "一键数据洞察", payload: R, span2: true });
        this.toast("洞察完成，详见画布卡片");
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async makeReport() {
      this.busy = true;
      try {
        const res = await fetch(`/api/datasets/${this.currentId}/report`, { method: "POST" });
        if (!res.ok) {
          let msg = "报告生成失败";
          try { const j = await res.json(); if (j.detail) msg = String(j.detail); } catch (e) { /* ignore */ }
          throw new Error(msg);
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (this.meta.name || "数据集") + "_分析报告.html";
        a.click();
        URL.revokeObjectURL(a.href);
        this.toast("HTML 报告已生成并下载（自包含，可离线打开分享）");
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- Python 变换 ----------
    applySample() {
      if (this.tfSample === "") return;
      const s = this.tfSamples[this.tfSample];
      if (s) { this.code = s.code + "\n"; this.tfSample = ""; }
    },

    async runTransform(apply) {
      if (apply && !confirm("把这段代码的结果应用到数据集？（可用「撤销上一步」恢复）")) return;
      this.busy = true;
      try {
        const r = await this.api("POST", `/api/datasets/${this.currentId}/transform`, { code: this.code, apply });
        this.addCard({
          type: "transform", icon: "🐍", span2: true, applied: apply,
          title: apply ? "Python 变换（已应用）" : "Python 变换（预览）",
          payload: {
            note: `${r.old_shape.rows} 行 × ${r.old_shape.cols} 列 → ${r.shape.rows} 行 × ${r.shape.cols} 列` +
              (r.stdout ? `；输出：${r.stdout.slice(0, 120)}` : ""),
            stdout: r.stdout,
            columns: r.preview.columns,
            rows: r.preview.rows,
          },
        });
        this.toast(apply ? `已应用：${r.old_shape.rows} 行 → ${r.shape.rows} 行` : "预览成功，可在卡片底部点击「应用到数据集」");
        if (apply) await this.afterDataChange(r.meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async applyTransformFromCard(card) {
      if (!confirm("把该预览结果应用到数据集？")) return;
      this.busy = true;
      try {
        const r = await this.api("POST", `/api/datasets/${this.currentId}/transform`, { code: this.code, apply: true });
        card.applied = true;
        card.title = "Python 变换（已应用）";
        this.toast(`已应用：${r.old_shape.rows} 行 → ${r.shape.rows} 行`);
        await this.afterDataChange(r.meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- AI ----------
    parseMsg(text) {
      const parts = [];
      const re = /```(\w*)\n?([\s\S]*?)(```|$)/g;
      let last = 0, m;
      while ((m = re.exec(text)) !== null) {
        if (m.index > last) parts.push({ text: text.slice(last, m.index), code: false });
        parts.push({ text: m[2].trim(), code: true });
        last = m.index + m[0].length;
      }
      if (last < text.length) parts.push({ text: text.slice(last), code: false });
      return parts.length ? parts : [{ text, code: false }];
    },

    msgHasCode(m) { return /```/.test(m.content); },

    useAiCode(m) {
      const segs = this.parseMsg(m.content).filter((s) => s.code);
      if (!segs.length) return;
      this.code = segs.map((s) => s.text).join("\n\n");
      this.openSec.tf = true;
      this.toast("已把 AI 建议代码放入 Python 变换，请先预览运行");
    },

    async loadAiSettings() {
      try {
        const s = await this.api("GET", "/api/ai/settings");
        this.aiSettings = { ...this.aiSettings, ...s };
        this.aiConfigured = !!(s.api_key && s.base_url && s.model);
      } catch (e) { /* 后端未就绪时静默 */ }
    },

    async saveAiSettings() {
      try {
        const s = await this.api("PUT", "/api/ai/settings", this.aiSettings);
        this.aiConfigured = !!(s.api_key && s.base_url && s.model);
        this.toast(this.aiConfigured ? "AI 配置已保存，可以开始提问了" : "已保存（填全 Key / 地址 / 模型后启用）");
      } catch (e) { this.toast(e.message, "error"); }
    },

    async sendAi() {
      const q = this.aiInput.trim();
      if (!q || !this.currentId) return;
      this.aiInput = "";
      this.aiMessages.push({ role: "user", content: q });
      this.busy = true;
      this.scrollChat();
      try {
        const r = await this.api("POST", "/api/ai/chat", { dataset_id: this.currentId, messages: this.aiMessages.slice(-10) });
        this.aiMessages.push({ role: "assistant", content: r.reply });
      } catch (e) {
        this.aiMessages.push({ role: "assistant", content: "⚠ " + e.message });
        this.toast(e.message, "error");
      } finally { this.busy = false; this.scrollChat(); }
    },

    async askAiInsight() {
      const card = [...this.cards].reverse().find((c) => c.type === "insight");
      if (!card) { this.toast("请先点击「🔍 一键洞察」生成洞察结果", "error"); return; }
      const summary = card.payload.alerts.join("\n");
      this.aiMessages.push({ role: "user", content: `以下是对当前数据集的自动洞察结果，请用业务视角解读这些发现并给出建议行动：\n${summary}` });
      this.busy = true;
      this.scrollChat();
      try {
        const r = await this.api("POST", "/api/ai/chat", { dataset_id: this.currentId, messages: this.aiMessages.slice(-10) });
        this.aiMessages.push({ role: "assistant", content: r.reply });
      } catch (e) {
        this.aiMessages.push({ role: "assistant", content: "⚠ " + e.message });
      } finally { this.busy = false; this.scrollChat(); }
    },

    scrollChat() {
      this.$nextTick(() => {
        const el = this.$refs.chatMsgs;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
  },
});

app.mount("#app");
