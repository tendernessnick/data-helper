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
      openSec: { cl: false, ana: true, ts: false, biz: false, tf: false, ai: false, hist: false },

      // 画像（列选择数据源）
      profile: { rows: 0, columns: [] },

      // 清洗
      cleanOp: "drop_duplicates",
      cleanSel: {
        columns: [], how: "any", method: "constant", value: "",
        column: "", to: "str", format: "", op: "eq",
        value1: "", value2: "", dropCols: [], outlierCols: [], outlierMethod: "iqr",
      },
      renameMap: {},

      // 统计分析
      aggs: ["count", "sum", "mean", "min", "max", "median", "std", "nunique"],
      anaKind: "groupby",
      ana: {
        by: [], metrics: [{ column: "", agg: "sum" }],
        index: "", columns: "", values: "", aggfunc: "sum",
        corrCols: [], histCol: "", bins: 20, boxCols: [],
        vcCol: "", top: 20,
      },

      // 时序分析
      tsKind: "trend",
      ts: { dateCol: "", valCol: "", freq: "M", agg: "sum", window: 3 },

      // 业务模板
      bizKind: "rfm",
      biz: { idCol: "", dateCol: "", valCol: "", catCol: "", topN: 30, outCols: [], outMethod: "iqr" },

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
  },

  async mounted() {
    await this.refreshDatasets();
    this.loadAiSettings();
    window.addEventListener("resize", () => {
      Object.values(this._charts || {}).forEach((c) => c && c.resize());
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

    // ---------- 卡片系统 ----------
    addCard(card) {
      card.id = CARD_SEQ++;
      card.time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      if (card.chartType === undefined) card.chartType = "bar";
      if (card.showDetail === undefined) card.showDetail = false;
      // 是否需要图表容器
      const R = card.payload;
      card.chartDiv = !!(R.matrix || R.box_stats || R.pareto || (R.rows && R.rows.length > 1 && R.columns && R.columns.some((c) => c.numeric)));
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
        const chart = echarts.init(el);
        this._charts[card.id] = chart;

        // 相关性热力图
        if (R.matrix) {
          const cols = R.matrix.columns;
          const data = [];
          R.matrix.values.forEach((row, i) => row.forEach((v, j) => { if (v !== null) data.push([j, i, v]); }));
          chart.setOption({
            tooltip: { position: "top", formatter: (p) => `${cols[p.value[0]]} × ${cols[p.value[1]]}: ${p.value[2]}` },
            grid: { left: 90, bottom: 80, right: 20, top: 20 },
            xAxis: { type: "category", data: cols, axisLabel: { rotate: 40, fontSize: 11 } },
            yAxis: { type: "category", data: cols },
            visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#3b82f6", "#fbbf24", "#ef4444"] }, itemWidth: 12 },
            series: [{ type: "heatmap", data, label: { show: true, fontSize: 10, formatter: (p) => p.value[2].toFixed(2) } }],
          });
          return;
        }

        // 箱线图
        if (R.box_stats) {
          const stats = R.box_stats;
          chart.setOption({
            tooltip: { trigger: "item" },
            grid: { left: 55, right: 20, top: 20, bottom: 50 },
            xAxis: { type: "category", data: stats.map((s) => s.name), axisLabel: { rotate: 25, fontSize: 11 } },
            yAxis: { type: "value", scale: true },
            series: [{ type: "boxplot", data: stats.map((s) => [Math.max(s.min, s.lower), s.q1, s.median, s.q3, Math.min(s.max, s.upper)]) }],
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
            legend: { bottom: 0 },
            grid: { left: 60, right: 55, top: 25, bottom: 70 },
            toolbox: { feature: { saveAsImage: { title: "保存" } }, right: 15 },
            xAxis: { type: "category", data: labels, axisLabel: { rotate: 35, fontSize: 11 } },
            yAxis: [
              { type: "value", scale: true },
              { type: "value", max: 100, axisLabel: { formatter: "{value}%" }, splitLine: { show: false } },
            ],
            series: [
              { name: R.columns[1] ? R.columns[1].name : "数值", type: "bar", data: values, itemStyle: { color: "#2563eb" } },
              { name: "累计占比%", type: "line", yAxisIndex: 1, data: cums, smooth: true, itemStyle: { color: "#d97706" }, markLine: { data: [{ yAxis: 80, name: "80%" }], lineStyle: { type: "dashed", color: "#dc2626" }, label: { formatter: "80%" } } },
            ],
          });
          return;
        }

        // 通用表格 → 柱/折/饼
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
            legend: { bottom: 0, type: "scroll", textStyle: { fontSize: 11 } },
            series: [{
              type: "pie", radius: ["28%", "62%"], center: ["50%", "46%"],
              data: R.rows.map((r, i) => ({ name: labels[i], value: r[valIdxs[0]] })),
              label: { fontSize: 11 },
            }],
          });
          return;
        }
        const series = valIdxs.map((i) => ({
          name: cols[i].name, type: card.chartType, smooth: true, emphasis: { focus: "series" },
          data: R.rows.map((r) => r[i]),
        }));
        chart.setOption({
          tooltip: { trigger: "axis" },
          legend: { bottom: 0, type: "scroll", textStyle: { fontSize: 11 } },
          grid: { left: 60, right: 20, top: 25, bottom: 70 },
          toolbox: { feature: { saveAsImage: { title: "保存" } }, right: 15 },
          xAxis: { type: "category", data: labels, axisLabel: { rotate: 35, fontSize: 11 } },
          yAxis: { type: "value", scale: true },
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
      await Promise.all([this.loadRows(), this.loadProfile(), this.initDefaults()]);
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
    },

    async runAnalyze() {
      const a = this.ana, k = this.anaKind;
      let params = {};
      if (k === "groupby") params = { by: a.by, metrics: a.metrics.filter((m) => m.column) };
      else if (k === "pivot") params = { index: a.index, columns: a.columns || null, values: a.values, aggfunc: a.aggfunc };
      else if (k === "corr") params = { columns: a.corrCols.length ? a.corrCols : undefined };
      else if (k === "histogram") params = { column: a.histCol, bins: a.bins };
      else if (k === "boxplot") params = { columns: a.boxCols.length ? a.boxCols : undefined };
      else if (k === "value_counts") params = { column: a.vcCol, top: a.top };
      await this.doAnalyze(k, params, "📈");
    },

    async runTs() {
      const t = this.ts;
      let params = { date_column: t.dateCol, value_column: t.valCol, freq: t.freq, agg: t.agg };
      if (this.tsKind === "moving_avg") params.window = t.window;
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
