(function () {
  "use strict";

  var state = null;
  var shownTrades = 20;
  var assetPeriod = "ytd";

  function el(id) { return document.getElementById(id); }
  function num(value) {
    if (value === null || value === undefined || value === "") return null;
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function positive(value) {
    var parsed = num(value);
    return parsed !== null && parsed > 0 ? parsed : null;
  }
  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (char) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char];
    });
  }
  function fmtYen(value) {
    var parsed = num(value);
    return parsed === null ? "—" : (parsed < 0 ? "-" : "") + "¥" + Math.abs(Math.round(parsed)).toLocaleString("ja-JP");
  }
  function fmtUsd(value) {
    var parsed = num(value);
    return parsed === null ? "—" : (parsed < 0 ? "-" : "") + "$" + Math.abs(parsed).toLocaleString("en-US", {maximumFractionDigits: 0});
  }
  function fmtPct(value, signed, digits) {
    var parsed = num(value);
    if (parsed === null) return "—";
    return (signed && parsed > 0 ? "+" : "") + (parsed * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }
  function fmtNum(value, digits) {
    var parsed = num(value);
    if (parsed === null) return "—";
    return parsed.toFixed(digits === undefined ? 2 : digits);
  }
  function tone(value) {
    var parsed = num(value);
    return parsed === null ? "" : parsed > 0 ? "pos" : parsed < 0 ? "neg" : "";
  }
  function dateOnly(value) { return value ? String(value).slice(0, 10) : "—"; }
  function daysBetween(start, end) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(start || "")) || !/^\d{4}-\d{2}-\d{2}$/.test(String(end || ""))) return null;
    return Math.max(0, Math.floor((new Date(end + "T00:00:00") - new Date(start + "T00:00:00")) / 86400000));
  }
  function normalizeColor(value) {
    var text = String(value || "UNKNOWN").trim().toUpperCase();
    var aliases = {"青": "BLUE", "緑": "GREEN", "黄": "YELLOW", "赤": "RED"};
    return aliases[text] || (["BLUE", "GREEN", "YELLOW", "RED"].indexOf(text) >= 0 ? text : "UNKNOWN");
  }
  function readJsonStorage(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      if (!raw) return fallback;
      var parsed = JSON.parse(raw);
      return parsed === null ? fallback : parsed;
    } catch (_) {
      return fallback;
    }
  }
  function extractAssignment(source, name) {
    var marker = "window." + name + "=";
    var start = source.indexOf(marker);
    if (start < 0) return null;
    start += marker.length;
    var end = source.indexOf(";</script>", start);
    if (end < 0) return null;
    try { return JSON.parse(source.slice(start, end)); }
    catch (_) { return null; }
  }
  async function fetchText(path) {
    var response = await fetch(path, {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error(path + " HTTP " + response.status);
    return response.text();
  }
  function parseEquity(text) {
    var rows = [];
    String(text || "").split(/\r?\n/).forEach(function (line) {
      var parts = line.trim().split(/[,\t ]+/);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(parts[0] || "")) return;
      var equity = positive(parts[1]);
      if (equity !== null) rows.push({date: parts[0], equity_jpy: equity});
    });
    rows.sort(function (a, b) { return a.date.localeCompare(b.date); });
    var unique = [];
    rows.forEach(function (row) {
      if (unique.length && unique[unique.length - 1].date === row.date) unique[unique.length - 1] = row;
      else unique.push(row);
    });
    var peak = null;
    unique.forEach(function (row) {
      peak = peak === null ? row.equity_jpy : Math.max(peak, row.equity_jpy);
      row.drawdown = peak > 0 ? row.equity_jpy / peak - 1 : null;
    });
    return unique;
  }
  function storageTrades() {
    var raw = readJsonStorage("v38_holdings", []);
    return Array.isArray(raw) ? raw.filter(function (item) { return item && typeof item === "object" && item.t; }) : [];
  }
  function filledSummary(item) {
    var fills = Array.isArray(item.fills) ? item.fills : [];
    var shares = fills.reduce(function (sum, fill) { return sum + (positive(fill && fill.shares) || 0); }, 0);
    var cost = fills.reduce(function (sum, fill) {
      var price = positive(fill && fill.price), quantity = positive(fill && fill.shares);
      return sum + (price && quantity ? price * quantity : 0);
    }, 0);
    if (!(shares > 0)) shares = positive(item.filledSharesTotal) || positive(item.sh) || 0;
    if (!(cost > 0)) {
      var average = positive(item.entryAvg) || positive(item.avgPx) || positive(item.px);
      cost = average && shares ? average * shares : 0;
    }
    return {shares: shares, cost: cost, average: shares > 0 && cost > 0 ? cost / shares : null};
  }
  function exitSummary(item) {
    var exits = Array.isArray(item.exits) ? item.exits : [];
    var pnl = 0, shares = 0, known = false;
    exits.forEach(function (exit) {
      var quantity = positive(exit && exit.shares) || 0;
      var realized = num(exit && exit.realizedPnl);
      if (realized === null) {
        var price = positive(exit && exit.price), basis = positive(exit && exit.costBasis);
        if (price && basis && quantity) realized = (price - basis) * quantity;
      }
      if (realized !== null) { pnl += realized; known = true; }
      shares += quantity;
    });
    if (!known && num(item.realizedPnl) !== null) { pnl = num(item.realizedPnl); known = true; }
    return {pnl: known ? pnl : null, shares: shares, exits: exits};
  }
  function currentStop(item, detail, calcName) {
    var override = positive(item.stopOverride);
    if (override) return {value: override, method: "手動"};
    if (item.exitType === "e21l" && positive(detail.e21l)) return {value: positive(detail.e21l), method: "21EMA Low"};
    if (item.exitType === "s10" && positive(detail.s10)) return {value: positive(detail.s10), method: "10MA"};
    if (positive(item.stop)) return {value: positive(item.stop), method: item.strat === "core" ? "Core Stop" : "手動"};
    if (calcName && positive(calcName.sysStop)) return {value: positive(calcName.sysStop), method: String(calcName.sysWhich || "Core Stop")};
    if (positive(item.initialStop)) return {value: positive(item.initialStop), method: "初期Stop"};
    return {value: null, method: "未取得"};
  }
  function normalizeRecords(raw, detailMap, calc, equity) {
    var fx = positive(calc.fx);
    var nameMap = {};
    (Array.isArray(calc.names) ? calc.names : []).forEach(function (row) { if (row && row.t) nameMap[String(row.t).toUpperCase()] = row; });
    var holdings = [], trades = [];
    raw.forEach(function (item) {
      var ticker = String(item.t || "").toUpperCase();
      if (!ticker) return;
      var detail = detailMap[ticker] || {};
      var filled = filledSummary(item);
      var exited = exitSummary(item);
      var entryDate = dateOnly(item.dt) === "—" ? null : dateOnly(item.dt);
      var closeDate = dateOnly(item.closeDate) === "—" ? null : dateOnly(item.closeDate);
      var setup = String(item.setup || (item.strat === "core" ? "Core 12" : "裁量スイング"));
      var sector = String(detail.sec || "未取得");
      var theme = String(item.theme || detail.sth || detail.sec || "未取得");
      var nq = normalizeColor(item.envColor || calc.color);
      if (item.status === "closed") {
        var returnPct = exited.pnl !== null && filled.cost > 0 ? exited.pnl / filled.cost : null;
        var risk = positive(item.initialRiskTotal);
        var rMultiple = num(item.realizedR);
        if (rMultiple === null && exited.pnl !== null && risk) rMultiple = exited.pnl / risk;
        trades.push({
          trade_id: String(item.tradeId || ticker + "-" + (entryDate || "")),
          ticker: ticker, entry_date: entryDate, exit_date: closeDate,
          setup: setup, sector: sector, theme: theme, nq_color: nq,
          pnl_usd: exited.pnl, return_pct: returnPct, r_multiple: rMultiple,
          hold_days: num(item.heldDays) !== null ? num(item.heldDays) : daysBetween(entryDate, closeDate),
          exit_reason: String(item.exitReason || (exited.exits.length ? exited.exits[exited.exits.length - 1].reason || "" : "")),
          partial_exit: exited.exits.some(function (entry) { return entry && entry.type === "partial"; })
        });
        return;
      }
      var remainingShares = num(item.remainingShares);
      if (remainingShares === null) remainingShares = Math.max(0, filled.shares - exited.shares);
      var remainingCost = num(item.remainingCost);
      if (remainingCost === null) remainingCost = filled.average !== null ? filled.average * remainingShares : null;
      var entry = remainingShares > 0 && remainingCost !== null ? remainingCost / remainingShares : filled.average;
      var current = positive(detail.px);
      var stop = currentStop(item, detail, nameMap[ticker]);
      var marketValue = current && fx && remainingShares > 0 ? current * remainingShares * fx : null;
      var unrealized = current && entry && fx && remainingShares > 0 ? (current - entry) * remainingShares * fx : null;
      var unrealizedPct = current && entry ? current / entry - 1 : null;
      var plannedLoss = entry && stop.value && fx && remainingShares > 0 ? Math.max(0, entry - stop.value) * remainingShares * fx : null;
      var allocation = marketValue !== null && equity ? marketValue / equity : null;
      var heat = plannedLoss !== null && equity ? plannedLoss / equity : null;
      var fills = Array.isArray(item.fills) ? item.fills : [];
      var target = positive(item.tpPrice) || (entry && positive(item.tpPct) ? entry * (1 + positive(item.tpPct) / 100) : null);
      holdings.push({
        ticker: ticker, quantity: remainingShares, entry_price: entry, current_price: current,
        stop_price: stop.value, stop_method: stop.method, market_value_jpy: marketValue,
        unrealized_pnl_jpy: unrealized, unrealized_pct: unrealizedPct, allocation: allocation,
        planned_loss_jpy: plannedLoss, heat_fraction: heat, adr_pct: num(detail.adr),
        sector: sector, theme: theme, setup: setup, entry_date: entryDate,
        hold_days: daysBetween(entryDate, calc.asof), nq_color: nq,
        entry_stage: fills.length >= 2 || item.leg2 === "filled" ? 2 : 1,
        entry_price_1: fills[0] ? num(fills[0].price) : num(item.px1),
        entry_price_2: fills[1] ? num(fills[1].price) : num(item.px2),
        partial_taken: exited.exits.some(function (entryExit) { return entryExit && entryExit.type === "partial"; }),
        partial_target_price: target, partial_take_due: current && target ? current >= target : false
      });
    });
    holdings.sort(function (a, b) { return (num(b.allocation) || 0) - (num(a.allocation) || 0); });
    trades.sort(function (a, b) { return String(b.exit_date || "").localeCompare(String(a.exit_date || "")); });
    return {holdings: holdings, trades: trades, fx: fx};
  }
  function appendLocalEquity(rows, asOf) {
    var local = positive(localStorage.getItem("eqLast"));
    if (!local || !/^\d{4}-\d{2}-\d{2}$/.test(String(asOf || ""))) return rows.slice();
    var output = rows.slice();
    var found = false;
    output = output.map(function (row) {
      if (row.date === asOf) { found = true; return {date: asOf, equity_jpy: local}; }
      return row;
    });
    if (!found) output.push({date: asOf, equity_jpy: local});
    output.sort(function (a, b) { return a.date.localeCompare(b.date); });
    var peak = null;
    output.forEach(function (row) {
      peak = peak === null ? row.equity_jpy : Math.max(peak, row.equity_jpy);
      row.drawdown = peak ? row.equity_jpy / peak - 1 : null;
    });
    return output;
  }
  function allocations(holdings, key) {
    var totals = {};
    holdings.forEach(function (holding) {
      var name = String(holding[key] || "未取得");
      totals[name] = (totals[name] || 0) + (num(holding.allocation) || 0);
    });
    return Object.keys(totals).map(function (name) { return {name: name, value: totals[name]}; }).sort(function (a, b) { return b.value - a.value; });
  }
  function stats(trades) {
    var usable = trades.filter(function (trade) { return num(trade.pnl_usd) !== null; });
    var wins = usable.filter(function (trade) { return trade.pnl_usd > 0; });
    var losses = usable.filter(function (trade) { return trade.pnl_usd <= 0; });
    var grossProfit = wins.reduce(function (sum, trade) { return sum + trade.pnl_usd; }, 0);
    var grossLoss = -losses.reduce(function (sum, trade) { return sum + trade.pnl_usd; }, 0);
    var rs = trades.map(function (trade) { return num(trade.r_multiple); }).filter(function (value) { return value !== null; });
    return {
      n: usable.length,
      wr: usable.length ? wins.length / usable.length : null,
      pf: usable.length ? (grossLoss ? grossProfit / grossLoss : (grossProfit ? Infinity : null)) : null,
      r: rs.length ? rs.reduce(function (sum, value) { return sum + value; }, 0) / rs.length : null,
      pnl: usable.length ? usable.reduce(function (sum, trade) { return sum + trade.pnl_usd; }, 0) : null
    };
  }
  function returns(equity) {
    if (!equity.length) return {daily: null, mtd: null, ytd: null, maxDd: null};
    var last = equity[equity.length - 1];
    var previous = equity.length > 1 ? equity[equity.length - 2] : null;
    var month = last.date.slice(0, 7), year = last.date.slice(0, 4);
    var monthRows = equity.filter(function (row) { return row.date.slice(0, 7) === month; });
    var yearRows = equity.filter(function (row) { return row.date.slice(0, 4) === year; });
    return {
      daily: previous ? last.equity_jpy / previous.equity_jpy - 1 : null,
      mtd: monthRows.length > 1 ? last.equity_jpy / monthRows[0].equity_jpy - 1 : null,
      ytd: yearRows.length > 1 ? last.equity_jpy / yearRows[0].equity_jpy - 1 : null,
      maxDd: Math.min.apply(null, equity.map(function (row) { return num(row.drawdown) || 0; }))
    };
  }
  function enrich(commandHtml, equityText) {
    var calc = extractAssignment(commandHtml, "CALC") || {};
    var detail = extractAssignment(commandHtml, "DET") || {};
    var asOf = /^\d{4}-\d{2}-\d{2}$/.test(String(calc.asof || "")) ? String(calc.asof) : null;
    var equity = appendLocalEquity(parseEquity(equityText), asOf);
    var account = positive(localStorage.getItem("eqLast")) || (equity.length ? equity[equity.length - 1].equity_jpy : null);
    var normalized = normalizeRecords(storageTrades(), detail, calc, account);
    var registeredValue = normalized.holdings.reduce(function (sum, holding) { return sum + (num(holding.market_value_jpy) || 0); }, 0);
    var nominalLoss = normalized.holdings.reduce(function (sum, holding) { return sum + (num(holding.planned_loss_jpy) || 0); }, 0);
    var adrValue = 0, adrWeight = 0, totalWeight = 0;
    normalized.holdings.forEach(function (holding) {
      var weight = num(holding.market_value_jpy) || 0;
      totalWeight += weight;
      if (num(holding.adr_pct) !== null) { adrValue += holding.adr_pct * weight; adrWeight += weight; }
    });
    var stopBreached = normalized.holdings.filter(function (holding) { return positive(holding.current_price) && positive(holding.stop_price) && holding.current_price <= holding.stop_price; }).length;
    var stopNear = normalized.holdings.filter(function (holding) {
      if (!positive(holding.current_price) || !positive(holding.stop_price) || holding.current_price <= holding.stop_price) return false;
      return (holding.current_price - holding.stop_price) / holding.current_price <= 0.02;
    }).length;
    return {
      calc: calc, detail: detail, asOf: asOf, nq: normalizeColor(calc.color),
      account: account, equity: equity, holdings: normalized.holdings, trades: normalized.trades,
      fx: normalized.fx, registeredValue: registeredValue || null,
      gross: account && registeredValue ? registeredValue / account : (account ? 0 : null),
      nominalHeat: account ? nominalLoss / account : null,
      portfolioAdr: adrWeight ? adrValue / adrWeight : null,
      adrCoverage: totalWeight ? adrWeight / totalWeight : null,
      sectors: allocations(normalized.holdings, "sector"),
      themes: allocations(normalized.holdings, "theme"),
      stopBreached: stopBreached, stopNear: stopNear,
      performance: returns(equity), tradeStats: stats(normalized.trades)
    };
  }

  function activate(id) {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    var panels = Array.prototype.slice.call(document.querySelectorAll(".tab-panel"));
    if (!panels.some(function (panel) { return panel.id === id; })) id = "today";
    tabs.forEach(function (tab) { tab.setAttribute("aria-selected", String(tab.dataset.tab === id)); });
    panels.forEach(function (panel) { panel.classList.toggle("active", panel.id === id); });
    window.scrollTo(0, 0);
  }
  function mountTabs() {
    window.addEventListener("hashchange", function () { activate(location.hash.slice(1) || "today"); });
    activate(location.hash.slice(1) || "today");
  }
  function setMetric(id, value, classValue) {
    var node = el(id);
    node.textContent = value;
    if (classValue !== undefined) node.className = "num " + classValue;
  }
  function renderBanner(data) {
    var banner = el("sync-banner");
    var count = data.holdings.length + data.trades.length;
    banner.className = "sync-banner " + (count ? "good" : "warn");
    el("sync-title").textContent = count ? "最新データに同期済み" : "保有・決済記録はありません";
    el("sync-detail").textContent = count
      ? "保有" + data.holdings.length + "件・決済" + data.trades.length + "件を反映しました。"
      : "登録済みの保有・決済記録がある場合は自動反映されます。";
  }
  function renderHeader(data) {
    el("asof").textContent = data.asOf || "—";
    var lastEquity = data.equity.length ? data.equity[data.equity.length - 1].date : null;
    el("freshness").textContent = lastEquity ? "資産更新 " + lastEquity : "資産履歴なし";
    el("registered-value").textContent = fmtYen(data.registeredValue);
    el("account-equity").textContent = fmtYen(data.account);
    el("gross-exposure").textContent = fmtPct(data.gross);
    if (data.account) el("sz-equity").value = Math.round(data.account);
    if (data.fx) el("sz-fx").value = data.fx.toFixed(2);
  }
  function renderDecision(data) {
    var decision = el("decision"), title, reason, toneName;
    if (!data.account) { title = "口座総資産が未取得"; reason = "口座評価額を更新してください"; toneName = "bad"; }
    else if (data.nq === "RED" || data.nq === "UNKNOWN") { title = "新規発注停止"; reason = "市場ゲート " + data.nq; toneName = "bad"; }
    else if (data.nq === "YELLOW") { title = "新規発注停止"; reason = "市場ゲート YELLOW"; toneName = "warn"; }
    else if (data.stopBreached) { title = "撤退確認を優先"; reason = "Stop逸脱 " + data.stopBreached + "銘柄"; toneName = "bad"; }
    else if (data.stopNear) { title = "保有管理を優先"; reason = "Stop接近 " + data.stopNear + "銘柄"; toneName = "warn"; }
    else { title = "新規発注可能"; reason = "市場ゲート " + data.nq + "・Stop逸脱なし"; toneName = "good"; }
    decision.className = "status-line " + toneName;
    el("decision-title").textContent = title;
    el("decision-reason").textContent = reason;
  }
  function renderToday(data) {
    var p = data.performance;
    setMetric("daily-return", fmtPct(p.daily, true), tone(p.daily));
    setMetric("mtd-return", fmtPct(p.mtd, true), tone(p.mtd));
    setMetric("ytd-return", fmtPct(p.ytd, true), tone(p.ytd));
    setMetric("max-dd", fmtPct(p.maxDd), "neg");
    setMetric("nominal-heat", fmtPct(data.nominalHeat));
    setMetric("stop-breached", data.stopBreached + "銘柄", data.stopBreached ? "neg" : "");
    setMetric("stop-near", data.stopNear + "銘柄", data.stopNear ? "warn-text" : "");
    setMetric("holding-count", data.holdings.length + "銘柄");
    var watch = data.holdings.filter(function (holding) { return positive(holding.current_price) && positive(holding.stop_price); }).sort(function (a, b) {
      return (a.current_price - a.stop_price) / a.current_price - (b.current_price - b.stop_price) / b.current_price;
    }).slice(0, 3);
    el("watch-list").innerHTML = watch.length ? watch.map(function (holding) {
      var distance = (holding.current_price - holding.stop_price) / holding.current_price;
      return '<details class="holding-card"><summary><div class="holding-main"><div><div class="holding-title">' + esc(holding.ticker) + '<small>' + esc(holding.setup) + '</small></div><div class="holding-quick"><div><span>Stop</span><b class="num">' + fmtNum(holding.stop_price) + '</b></div><div><span>Stop距離</span><b class="num ' + (distance <= 0.02 ? "neg" : "") + '">' + fmtPct(distance, true) + '</b></div><div><span>保有</span><b class="num">' + (num(holding.hold_days) === null ? "—" : holding.hold_days + "日") + '</b></div></div></div><div class="holding-pnl num ' + tone(holding.unrealized_pct) + '">' + fmtPct(holding.unrealized_pct, true) + '</div></div></summary></details>';
    }).join("") : '<div class="empty-action"><b>撤退線を評価できる保有なし</b><span>保有記録と価格・撤退線が揃うと表示します。</span></div>';
  }
  function renderBars(rows, target) {
    var max = Math.max.apply(null, rows.map(function (row) { return row.value; }).concat([0.0001]));
    el(target).innerHTML = rows.length ? rows.map(function (row) {
      return '<div class="bar-row"><span>' + esc(row.name) + '</span><div class="bar-track"><i style="width:' + Math.min(100, row.value / max * 100).toFixed(0) + '%"></i></div><b class="num">' + fmtPct(row.value) + '</b></div>';
    }).join("") : '<div class="stub">実保有なし</div>';
  }
  function renderPortfolio(data) {
    el("portfolio-count").textContent = data.holdings.length + "銘柄";
    setMetric("p-heat", fmtPct(data.nominalHeat));
    setMetric("p-gross", fmtPct(data.gross));
    setMetric("p-adr", data.portfolioAdr === null ? "—" : data.portfolioAdr.toFixed(1) + "%");
    el("p-adr-coverage").textContent = "カバー率 " + fmtPct(data.adrCoverage);
    el("p-cluster").textContent = data.themes.length ? data.themes[0].name : "—";
    el("conc-list").innerHTML = data.holdings.length ? data.holdings.map(function (holding, index) {
      return '<div class="conc-row"><span class="conc-rank">' + (index + 1) + '</span><span class="conc-ticker">' + esc(holding.ticker) + '</span><span class="conc-track ' + ((num(holding.unrealized_pct) || 0) >= 0 ? "up" : "down") + '"><i style="width:' + Math.min(100, (num(holding.allocation) || 0) / Math.max(num(data.holdings[0].allocation) || 0.0001, 0.0001) * 100).toFixed(0) + '%"></i></span><span class="conc-pct num">' + fmtPct(holding.allocation) + '</span><span class="conc-pnl num ' + tone(holding.unrealized_pct) + '">' + fmtPct(holding.unrealized_pct, true) + '</span></div>';
    }).join("") : '<div class="stub">実保有なし</div>';
    renderBars(data.sectors, "sector-bars");
    renderBars(data.themes, "theme-bars");
    el("holdings-cards").innerHTML = data.holdings.length ? data.holdings.map(function (holding) {
      var distance = positive(holding.current_price) && positive(holding.stop_price) ? (holding.current_price - holding.stop_price) / holding.current_price : null;
      return '<details class="holding-card"><summary><div class="holding-main"><div><div class="holding-title">' + esc(holding.ticker) + (distance !== null && distance <= 0 ? '<span class="risk-badge">STOP逸脱</span>' : '') + (holding.partial_take_due ? '<span class="risk-badge">+25%到達</span>' : '') + '<small>' + esc(holding.setup) + '｜' + esc(holding.sector) + '</small></div><div class="holding-quick"><div><span>配分</span><b class="num">' + fmtPct(holding.allocation) + '</b></div><div><span>保有</span><b class="num">' + (num(holding.hold_days) === null ? "—" : holding.hold_days + "日") + '</b></div><div><span>Stop距離</span><b class="num ' + (distance !== null && distance <= .02 ? "neg" : "") + '">' + fmtPct(distance, true) + '</b></div></div></div><div class="holding-pnl num ' + tone(holding.unrealized_pct) + '">' + fmtPct(holding.unrealized_pct, true) + '<small style="display:block;color:var(--muted);font-size:7px">' + fmtYen(holding.unrealized_pnl_jpy) + '</small></div></div></summary><div class="holding-detail"><div><span>現在値</span><b class="num">' + fmtNum(holding.current_price) + '</b></div><div><span>平均Entry</span><b class="num">' + fmtNum(holding.entry_price) + '</b></div><div><span>撤退線</span><b class="num">' + fmtNum(holding.stop_price) + '</b></div><div><span>撤退方法</span><b>' + esc(holding.stop_method) + '</b></div><div><span>残株</span><b class="num">' + fmtNum(holding.quantity, 0) + '</b></div><div><span>評価額</span><b class="num">' + fmtYen(holding.market_value_jpy) + '</b></div><div><span>ADR%</span><b class="num">' + (num(holding.adr_pct) === null ? "—" : holding.adr_pct.toFixed(1) + "%") + '</b></div><div><span>Theme</span><b>' + esc(holding.theme) + '</b></div><div><span>Entry日</span><b>' + dateOnly(holding.entry_date) + '</b></div><div><span>2分割Entry</span><b>' + (holding.entry_stage >= 2 ? "2nd組入済" : "1stのみ") + '</b></div><div><span>1st / 2nd</span><b class="num">' + fmtNum(holding.entry_price_1) + " / " + fmtNum(holding.entry_price_2) + '</b></div><div><span>+25%ルール</span><b>' + (holding.partial_take_due ? "利確候補" : holding.partial_taken ? "利確済" : "未到達") + '</b></div></div></details>';
    }).join("") : '<div class="empty-action"><b>保有記録はありません</b><span>保有を登録すると自動反映されます。</span></div>';
  }
  function renderCurve(rows) {
    var svg = el("equity-svg"), empty = el("equity-empty");
    if (!rows.length) { svg.innerHTML = ""; empty.hidden = false; return; }
    empty.hidden = true;
    var values = rows.map(function (row) { return row.equity_jpy; });
    var width = 600, height = 190, padding = 8;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var points = values.map(function (value, index) {
      var x = padding + (values.length === 1 ? 0 : index / (values.length - 1)) * (width - 2 * padding);
      var y = height - padding - (value - min) / ((max - min) || 1) * (height - 2 * padding);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    svg.innerHTML = '<polygon class="area" points="' + padding + "," + (height - padding) + " " + points + " " + (width - padding) + "," + (height - padding) + '"></polygon><polyline class="line" points="' + points + '"></polyline><line class="axis" x1="' + padding + '" y1="' + (height - padding) + '" x2="' + (width - padding) + '" y2="' + (height - padding) + '"></line>';
  }
  function periodRows(data) {
    if (!data.equity.length || assetPeriod === "all") return data.equity;
    var end = new Date(data.equity[data.equity.length - 1].date + "T00:00:00");
    var start = new Date(end);
    if (assetPeriod === "1m") start.setMonth(start.getMonth() - 1);
    else if (assetPeriod === "3m") start.setMonth(start.getMonth() - 3);
    else start = new Date(end.getFullYear() + "-01-01T00:00:00");
    var iso = start.toISOString().slice(0, 10);
    return data.equity.filter(function (row) { return row.date >= iso; });
  }
  function renderAssets(data) {
    var rows = periodRows(data), tradeStats = data.tradeStats;
    var ret = rows.length > 1 ? rows[rows.length - 1].equity_jpy / rows[0].equity_jpy - 1 : null;
    var dd = rows.length ? Math.min.apply(null, rows.map(function (row) { return num(row.drawdown) || 0; })) : null;
    setMetric("a-ret", fmtPct(ret, true), tone(ret));
    setMetric("a-pf", tradeStats.pf === Infinity ? "∞" : fmtNum(tradeStats.pf));
    setMetric("a-wr", fmtPct(tradeStats.wr));
    setMetric("a-r", fmtNum(tradeStats.r));
    setMetric("a-dd", fmtPct(dd), "neg");
    setMetric("a-n", String(tradeStats.n));
    renderCurve(rows);
    var months = {};
    rows.forEach(function (row) {
      var key = row.date.slice(0, 7);
      if (!months[key]) months[key] = [];
      months[key].push(row);
    });
    el("month-grid").innerHTML = Object.keys(months).sort().map(function (key) {
      var values = months[key], value = values.length > 1 ? values[values.length - 1].equity_jpy / values[0].equity_jpy - 1 : null;
      return '<div class="month-cell ' + ((num(value) || 0) >= 0 ? "up" : "down") + '"><span class="m">' + key + '</span><span class="v num ' + tone(value) + '">' + fmtPct(value, true) + '</span></div>';
    }).join("") || '<div class="stub" style="grid-column:1/-1">資産履歴なし</div>';
    var worst = rows.slice().sort(function (a, b) { return (num(a.drawdown) || 0) - (num(b.drawdown) || 0); }).slice(0, 6);
    el("dd-list").innerHTML = worst.length ? worst.map(function (row) {
      return '<div class="dd-row"><div><b class="num neg">' + fmtPct(row.drawdown) + '</b><small>' + row.date + '</small></div><div><span>口座評価額</span><b class="num">' + fmtYen(row.equity_jpy) + '</b></div><em>DD</em></div>';
    }).join("") : '<div class="stub">資産履歴なし</div>';
  }
  function filteredTrades(data) {
    var query = String(el("j-search").value || "").trim().toLowerCase();
    return data.trades.filter(function (trade) {
      var haystack = [trade.ticker, trade.sector, trade.theme, trade.exit_reason].join(" ").toLowerCase();
      if (query && haystack.indexOf(query) < 0) return false;
      if (el("j-setup").value && trade.setup !== el("j-setup").value) return false;
      if (el("j-nq").value && trade.nq_color !== el("j-nq").value) return false;
      if (el("j-result").value === "win" && !(trade.pnl_usd > 0)) return false;
      if (el("j-result").value === "loss" && !(trade.pnl_usd <= 0)) return false;
      return true;
    });
  }
  function renderJournal(data, reset) {
    if (reset) shownTrades = 20;
    var list = filteredTrades(data), visible = list.slice(0, shownTrades);
    el("j-count").innerHTML = "<span>" + visible.length + " / " + list.length + "件</span><span>全" + data.trades.length + "件</span>";
    el("j-list").innerHTML = visible.length ? visible.map(function (trade) {
      return '<div class="trade-card"><div class="trade-top"><span class="tk">' + esc(trade.ticker) + '<small>' + esc(trade.setup) + '</small></span><span class="pnl num ' + tone(trade.pnl_usd) + '">' + fmtPct(trade.return_pct, true) + "｜" + (num(trade.r_multiple) === null ? "R—" : fmtNum(trade.r_multiple) + "R") + '</span></div><div class="trade-meta"><span>' + dateOnly(trade.entry_date) + " → " + dateOnly(trade.exit_date) + '</span><span><i class="nq-dot nq-' + esc(trade.nq_color) + '"></i>' + esc(trade.nq_color) + '</span><span>' + (num(trade.hold_days) === null ? "—" : trade.hold_days + "日") + '</span><span>' + esc(trade.exit_reason || "—") + '</span>' + (trade.partial_exit ? "<span>分割利確</span>" : "") + '<span class="num ' + tone(trade.pnl_usd) + '">' + fmtUsd(trade.pnl_usd) + '</span></div></div>';
    }).join("") : '<div class="empty-action"><b>決済履歴はありません</b><span>決済済みの取引だけを表示します。</span></div>';
    el("j-more").hidden = shownTrades >= list.length;
  }
  function renderEdge(data) {
    var axis = el("edge-axis").value, sort = el("edge-sort").value, minN = Number(el("edge-minn").value || 1);
    var buckets = {};
    data.trades.forEach(function (trade) {
      var key;
      if (axis === "nq") key = trade.nq_color;
      else if (axis === "sector") key = trade.sector;
      else if (axis === "theme") key = trade.theme;
      else if (axis === "holdBucket") {
        var days = num(trade.hold_days) || 0;
        key = days <= 7 ? "0-7日" : days <= 14 ? "8-14日" : days <= 21 ? "15-21日" : days <= 30 ? "22-30日" : "31日+";
      } else if (axis === "setupNq") key = trade.setup + " × " + trade.nq_color;
      else key = trade.setup;
      if (!buckets[key]) buckets[key] = [];
      buckets[key].push(trade);
    });
    var rows = Object.keys(buckets).map(function (key) { var result = stats(buckets[key]); result.key = key; return result; });
    rows.sort(function (a, b) { return (num(b[sort]) || 0) - (num(a[sort]) || 0); });
    var best = rows.filter(function (row) { return row.n >= minN; })[0];
    el("edge-callout").innerHTML = best ? "<b>上位条件：" + esc(best.key) + "</b>n=" + best.n + "｜PF " + (best.pf === Infinity ? "∞" : fmtNum(best.pf)) + "｜平均R " + fmtNum(best.r) : "<b>十分な実取引サンプルなし</b>最小件数を下げるか、履歴の蓄積を待ってください。";
    el("rank-body").innerHTML = rows.length ? rows.map(function (row) {
      return '<div class="rank-row ' + (row.n < minN ? "low-n" : "") + '"><span class="lbl">' + esc(row.key) + (row.n < minN ? '<span class="tag-low">n少</span>' : "") + '</span><b>' + row.n + '</b><b>' + fmtPct(row.wr) + '</b><b>' + (row.pf === Infinity ? "∞" : fmtNum(row.pf)) + '</b><b>' + fmtNum(row.r) + '</b></div>';
    }).join("") : '<div class="stub">実決済履歴なし</div>';
  }
  function renderReview(data) {
    var s = data.tradeStats;
    var best = null, groups = {};
    data.trades.forEach(function (trade) { if (!groups[trade.setup]) groups[trade.setup] = []; groups[trade.setup].push(trade); });
    Object.keys(groups).forEach(function (key) {
      var result = stats(groups[key]);
      if (result.n >= 5 && (!best || (num(result.pf) || 0) > (num(best.pf) || 0))) { result.key = key; best = result; }
    });
    var html = "<h3>自動集計</h3><ul>";
    html += "<li>実決済 " + data.trades.length + "件、実保有 " + data.holdings.length + "件。</li>";
    html += "<li>勝率 " + fmtPct(s.wr) + "、PF " + (s.pf === Infinity ? "∞" : fmtNum(s.pf)) + "、平均R " + fmtNum(s.r) + "。</li>";
    html += "<li>市場ゲート " + esc(data.nq) + "、Stop逸脱 " + data.stopBreached + "銘柄、Stop接近 " + data.stopNear + "銘柄。</li>";
    if (best) html += "<li>n≥5のSetup上位は「" + esc(best.key) + "」（n=" + best.n + "、PF " + (best.pf === Infinity ? "∞" : fmtNum(best.pf)) + "）。</li>";
    html += "</ul>";
    if (!data.trades.length) html += '<div class="stub">決済履歴が蓄積されるとSetup別の事実を表示します。</div>';
    el("review-body").innerHTML = html;
  }
  function renderShare(data) {
    var s = data.tradeStats, p = data.performance;
    el("share-eyebrow").textContent = "Swinote — " + (data.asOf ? data.asOf.slice(0, 7) : "未取得");
    el("share-wr").textContent = fmtPct(s.wr);
    el("share-pf").textContent = s.pf === Infinity ? "∞" : fmtNum(s.pf);
    el("share-r").textContent = fmtNum(s.r);
    el("share-dd").textContent = fmtPct(p.maxDd);
    el("share-text").value = "運用実績 " + (data.asOf || "日付未取得") + "\n総資産 " + fmtYen(data.account) + "｜本日 " + fmtPct(p.daily, true) + "｜月初来 " + fmtPct(p.mtd, true) + "｜年初来 " + fmtPct(p.ytd, true) + "\nPF " + (s.pf === Infinity ? "∞" : fmtNum(s.pf)) + "｜勝率 " + fmtPct(s.wr) + "｜平均R " + fmtNum(s.r) + "｜最大DD " + fmtPct(p.maxDd);
  }
  function renderSizer() {
    function value(id) { return Number(el(id).value); }
    var equity = value("sz-equity"), riskPct = value("sz-risk"), capPct = value("sz-cap"), fx = value("sz-fx");
    var entry1 = value("sz-entry1"), entry2 = value("sz-entry2"), split = Math.max(0, Math.min(1, value("sz-split1") / 100));
    var method = el("sz-stop-method").value, stop = value(method === "10MA" ? "sz-stop10" : "sz-stop21");
    var second = entry2 > 0 ? entry2 : entry1, estimated = entry1 * split + second * (1 - split), message = el("sz-message");
    if (!(equity > 0 && riskPct > 0 && capPct > 0 && fx > 0 && entry1 > 0 && estimated > stop && stop > 0)) {
      ["sz-avg", "sz-qty", "sz-tranches", "sz-value", "sz-loss", "sz-partial", "sz-runner", "sz-trail"].forEach(function (id) { el(id).textContent = "—"; });
      message.className = "sizer-message bad"; message.textContent = "口座、リスク、FX、Entry、選択した撤退線を入力してください。"; return;
    }
    var riskBudget = equity * riskPct / 100, capBudget = equity * capPct / 100;
    var byRisk = Math.floor(riskBudget / ((estimated - stop) * fx)), byCap = Math.floor(capBudget / (estimated * fx));
    var quantity = Math.max(0, Math.min(byRisk, byCap)), q1 = 0, q2 = 0, average = estimated, valueJpy = 0, loss = 0;
    while (quantity > 0) {
      q1 = quantity === 1 ? 1 : Math.max(1, Math.min(quantity - 1, Math.round(quantity * split))); q2 = quantity - q1;
      average = (entry1 * q1 + second * q2) / quantity; valueJpy = quantity * average * fx; loss = quantity * (average - stop) * fx;
      if (valueJpy <= capBudget + .01 && loss <= riskBudget + .01) break;
      quantity -= 1;
    }
    var partial = quantity ? Math.max(1, Math.round(quantity * .25)) : 0;
    el("sz-avg").textContent = fmtNum(average); el("sz-qty").textContent = quantity.toLocaleString("ja-JP") + "株";
    el("sz-tranches").textContent = q1 + "株 / " + q2 + "株"; el("sz-value").textContent = fmtYen(valueJpy) + " (" + fmtPct(valueJpy / equity) + ")";
    el("sz-loss").textContent = fmtYen(loss); el("sz-partial").textContent = fmtNum(average * 1.25) + " で " + partial + "株";
    el("sz-runner").textContent = Math.max(0, quantity - partial) + "株"; el("sz-trail").textContent = method === "10MA" ? "10MA" : "21EMA Low";
    message.className = "sizer-message"; message.textContent = (byRisk <= byCap ? "リスク側" : "建率上限側") + "がボトルネック。";
  }
  function copyText(value, button) {
    var done = function () { var old = button.textContent; button.textContent = "コピー済み"; setTimeout(function () { button.textContent = old; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(value).then(done, function () {
      var area = document.createElement("textarea"); area.value = value; document.body.appendChild(area); area.select(); document.execCommand("copy"); area.remove(); done();
    });
    else { var fallback = document.createElement("textarea"); fallback.value = value; document.body.appendChild(fallback); fallback.select(); document.execCommand("copy"); fallback.remove(); done(); }
  }
  function renderAll(data) {
    state = data;
    renderBanner(data); renderHeader(data); renderDecision(data); renderToday(data); renderPortfolio(data);
    var setups = Array.from(new Set(data.trades.map(function (trade) { return trade.setup; }).filter(Boolean))).sort();
    el("j-setup").innerHTML = '<option value="">Setup すべて</option>' + setups.map(function (setup) { return "<option>" + esc(setup) + "</option>"; }).join("");
    renderAssets(data); renderJournal(data, true); renderEdge(data); renderReview(data); renderShare(data); renderSizer();
  }
  function showFailure(error) {
    el("sync-banner").className = "sync-banner bad";
    el("sync-title").textContent = "データを取得できません";
    el("sync-detail").textContent = "時間を置いて再同期してください。";
    el("decision").className = "status-line bad"; el("decision-title").textContent = "判断停止"; el("decision-reason").textContent = "データ未取得";
  }
  async function load() {
    el("sync-banner").className = "sync-banner warn"; el("sync-title").textContent = "データを同期中";
    el("sync-detail").textContent = "最新データを確認しています。";
    try {
      var results = await Promise.all([fetchText("../command-center.html"), fetchText("../equity.csv").catch(function () { return ""; })]);
      renderAll(enrich(results[0], results[1]));
    } catch (error) { showFailure(error); }
  }
  function mountEvents() {
    el("sync-now").addEventListener("click", load);
    ["j-search", "j-setup", "j-nq", "j-result"].forEach(function (id) { el(id).addEventListener("input", function () { if (state) renderJournal(state, true); }); });
    el("j-more").addEventListener("click", function () { shownTrades += 20; if (state) renderJournal(state, false); });
    ["edge-axis", "edge-sort", "edge-minn"].forEach(function (id) { el(id).addEventListener("input", function () { if (state) renderEdge(state); }); });
    el("assets-period").addEventListener("click", function (event) {
      var button = event.target.closest("button[data-period]"); if (!button) return;
      assetPeriod = button.dataset.period;
      el("assets-period").querySelectorAll("button").forEach(function (item) { item.setAttribute("aria-pressed", String(item === button)); });
      if (state) renderAssets(state);
    });
    ["sz-equity", "sz-risk", "sz-cap", "sz-fx", "sz-entry1", "sz-entry2", "sz-split1", "sz-stop-method", "sz-stop21", "sz-stop10"].forEach(function (id) { el(id).addEventListener("input", renderSizer); });
    el("copy-holdings").addEventListener("click", function () { copyText(state ? state.holdings.map(function (holding) { return holding.ticker; }).join(" ") : "", el("copy-holdings")); });
    el("copy-share").addEventListener("click", function () { copyText(el("share-text").value, el("copy-share")); });
    window.addEventListener("storage", function (event) { if (event.key === "v38_holdings" || event.key === "eqLast") load(); });
  }
  mountTabs();
  mountEvents();
  load();
})();
