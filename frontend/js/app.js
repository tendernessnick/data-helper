/* 数据分析小助手 - 前端逻辑（Vue3 全局构建 · IDE 式工作台：数据表/结果主区 + 底部工具面板） */
const { createApp } = Vue;

let CARD_SEQ = 1;

// 外部主页回跳：从个人主页带 ?home=<url> 链接进入时生效（本地直开无参数则保持站内重置行为）
const HOME_URL = (new URLSearchParams(location.search).get("home") || "").trim();

const app = createApp({
  data() {
    return {
      homeUrl: HOME_URL,          // 非空时品牌区点击/主页按钮跳转外部主页
      datasets: [],
      currentId: null,
      meta: {},
      busy: false,
      busyRows: false,
      toasts: [],

      // 项目化管理
      projects: [],               // [{id, name, created_at}]
      activeProject: "",          // 新导入/粘贴/示例归入的项目（空 = 未分组）
      collapsedProjects: {},      // {projectId: true}
      creatingProject: false,
      newProjectName: "",
      dsSearch: "",

      // 版本快照（历史回跳）
      versionsInfo: { current: -1, snapshots: [] },
      maxVersions: 20,

      // 预览
      rowsData: { total: 0, unfiltered_total: 0, columns: [], rows: [] },
      page: 1,
      pageSize: 50,

      // 主区 tab：table 数据表 / cards 结果
      mainTab: "table",

      // 表格视图状态：排序 + 列筛选（只影响查看，不改数据）
      sortCol: "",
      sortDir: "asc",
      colFilters: {},
      colFilterSel: [],

      // 列头下拉面板
      colMenu: { show: false, x: 0, y: 0, col: "", dtype: "", values: null, missingCount: 0, search: "", truncated: false },

      // 底部工具面板（SQL / Python）
      bottomTab: "sql",
      bottomH: 300,
      bottomCollapsed: false,
      bottomTabs: [
        { k: "sql", l: "🗄️ SQL 控制台" },
        { k: "tf", l: "🐍 Python 变换" },
      ],

      // 右侧工具栏（清洗 / 统计 / 采样 / 历史）
      rightTab: "clean",
      rightCollapsed: false,
      rightTabs: [
        { k: "clean", l: "🧹 清洗", icon: "🧹" },
        { k: "ana", l: "📈 统计", icon: "📈" },
        { k: "cmp", l: "🎯 采样", icon: "🎯" },
        { k: "hist", l: "🕘 历史", icon: "🕘" },
      ],

      // 结果画布
      cards: [],

      // 运营看板（nio 分支）：钉卡配置存后端，进入 tab 时重放重建
      dashCards: [],
      dashLoading: false,
      dashLoaded: false,     // 当前数据集是否已加载过看板（数据变更后置 false 触发重建）
      dashConfigs: [],       // 服务端配置镜像 [{kind, params, title, icon, span2}]
      showMode: false,       // 放映模式：隐藏侧栏纯看板展示

      // 主题
      theme: "light",

      // 拖放导入
      dragOver: false,

      // MCP 弹窗
      mcpOpen: false,

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
        // 文本与格式清洗
        emptyToNa: false, percentScale: false, mapText: "",
        splitSep: ",", splitInto: "", missThreshold: 0.5, missAxis: "column",
      },
      dateParts: { year: "年", month: "月", day: "日", quarter: "季度", weekday: "星期", hour: "小时" },
      renameMap: {},

      // 快速统计与图表
      aggs: ["count", "sum", "mean", "min", "max", "median", "std", "nunique"],
      anaKind: "groupby",
      ana: {
        by: [], metrics: [{ column: "", agg: "sum" }],
        corrCols: [], corrMethod: "pearson", histCol: "", bins: 20, boxCols: [],
        vcCol: "", top: 20, outMethod: "iqr",
        dateCol: "", valCol: "", freq: "M", agg: "sum",
        kpiCol: "", kpiAgg: "sum", kpiDate: "",
        fnMode: "events", fnCol: "", fnSteps: "", fnUser: "", fnCols: [],
      },

      // SQL 控制台
      sqlQuery: "",
      sqlTables: [],

      // 采样
      cmp: { sampleMethod: "random", n: 30, by: "", name: "" },

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

      // 粘贴导入
      pasteOpen: false,
      pasteText: "",
      pasteName: "",
    };
  },

  watch: {
    mainTab(v) {
      if (v === "cards") {
        // 结果页此前处于隐藏状态时图表未定尺寸，切回必须补一次渲染
        this.$nextTick(() => {
          (this.cards || []).forEach((c) => {
            if (c.chartDiv) this.renderCardChart(c);
            if (c.type === "insight") this.renderInsightRadar(c);  // 六维雷达同需补渲
          });
        });
      } else if (v === "dash") {
        this.ensureDash();
      }
    },
  },

  computed: {
    mcpUrl() {
      // MCP 与主应用同端口；Streamable HTTP 端点为 /mcp/mcp
      return `${location.origin}/mcp/mcp`;
    },
    sseUrl() {
      return `${location.origin}/sse/sse`;
    },

    filteredDatasets() {
      const q = (this.dsSearch || "").trim().toLowerCase();
      if (!q) return this.datasets;
      return this.datasets.filter((d) => (d.name || "").toLowerCase().includes(q));
    },
    groupedDatasets() {
      const q = (this.dsSearch || "").trim().toLowerCase();
      const groups = this.projects.map((p) => ({
        id: p.id, name: p.name, items: [],
        collapsed: this.collapsedProjects[p.id] === true,
      }));
      const ungrouped = { id: "", name: "未分组", items: [], collapsed: this.collapsedProjects["__ungrouped__"] === true };
      const byId = Object.fromEntries(groups.map((g) => [g.id, g]));
      for (const d of this.filteredDatasets) {
        (byId[d.project] || ungrouped).items.push(d);
      }
      const out = groups.filter((g) => g.items.length || !q);  // 搜索时收起空项目
      if (ungrouped.items.length) out.push(ungrouped);
      return out;
    },
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
    dashCount() {
      return this.dashConfigs.length;
    },
    anaReady() {
      const a = this.ana, k = this.anaKind;
      if (k === "groupby") return a.by.length && a.metrics.every((m) => m.column);
      if (k === "histogram") return a.histCol;
      if (k === "value_counts") return a.vcCol;
      if (k === "trend") return a.dateCol && a.valCol;
      if (k === "kpi") return a.kpiAgg === "count" || !!a.kpiCol;
      if (k === "funnel") {
        if (a.fnMode === "columns") return a.fnCols.length >= 2;
        return !!a.fnCol && a.fnSteps.split(/[,，、]/).map((s) => s.trim()).filter(Boolean).length >= 2;
      }
      return true;
    },
    statusMissing() {
      const p = this.profile;
      if (!p.columns || !p.columns.length || !p.rows) return "0.00";
      const cells = p.columns.reduce((acc, c) => acc + (c.missing || 0), 0);
      return ((cells / (p.rows * p.columns.length)) * 100).toFixed(2);
    },
    hasViewFilters() {
      return Object.keys(this.colFilters).length > 0;
    },
    shownColValues() {
      const m = this.colMenu;
      if (!m.values) return [];
      const q = (m.search || "").trim().toLowerCase();
      if (!q) return m.values;
      return m.values.filter((v) => String(v.label).toLowerCase().includes(q));
    },
  },

  async mounted() {
    this.theme = localStorage.getItem("dh-theme") || "light";
    document.documentElement.dataset.theme = this.theme;
    this.activeProject = localStorage.getItem("dh-active-project") || "";
    try { this.collapsedProjects = JSON.parse(localStorage.getItem("dh-collapsed-projects") || "{}"); } catch (e) { this.collapsedProjects = {}; }
    await Promise.all([this.refreshDatasets(), this.loadProjects()]);

    window.addEventListener("resize", () => {
      Object.values(this._charts || {}).forEach((c) => c && c.resize());
    });
    // 看板放映模式：Esc 退出
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.showMode) this.toggleShowMode();
    });
    // 列头下拉面板：点击面板外关闭
    window.addEventListener("click", (e) => {
      if (this.colMenu.show && !e.target.closest(".col-menu") && !e.target.closest(".th-menu-btn")) {
        this.colMenu.show = false;
      }
    });
    // 全窗口拖放导入：任何位置拖入文件即可建数据集
    let dragDepth = 0;
    window.addEventListener("dragenter", (e) => {
      if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) {
        dragDepth++;
        this.dragOver = true;
      }
    });
    window.addEventListener("dragleave", () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) this.dragOver = false;
    });
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      dragDepth = 0;
      this.dragOver = false;
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) this.uploadOne(f);
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

    // 列头类型缩写：完整 dtype（如 datetime64[ns]）在窄列里会撑爆列宽
    dtypeShort(d) {
      const k = String(d || "");
      const m = {
        int64: "int", int32: "int", int16: "int", int8: "int",
        uint64: "int", uint32: "int", uint16: "int", uint8: "int",
        Int64: "int", Int32: "int", Int16: "int", Int8: "int",
        float64: "float", float32: "float", Float64: "float", Float32: "float",
        bool: "bool", boolean: "bool",
        object: "text", str: "text", string: "text", category: "cat",
        "datetime64[ns]": "datetime", datetime64: "datetime",
      };
      if (m[k] !== undefined) return m[k];
      if (k.startsWith("datetime64")) return "datetime";
      if (k.startsWith("string") || k.startsWith("large_string") || k.startsWith("str")) return "text";
      return k;
    },

    timeAgo(ts) {
      if (!ts) return "";
      const d = new Date(ts.replace(" ", "T"));
      const diff = (Date.now() - d.getTime()) / 1000;
      if (isNaN(diff)) return ts;
      if (diff < 60) return "刚刚";
      if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
      if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
      if (diff < 7 * 86400) return Math.floor(diff / 86400) + " 天前";
      return ts.slice(5, 10);
    },

    aggLabel(a) {
      return { count: "计数", sum: "求和", mean: "平均", min: "最小", max: "最大", median: "中位数", std: "标准差", nunique: "去重计数" }[a] || a;
    },

    goHome() {
      if (this.homeUrl) { location.href = this.homeUrl; return; }
      this.currentId = null;
      this.meta = {};
      this.cards = [];
      Object.values(this._charts || {}).forEach((c) => c && c.dispose());
      this._charts = {};
      this.mainTab = "table";
      this.page = 1;
      this.resetTableView();
      window.scrollTo(0, 0);
    },

    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = this.theme;
      localStorage.setItem("dh-theme", this.theme);
      // 重新渲染所有图表以应用文字颜色
      this.cards.forEach((c) => { this.renderCardChart(c); if (c.type === "insight") this.renderInsightRadar(c); });
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
      return !(R.matrix || R.box_stats || R.points || R.heatmap || R.row_labels || R.kind === "funnel");
    },

    moveCard(idx, dir) {
      const j = idx + dir;
      if (j < 0 || j >= this.cards.length) return;
      const arr = this.cards;
      [arr[idx], arr[j]] = [arr[j], arr[idx]];
      this.cards = [...arr];
    },

    // ---------- 卡片系统 ----------
    addCard(card) {
      card.id = CARD_SEQ++;
      card.time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      if (card.chartType === undefined) card.chartType = "bar";
      if (card.showDetail === undefined) card.showDetail = false;
      // 是否需要图表容器
      const R = card.payload;
      card.chartDiv = !!(R.matrix || R.box_stats || R.points || R.heatmap || R.row_labels
        || (R.rows && R.rows.length > 1 && R.columns && R.columns.some((c) => c.numeric)));
      if (card.type === "insight") card.chartDiv = false;
      if (R.chart && R.chart.type && !R.matrix && !R.box_stats) card.chartType = R.chart.type;
      this.cards.push(card);
      this.mainTab = "cards";  // 结果生成即切到结果页
      this.$nextTick(() => {
        this.renderCardChart(card);
        const el = document.querySelector(".cards-grid .card-item:last-child");
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      if (this.cards.length > 12) this.removeCard(this.cards[0]);
      return card;
    },

    removeCard(card) {
      if (this._charts) {
        for (const key of [card.id, card.id + ":deep", card.id + ":radar"]) {  // :deep/:radar = 体检卡下钻图/雷达
          if (this._charts[key]) { this._charts[key].dispose(); delete this._charts[key]; }
        }
      }
      this.cards = this.cards.filter((c) => c.id !== card.id);
    },

    setCardEl(card, el) {
      if (!this._charts) this._charts = {};
      this._cardEls = this._cardEls || {};
      this._cardEls[card.id] = el;
    },

    setCardDeepEl(card, el) {
      // 体检卡的下钻图容器（缺失矩阵）：v-if 挂载后回填，卸载时 el 为 null
      this._deepEls = this._deepEls || {};
      this._deepEls[card.id] = el;
    },

    setCardRadarEl(card, el) {
      // 体检卡的六维雷达容器：数据随卡片即到，ref 回调触发即渲染
      this._radarEls = this._radarEls || {};
      if (!el) { delete this._radarEls[card.id]; return; }
      this._radarEls[card.id] = el;
      this.$nextTick(() => this.renderInsightRadar(card));
    },

    radarDims(card) {
      const dims = card.payload && card.payload.quality_dims;
      return (dims || []).filter((d) => d.score !== null && d.score !== undefined);
    },

    renderInsightRadar(card) {
      const dims = this.radarDims(card);
      if (dims.length < 3) return;
      const key = card.id + ":radar";
      const el = (this._radarEls || {})[card.id];
      if (!el) return;
      if (!this._charts) this._charts = {};
      if (this._charts[key]) { this._charts[key].dispose(); delete this._charts[key]; }
      const T = this.chartTheme();
      const ch = echarts.init(el);
      this._charts[key] = ch;
      ch.setOption({
        color: [T.blue],
        radar: {
          indicator: dims.map((d) => ({ name: d.name, max: 100 })),
          radius: "62%", center: ["50%", "52%"],
          axisName: { color: T.txt, fontSize: 11 },
          splitLine: { lineStyle: { color: T.split } },
          axisLine: { lineStyle: { color: T.split } },
          splitArea: { show: false },
        },
        series: [{
          type: "radar",
          data: [{
            value: dims.map((d) => d.score),
            name: "质量维度",
            areaStyle: { opacity: 0.25 },
            lineStyle: { width: 2 },
          }],
        }],
        tooltip: {},
      });
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

        // 转化漏斗（运营看板）
        if (R.kind === "funnel") {
          chart.setOption({
            tooltip: { trigger: "item", formatter: (p) => {
              const s = R.steps[p.dataIndex];
              return s.conv_from_prev === null || s.conv_from_prev === undefined
                ? `${p.name}：${p.value.toLocaleString()}`
                : `${p.name}：${p.value.toLocaleString()}（转化 ${s.conv_from_prev}%）`;
            } },
            series: [{
              type: "funnel", sort: "none", gap: 4, left: "8%", width: "84%", top: 12, bottom: 12, minSize: "24%",
              label: { show: true, position: "inside", color: "#fff", fontSize: 12,
                formatter: (p) => `${p.name}\n${p.value.toLocaleString()}` },
              itemStyle: { borderColor: T.split, borderWidth: 1 },
              data: R.steps.map((s) => ({ name: s.name, value: s.count })),
            }],
          });
          return;
        }

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

    // ---------- 项目（数据集分组） ----------
    async loadProjects() {
      try { this.projects = await this.api("GET", "/api/projects"); }
      catch (e) { this.projects = []; }
    },
    parentName(parentId) {
      const p = this.datasets.find((d) => d.id === parentId);
      return p ? p.name : "";
    },
    startNewProject() {
      this.creatingProject = true;
      this.newProjectName = "";
      this.$nextTick(() => this.$refs.newPrjInput && this.$refs.newPrjInput.focus());
    },
    async confirmNewProject() {
      const name = (this.newProjectName || "").trim();
      if (!name) { this.creatingProject = false; return; }
      try {
        const prj = await this.api("POST", "/api/projects", { name });
        this.creatingProject = false;
        this.projects.push(prj);
        this.setActiveProject(prj.id);
        this.toast(`项目「${prj.name}」已创建，之后导入的表会归入其中`);
      } catch (e) { this.toast(e.message, "error"); }
    },
    async renameProject(g) {
      const name = prompt("新的项目名称：", g.name);
      if (!name || !name.trim() || name.trim() === g.name) return;
      try {
        const prj = await this.api("PATCH", `/api/projects/${g.id}`, { name: name.trim() });
        const p = this.projects.find((x) => x.id === g.id);
        if (p) p.name = prj.name;
      } catch (e) { this.toast(e.message, "error"); }
    },
    async deleteProject(g) {
      const n = g.items.length;
      const ok = confirm(`删除项目「${g.name}」？${n ? `其中 ${n} 个数据集将移回「未分组」（数据本身不受影响）。` : ""}`);
      if (!ok) return;
      try {
        await this.api("DELETE", `/api/projects/${g.id}`);
        if (this.activeProject === g.id) this.setActiveProject("");
        await Promise.all([this.loadProjects(), this.refreshDatasets()]);
        this.toast(`项目「${g.name}」已删除`);
      } catch (e) { this.toast(e.message, "error"); }
    },
    setActiveProject(id) {
      this.activeProject = id || "";
      localStorage.setItem("dh-active-project", this.activeProject);
    },
    toggleProject(id) {
      const key = id || "__ungrouped__";
      this.collapsedProjects = { ...this.collapsedProjects, [key]: !this.collapsedProjects[key] };
      localStorage.setItem("dh-collapsed-projects", JSON.stringify(this.collapsedProjects));
    },
    async moveDs(projectId) {
      try {
        const m = await this.api("POST", `/api/datasets/${this.currentId}/move`, { project: projectId || "" });
        this.meta = m;
        await this.refreshDatasets();
        const pname = projectId ? (this.projects.find((p) => p.id === projectId) || {}).name : "未分组";
        this.toast(`已移动到「${pname}」`);
      } catch (e) { this.toast(e.message, "error"); }
    },

    // ---------- 版本快照（多步回溯） ----------
    async loadVersions() {
      if (!this.currentId) return;
      try { this.versionsInfo = await this.api("GET", `/api/datasets/${this.currentId}/versions`); }
      catch (e) { this.versionsInfo = { current: -1, snapshots: [] }; }
    },
    canJump(v) {
      return v === this.versionsInfo.current || this.versionsInfo.snapshots.includes(v);
    },
    async restoreTo(v) {
      this.busy = true;
      try {
        const m = await this.api("POST", `/api/datasets/${this.currentId}/restore`, { version: v });
        this.toast(`已回到 v${v}（${m.rows} 行 × ${m.cols} 列）`);
        await this.afterDataChange(m);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    async selectDataset(id) {
      if (this.currentId === id) return;
      this.currentId = id;
      const seq = (this._dsSeq = (this._dsSeq || 0) + 1);  // 连点竞态：只认最后一次选择
      this.meta = this.datasets.find((d) => d.id === id) || {};
      this.page = 1;
      this.cards = [];
      this.resetDash();  // 换数据集：看板配置清空，进入看板 tab 时重新加载
      Object.values(this._charts || {}).forEach((c) => c && c.dispose());
      this._charts = {};
      this.cleanSel.columns = [];
      this.cleanSel.dropCols = [];
      this.cleanSel.outlierCols = [];
      this.mainTab = "table";
      this.sortCol = "";
      this.colFilters = {};
      this.suggestions = [];
      await Promise.all([this.loadRows(), this.loadProfile(), this.loadSqlTables(), this.loadVersions()]);
      if (seq !== this._dsSeq) return;  // 期间又切了别的数据集：本批结果作废
      this.initDefaults();  // 必须在 loadProfile 之后：否则默认列取到上一个数据集的列
      const m = await this.api("GET", `/api/datasets/${id}`);
      if (seq === this._dsSeq) this.meta = m;
    },

    async loadRows() {
      if (!this.currentId) return;
      this.busyRows = true;
      try {
        const p = new URLSearchParams({ page: this.page, page_size: this.pageSize });
        if (this.sortCol) { p.set("sort", this.sortCol); p.set("order", this.sortDir); }
        if (this.hasViewFilters) p.set("filters", JSON.stringify(this.colFilters));
        this.rowsData = await this.api("GET", `/api/datasets/${this.currentId}/rows?${p}`);
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
      // 数据变了：排序/筛选仍有效，但回到数据表并刷新；看板置为待重建（下次进入重放最新数据）
      this.mainTab = "table";
      this.dashLoaded = false;
      await Promise.all([this.loadRows(), this.loadProfile(), this.refreshDatasets(), this.loadVersions()]);
    },

    // ---------- 表格交互：排序 / 列筛选 ----------
    toggleSort(name) {
      if (this.sortCol !== name) { this.sortCol = name; this.sortDir = "asc"; }
      else if (this.sortDir === "asc") { this.sortDir = "desc"; }
      else { this.sortCol = ""; this.sortDir = "asc"; }
      this.page = 1;
      this.loadRows();
    },

    colSort(dir) {
      this.sortCol = this.colMenu.col;
      this.sortDir = dir;
      this.page = 1;
      this.colMenu.show = false;
      this.loadRows();
    },

    colMissingPct(name) {
      const c = (this.profile.columns || []).find((x) => x.name === name);
      return c && c.missing_pct > 0 ? c.missing_pct : (c ? null : null);
    },

    async openColMenu(ev, c) {
      const isDate = /datetime/i.test(c.dtype);
      this.colMenu = {
        show: true, col: c.name, dtype: c.dtype,
        values: isDate ? [] : null,  // 日期列值筛选不便按原值勾选，直接置空并提示
        missingCount: 0, search: "", truncated: false,
        x: Math.min(ev.clientX, window.innerWidth - 290),
        y: Math.min(ev.clientY + 12, window.innerHeight - 430),
      };
      const prof = (this.profile.columns || []).find((p) => p.name === c.name);
      if (prof) this.colMenu.missingCount = prof.missing || 0;
      if (isDate) return;
      try {
        const R = await this.api("POST", `/api/datasets/${this.currentId}/analyze`,
          { kind: "value_counts", params: { column: c.name, top: 100 } });
        if (!this.colMenu.show || this.colMenu.col !== c.name) return;  // 菜单已关/已换列
        const isNum = /^(int|uint|float|Int|Float)/.test(c.dtype);
        this.colMenu.values = R.rows.filter((r) => r[0] !== "None")
          .map((r) => ({ v: isNum ? Number(r[0]) : r[0], label: r[0], count: r[1] }));
        this.colMenu.truncated = R.rows.length >= 100;
        // 预选：该列已有筛选用已选值；否则默认全选（全选应用 = 无变化）
        const existing = this.colFilters[c.name];
        if (existing) this.colFilterSel = [...existing];
        else {
          this.colFilterSel = this.colMenu.values.map((v) => v.v);
          if (this.colMenu.missingCount > 0) this.colFilterSel.push("__NULL__");
        }
      } catch (e) {
        if (this.colMenu.show && this.colMenu.col === c.name) this.colMenu.values = [];
      }
    },

    applyColFilter() {
      const col = this.colMenu.col;
      const total = (this.colMenu.values || []).length + (this.colMenu.missingCount > 0 ? 1 : 0);
      if (!this.colFilterSel.length) {
        this.toast("至少勾选一个要保留的值（全部不选等于删光）", "error");
        return;
      }
      const next = { ...this.colFilters };
      if (this.colFilterSel.length >= total) delete next[col];  // 全选 = 无筛选
      else next[col] = [...this.colFilterSel];
      this.colFilters = next;
      this.colMenu.show = false;
      this.page = 1;
      this.loadRows();
    },

    clearColFilter(col) {
      const next = { ...this.colFilters };
      delete next[col];
      this.colFilters = next;
      this.page = 1;
      this.loadRows();
    },

    clearAllFilters() {
      this.colFilters = {};
      this.page = 1;
      this.loadRows();
    },

    resetTableView() {
      this.sortCol = "";
      this.sortDir = "asc";
      this.colFilters = {};
      this.page = 1;
      if (this.currentId) this.loadRows();
    },

    // ---------- 上传 / 导入 ----------
    uploadFile(ev) {
      const file = ev.target.files[0];
      ev.target.value = "";
      if (file) this.uploadOne(file);
    },

    async uploadOne(file) {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", "");
      fd.append("project", this.activeProject || "");
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
        const j = await this.api("POST", "/api/upload-paste", { text: this.pasteText, name: this.pasteName, project: this.activeProject || "" });
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
        const j = await this.api("POST", `/api/sample?project=${encodeURIComponent(this.activeProject || "")}`);
        this.toast(`已生成示例数据：${j.meta.rows} 行（含缺失/重复，可体验体检与清洗）`);
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
        Object.values(this._charts || {}).forEach((c) => c && c.dispose());  // 此前漏 dispose：实例随画布重建泄漏
        this._charts = {};
        this.suggestions = [];
        this.page = 1;
        this.resetTableView();
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

    // ---------- 底部（SQL/Python）与右侧（清洗/统计/采样/历史）工具面板 ----------
    switchBottomTab(k) {
      this.bottomTab = k;
      this.bottomCollapsed = false;
    },

    switchRightTab(k) {
      this.rightTab = k;
      this.rightCollapsed = false;
    },

    openBottom(k) {
      // 统一入口：sql/tf 进底部面板，其余进右侧工具栏
      if (k === "sql" || k === "tf") {
        this.bottomTab = k;
        this.bottomCollapsed = false;
      } else {
        this.rightTab = k;
        this.rightCollapsed = false;
      }
    },

    startResize(e) {
      e.preventDefault();
      const startY = e.clientY;
      const startH = this.bottomH;
      const onMove = (ev) => {
        this.bottomH = Math.max(160, Math.min(Math.round(window.innerHeight * 0.7), startH + (startY - ev.clientY)));
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },

    resetBottomH() {
      this.bottomH = 300;
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
        case "trim_whitespace": {
          if (!s.columns.length) throw new Error("请选择要去空格的列");
          return { columns: s.columns };
        }
        case "normalize_text": {
          if (!s.columns.length) throw new Error("请选择要规范化的列");
          return { columns: s.columns, empty_to_na: !!s.emptyToNa };
        }
        case "parse_number": {
          if (!s.column) throw new Error("请选择列");
          const p = { column: s.column, percent_scale: !!s.percentScale };
          if (s.newColumn.trim()) p.new_column = s.newColumn.trim();
          return p;
        }
        case "map_values": {
          if (!s.column) throw new Error("请选择列");
          const mapping = {};
          for (const line of s.mapText.split("\n")) {
            const t = line.trim();
            if (!t) continue;
            const eq = t.indexOf("=");
            if (eq <= 0) throw new Error(`映射格式应为「原值=新值」：${t}`);
            mapping[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
          }
          if (!Object.keys(mapping).length) throw new Error("请至少填写一条映射（原值=新值）");
          return { column: s.column, mapping, keep_original: true };
        }
        case "split_column": {
          if (!s.column || !s.splitSep.trim()) throw new Error("请选择列并填写分隔符");
          const p = { column: s.column, sep: s.splitSep };
          const into = s.splitInto.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
          if (into.length) p.into = into;
          return p;
        }
        case "cap_outliers": {
          if (!s.outlierCols.length) throw new Error("请选择要盖帽的数值列");
          return { columns: s.outlierCols, method: s.outlierMethod };
        }
        case "drop_high_missing": {
          if (!(s.missThreshold > 0 && s.missThreshold <= 1)) throw new Error("阈值需在 (0, 1] 之间");
          return { threshold: s.missThreshold, axis: s.missAxis };
        }
        case "unify_boolean_text": {
          if (!s.column) throw new Error("请选择列");
          return { column: s.column };
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
      a.histCol = nums[0] ? nums[0].name : "";
      a.vcCol = cats[0] ? cats[0].name : "";
      a.valCol = nums[0] ? nums[0].name : "";
      const dt = (this.profile.columns || []).find((c) => c.kind === "datetime");
      const dateLike = dt ? dt.name : (cats || []).find((c) => /日期|时间|date/i.test(c.name))?.name || "";
      a.dateCol = dateLike;
    },

    async runAnalyze() {
      const a = this.ana, k = this.anaKind;
      let params = {};
      if (k === "groupby") params = { by: a.by, metrics: a.metrics.filter((m) => m.column) };
      else if (k === "corr") params = { columns: a.corrCols.length ? a.corrCols : undefined, method: a.corrMethod };
      else if (k === "histogram") params = { column: a.histCol, bins: a.bins };
      else if (k === "boxplot") params = { columns: a.boxCols.length ? a.boxCols : undefined };
      else if (k === "value_counts") params = { column: a.vcCol, top: a.top };
      else if (k === "trend") params = { date_column: a.dateCol, value_column: a.valCol, freq: a.freq, agg: a.agg };
      else if (k === "outliers") params = { columns: a.boxCols.length ? a.boxCols : undefined, method: a.outMethod };
      else if (k === "kpi") params = { value_column: a.kpiCol, agg: a.kpiAgg, date_column: a.kpiAgg === "count" ? "" : a.kpiDate };
      else if (k === "funnel") {
        params = a.fnMode === "columns"
          ? { mode: "columns", columns: a.fnCols }
          : { mode: "events", column: a.fnCol, steps: a.fnSteps.split(/[,，、]/).map((s) => s.trim()).filter(Boolean), user_column: a.fnUser };
      }
      await this.doAnalyze(k, params, k === "kpi" ? "🎯" : (k === "funnel" ? "⏬" : "📈"));
    },

    async doAnalyze(kind, params, icon, span2 = false) {
      this.busy = true;
      try {
        const R = await this.api("POST", `/api/datasets/${this.currentId}/analyze`, { kind, params });
        const titleMap = {
          groupby: "分组聚合", corr: "相关性分析", histogram: "直方图",
          boxplot: "箱线图", value_counts: "频次统计", describe: "汇总统计",
          trend: "时间趋势", outliers: "异常值检测",
          kpi: "KPI 指标", funnel: "转化漏斗",
        };
        const card = this.addCard({ type: kind === "kpi" ? "kpi" : "table", icon, title: titleMap[kind] || kind, payload: R, span2 });
        card._ana = { kind, params };  // 可重放配置：钉看板时保存
        if (kind === "funnel") {  // 漏斗无表格行，仅图表（同步置位赶在 addCard 的 nextTick 渲染前）
          card.chartDiv = true;
          card.chartType = "funnel";
        }
        this.syncResultPins();  // 与看板配置比对，已钉过的组合直接显示「已钉」
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

    // ---------- 运营看板（钉卡配置存后端，重放重建） ----------
    async ensureDash() {
      if (this.dashLoaded) {
        this.$nextTick(() => this.dashCards.forEach((c) => {
          if (c.chartDiv) this.renderCardChart(c);
          if (c.type === "insight") this.renderInsightRadar(c);
        }));
        return;
      }
      this.dashLoading = true;
      try {
        const R = await this.api("GET", `/api/datasets/${this.currentId}/dashboard`);
        this.dashConfigs = R.cards || [];
        this.syncResultPins();
        await this.rebuildDash();
        this.dashLoaded = true;
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.dashLoading = false; }
    },

    resetDash() {
      (this.dashCards || []).forEach((c) => {
        if (this._charts && this._charts[c.id]) { this._charts[c.id].dispose(); delete this._charts[c.id]; }
      });
      this.dashCards = [];
      this.dashConfigs = [];
      this.dashLoaded = false;
    },

    async rebuildDash() {
      // 清掉旧图实例再按配置重放——数据更新后看板自然反映最新值
      (this.dashCards || []).forEach((c) => {
        if (this._charts && this._charts[c.id]) { this._charts[c.id].dispose(); delete this._charts[c.id]; }
      });
      this.dashCards = [];
      const built = [];
      for (const cfg of this.dashConfigs) {
        try {
          const payload = cfg.kind === "insight"
            ? await this.api("GET", `/api/datasets/${this.currentId}/insights`)
            : await this.api("POST", `/api/datasets/${this.currentId}/analyze`, { kind: cfg.kind, params: cfg.params });
          built.push(this.makeDashCard(cfg, payload));
        } catch (e) {
          built.push({ id: "dash-err-" + built.length, type: "table", icon: "⚠️", title: cfg.title, time: "",
            span2: !!cfg.span2, chartDiv: false, payload: { note: "重建失败：" + e.message } });
        }
      }
      this.dashCards = built;
      this.$nextTick(() => built.forEach((c) => {
        if (c.chartDiv) this.renderCardChart(c);
        if (c.type === "insight") this.renderInsightRadar(c);
      }));
    },

    makeDashCard(cfg, payload) {
      const card = {
        id: "dash-" + CARD_SEQ++,
        type: cfg.kind === "kpi" ? "kpi" : (cfg.kind === "insight" ? "insight" : "table"),
        icon: cfg.icon, title: cfg.title,
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        span2: !!cfg.span2, payload, chartType: "bar", showDetail: false,
        _ana: { kind: cfg.kind, params: cfg.params }, pinned: true,
      };
      if (cfg.kind === "funnel") { card.chartDiv = true; card.chartType = "funnel"; }
      else if (cfg.kind === "insight") card.chartDiv = false;
      else {
        const R = payload;
        card.chartDiv = !!(R.matrix || R.box_stats || R.points || R.heatmap || R.row_labels || R.kind === "funnel"
          || (R.rows && R.rows.length > 1 && R.columns && R.columns.some((c) => c.numeric)));
        if (R.chart && R.chart.type && !R.matrix && !R.box_stats) card.chartType = R.chart.type;
      }
      return card;
    },

    async pinCard(card) {
      if (!card._ana) return;
      this.dashConfigs.push({ kind: card._ana.kind, params: card._ana.params, title: card.title, icon: card.icon, span2: !!card.span2 });
      card.pinned = true;
      await this.persistDash();
      this.rebuildDash();
      this.toast("已钉到看板");
    },

    async unpinCard(card) {
      const key = JSON.stringify(card._ana ? card._ana.params || {} : {});
      const idx = this.dashConfigs.findIndex((c) => c.kind === card._ana.kind && JSON.stringify(c.params || {}) === key);
      if (idx >= 0) this.dashConfigs.splice(idx, 1);
      this.syncResultPins();
      await this.persistDash();
      this.rebuildDash();
    },

    async persistDash() {
      try { await this.api("PUT", `/api/datasets/${this.currentId}/dashboard`, { cards: this.dashConfigs }); }
      catch (e) { this.toast(e.message, "error"); }
    },

    // 结果页卡片 📌 状态与配置表比对（kind+params 相同 = 同一张钉卡）
    syncResultPins() {
      const key = (a) => (a ? a.kind + "|" + JSON.stringify(a.params || {}) : "");
      const keys = new Set(this.dashConfigs.map((c) => key({ kind: c.kind, params: c.params })));
      (this.cards || []).forEach((c) => { c.pinned = !!(c._ana && keys.has(key(c._ana))); });
    },

    async refreshDash() {
      this.dashLoading = true;
      try { await this.rebuildDash(); } finally { this.dashLoading = false; }
    },

    toggleShowMode() {
      this.showMode = !this.showMode;
      document.body.classList.toggle("showmode", this.showMode);
      // 侧栏隐藏后容器尺寸变化，等过渡结束再 resize 图表
      this.$nextTick(() => setTimeout(() => {
        Object.values(this._charts || {}).forEach((c) => c && c.resize());
      }, 260));
    },

    fmtKpi(v) {
      if (v === null || v === undefined) return "—";
      if (typeof v !== "number") return String(v);
      return v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    },

    kpiAggLabel(a) {
      return { sum: "求和", mean: "平均", count: "行数" }[a] || a;
    },

    // ---------- 列头快捷动作 ----------
    colProfile() {
      const col = this.colMenu.col;
      this.colMenu.show = false;
      this.doAnalyze("value_counts", { column: col, top: 15 }, "📊");
    },

    colClean() {
      const col = this.colMenu.col;
      this.colMenu.show = false;
      this.cleanSel.column = col;
      this.cleanOp = "filter_rows";
      this.openBottom("clean");
      this.toast(`已把「${col}」填入清洗面板的筛选条件`);
    },

    colSql() {
      const col = this.colMenu.col;
      this.colMenu.show = false;
      this.sqlQuery = `SELECT "${col}", COUNT(*) AS n FROM df GROUP BY "${col}" ORDER BY n DESC LIMIT 20`;
      this.openBottom("sql");
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
      const iconMap = { trend: "📉", groupby: "📈", value_counts: "🥧", histogram: "📊", boxplot: "📦", corr: "🔗" };
      await this.doAnalyze(s.kind, s.params, iconMap[s.kind] || "🎯");
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

    // ---------- 采样 ----------
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

    // ---------- 数据体检 ----------
    catLabel(cat) {
      return {
        structure: "结构", missing: "缺失", type: "类型", text: "格式",
        category: "类别", numeric: "数值", datetime: "日期", consistency: "一致性",
      }[cat] || cat;
    },

    async runInsights() {
      this.busy = true;
      try {
        const R = await this.api("GET", `/api/datasets/${this.currentId}/insights`);
        const card = this.addCard({ type: "insight", icon: "🩺", title: "数据体检报告", payload: R, span2: true });
        card._ana = { kind: "insight", params: {} };  // 体检卡同样可钉到看板
        const n = (R.findings || []).length;
        this.toast(n ? `体检完成：发现 ${n} 个问题，详见结果页` : "体检完成：未发现问题");
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // 体检问题一键修复：把后端建议的 op+params 预填进清洗面板，用户确认后才执行
    applyFix(fix) {
      const p = fix.params || {};
      const s = this.cleanSel;
      this.cleanOp = fix.op;
      // 重置多选字段，避免上一个操作的残留选择混入
      s.columns = []; s.column = ""; s.dropCols = []; s.outlierCols = [];
      switch (fix.op) {
        case "drop_duplicates": s.columns = p.columns || []; break;
        case "drop_columns": s.dropCols = p.columns || []; break;
        case "drop_high_missing": s.missThreshold = p.threshold ?? 0.5; s.missAxis = p.axis || "column"; break;
        case "cast_type": s.column = p.column || ""; s.to = p.to || "float"; s.format = p.format || ""; break;
        case "parse_number": s.column = p.column || ""; s.percentScale = !!p.percent_scale; s.newColumn = p.new_column || ""; break;
        case "trim_whitespace": case "normalize_text": s.columns = p.columns || []; s.emptyToNa = !!p.empty_to_na; break;
        case "cap_outliers": case "drop_outliers": s.outlierCols = p.columns || []; s.outlierMethod = p.method || "iqr"; break;
        case "map_values": {
          s.column = p.column || "";
          s.mapText = Object.entries(p.mapping || {}).map(([k, v]) => `${k}=${v}`).join("\n");
          break;
        }
        case "unify_boolean_text": s.column = p.column || ""; break;
        case "rename_columns": this.renameMap = { ...(p.mapping || {}) }; break;
      }
      this.openBottom("clean");
      this.toast(`已把「${fix.label}」填入清洗面板，请检查参数后点「执行」`);
    },

    async loadDeep(kind) {
      this.busy = true;
      try {
        const card = [...this.cards].reverse().find((c) => c.type === "insight");
        if (!card) { this.toast("请先运行数据体检", "error"); return; }
        if (kind === "missing") {
          card.deepData = await this.api("GET", `/api/datasets/${this.currentId}/missing-matrix`);
          card.deep = "missing";
          await this.$nextTick();
          // 体检卡 chartDiv=false，缺失矩阵热力图单独渲染到「本卡」的深度容器
          const el = (this._deepEls || {})[card.id];
          if (el) {
            if (!this._charts) this._charts = {};
            if (this._charts[card.id + ':deep']) this._charts[card.id + ':deep'].dispose();
            const T = this.chartTheme();
            const D = card.deepData;
            const data = [];
            D.values.forEach((row, i) => row.forEach((v, j) => data.push([j, i, v])));
            const ch = echarts.init(el);
            this._charts[card.id + ':deep'] = ch;
            ch.setOption({
              tooltip: { position: "top", formatter: (p2) => `${D.columns[p2.value[0]]} · ${D.row_labels[p2.value[1]]}: ${p2.value[2]}%` },
              grid: { left: 80, bottom: 55, right: 15, top: 10 },
              xAxis: { type: "category", data: D.columns, axisLabel: { rotate: 40, fontSize: 10, color: T.txt } },
              yAxis: { type: "category", data: D.row_labels, axisLabel: { fontSize: 9, color: T.txt } },
              visualMap: { min: 0, max: 100, orient: "horizontal", left: "center", bottom: 0, textStyle: { color: T.txt }, itemWidth: 12, inRange: { color: ["#ffffff", "#ff9500"] } },
              series: [{ type: "heatmap", data }],
            });
          }
        } else {
          card.deepData = await this.api("GET", `/api/datasets/${this.currentId}/duplicates`);
          card.deep = "dup";
        }
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
          code: this.code,  // 快照：卡片上的「应用」必须重放生成该预览的代码，而非编辑器当前内容
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
        const r = await this.api("POST", `/api/datasets/${this.currentId}/transform`, { code: card.code, apply: true });
        card.applied = true;
        card.title = "Python 变换（已应用）";
        this.toast(`已应用：${r.old_shape.rows} 行 → ${r.shape.rows} 行`);
        await this.afterDataChange(r.meta);
      } catch (e) { this.toast(e.message, "error"); }
      finally { this.busy = false; }
    },

    // ---------- MCP ----------
    copyMcpUrl() {
      const url = this.mcpUrl;
      const done = () => this.toast(`已复制：${url}`);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, () => this.toast(url));
      } else {
        this.toast(url);
      }
    },
  },
});

app.mount("#app");
