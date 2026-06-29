"use strict";

const SESSION_KEY = "coindcx_report_session";
const LATEST_REPORT_KEY = "coindcx_latest_report";

const state = {
  sessionId: sessionStorage.getItem(SESSION_KEY) || "",
  latestReportId: sessionStorage.getItem(LATEST_REPORT_KEY) || "",
  latestSummary: null,
  latestDaywise: [],
  latestTransactionsPreview: [],
  latestTokenBreakdown: [],
  latestColumns: { transactions: [], daywise: [], token_breakdown: [] },
  latestFiles: {},
  charts: {},
  sort: {},
  busy: false,
  marginCurrency: "INR",
};

const $ = (id) => document.getElementById(id);
const elements = {
  authForm: $("authForm"),
  authButton: $("authButton"),
  apiKey: $("apiKey"),
  apiSecret: $("apiSecret"),
  authMessage: $("authMessage"),
  connectionPill: $("connectionPill"),
  connectionText: $("connectionText"),
  logoutButton: $("logoutButton"),
  progressPanel: $("progressPanel"),
  progressTitle: $("progressTitle"),
  progressPercent: $("progressPercent"),
  progressBar: $("progressBar"),
  logList: $("logList"),
  dashboard: $("dashboard"),
  recentReports: $("recentReports"),
};

function setConnection(online, message = online ? "Connected" : "Not connected") {
  elements.connectionPill.classList.toggle("is-online", online);
  elements.connectionPill.classList.toggle("is-offline", !online);
  elements.connectionText.textContent = message;
  elements.logoutButton.disabled = !online || state.busy;
  $("sessionHint").textContent = online
    ? "Connected. Select a mode and generate your report."
    : "Connect your API session to generate reports.";
  updateActionState();
}

function updateActionState() {
  const connected = Boolean(state.sessionId);
  $("generateMulti").disabled = !connected || state.busy;
  $("generateSingle").disabled = !connected || state.busy;
  $("generateDaily").disabled = !connected || !state.latestReportId || state.busy;
  elements.authButton.disabled = state.busy;
  elements.logoutButton.disabled = !connected || state.busy;
}

function showToast(message, type = "info", timeout = 4200) {
  const toast = document.createElement("div");
  toast.className = `toast is-${type}`;
  const text = document.createElement("span");
  text.textContent = message;
  toast.append(text);
  $("toastRegion").append(toast);
  window.setTimeout(() => toast.remove(), timeout);
}

