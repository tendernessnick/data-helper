/* 数据分析小助手 - 前端逻辑（Vue3 全局构建，无构建步骤） */
const { createApp } = Vue;

const app = createApp({
  data() {
    return {
      datasets: [],
      currentId: null,
      meta: {},
      tab: "preview",
      tabs: [
        { key: "preview", label: "数据预览" },
        { key: "profile", label: "列画像" },
        { key: "clean", label: "数据清洗" },
        { key: "analyze", label: "统计分析" },
        { key: "transform", label: "Python 变换" },
        { key: "ai", label: "AI 问答" },
        { key: "history", label: "操作历史" },
      ],
      busy: false,
      busyRows: false,
      toasts: [],

      // 预览
      rowsData: { total: 0, columns: [], rows: [] },
      page: 1,
      pageSize: 50,

      // 画像
      profile: { rows: 0, columns: [] },

      // 清洗
      cleanOp: "drop_duplicates",
      cleanSel: {
        columns: [], how: "any", method: "constant", value: "",
        column: "", to: "str", format: "", op: "eq",
        value1: "", value2: "", dropCols: [],
      },
      renameMap: {},

      // 分析
      aggs: ["count", "sum", "mean", "min", "max", "median", "std", "nunique"],
      anaKind: "groupby",
      ana: {
        by: [], metrics: [{ column: "", agg: "sum" }],
        index: "", columns: "", values: "", aggfunc: "sum",
        corrCols: [], histCol: "", bins: 20, boxCols: [],
        vcCol: "", top: 20, dateCol: "", valCol: "", freq: "M", trendAgg: "sum",
      },
      anaResult: null,
      chartType: "bar",

      // Python 变换
      code: "# 示例：新增一列\n# df['客单价'] = df['销售额'] / df['数量']\n",
      tfResult: null,
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
    numericResultCols() {
      return (this.anaResult && this.anaResult.columns || []).filter((c) => c.numeric);
    },
    anaReady() {
      const a = this.ana, k = this.anaKind;
      if (k === "groupby") return a.by.length && a.metrics.every((m) => m.column);
      if (k === "pivot") return a.index && a.values;
      if (k === "trend") return a.dateCol && a.valCol;
      if (k === "histogram") return a.histCol;
      if (k === "value_counts") return a.vcCol;
      return true; // describe / corr / boxplot 有默认值
    },
  },

  async mounted() {
    await this.refreshDatasets();
    window.addEventListener("resize", this._onResize = () => {
      if (this._chart) this._chart.resize();
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

    kindLabel(k) {
      return { numeric: "数值", categorical: "类别", datetime: "日期", boolean: "布尔" }[k] || k;
    },

    aggLabel(a) {
      return { count: "计数", sum: "求和", mean: "平均", min: "最小", max: "最大", median: "中位数", std: "标准差", nunique: "去重计数", first: "第一个", last: "最后一个" }[a] || a;
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
      this.anaResult = null;
      this.tfResult = null;
      this.tab = "preview";
      this.cleanSel.columns = [];
      this.cleanSel.dropCols = [];
      await Promise.all([this.loadRows(), this.loadProfile(), this.initAnalyzeDefaults()]);
      this.meta = await this.api("GET", `/api/datasets/${id}`);
    },

    async loadRows() {
      if (!this.currentId) return;
      this.busyRows = true;
      try {
        this.rowsData = await this.api(
          "GET",
          `/api/datasets/${this.currentId}/rows?page=${this.page}&page_size=${this.pageSize}`
        );
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busyRows = false; }
    },

    async loadProfile() {
      if (!this.currentId) return;
      try {
        this.profile = await this.api("GET", `/api/datasets/${this.currentId}/profile`);
      } catch (e) { this.toast(e.message, "error"); }
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

    async createSample() {
      this.busy = true;
      try {
        const j = await this.api("POST", "/api/sample");
        this.toast(`已生成示例数据：${j.meta.rows} 行 × ${j.meta.cols} 列（含缺失值与重复行，可体验清洗功能）`);
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
        this.currentId = null; this.meta = {};
        await this.refreshDatasets();
        this.toast("已删除");
      } catch (e) { this.toast(e.message, "error"); }
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

    async exportTable(fmt) {
      if (!this.anaResult) return;
      try {
        const res = await fetch("/api/export-table", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            columns: this.anaResult.columns,
            rows: this.anaResult.rows,
            filename: this.anaResult.note.slice(0, 30) || "分析结果",
            format: fmt,
          }),
        });
        if (!res.ok) throw new Error("导出失败");
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (this.meta.name || "分析结果") + (fmt === "csv" ? ".csv" : ".xlsx");
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (e) { this.toast(e.message, "error"); }
    },

    switchTab(key) {
      this.tab = key;
      if (key === "analyze") this.$nextTick(() => this.renderChart());
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
          for (const [k, v] of Object.entries(this.renameMap)) {
            if (v && v !== k) mapping[k] = v;
          }
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
    async initAnalyzeDefaults() {
      const nums = this.numCols, cats = this.catCols;
      const a = this.ana;
      a.metrics = [{ column: nums[0] ? nums[0].name : "", agg: "sum" }];
      a.values = nums[0] ? nums[0].name : "";
      a.histCol = nums[0] ? nums[0].name : "";
      a.valCol = nums[0] ? nums[0].name : "";
      a.index = cats[0] ? cats[0].name : "";
      a.vcCol = cats[0] ? cats[0].name : "";
      const dt = (this.profile.columns || []).find((c) => c.kind === "datetime");
      const dateLike = dt ? dt.name : (cats || []).find((c) => /日期|时间|date|month/i.test(c.name))?.name || "";
      a.dateCol = dateLike;
    },

    async runAnalyze() {
      const a = this.ana, k = this.anaKind;
      let params = {};
      if (k === "groupby") {
        params = { by: a.by, metrics: a.metrics.filter((m) => m.column) };
      } else if (k === "pivot") {
        params = { index: a.index, columns: a.columns || null, values: a.values, aggfunc: a.aggfunc };
      } else if (k === "trend") {
        params = { date_column: a.dateCol, value_column: a.valCol, freq: a.freq, agg: a.trendAgg };
      } else if (k === "corr") {
        params = { columns: a.corrCols.length ? a.corrCols : undefined };
      } else if (k === "histogram") {
        params = { column: a.histCol, bins: a.bins };
      } else if (k === "boxplot") {
        params = { columns: a.boxCols.length ? a.boxCols : undefined };
      } else if (k === "value_counts") {
        params = { column: a.vcCol, top: a.top };
      }
      this.busy = true;
      try {
        this.anaResult = await this.api("POST", `/api/datasets/${this.currentId}/analyze`, { kind: k, params });
        const sug = this.anaResult.chart && this.anaResult.chart.type;
        if (sug) this.chartType = sug;
        await this.$nextTick();
        this.renderChart();
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    renderChart() {
      const el = this.$refs.chart;
      const R = this.anaResult;
      if (!el || !R) return;
      if (this._chart) { this._chart.dispose(); this._chart = null; }

      // 相关性矩阵 → 热力图
      if (R.matrix) {
        this._chart = echarts.init(el);
        const cols = R.matrix.columns;
        const data = [];
        R.matrix.values.forEach((row, i) => row.forEach((v, j) => {
          if (v !== null) data.push([j, i, v]);
        }));
        this._chart.setOption({
          tooltip: { position: "top", formatter: (p) => `${cols[p.value[0]]} × ${cols[p.value[1]]}: ${p.value[2]}` },
          grid: { left: 100, bottom: 90, right: 30, top: 30 },
          xAxis: { type: "category", data: cols, axisLabel: { rotate: 40 } },
          yAxis: { type: "category", data: cols },
          visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#3b82f6", "#fbbf24", "#ef4444"] } },
          series: [{ type: "heatmap", data, label: { show: true, formatter: (p) => p.value[2].toFixed(2) } }],
        });
        return;
      }

      // 箱线图
      if (R.box_stats) {
        this._chart = echarts.init(el);
        const stats = R.box_stats;
        this._chart.setOption({
          tooltip: { trigger: "item" },
          grid: { left: 60, right: 30, top: 30, bottom: 60 },
          xAxis: { type: "category", data: stats.map((s) => s.name), axisLabel: { rotate: 30 } },
          yAxis: { type: "value", scale: true },
          series: [{
            type: "boxplot",
            data: stats.map((s) => [Math.max(s.min, s.lower), s.q1, s.median, s.q3, Math.min(s.max, s.upper)]),
          }],
        });
        return;
      }

      // 通用表 → 柱/折/饼
      if (!R.rows || !R.rows.length) return;
      const cols = R.columns;
      let labelIdx = cols.findIndex((c) => c.name === (R.chart && R.chart.label_col));
      if (labelIdx < 0) labelIdx = cols.findIndex((c) => !c.numeric);
      if (labelIdx < 0) labelIdx = 0;
      const valIdxs = cols.map((c, i) => (c.numeric && i !== labelIdx ? i : -1)).filter((i) => i >= 0).slice(0, 6);
      if (!valIdxs.length) return;

      this._chart = echarts.init(el);
      const labels = R.rows.map((r) => String(r[labelIdx] ?? "空"));
      const series = valIdxs.map((i) => ({
        name: cols[i].name,
        type: this.chartType === "pie" ? "pie" : this.chartType,
        radius: this.chartType === "pie" ? "70%" : undefined,
        center: this.chartType === "pie" ? ["50%", "55%"] : undefined,
        data: this.chartType === "pie"
          ? R.rows.map((r) => ({ name: String(r[labelIdx] ?? "空"), value: r[i] }))
          : undefined,
        smooth: true,
        emphasis: { focus: "series" },
      }));
      if (this.chartType === "pie") {
        this._chart.setOption({
          tooltip: { trigger: "item" },
          legend: { bottom: 0, type: "scroll" },
          series: series.slice(0, 1),
        });
      } else {
        this._chart.setOption({
          tooltip: { trigger: "axis" },
          legend: { bottom: 0, type: "scroll" },
          grid: { left: 70, right: 30, top: 40, bottom: 80 },
          toolbox: { feature: { saveAsImage: { title: "保存图片" } }, right: 20 },
          xAxis: { type: "category", data: labels, axisLabel: { rotate: 35 } },
          yAxis: { type: "value", scale: true },
          series,
        });
      }
    },

    // ---------- Python 变换 ----------
    applySample() {
      if (this.tfSample === "") return;
      const s = this.tfSamples[this.tfSample];
      if (s) { this.code = s.code + "\n"; this.tfSample = ""; }
    },

    async runTransform(apply) {
      if (apply && !confirm("把这段代码的结果应用到数据集？（可随时「回滚原始数据」）")) return;
      this.busy = true;
      try {
        const r = await this.api("POST", `/api/datasets/${this.currentId}/transform`, { code: this.code, apply });
        this.tfResult = r;
        this.toast(apply ? `已应用：${r.old_shape.rows} 行 → ${r.shape.rows} 行` : "预览成功，确认无误后可应用");
        if (apply) await this.afterDataChange(r.meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- AI ----------
    parseMsg(text) {
      // 把消息拆成 文本 / ```代码块``` 片段
      const parts = [];
      const re = /```(\w*)\n?([\s\S]*?)(```|$)/g;
      let last = 0, m;
      while ((m = re.exec(text)) !== null) {
        if (m.index > last) parts.push({ text: text.slice(last, m.index), code: false });
        parts.push({ text: m[2].trim(), code: true, lang: m[1] });
        last = m.index + m[0].length;
      }
      if (last < text.length) parts.push({ text: text.slice(last), code: false });
      return parts.length ? parts : [{ text, code: false }];
    },

    msgHasCode(m) {
      return /```/.test(m.content);
    },

    useAiCode(m) {
      const segs = this.parseMsg(m.content).filter((s) => s.code);
      if (!segs.length) return;
      this.code = segs.map((s) => s.text).join("\n\n");
      this.tab = "transform";
      this.toast("已把 AI 建议的代码填入「Python 变换」，请先预览运行", "success");
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
        const r = await this.api("POST", "/api/ai/chat", {
          dataset_id: this.currentId,
          messages: this.aiMessages.slice(-10),
        });
        this.aiMessages.push({ role: "assistant", content: r.reply });
      } catch (e) {
        this.aiMessages.push({ role: "assistant", content: "⚠ " + e.message });
        this.toast(e.message, "error");
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