async function apiFetch(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (error) {
    throw new Error("Could not reach the local report server.");
  }

  let payload = {};
  try {
    payload = await response.json();
  } catch (_) {
    throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`);
  }
  if (!response.ok || payload.success === false) {
    const error = new Error(payload.message || `Request failed (HTTP ${response.status}).`);
    error.details = payload.details || {};
    error.status = response.status;
    throw error;
  }
  return payload;
}

function selectedMargin() {
  return document.querySelector('input[name="marginCurrency"]:checked').value;
}

function parseList(value) {
  return [...new Set(value.split(/[,\s]+/).map((item) => item.trim().toUpperCase()).filter(Boolean))];
}

function parseRawList(value) {
  return [...new Set(value.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean))];
}

function parsePositiveNumber(id, label, { integer = false, optional = false } = {}) {
  const raw = $(id).value.trim();
  if (!raw && optional) return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) {
    throw new Error(`${label} must be a positive ${integer ? "whole number" : "number"}.`);
  }
  return value;
}

function validateDateText(value, label) {
  if (!/^\d{2}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) {
    throw new Error(`${label} must use DD/MM/YY HH:MM:SS.`);
  }
  return value;
}

function commonReportPayload() {
  if (!state.sessionId) throw new Error("Connect your CoinDCX session first.");
  const margin = selectedMargin();
  state.marginCurrency = margin;
  return {
    session_id: state.sessionId,
    margin_currency: margin,
    from_ist: validateDateText($("fromIST").value.trim(), "From IST"),
    to_ist: validateDateText($("toIST").value.trim(), "To IST"),
    include_zero_amounts: $("includeZero").checked,
    exclude_liquidate_stage: $("excludeLiquidate").checked,
    force_exclude_xau: $("excludeXAU").checked,
    excluded_position_ids: parseRawList($("excludedPositionIds").value),
    initial_capital: parsePositiveNumber("initialCapital", "Initial capital"),
    max_pages: parsePositiveNumber("maxPages", "Max pages", { integer: true, optional: true }),
    page_size: parsePositiveNumber("pageSize", "Page size", { integer: true }),
  };
}

function timeLabel() {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

function setProgress(percent, title) {
  const normalized = Math.max(0, Math.min(100, Math.round(percent)));
  elements.progressBar.style.width = `${normalized}%`;
  elements.progressPercent.textContent = `${normalized}%`;
  if (title) elements.progressTitle.textContent = title;
}

function addLog(message) {
  if (elements.logList.children.length === 1 && elements.logList.textContent.includes("Waiting for")) {
    elements.logList.replaceChildren();
  }
  const item = document.createElement("li");
  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = timeLabel();
  const text = document.createElement("span");
  text.textContent = message;
  item.append(time, text);
  elements.logList.append(item);
  elements.logList.scrollTop = elements.logList.scrollHeight;
}

function markLoading(loading) {
  document.querySelectorAll(".kpi-card strong").forEach((node) => node.classList.toggle("skeleton", loading));
}

async function runReport(button, endpoint, payload) {
  state.busy = true;
  updateActionState();
  button.classList.add("is-loading");
  elements.logList.replaceChildren();
  setProgress(7, "Validating request");
  addLog("Validated local form inputs.");
  markLoading(true);

  const stages = [
    [18, "Signing read-only request"],
    [34, "Fetching transaction pages"],
    [55, "Cleaning and filtering rows"],
    [72, "Calculating report metrics"],
    [86, "Exporting report files"],
  ];
  let stageIndex = 0;
  const timer = window.setInterval(() => {
    if (stageIndex < stages.length) {
      const [percent, label] = stages[stageIndex++];
      setProgress(percent, label);
      addLog(label);
    }
  }, 720);

  try {
    const result = await apiFetch(endpoint, { method: "POST", body: JSON.stringify(payload) });
    window.clearInterval(timer);
    (result.messages || []).forEach(addLog);
    setProgress(100, "Report complete");
    state.latestReportId = result.report_id;
    sessionStorage.setItem(LATEST_REPORT_KEY, state.latestReportId);
    $("dailyReportId").value = state.latestReportId;
    renderReport(result);
    await refreshRecentReports();
    showToast("Report generated successfully.", "success");
    elements.dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    window.clearInterval(timer);
    setProgress(100, "Report failed");
    elements.progressBar.style.background = "var(--red)";
    addLog(error.message);
    showToast(error.message, "error", 6000);
    if (error.status === 401) clearLocalSession();
  } finally {
    window.setTimeout(() => { elements.progressBar.style.background = ""; }, 900);
    markLoading(false);
    state.busy = false;
    button.classList.remove("is-loading");
    updateActionState();
  }
}

function currencyFormatter(value, maximumFractionDigits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  if (state.marginCurrency === "INR") {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits,
    }).format(number);
  }
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(number)} USDT`;
}

function plainNumber(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(Number(value));
}

function percentage(value, { ratio = false } = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value) * (ratio ? 100 : 1);
  return `${plainNumber(number, 2)}%`;
}

function setKPI(id, value, signValue = null, negativeWhenPositive = false) {
  const node = $(id);
  node.textContent = value;
  const card = node.closest(".kpi-card");
  card.classList.remove("is-positive", "is-negative");
  if (signValue === null || !Number.isFinite(Number(signValue)) || Number(signValue) === 0) return;
  const negative = negativeWhenPositive ? Number(signValue) > 0 : Number(signValue) < 0;
  card.classList.add(negative ? "is-negative" : "is-positive");
}

function renderKPIs(summary) {
  setKPI("kpiNet", currencyFormatter(summary.net_pnl), summary.net_pnl);
  setKPI("kpiGross", currencyFormatter(summary.gross_pnl), summary.gross_pnl);
  setKPI("kpiFees", currencyFormatter(summary.total_fees), null);
  setKPI("kpiROI", percentage(summary.roi_pct), summary.roi_pct);
  setKPI("kpiWinRate", percentage(summary.win_rate, { ratio: true }), null);
  setKPI("kpiTrades", plainNumber(summary.total_estimated_trades, 0), null);
  setKPI("kpiDrawdown", currencyFormatter(summary.max_equity_drawdown_abs), summary.max_equity_drawdown_abs, true);
  setKPI("kpiSharpe", plainNumber(summary.annualized_return_sharpe, 3), summary.annualized_return_sharpe);
}

const exportLabels = {
  clean_transactions_csv: "Clean transactions CSV",
  daywise_csv: "Daywise stats CSV",
  token_breakdown_csv: "Token breakdown CSV",
  summary_json: "Summary JSON",
};

function renderExports(files) {
  const container = $("exportButtons");
  container.replaceChildren();
  Object.entries(files || {}).forEach(([key, href]) => {
    if (!href) return;
    const link = document.createElement("a");
    link.className = "download-button";
    link.href = href;
    link.textContent = exportLabels[key] || key.replaceAll("_", " ");
    link.setAttribute("download", "");
    container.append(link);
  });
  if (!container.children.length) {
    const empty = document.createElement("p");
    empty.className = "empty-copy";
    empty.textContent = "No files were generated for this result.";
    container.append(empty);
  }
}

function renderReport(result) {
  state.latestSummary = result.summary || {};
  state.latestDaywise = result.preview?.daywise || [];
  state.latestTransactionsPreview = result.preview?.transactions || [];
  state.latestTokenBreakdown = result.preview?.token_breakdown || [];
  state.latestColumns = result.columns || { transactions: [], daywise: [], token_breakdown: [] };
  state.latestFiles = result.files || {};
  elements.dashboard.hidden = false;
  $("reportMeta").textContent = `${result.report_id} · ${state.latestSummary.total_transactions || 0} rows · ${state.marginCurrency}`;
  renderKPIs(state.latestSummary);
  renderExports(state.latestFiles);
  renderAllTables();
  renderCharts();
}

function normalizedCell(value) {
  if (value === null || value === undefined || (typeof value === "number" && !Number.isFinite(value))) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return plainNumber(value, 6);
  if (typeof value === "object") return JSON.stringify(value);
  const string = String(value);
  return string.length > 90 ? `${string.slice(0, 87)}…` : string;
}

function isPerformanceColumn(column) {
  const name = column.toLowerCase();
  return ["pnl", "amount", "return", "gross", "net", "funding_gross_sum"].some((part) => name.includes(part))
    && !name.includes("count") && !name.includes("drawdown");
}

function renderTable(tableId, rows, columns, key) {
  const table = $(tableId);
  table.replaceChildren();
  const search = $("tableSearch").value.trim().toLowerCase();
  const limit = Number($("previewCount").value) || 50;
  let visible = rows.filter((row) => !search || Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(search)));
  const sort = state.sort[key];
  if (sort) {
    visible = [...visible].sort((left, right) => {
      const a = left[sort.column];
      const b = right[sort.column];
      const numericA = Number(a);
      const numericB = Number(b);
      let compared;
      if (Number.isFinite(numericA) && Number.isFinite(numericB)) compared = numericA - numericB;
      else compared = String(a ?? "").localeCompare(String(b ?? ""));
      return sort.direction === "asc" ? compared : -compared;
    });
  }
  visible = visible.slice(0, limit);

  if (!columns.length) {
    const body = document.createElement("tbody");
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty";
    cell.textContent = "No data available for this table.";
    row.append(cell);
    body.append(row);
    table.append(body);
    return;
  }

  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const cell = document.createElement("th");
    const active = sort?.column === column;
    cell.textContent = `${column.replaceAll("_", " ")}${active ? (sort.direction === "asc" ? " ↑" : " ↓") : ""}`;
    cell.title = `Sort by ${column}`;
    cell.addEventListener("click", () => {
      state.sort[key] = { column, direction: active && sort.direction === "asc" ? "desc" : "asc" };
      renderAllTables();
    });
    headRow.append(cell);
  });
  head.append(headRow);

  const body = document.createElement("tbody");
  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columns.length;
    cell.className = "table-empty";
    cell.textContent = search ? "No visible rows match your filter." : "No rows in this result.";
    row.append(cell);
    body.append(row);
  } else {
    visible.forEach((data) => {
      const row = document.createElement("tr");
      columns.forEach((column) => {
        const cell = document.createElement("td");
        const value = data[column];
        cell.textContent = normalizedCell(value);
        cell.title = value === null || value === undefined ? "" : String(value);
        if (isPerformanceColumn(column) && Number.isFinite(Number(value))) {
          if (Number(value) > 0) cell.classList.add("is-positive");
          if (Number(value) < 0) cell.classList.add("is-negative");
        }
        row.append(cell);
      });
      body.append(row);
    });
  }
  table.append(head, body);
}

function renderAllTables() {
  renderTable("daywiseTable", state.latestDaywise, state.latestColumns.daywise || [], "daywise");
  renderTable("tokenTable", state.latestTokenBreakdown, state.latestColumns.token_breakdown || [], "token");
  renderTable("transactionTable", state.latestTransactionsPreview, state.latestColumns.transactions || [], "transactions");
}

const chartPalette = {
  green: "#54e3a5",
  greenFill: "rgba(84, 227, 165, .12)",
  red: "#ff7185",
  redFill: "rgba(255, 113, 133, .12)",
  cyan: "#66d9e8",
  cyanFill: "rgba(102, 217, 232, .12)",
  amber: "#f1b86b",
  grid: "rgba(165, 210, 196, .08)",
  text: "#718d85",
};

function chartOptions({ percent = false, beginAtZero = true } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "rgba(7, 18, 16, .96)",
        borderColor: "rgba(165, 210, 196, .18)",
        borderWidth: 1,
        titleColor: "#eff7f4",
        bodyColor: "#b5c9c3",
        padding: 10,
        callbacks: {
          label(context) {
            const value = context.parsed.y ?? context.parsed;
            return percent ? `${plainNumber(value, 3)}%` : currencyFormatter(value, 4);
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: chartPalette.text, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 9 } },
        border: { color: chartPalette.grid },
      },
      y: {
        beginAtZero,
        grid: { color: chartPalette.grid },
        ticks: {
          color: chartPalette.text,
          font: { size: 9 },
          callback: (value) => percent ? `${plainNumber(value, 1)}%` : plainNumber(value, 2),
        },
        border: { display: false },
      },
    },
  };
}

function destroyChart(id) {
  if (state.charts[id]?.destroy) state.charts[id].destroy();
  delete state.charts[id];
}

function renderCanvasFallback(id, labels, values, type = "line", colors = []) {
  destroyChart(id);
  const canvas = $(id);
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(300, rect.width || 600);
  const height = Math.max(180, rect.height || 240);
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  if (!values.length) {
    ctx.fillStyle = chartPalette.text;
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No data for this chart", width / 2, height / 2);
    return;
  }

  if (type === "doughnut") {
    const total = values.reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0) || 1;
    let start = -Math.PI / 2;
    values.forEach((value, index) => {
      const angle = Math.max(0, Number(value) || 0) / total * Math.PI * 2;
      ctx.beginPath();
      ctx.strokeStyle = colors[index] || chartPalette.green;
      ctx.lineWidth = 24;
      ctx.arc(width / 2, height / 2, Math.min(width, height) * .24, start, start + angle);
      ctx.stroke();
      start += angle;
    });
    return;
  }

  const padding = { top: 15, right: 12, bottom: 25, left: 42 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const numeric = values.map((value) => Number(value) || 0);
  const min = Math.min(0, ...numeric);
  const max = Math.max(0, ...numeric);
  const span = max - min || 1;
  const y = (value) => padding.top + (max - value) / span * chartHeight;
  const baseline = y(0);
  ctx.strokeStyle = chartPalette.grid;
  ctx.beginPath();
  ctx.moveTo(padding.left, baseline);
  ctx.lineTo(width - padding.right, baseline);
  ctx.stroke();

  if (type === "bar") {
    const slot = chartWidth / numeric.length;
    numeric.forEach((value, index) => {
      const barWidth = Math.max(2, slot * .62);
      const top = Math.min(y(value), baseline);
      ctx.fillStyle = colors[index] || (value >= 0 ? chartPalette.green : chartPalette.red);
      ctx.fillRect(padding.left + index * slot + (slot - barWidth) / 2, top, barWidth, Math.max(1, Math.abs(y(value) - baseline)));
    });
  } else {
    ctx.beginPath();
    ctx.strokeStyle = colors[0] || chartPalette.cyan;
    ctx.lineWidth = 2;
    numeric.forEach((value, index) => {
      const x = padding.left + index / Math.max(1, numeric.length - 1) * chartWidth;
      if (index === 0) ctx.moveTo(x, y(value)); else ctx.lineTo(x, y(value));
    });
    ctx.stroke();
  }
}

function createChart(id, config, fallback) {
  destroyChart(id);
  if (window.Chart) {
    state.charts[id] = new window.Chart($(id), config);
  } else {
    renderCanvasFallback(id, fallback.labels, fallback.values, fallback.type, fallback.colors);
  }
}

function tokenData() {
  if (state.latestTokenBreakdown.length) {
    return {
      labels: state.latestTokenBreakdown.map((row) => row.pair),
      values: state.latestTokenBreakdown.map((row) => Number(row.net_pnl) || 0),
    };
  }
  const grouped = new Map();
  state.latestTransactionsPreview.forEach((row) => {
    if (!row.pair) return;
    grouped.set(row.pair, (grouped.get(row.pair) || 0) + (Number(row.net_amount) || 0));
  });
  return { labels: [...grouped.keys()], values: [...grouped.values()] };
}

function renderCharts() {
  const daily = state.latestDaywise;
  const labels = daily.map((row) => row.date || "—");
  const dailyNet = daily.map((row) => Number(row.net_pnl) || 0);
  const cumulative = daily.map((row) => Number(row.cum_net_pnl) || 0);
  const drawdown = daily.map((row) => -(Number(row.equity_drawdown_pct) || 0));
  const fees = daily.map((row) => Number(row.total_fees) || 0);
  const tokens = tokenData();

  createChart("dailyNetChart", {
    type: "bar",
    data: { labels, datasets: [{ data: dailyNet, backgroundColor: dailyNet.map((value) => value >= 0 ? "rgba(84,227,165,.72)" : "rgba(255,113,133,.72)"), borderRadius: 4, maxBarThickness: 28 }] },
    options: chartOptions(),
  }, { labels, values: dailyNet, type: "bar" });

  createChart("cumulativeChart", {
    type: "line",
    data: { labels, datasets: [{ data: cumulative, borderColor: chartPalette.cyan, backgroundColor: chartPalette.cyanFill, fill: true, tension: .28, pointRadius: cumulative.length > 45 ? 0 : 2, borderWidth: 2 }] },
    options: chartOptions({ beginAtZero: false }),
  }, { labels, values: cumulative, type: "line", colors: [chartPalette.cyan] });

  createChart("drawdownChart", {
    type: "line",
    data: { labels, datasets: [{ data: drawdown, borderColor: chartPalette.red, backgroundColor: chartPalette.redFill, fill: true, tension: .2, pointRadius: 0, borderWidth: 1.8 }] },
    options: chartOptions({ percent: true }),
  }, { labels, values: drawdown, type: "line", colors: [chartPalette.red] });

  createChart("tokenChart", {
    type: "bar",
    data: { labels: tokens.labels, datasets: [{ data: tokens.values, backgroundColor: tokens.values.map((value) => value >= 0 ? "rgba(84,227,165,.68)" : "rgba(255,113,133,.68)"), borderRadius: 4 }] },
    options: { ...chartOptions(), indexAxis: "y" },
  }, { labels: tokens.labels, values: tokens.values, type: "bar" });

  const wins = Number(state.latestSummary?.total_wins) || 0;
  const losses = Number(state.latestSummary?.total_losses) || 0;
  createChart("winLossChart", {
    type: "doughnut",
    data: { labels: ["Wins", "Losses"], datasets: [{ data: [wins, losses], backgroundColor: [chartPalette.green, chartPalette.red], borderColor: "#102321", borderWidth: 4, hoverOffset: 3 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "70%", plugins: { legend: { display: true, position: "bottom", labels: { color: chartPalette.text, boxWidth: 8, boxHeight: 8, padding: 18, font: { size: 9 } } }, tooltip: { backgroundColor: "rgba(7,18,16,.96)" } } },
  }, { labels: ["Wins", "Losses"], values: [wins, losses], type: "doughnut", colors: [chartPalette.green, chartPalette.red] });

  createChart("feeChart", {
    type: "line",
    data: { labels, datasets: [{ data: fees, borderColor: chartPalette.amber, backgroundColor: "rgba(241,184,107,.1)", fill: true, tension: .25, pointRadius: fees.length > 45 ? 0 : 2, borderWidth: 1.8 }] },
    options: chartOptions(),
  }, { labels, values: fees, type: "line", colors: [chartPalette.amber] });
}

function formatIST(date) {
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]));
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.day}/${parts.month}/${parts.year} ${hour}:${parts.minute}:${parts.second}`;
}

function setDateRange(daysBack = 7, todayOnly = false) {
  const now = new Date();
  if (todayOnly) {
    const current = formatIST(now);
    $("fromIST").value = `${current.slice(0, 8)} 00:00:00`;
    $("toIST").value = current;
  } else {
    $("fromIST").value = formatIST(new Date(now.getTime() - daysBack * 86_400_000));
    $("toIST").value = formatIST(now);
  }
}

function clearLocalSession() {
  state.sessionId = "";
  state.latestReportId = "";
  sessionStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(LATEST_REPORT_KEY);
  elements.apiKey.value = "";
  elements.apiSecret.value = "";
  $("dailyReportId").value = "";
  setConnection(false);
}

async function refreshRecentReports() {
  if (!state.sessionId) return;
  try {
    const result = await apiFetch(`/api/reports/recent?session_id=${encodeURIComponent(state.sessionId)}`);
    renderRecent(result.reports || []);
  } catch (error) {
    if (error.status === 401) clearLocalSession();
  }
}

function renderRecent(reports) {
  elements.recentReports.replaceChildren();
  if (!reports.length) {
    const empty = document.createElement("p");
    empty.className = "empty-copy";
    empty.textContent = "Reports created in this session will appear here.";
    elements.recentReports.append(empty);
    return;
  }
  reports.forEach((report) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "recent-item";
    item.title = "Use this report for daily conversion";
    const id = document.createElement("strong");
    id.textContent = report.report_id;
    const date = document.createElement("small");
    date.textContent = new Date(report.created_at).toLocaleString();
    const pnl = document.createElement("span");
    pnl.className = "recent-pnl";
    pnl.textContent = currencyFormatter(report.net_pnl);
    if (Number(report.net_pnl) > 0) pnl.style.color = "var(--green)";
    if (Number(report.net_pnl) < 0) pnl.style.color = "var(--red)";
    item.append(id, pnl, date);
    item.addEventListener("click", () => {
      state.latestReportId = report.report_id;
      sessionStorage.setItem(LATEST_REPORT_KEY, report.report_id);
      $("dailyReportId").value = report.report_id;
      document.querySelector('[data-tab="dailyPanel"]').click();
      updateActionState();
      showToast("Selected report for daily conversion.");
    });
    elements.recentReports.append(item);
  });
}

async function restoreSession() {
  if (!state.sessionId) {
    setConnection(false);
    return;
  }
  elements.connectionText.textContent = "Restoring session";
  try {
    const result = await apiFetch(`/api/reports/recent?session_id=${encodeURIComponent(state.sessionId)}`);
    setConnection(true, "Session active");
    renderRecent(result.reports || []);
    if (state.latestReportId) $("dailyReportId").value = state.latestReportId;
  } catch (_) {
    clearLocalSession();
  }
}

elements.authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const apiKey = elements.apiKey.value.trim();
  const apiSecret = elements.apiSecret.value.trim();
  if (!apiKey || !apiSecret) {
    showToast("Enter both the API key and secret.", "error");
    return;
  }
  state.busy = true;
  elements.authButton.classList.add("is-loading");
  updateActionState();
  elements.authMessage.className = "microcopy";
  elements.authMessage.textContent = "Testing the read-only Futures transaction endpoint…";
  try {
    const result = await apiFetch("/api/auth/test", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, api_secret: apiSecret, margin_currency: selectedMargin() }),
    });
    state.sessionId = result.session_id;
    sessionStorage.setItem(SESSION_KEY, state.sessionId);
    elements.apiKey.value = "";
    elements.apiSecret.value = "";
    elements.authMessage.className = "microcopy is-success";
    elements.authMessage.textContent = result.message;
    setConnection(true);
    showToast("CoinDCX connection established.", "success");
    await refreshRecentReports();
  } catch (error) {
    elements.authMessage.className = "microcopy is-error";
    elements.authMessage.textContent = error.message;
    setConnection(false);
    showToast(error.message, "error", 6000);
  } finally {
    state.busy = false;
    elements.authButton.classList.remove("is-loading");
    updateActionState();
  }
});

elements.logoutButton.addEventListener("click", async () => {
  const sessionId = state.sessionId;
  clearLocalSession();
  if (sessionId) {
    try {
      await apiFetch("/api/auth/logout", { method: "POST", body: JSON.stringify({ session_id: sessionId }) });
    } catch (_) {
      // Local state is already cleared; avoid retaining credentials because of a network failure.
    }
  }
  showToast("Session cleared from memory.", "success");
});

$("secretToggle").addEventListener("click", () => {
  const visible = elements.apiSecret.type === "text";
  elements.apiSecret.type = visible ? "password" : "text";
  $("secretToggle").textContent = visible ? "Show" : "Hide";
  $("secretToggle").setAttribute("aria-label", visible ? "Show API secret" : "Hide API secret");
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((node) => {
      const active = node === tab;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-selected", String(active));
      const panel = $(node.dataset.tab);
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
  });
});

document.querySelectorAll(".table-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".table-tab").forEach((node) => {
      const active = node === tab;
      node.classList.toggle("is-active", active);
      const panel = $(node.dataset.table);
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
  });
});

$("sampleTokens").addEventListener("click", () => {
  $("multiTokens").value = "B-ETH_USDT\nB-SOL_USDT\nB-XRP_USDT";
  $("excludeTokens").value = "B-XAU_USDT";
});

$("last7Days").addEventListener("click", () => setDateRange(7, false));
$("todayIST").addEventListener("click", () => setDateRange(0, true));
$("resetFilters").addEventListener("click", () => {
  setDateRange(7, false);
  $("initialCapital").value = "5000";
  $("pageSize").value = "100";
  $("maxPages").value = "";
  $("includeZero").checked = true;
  $("excludeLiquidate").checked = true;
  $("excludeXAU").checked = true;
  $("excludedPositionIds").value = "be09f054-356b-11f1-a6e6-cf5910827b69";
});

$("generateMulti").addEventListener("click", () => {
  try {
    const payload = commonReportPayload();
    payload.tokens = parseList($("multiTokens").value);
    payload.exclude_tokens = parseList($("excludeTokens").value);
    if (!payload.tokens.length) throw new Error("Enter at least one included futures pair.");
    runReport($("generateMulti"), "/api/reports/multi-token", payload);
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("generateSingle").addEventListener("click", () => {
  try {
    const payload = commonReportPayload();
    payload.token = $("singleToken").value.trim().toUpperCase();
    if (!payload.token) throw new Error("Enter an exact futures pair.");
    runReport($("generateSingle"), "/api/reports/single-token", payload);
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("generateDaily").addEventListener("click", () => {
  try {
    const reportId = $("dailyReportId").value.trim() || state.latestReportId;
    if (!state.sessionId) throw new Error("Connect your CoinDCX session first.");
    if (!reportId) throw new Error("Generate or select a source report first.");
    const payload = {
      session_id: state.sessionId,
      report_id: reportId,
      initial_capital: parsePositiveNumber("dailyInitialCapital", "Initial capital override"),
      funding_detection_mode: $("fundingHeuristic").checked
        ? "parent_type_stage_and_zero_heuristic"
        : "parent_type_and_stage_only",
      trade_count_mode: $("tradeCountMode").value,
    };
    runReport($("generateDaily"), "/api/reports/daily-from-report", payload);
  } catch (error) {
    showToast(error.message, "error");
  }
});

$("tableSearch").addEventListener("input", renderAllTables);
$("previewCount").addEventListener("change", renderAllTables);

$("copySummary").addEventListener("click", async () => {
  if (!state.latestSummary) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.latestSummary, null, 2));
    showToast("Summary JSON copied.", "success");
  } catch (_) {
    showToast("Clipboard access was unavailable.", "error");
  }
});

document.querySelectorAll('input[name="marginCurrency"]').forEach((input) => {
  input.addEventListener("change", () => { state.marginCurrency = selectedMargin(); });
});

setDateRange(7, false);
restoreSession();
updateActionState();
