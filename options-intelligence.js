(() => {
'use strict';

const SAME = {
  intel: './options_intelligence.json',
  pos: './options_positioning.json',
  dh: './options_history.csv',
  sh: './options_scan_history.csv',
  uni: './universe.csv',
  leaders: './rotation/data/rotation-theme56-stock-context.json',
  rotStatus: './rotation/data/status.json',
  state: './state.json'
};
const RAW = {
  intel: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_intelligence.json',
  pos: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_positioning.json',
  dh: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_history.csv',
  sh: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_scan_history.csv',
  uni: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/universe.csv',
  leaders: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/rotation/data/rotation-theme56-stock-context.json',
  rotStatus: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/rotation/data/status.json',
  state: 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/state.json'
};

const $ = s => document.querySelector(s);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const num = v => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));
const money = v => {
  const n = num(v);
  if (n === null) return '—';
  return '$' + n.toLocaleString('en-US', {
    minimumFractionDigits: n >= 100 ? 0 : 2,
    maximumFractionDigits: 2
  });
};
const day = v => String(v || '').slice(0, 10);

let universe = [];
let universeMap = {};
let leaderMap = {};
let records = [];
let optionMap = {};
let positioning = {};
let state = {};
let intelMeta = {};
let rotationStatus = {};
let historyRows = [];
let scanRows = [];
let activeSuggestion = -1;
let activePeriod = 'swing';
let selectedTicker = null;
let leaderFresh = false;
let leaderAsOf = '';
let leaderHealthReason = '';
const exactExpiryByTicker = {};

const PERIODS = {
  short: { label: '短期 0–6DTE', hint: '直近需給。イベント・0DTE/週次ノイズの影響を受けやすい。' },
  swing: { label: 'スイング 7–21DTE', hint: 'デフォルト。1〜3週間の売買判断に使う主期間。' },
  medium: { label: '中期 22–45DTE', hint: '短期ノイズを薄め、数週間先の構造を確認。' },
  multi: { label: '複数満期統合', hint: '0〜45DTEを合算し、満期間の方向一致とWall集中を確認。' },
  exact: { label: '満期指定', hint: '銘柄詳細の満期プルダウンで実在満期を直接指定。未指定銘柄はスイング基準満期。' }
};

async function getText(k) {
  let last;
  for (const u of [SAME[k], RAW[k]]) {
    try {
      const r = await fetch(`${u}?v=${Date.now()}`, { cache: 'no-store' });
      if (r.ok) return await r.text();
      last = new Error(`${k}:${r.status}`);
    } catch (e) {
      last = e;
    }
  }
  throw last || new Error(`${k} unavailable`);
}
async function getJson(k) { return JSON.parse(await getText(k)); }

function parseCsv(text) {
  const rows = [];
  let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i], n = text[i + 1];
    if (q) {
      if (c === '"' && n === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else {
      if (c === '"') q = true;
      else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
      else if (c !== '\r') cell += c;
    }
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  if (rows.length < 2) return [];
  const h = rows[0];
  return rows.slice(1)
    .filter(r => r.some(x => x !== ''))
    .map(r => Object.fromEntries(h.map((k, i) => [k, r[i] ?? ''])));
}

function latestTwo(rows) {
  const m = {};
  for (const r of rows) {
    const t = String(r.ticker || '').trim().toUpperCase();
    if (!t) continue;
    (m[t] ??= []).push(r);
  }
  for (const t in m) {
    const d = {};
    for (const r of m[t]) d[day(r.date)] = r;
    const a = Object.values(d).sort((x, y) => String(x.date).localeCompare(String(y.date)));
    m[t] = [a.at(-1) || null, a.length > 1 ? a.at(-2) : null];
  }
  return m;
}

function parseUniverse(rows) {
  universe = [];
  universeMap = {};
  for (const r of rows) {
    const ticker = String(r['シンボル'] || r.ticker || '').trim().toUpperCase();
    if (!ticker) continue;
    const u = {
      ticker,
      name: r['名称'] || '',
      sector: r['セクター'] || '',
      industry: r['業種'] || '',
      type: String(r['証券種別'] || '').toLowerCase(),
      price: num(r['価格']),
      changePct: num(r['価格変動 %, 1日']),
      volume: num(r['出来高, 1日'])
    };
    universe.push(u);
    universeMap[ticker] = u;
  }
}

function scoreLeader(x) {
  const n = (k, d = 50) => num(x[k]) ?? d;
  const acc = num(x.slow_acceleration) ?? num(x.acceleration) ?? 0;
  let s = .36 * n('strength') + .25 * n('rs189') + .20 * n('rs63') + .11 * n('rs21') + .08 * clamp(50 + acc, 0, 100);
  if (String(x.role || '').toUpperCase() === 'LEADER') s += 3;
  if (['LEADING', 'EMERGING'].includes(String(x.group_phase || '').toUpperCase())) s += 3;
  if (String(x.breakout_status || '').toUpperCase().includes('BREAKOUT')) s += 3;
  return clamp(Math.round(s), 0, 100);
}

function collectLeaders(root) {
  const out = {};
  function walk(node, ctx = {}) {
    if (Array.isArray(node)) { node.forEach(v => walk(v, ctx)); return; }
    if (!node || typeof node !== 'object') return;
    const next = { ...ctx };
    if (node.etf) next.etf = node.etf;
    if (node.label) next.theme = node.label;
    if (typeof node.symbol === 'string' && (node.role || node.strength != null || node.rs189 != null || node.stock_rank_within_group != null)) {
      const t = node.symbol.trim().toUpperCase();
      const c = { ...node, ticker: t, theme: next.theme || '', etf: next.etf || '', leaderScore: scoreLeader(node) };
      if (!out[t] || c.leaderScore > out[t].leaderScore) out[t] = c;
    }
    for (const [k, v] of Object.entries(node)) {
      if (!['symbol', 'name'].includes(k) && v && typeof v === 'object') walk(v, next);
    }
  }
  walk(root);
  return out;
}

function updateLeaderFreshness(leaders) {
  const session = day(state.date || intelMeta?.session_date || '');
  const marketAsOf = day(leaders?.leadership_market?.asof);
  const statusAsOf = day(rotationStatus?.asof);
  leaderAsOf = marketAsOf || statusAsOf || day(leaders?.leadership_generated_at);
  leaderFresh = !!session && !!marketAsOf && !!statusAsOf && marketAsOf === session && statusAsOf === session;
  if (leaderFresh) leaderHealthReason = '';
  else if (!session) leaderHealthReason = '基準セッション不明のためLeadershipをランキングへ使用しません。';
  else leaderHealthReason = `Leadership ${leaderAsOf || '—'} / 基準 ${session}。同一セッションになるまでリーダー順位とDirectionへの加点を停止。`;
}

function expiryEntries(r) {
  return Object.entries(r?.expiries || {})
    .map(([key, e]) => ({ key, e, dte: num(e?.dte) }))
    .filter(x => x.dte !== null && x.dte >= 0)
    .sort((a, b) => a.dte - b.dte || a.key.localeCompare(b.key));
}
function bucketEntries(r, mode) {
  const a = expiryEntries(r);
  if (mode === 'short') return a.filter(x => x.dte <= 6);
  if (mode === 'swing') return a.filter(x => x.dte >= 7 && x.dte <= 21);
  if (mode === 'medium') return a.filter(x => x.dte >= 22 && x.dte <= 45);
  if (mode === 'multi') return a.filter(x => x.dte <= 45);
  return a;
}
function periodAvailability(r) {
  if (!r) return { short: false, swing: false, medium: false, multi: false, count: 0 };
  const all = expiryEntries(r);
  return {
    short: all.some(x => x.dte <= 6),
    swing: all.some(x => x.dte >= 7 && x.dte <= 21),
    medium: all.some(x => x.dte >= 22 && x.dte <= 45),
    multi: all.some(x => x.dte <= 45),
    count: all.length
  };
}
function availabilityHtml(t) {
  const a = periodAvailability(positioning[t]);
  if (!positioning[t]) return '<div class="availabilityRow"><span class="avail no">詳細Options 未取得</span></div>';
  const chip = (label, ok) => `<span class="avail ${ok ? 'yes' : 'no'}">${label} ${ok ? '●' : '—'}</span>`;
  return `<div class="availabilityRow">${chip('短期', a.short)}${chip('スイング', a.swing)}${chip('中期', a.medium)}<span class="avail count">満期 ${a.count}本</span></div>`;
}
function pickExpiry(r, mode, ticker) {
  const all = expiryEntries(r);
  if (!all.length) return null;
  if (mode === 'exact') {
    const wanted = exactExpiryByTicker[ticker];
    if (wanted && r.expiries?.[wanted]) return { key: wanted, e: r.expiries[wanted], dte: num(r.expiries[wanted]?.dte) };
    const def = r.selected_expiry || r.nearest;
    if (def && r.expiries?.[def]) return { key: def, e: r.expiries[def], dte: num(r.expiries[def]?.dte) };
    mode = 'swing';
  }
  const b = bucketEntries(r, mode);
  if (!b.length) return null;
  if (mode === 'short') return b[0];
  const target = mode === 'medium' ? 30 : 14;
  return [...b].sort((a, b) => Math.abs(a.dte - target) - Math.abs(b.dte - target) || a.dte - b.dte)[0];
}

function interp(xs, ys, x) {
  if (!xs?.length || xs.length !== ys?.length) return null;
  if (x <= xs[0]) return num(ys[0]);
  if (x >= xs.at(-1)) return num(ys.at(-1));
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) {
      const x0 = num(xs[i - 1]), x1 = num(xs[i]), y0 = num(ys[i - 1]), y1 = num(ys[i]);
      if ([x0, x1, y0, y1].some(v => v === null) || x1 === x0) return null;
      return y0 + (x - x0) / (x1 - x0) * (y1 - y0);
    }
  }
  return null;
}
function zeroCross(xs, ys) {
  for (let i = 1; i < xs.length; i++) {
    const y0 = num(ys[i - 1]), y1 = num(ys[i]), x0 = num(xs[i - 1]), x1 = num(xs[i]);
    if ([y0, y1, x0, x1].some(v => v === null)) continue;
    if (y0 === 0) return x0;
    if (y0 * y1 < 0) return x0 - y0 * (x1 - x0) / (y1 - y0);
  }
  return null;
}
function topAggWalls(strikeMap, side, spot) {
  const vals = [];
  for (const [k, v] of strikeMap) {
    const strike = Number(k), g = Math.abs(side === 'call' ? v.call : v.put);
    if (!Number.isFinite(strike) || !Number.isFinite(g) || g <= 0) continue;
    if (side === 'call' && strike <= spot) continue;
    if (side === 'put' && strike >= spot) continue;
    vals.push({ strike, gex: g });
  }
  vals.sort((a, b) => b.gex - a.gex);
  return vals.slice(0, 3);
}
function aggregateExpiry(r, entries) {
  if (!entries.length) return null;
  const spot = num(r.spot);
  if (spot === null) return null;
  const strikeMap = new Map();
  let totalOi = 0, callOi = 0, putOi = 0, net = 0, conf = 'LOW';
  for (const { e } of entries) {
    totalOi += num(e.total_oi) || 0;
    callOi += num(e.call_oi) || 0;
    putOi += num(e.put_oi) || 0;
    net += num(e.net_gex) || 0;
    if (String(e.confidence).toUpperCase() === 'HIGH') conf = 'HIGH';
    else if (conf !== 'HIGH' && String(e.confidence).toUpperCase() === 'MEDIUM') conf = 'MEDIUM';
    for (const s of e.strikes || []) {
      const k = String(s.k), v = strikeMap.get(k) || { call: 0, put: 0 };
      v.call += num(s.call) || 0;
      v.put += num(s.put) || 0;
      strikeMap.set(k, v);
    }
  }
  const callWalls = topAggWalls(strikeMap, 'call', spot), putWalls = topAggWalls(strikeMap, 'put', spot);
  const cw = callWalls[0]?.strike ?? null, pw = putWalls[0]?.strike ?? null;
  const profiles = entries.map(x => x.e.profile).filter(p => Array.isArray(p?.x) && Array.isArray(p?.y) && p.x.length > 1 && p.x.length === p.y.length);
  let gf = null;
  if (profiles.length) {
    const xs = profiles[0].x.map(Number);
    const ys = xs.map(x => profiles.reduce((sum, p) => sum + (interp(p.x.map(Number), p.y.map(Number), x) || 0), 0));
    gf = zeroCross(xs, ys);
  }
  const anchor = [...entries].sort((a, b) => b.dte - a.dte)[0];
  return {
    key: `複数 ${entries[0].dte}–${entries.at(-1).dte}DTE`,
    e: {
      expiry: `複数 ${entries[0].dte}–${entries.at(-1).dte}DTE`,
      dte: entries.at(-1).dte,
      call_wall: cw,
      put_wall: pw,
      gamma_flip: gf,
      net_gex: net,
      total_oi: totalOi,
      call_oi: callOi,
      put_oi: putOi,
      n_strikes: strikeMap.size,
      confidence: conf,
      call_walls: callWalls,
      put_walls: putWalls,
      expected_move: anchor?.e?.expected_move,
      expected_move_pct: anchor?.e?.expected_move_pct,
      expected_move_method: anchor?.e?.expected_move_method ? `multi→${anchor.key} ${anchor.e.expected_move_method}` : 'multi',
      expected_low: anchor?.e?.expected_low,
      expected_high: anchor?.e?.expected_high,
      atm_iv: anchor?.e?.atm_iv,
      multi_source_expiries: entries.map(x => x.key)
    },
    dte: entries.at(-1).dte
  };
}
function modeChoice(r, ticker) {
  if (activePeriod === 'multi') return aggregateExpiry(r, bucketEntries(r, 'multi'));
  return pickExpiry(r, activePeriod, ticker);
}

function histObs(r) {
  if (!r) return null;
  return {
    date: day(r.date), price_session_date: day(r.date), expiry: r.expiry || '',
    spot: num(r.spot), atr14: num(r.atr14), call_wall: num(r.call_wall), put_wall: num(r.put_wall),
    gamma_flip: num(r.gamma_flip), net_gex: num(r.net_gex), regime: r.regime || 'UNKNOWN',
    confidence: String(r.confidence || '').toUpperCase(), total_oi: num(r.total_oi), n_strikes: num(r.n_strikes),
    detail: false, stale: false, session_consistent: false, expected_move: null
  };
}
function currentObs(r, asof, ticker) {
  const choice = modeChoice(r, ticker);
  if (!choice) return null;
  const k = choice.key, e = choice.e || {};
  const em = e.expected_move !== undefined ? {
    expected_move: e.expected_move,
    expected_move_pct: e.expected_move_pct,
    expected_move_method: e.expected_move_method,
    expected_low: e.expected_low,
    expected_high: e.expected_high,
    atm_iv: e.atm_iv
  } : r.expected_move || {};
  return {
    date: day(r.price_session_date || r.asof || asof),
    price_session_date: day(r.price_session_date || r.asof || asof),
    expected_session_date: day(r.expected_session_date),
    history_session_date: day(r.history_session_date),
    tech_session_date: day(r.tech_session_date),
    session_consistent: r.session_consistent === true,
    price_source: r.price_source || r.source || '',
    options_observed_at: r.options_observed_at || r.asof || asof || '',
    oi_basis: r.oi_basis || '',
    expiry: k || '', dte: num(e.dte), spot: num(r.spot), atr14: num(r.atr14),
    call_wall: num(e.call_wall), put_wall: num(e.put_wall), gamma_flip: num(e.gamma_flip), net_gex: num(e.net_gex),
    regime: regime(num(r.spot), num(e.gamma_flip), num(r.atr14)), confidence: String(e.confidence || r.confidence || '').toUpperCase(),
    total_oi: num(e.total_oi), n_strikes: num(e.n_strikes), call_oi: num(e.call_oi), put_oi: num(e.put_oi),
    call_wall_share: num(e.call_wall_share), put_wall_share: num(e.put_wall_share),
    call_wall_vs_second: num(e.call_wall_vs_second), put_wall_vs_second: num(e.put_wall_vs_second),
    call_walls: e.call_walls || [], put_walls: e.put_walls || [], tech: r.tech || {}, detail: true,
    stale: !!r.stale, refresh_failed: !!r.refresh_failed, expected_move: em,
    upstream_change_pct: num(r.upstream_change_pct), multi_source_expiries: e.multi_source_expiries || null
  };
}

function datr(level, spot, atr) { return level !== null && spot !== null && atr && atr > 0 ? (level - spot) / atr : null; }
function regime(spot, gf, atr) {
  if (spot === null || gf === null) return 'UNKNOWN';
  if (atr && Math.abs(spot - gf) / atr <= 1) return 'NEAR_FLIP';
  return spot > gf ? 'POSITIVE_GAMMA' : 'NEGATIVE_GAMMA';
}
function multiConsensus(r) {
  if (!r) return null;
  const s = num(r.spot), a = num(r.atr14), entries = bucketEntries(r, 'multi');
  const rs = entries.map(({ e }) => regime(s, num(e.gamma_flip), a));
  const c = x => rs.filter(v => v === x).length;
  return rs.length ? { count: rs.length, positive: c('POSITIVE_GAMMA'), near: c('NEAR_FLIP'), negative: c('NEGATIVE_GAMMA') } : null;
}
function sameHorizon(p, c) { return !!p && !!c && p.expiry && c.expiry && p.expiry === c.expiry && !String(c.expiry).startsWith('複数'); }
function crossedCall(p, c) { return sameHorizon(p, c) && p.spot !== null && p.call_wall !== null && c.spot !== null && p.spot < p.call_wall && c.spot > p.call_wall * 1.002; }
function crossedPut(p, c) { return sameHorizon(p, c) && p.spot !== null && p.put_wall !== null && c.spot !== null && p.spot > p.put_wall && c.spot < p.put_wall * .998; }
function timeQuality(cur, source, u) {
  if (source !== 'DETAIL') return 'UNVERIFIED_HISTORY';
  if (!cur) return 'PERIOD_UNAVAILABLE';
  if (cur.refresh_failed || cur.stale) return 'STALE';
  const session = day(state.date), pday = cur.price_session_date;
  if (cur.session_consistent && (!session || pday === session)) return 'VERIFIED';
  if (!cur.expected_session_date && session && pday === session && u?.price && cur.spot && Math.abs(cur.spot / u.price - 1) <= .003) return 'INFERRED_MATCH';
  return 'MISMATCH';
}

function localSignal(cur, prev, m, tq) {
  if (!cur) return { signal: 'DATA LOW', score: 0, reasons: ['選択期間に取得済み満期なし'] };
  if (!['VERIFIED', 'INFERRED_MATCH'].includes(tq) || cur.confidence === 'LOW') return { signal: 'DATA LOW', score: 0, reasons: ['価格・Options時点またはデータ品質が不足'] };
  let s = 50, why = [];
  const rg = cur.regime || regime(cur.spot, cur.gamma_flip, cur.atr14), ca = datr(cur.call_wall, cur.spot, cur.atr14), pa = datr(cur.put_wall, cur.spot, cur.atr14);
  if (rg === 'POSITIVE_GAMMA') { s += 18; why.push('Gamma Flip上'); }
  else if (rg === 'NEGATIVE_GAMMA') { s -= 28; why.push('Gamma Flip下'); }
  else if (rg === 'NEAR_FLIP') { s -= 4; why.push('Gamma Flip近辺'); }
  if (pa !== null && pa < 0 && Math.abs(pa) <= 2.2) { s += 10; why.push('Put支持が近い'); }
  if (ca !== null) {
    if (ca > 0 && ca <= 1.2) { s += 4; why.push('Call Wall接近'); }
    else if (ca > 1.2) { s += 6; why.push('上側余地'); }
  }
  if (cur.net_gex !== null && cur.net_gex > 0) s += 5;
  if (m && m.positive > m.negative) s += 5;
  const br = crossedCall(prev, cur);
  if (br) { s += 18; why.push('同一満期の前回Call Wall突破'); }
  s = clamp(Math.round(s), 0, 100);
  let signal = 'NEUTRAL';
  if (br && rg !== 'NEGATIVE_GAMMA') signal = 'ACCELERATION';
  else if (rg === 'NEGATIVE_GAMMA') signal = 'HEADWIND';
  else if (['POSITIVE_GAMMA', 'NEAR_FLIP'].includes(rg) && ca !== null && ca > 0 && ca <= 1.2) signal = 'BREAKOUT WATCH';
  else if (rg === 'POSITIVE_GAMMA') signal = 'SUPPORTIVE';
  return { signal, score: s, reasons: why };
}

function directionBias(cur, prev, m, u, l, tq) {
  if (!cur || !['VERIFIED', 'INFERRED_MATCH'].includes(tq) || cur.spot === null || cur.confidence === 'LOW') {
    return { direction: 'UNKNOWN', score: 50, confidence: 0, reasons: [cur ? '時間整合または品質未確認' : '選択期間に満期なし'], volatility: 'UNKNOWN' };
  }
  let s = 50, why = [];
  const spot = cur.spot, atr = cur.atr14 || spot * .02, gf = cur.gamma_flip, pw = cur.put_wall, cw = cur.call_wall;
  if (gf !== null) {
    const d = (spot - gf) / atr;
    if (d > .35) { s += 10; why.push('終値がFlip上'); }
    else if (d < -.35) { s -= 10; why.push('終値がFlip下'); }
    else why.push('Flip近辺');
  }
  const ema = num(cur.tech?.['21EMA']), vw = num(cur.tech?.['63VWAP']);
  if (ema !== null) { s += spot > ema ? 8 : -8; why.push(spot > ema ? '21EMA上' : '21EMA下'); }
  if (vw !== null) { s += spot > vw ? 5 : -5; why.push(spot > vw ? '63VWAP上' : '63VWAP下'); }
  const ch = num(u?.changePct ?? cur.upstream_change_pct);
  if (ch !== null) {
    if (ch >= 2) { s += 5; why.push('当日モメンタム上'); }
    else if (ch <= -2) { s -= 5; why.push('当日モメンタム下'); }
  }
  const up = datr(cw, spot, atr), down = pw !== null ? (spot - pw) / atr : null;
  if (up !== null && down !== null && up > 0 && down > 0) {
    const rr = up / Math.max(down, .05);
    if (rr >= 1.4) { s += 10; why.push('上側余地優勢'); }
    else if (rr <= .7) { s -= 10; why.push('下側余地優勢'); }
    else if (rr >= 1.15) s += 4;
    else if (rr <= .87) s -= 4;
  }
  if (crossedCall(prev, cur)) { s += 12; why.push('同一満期の前回Call Wall突破'); }
  if (crossedPut(prev, cur)) { s -= 12; why.push('同一満期の前回Put Wall割れ'); }
  if (m) {
    if (m.positive > m.negative) { s += 6; why.push('0–45DTEでFlip上多数'); }
    else if (m.negative > m.positive) { s -= 6; why.push('0–45DTEでFlip下多数'); }
  }
  if (leaderFresh && l?.leaderScore >= 75) { s += 6; why.push('同日Leadership上位'); }
  else if (leaderFresh && l?.leaderScore >= 60) s += 3;
  s = clamp(Math.round(s), 0, 100);
  const rg = cur.regime || 'UNKNOWN';
  const direction = s >= 68 ? 'UP' : s <= 32 ? 'DOWN' : (44 <= s && s <= 56 && rg === 'POSITIVE_GAMMA' ? 'RANGE' : (['NEGATIVE_GAMMA', 'NEAR_FLIP'].includes(rg) ? 'VOLATILE' : 'RANGE'));
  const conf = clamp(Math.round(45 + Math.abs(s - 50) * 1.35 + (cur.confidence === 'HIGH' ? 8 : 0)), 20, 95);
  const ep = num(cur.expected_move?.expected_move_pct);
  let vol = ep === null ? (rg === 'NEGATIVE_GAMMA' ? 'EXPANSION' : 'UNKNOWN') : ep >= .08 ? 'HIGH' : ep >= .04 ? 'MEDIUM' : 'LOW';
  if (rg === 'NEGATIVE_GAMMA' && ['LOW', 'MEDIUM'].includes(vol)) vol = 'EXPANSION';
  return { direction, score: s, confidence: conf, reasons: why, volatility: vol };
}

function analysisText(cur, d, l) {
  if (!cur) return '選択した期間に取得済み満期がありません。別の期間または満期指定を選んでください。';
  if (d.direction === 'UNKNOWN') return '基準終値とOptions計算時点、またはOptions品質を確認できないため方向判定を止めています。';
  const lead = leaderFresh && l?.leaderScore >= 70 ? ' Leadershipも同日データで上位。' : '';
  const p = { UP: 'オプション配置は上方向優位。', DOWN: 'オプション配置は下方向優位。', RANGE: '現状はレンジ寄り。', VOLATILE: '方向は混在、値幅拡大に注意。' }[d.direction] || '';
  const bits = [];
  if (cur.gamma_flip !== null) bits.push(`終値${money(cur.spot)}はFlip ${money(cur.gamma_flip)}の${cur.spot > cur.gamma_flip ? '上' : '下'}`);
  if (cur.put_wall !== null) bits.push(`下は${money(cur.put_wall)}`);
  if (cur.call_wall !== null) bits.push(`上は${money(cur.call_wall)}`);
  const ep = num(cur.expected_move?.expected_move_pct);
  if (ep !== null) bits.push(`織込み値幅 約±${(ep * 100).toFixed(1)}%`);
  return p + bits.join('、') + '。' + lead;
}
function plan(cur) {
  if (!cur) return { up: '選択期間に満期データなし。', down: '選択期間に満期データなし。' };
  const cw = cur.call_wall, pw = cur.put_wall, gf = cur.gamma_flip;
  const up = cw !== null ? `${money(cw)} を終値突破・維持なら上方向の加速候補。` : '上側Call Wall未検出。';
  let down = gf !== null ? `${money(gf)} 終値割れで構造悪化。` : '';
  if (pw !== null) down += `${money(pw)} 割れで下方向加速を警戒。`;
  return { up, down: down || '明確な下方向トリガーなし' };
}

function rebuildRecords() {
  const dh = latestTwo(historyRows), sh = latestTwo(scanRows);
  const all = new Set([...Object.keys(positioning), ...Object.keys(dh), ...Object.keys(sh)]);
  records = [];
  optionMap = {};
  for (const t of all) {
    let cur, prev, source, periodUnavailable = false;
    if (positioning[t]) {
      cur = currentObs(positioning[t], intelMeta?.positioning_asof, t);
      prev = histObs((dh[t] || [])[1]);
      source = 'DETAIL';
      periodUnavailable = !cur;
    } else {
      const p = sh[t] || dh[t];
      if (!p) continue;
      cur = histObs(p[0]);
      prev = histObs(p[1]);
      source = sh[t] ? 'SCAN' : 'HISTORY';
    }
    const u = universeMap[t] || {}, l = leaderFresh ? (leaderMap[t] || null) : null, m = multiConsensus(positioning[t]);
    const tq = timeQuality(cur, source, u), sig = localSignal(cur, prev, m, tq), dir = directionBias(cur, prev, m, u, l, tq);
    const rec = {
      ticker: t, name: u.name || '', sector: u.sector || '', industry: u.industry || '', source,
      time_quality: tq, signal: sig.signal, score: sig.score, reasons: sig.reasons,
      current: cur, previous: prev, multi_expiry: m, direction: dir,
      analysis: analysisText(cur, dir, l), leader: l, plan: plan(cur), period_unavailable: periodUnavailable
    };
    records.push(rec);
    optionMap[t] = rec;
  }
}

function isUsable(o) {
  return !!o && !!o.current && ['VERIFIED', 'INFERRED_MATCH'].includes(o.time_quality) && o.current.confidence !== 'LOW' && o.signal !== 'DATA LOW';
}
function coverageStats() {
  const detail = records.filter(r => r.source === 'DETAIL').length;
  const history = records.filter(r => r.source !== 'DETAIL').length;
  const valid = records.filter(isUsable).length;
  const invalid = records.filter(r => r.source === 'DETAIL' && !isUsable(r)).length;
  return { valid, detail, history, invalid };
}
function renderHealth() {
  const s = coverageStats();
  $('#coverageValid').textContent = s.valid.toLocaleString();
  $('#coverageDetail').textContent = s.detail.toLocaleString();
  $('#coverageHistory').textContent = s.history.toLocaleString();
  $('#coverageInvalid').textContent = s.invalid.toLocaleString();
  const session = day(state.date || intelMeta?.session_date);
  const issues = [];
  if (!leaderFresh) issues.push(leaderHealthReason);
  const posSession = day(positioningSessionDate());
  if (session && posSession && session !== posSession) issues.push(`Options価格セッション ${posSession} / 基準 ${session}。一致しないデータはランキングから除外。`);
  const node = $('#healthNote');
  if (issues.length) {
    node.className = 'healthNote warn';
    node.textContent = issues.join(' ');
  } else {
    node.className = 'healthNote ok';
    node.textContent = `基準 ${session || '—'}。価格・Options・Leadershipの同一セッション確認済み。`;
  }
}
function positioningSessionDate() {
  return intelMeta?.session_date || Object.values(positioning)[0]?.price_session_date || state.date || '';
}

function dirView(d) {
  const x = d?.direction;
  return x === 'UP' ? { arrow: '↑', label: '上方向', cls: 'bUp', ac: 'up' }
    : x === 'DOWN' ? { arrow: '↓', label: '下方向', cls: 'bDown', ac: 'down' }
    : x === 'RANGE' ? { arrow: '↔', label: 'レンジ', cls: 'bRange', ac: 'range' }
    : x === 'VOLATILE' ? { arrow: '↕', label: '変動拡大', cls: 'bVol', ac: 'vol' }
    : { arrow: '?', label: '判定保留', cls: 'bLow', ac: 'vol' };
}
function leaderBadge(l) { return leaderFresh && l ? `<span class="badge bLeader">主導株 ${l.leaderScore ?? l.leader_score ?? '—'}</span>` : ''; }
function expectedLabel(c) { const ep = num(c?.expected_move?.expected_move_pct); return ep === null ? '—' : `±${(ep * 100).toFixed(1)}%`; }
function horizonLabel(c) {
  if (!c) return PERIODS[activePeriod].label;
  if (activePeriod === 'multi') return c.expiry;
  const d = c.dte !== null && c.dte !== undefined ? ` · ${c.dte}DTE` : '';
  return `${c.expiry || '—'}${d}`;
}
function miniCard(t, o, l, combined) {
  const u = universeMap[t] || {}, d = dirView(o?.direction), c = o?.current, verified = isUsable(o), periodMissing = o?.period_unavailable;
  const levels = verified && c ? `<div class="miniLevels"><div class="miniLv"><span>終値</span><b>${money(c.spot)}</b></div><div class="miniLv"><span>支持</span><b>${money(c.put_wall)}</b></div><div class="miniLv"><span>上値壁</span><b>${money(c.call_wall)}</b></div><div class="miniLv"><span>織込み</span><b>${expectedLabel(c)}</b></div></div>` : '';
  const note = periodMissing ? 'この期間の満期データは未取得。' : o ? (verified ? o.analysis : (o.source === 'DETAIL' ? 'Options詳細はあるが時点・品質条件を満たさない。' : '履歴のみ。現在の方向判定には使用しない。')) : 'Options詳細未取得。';
  return `<article class="miniCard" data-ticker="${esc(t)}"><div class="miniHead"><div class="ticker">${esc(t)}</div><div class="company">${esc(u.name || l?.name || '')}</div><div class="score">${verified ? (combined ?? o?.direction?.confidence ?? '—') : '—'}</div></div><div class="badges">${leaderBadge(l)}<span class="badge ${d.cls}">${verified ? `${d.arrow} ${d.label}` : '? 未判定'}</span>${periodMissing ? '<span class="badge bLow">期間データなし</span>' : o && !verified ? '<span class="badge bLow">参考外</span>' : ''}</div>${verified ? `<div class="miniDirection"><strong class="${d.cls}">${d.arrow} ${d.label}</strong><span>方向 ${o.direction.score}/100 · 確度 ${o.direction.confidence}</span></div>` : ''}<div class="miniThesis">${esc(note)}</div>${levels}<div class="miniMeta">${esc(u.sector || '')} · ${esc(u.industry || '')}${c ? ` · ${esc(horizonLabel(c))}` : ''}</div></article>`;
}
function buildLeaderRows() {
  if (!leaderFresh) return [];
  const a = [];
  for (const [t, l] of Object.entries(leaderMap)) {
    const o = optionMap[t] || null, verified = isUsable(o), bonus = verified ? (o.direction.direction === 'UP' ? 15 : o.direction.direction === 'DOWN' ? -12 : 0) : 0;
    const combined = Math.round(.78 * l.leaderScore + .22 * (verified ? o.direction.confidence : 50) + bonus);
    a.push({ t, l, o, combined });
  }
  return a.sort((x, y) => y.combined - x.combined).slice(0, 8);
}
function renderLeaders() {
  if (!leaderFresh) {
    $('#leaders').innerHTML = `<div class="noData"><strong>Leadership更新待ち</strong>${esc(leaderHealthReason)} 古いLeadershipを今日のランキングへ流用しません。</div>`;
    return;
  }
  const a = buildLeaderRows();
  $('#leaders').innerHTML = a.length ? a.map(x => miniCard(x.t, x.o, x.l, x.combined)).join('') : '<div class="empty">Leadershipデータなし。</div>';
  bind($('#leaders'));
}
function directionalRows(dir) {
  return records.filter(r => isUsable(r) && r.direction?.direction === dir && r.direction.confidence >= 55 && String(universeMap[r.ticker]?.type || 'stock') === 'stock')
    .sort((a, b) => dir === 'UP' ? b.direction.score - a.direction.score : a.direction.score - b.direction.score)
    .slice(0, 8);
}
function renderDirectional() {
  const up = directionalRows('UP'), dn = directionalRows('DOWN');
  $('#bullish').innerHTML = up.length ? up.map(r => miniCard(r.ticker, r, leaderFresh ? leaderMap[r.ticker] : null, r.direction.confidence)).join('') : '<div class="empty">この期間で有効な強い上方向配置なし。</div>';
  $('#bearish').innerHTML = dn.length ? dn.map(r => miniCard(r.ticker, r, leaderFresh ? leaderMap[r.ticker] : null, r.direction.confidence)).join('') : '<div class="empty">この期間で有効な強い下方向配置なし。</div>';
  bind($('#bullish')); bind($('#bearish'));
}
function renderAll() {
  const a = [...records].sort((a, b) => (isUsable(b) ? 1 : 0) - (isUsable(a) ? 1 : 0) || Math.abs(b.direction.score - 50) - Math.abs(a.direction.score - 50)).slice(0, 150);
  $('#allRecords').innerHTML = a.map(r => {
    const u = universeMap[r.ticker] || {}, d = dirView(r.direction), valid = isUsable(r);
    return `<div class="allRow" data-ticker="${esc(r.ticker)}"><strong>${esc(r.ticker)}</strong><span>${esc(u.name || '')}</span><em class="${valid ? d.cls : 'bLow'}">${valid ? `${d.arrow} ${d.label}` : '参考外'}</em><b>${valid ? r.direction.confidence : '—'}</b></div>`;
  }).join('');
  bind($('#allRecords'));
}
function bind(root) { for (const e of root.querySelectorAll('[data-ticker]')) e.addEventListener('click', () => selectTicker(e.dataset.ticker, true)); }
function fmtTime(x) {
  if (!x) return '—';
  const d = new Date(x);
  if (!Number.isFinite(d.getTime())) return String(x);
  return new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(d) + ' JST';
}
function detailMetrics(o) {
  const c = o.current, m = o.multi_expiry, em = c?.expected_move || {};
  return `<div class="detailGrid"><div class="detailMetric"><span>Direction</span><b>${o.direction.score}/100</b></div><div class="detailMetric"><span>Options配置</span><b>${o.score ?? '—'}/100</b></div><div class="detailMetric"><span>Net GEX</span><b>${c?.net_gex === null || c?.net_gex === undefined ? '—' : (c.net_gex / 1e6).toFixed(1) + 'M'}</b></div><div class="detailMetric"><span>0–45DTE一致</span><b>${m ? `${m.positive}上 / ${m.negative}下` : '—'}</b></div><div class="detailMetric"><span>ATM IV</span><b>${num(em.atm_iv) === null ? '—' : (em.atm_iv * 100).toFixed(1) + '%'}</b></div><div class="detailMetric"><span>P/C OI</span><b>${c?.put_oi && c?.call_oi ? (c.put_oi / c.call_oi).toFixed(2) : '—'}</b></div><div class="detailMetric"><span>OI</span><b>${c?.total_oi?.toLocaleString?.() ?? '—'}</b></div><div class="detailMetric"><span>Strikes</span><b>${c?.n_strikes ?? '—'}</b></div></div>`;
}
function distText(level, c) {
  const a = datr(level, c.spot, c.atr14);
  if (level === null || c.spot === null) return '';
  const p = (level / c.spot - 1) * 100;
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%${a !== null ? ' / ' + Math.abs(a).toFixed(1) + 'ATR' : ''}`;
}
function expiryPicker(t) {
  const r = positioning[t];
  if (!r) return '';
  const a = expiryEntries(r);
  if (!a.length) return '';
  const selected = exactExpiryByTicker[t] || r.selected_expiry || r.nearest || a[0].key;
  return `<div class="expiryPicker"><div><span>特定満期を指定</span><small>選ぶと「満期指定」モードへ切替</small></div><select id="expirySelect">${a.map(x => `<option value="${esc(x.key)}" ${x.key === selected ? 'selected' : ''}>${esc(x.key)} · ${x.dte}DTE</option>`).join('')}</select></div>`;
}
function selectedHtml(t) {
  const u = universeMap[t], o = optionMap[t], l = leaderFresh ? leaderMap[t] : null, raw = positioning[t];
  if (!u && !o && !l) return '<div class="noData"><strong>銘柄が見つかりません</strong>Tickerまたは会社名で検索してください。</div>';
  const name = u?.name || l?.name || o?.name || '', price = u?.price ?? o?.current?.spot;
  const leaderStats = l ? `<div class="leaderStats"><span class="statPill">Leader<b>${l.leaderScore}</b></span><span class="statPill">RS189<b>${num(l.rs189) ?? '—'}</b></span><span class="statPill">RS63<b>${num(l.rs63) ?? '—'}</b></span><span class="statPill">RS21<b>${num(l.rs21) ?? '—'}</b></span></div>` : '';
  const leaderWait = !leaderFresh && leaderMap[t] ? '<span class="badge bLow">Leadership更新待ち</span>' : '';
  const availability = availabilityHtml(t);
  if (!raw) {
    return `<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(t)}</div><div class="selectedName">${esc(name)} · ${esc(u?.sector || '')} · ${esc(u?.industry || '')}</div></div><div class="selectedPrice"><b>${money(price)}</b><span>基準価格 ${esc(state.date || '—')}</span></div></div><div class="selectedBadges">${leaderBadge(l)}${leaderWait}<span class="badge bLow">詳細Options未取得</span></div>${availability}${leaderStats}<div class="noData"><strong>銘柄は存在します。</strong>履歴があっても現在の壁・方向・値幅には流用しません。詳細Options取得後に判定します。</div></article>`;
  }
  if (o?.period_unavailable) {
    return `<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(t)}</div><div class="selectedName">${esc(name)} · ${esc(u?.sector || '')} · ${esc(u?.industry || '')}</div></div><div class="selectedPrice"><b>${money(price)}</b><span>基準終値 ${esc(state.date || '—')}</span></div></div><div class="selectedBadges">${leaderBadge(l)}${leaderWait}<span class="badge bLow">${esc(PERIODS[activePeriod].label)} データなし</span></div>${availability}${expiryPicker(t)}${leaderStats}<div class="noData"><strong>Options自体は取得済みです。</strong>現在の詳細スナップショットにこの期間の満期がありません。別期間か特定満期を選んでください。</div></article>`;
  }
  if (!o) return '<div class="noData"><strong>Options未取得</strong>現在の詳細スナップショットがありません。</div>';
  const c = o.current, verified = isUsable(o), d = dirView(o.direction), em = c?.expected_move || {};
  const reasons = [...(o.direction?.reasons || []), ...(o.reasons || [])].filter((x, i, a) => a.indexOf(x) === i).map(x => `<span class="reason">${esc(x)}</span>`).join('');
  if (!verified) {
    const why = o.time_quality === 'VERIFIED' || o.time_quality === 'INFERRED_MATCH' ? `Options品質 ${esc(c?.confidence || '—')} のため` : `基準価格 ${money(price)} に対しOptions計算基準 ${money(c?.spot)} / ${esc(c?.price_session_date || c?.date || '—')} のため`;
    return `<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(t)}</div><div class="selectedName">${esc(name)} · ${esc(u?.sector || '')}</div></div><div class="selectedPrice"><b>${money(price)}</b><span>基準セッション ${esc(state.date || '—')}</span></div></div><div class="selectedBadges">${leaderBadge(l)}${leaderWait}<span class="badge bLow">方向判定停止</span></div>${availability}${expiryPicker(t)}<div class="decision"><label>データ監査</label><div>${why}、現在の売買判断へ使用しません。古いWall・低品質チェーンを代用しません。</div></div>${leaderStats}</article>`;
  }
  const p = plan(c), move = num(em.expected_move), ep = num(em.expected_move_pct), lo = num(em.expected_low), hi = num(em.expected_high);
  return `<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(t)}</div><div class="selectedName">${esc(name)} · ${esc(u?.sector || '')} · ${esc(u?.industry || '')}</div></div><div class="selectedPrice"><b>${money(c.spot)}</b><span>基準終値 ${esc(c.price_session_date || '—')}</span></div></div><div class="selectedBadges">${leaderBadge(l)}${leaderWait}<span class="badge ${d.cls}">${d.arrow} ${d.label}</span><span class="badge ${o.signal === 'ACCELERATION' ? 'bAccel' : o.signal === 'HEADWIND' ? 'bHead' : 'bNeutral'}">${esc(o.signal || '—')}</span><span class="badge bPeriod">${esc(horizonLabel(c))}</span></div>${availability}${expiryPicker(t)}<div class="directionHero"><div class="directionArrow ${d.ac}">${d.arrow}</div><div class="directionCopy"><b>${d.label}</b><span>${esc(o.direction.volatility || '')} / 確度 ${o.direction.confidence}</span></div><div class="directionScore"><b>${o.direction.score}/100</b><span>方向スコア</span></div></div><div class="decision"><label>配置読み</label><div>${esc(o.analysis || analysisText(c, o.direction, l))}</div></div><div class="bigLevels"><div class="bigLv"><span>終値</span><b>${money(c.spot)}</b><small>${esc(c.price_session_date || '')}</small></div><div class="bigLv"><span>Put支持</span><b>${money(c.put_wall)}</b><small>${distText(c.put_wall, c)}</small></div><div class="bigLv"><span>Gamma Flip</span><b>${money(c.gamma_flip)}</b><small>${distText(c.gamma_flip, c)}</small></div><div class="bigLv"><span>Call壁</span><b>${money(c.call_wall)}</b><small>${distText(c.call_wall, c)}</small></div><div class="bigLv"><span>織込み値幅</span><b>${ep === null ? '—' : '±' + (ep * 100).toFixed(1) + '%'}</b><small>${esc(em.expected_move_method || '')}</small></div></div><div class="expectedBox"><label>${esc(c.expiry || '')} の値動き見込み</label><div class="expectedRow"><b>${move === null ? '—' : `±${money(move)}`}</b><span>想定レンジ ${money(lo)} ～ ${money(hi)}</span><span>${esc(em.expected_move_method || '')}</span></div></div><div class="scenario"><div class="scenarioBox"><label>↑ 上方向</label><div>${esc(p.up)}</div></div><div class="scenarioBox"><label>↓ 下方向</label><div>${esc(p.down)}</div></div></div><div class="timeBox"><div class="timeCell"><span>価格セッション</span><b class="timeOk">${esc(c.price_session_date || '—')}</b></div><div class="timeCell"><span>Options取得</span><b>${esc(fmtTime(c.options_observed_at))}</b></div><div class="timeCell"><span>Tech最終足</span><b>${esc(c.tech_session_date || c.history_session_date || '—')}</b></div><div class="timeCell"><span>OI更新時刻</span><b>provider非開示</b></div></div>${leaderStats}<details class="moreInfo"><summary>詳しい根拠を見る</summary>${detailMetrics(o)}<div class="reasonRow">${reasons}</div><div class="miniMeta">price source ${esc(c.price_source || '—')} · expiry ${esc(c.expiry || '—')} · confidence ${esc(c.confidence || '—')} · time ${esc(o.time_quality)}</div></details></article>`;
}

function bindExpiryPicker(t) {
  const el = $('#expirySelect');
  if (!el) return;
  el.addEventListener('change', () => { exactExpiryByTicker[t] = el.value; setPeriod('exact', false); rebuildAndRender(t, false); });
}
function selectTicker(t, scroll) {
  t = String(t || '').trim().toUpperCase();
  if (!t) return;
  selectedTicker = t;
  $('#selected').innerHTML = selectedHtml(t);
  $('#selectedSection').hidden = false;
  $('#search').value = t;
  hideSuggestions();
  bindExpiryPicker(t);
  if (scroll) $('#selectedSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function matches(q) {
  q = q.trim().toLowerCase();
  if (!q) return [];
  const exact = [], pre = [], other = [];
  for (const u of universe) {
    const t = u.ticker.toLowerCase(), hay = `${u.name} ${u.sector} ${u.industry}`.toLowerCase();
    if (t === q) exact.push(u);
    else if (t.startsWith(q)) pre.push(u);
    else if (hay.includes(q)) other.push(u);
  }
  return [...exact, ...pre, ...other].slice(0, 10);
}
function showSuggestions() {
  const b = $('#suggestions'), a = matches($('#search').value);
  activeSuggestion = -1;
  if (!a.length) { b.hidden = true; b.innerHTML = ''; return; }
  b.innerHTML = a.map((u, i) => `<div class="suggestion" data-ticker="${esc(u.ticker)}" data-i="${i}"><strong>${esc(u.ticker)}</strong><span>${esc(u.name)}</span><small>${esc(u.sector)}</small></div>`).join('');
  b.hidden = false;
  for (const e of b.querySelectorAll('.suggestion')) e.addEventListener('click', () => selectTicker(e.dataset.ticker, true));
}
function hideSuggestions() { const b = $('#suggestions'); b.hidden = true; b.innerHTML = ''; activeSuggestion = -1; }
function runSearch() {
  const q = $('#search').value.trim();
  if (!q) return;
  const t = q.toUpperCase();
  if (universeMap[t] || optionMap[t] || leaderMap[t]) selectTicker(t, true);
  else {
    const m = matches(q);
    if (m[0]) selectTicker(m[0].ticker, true);
    else { $('#selected').innerHTML = '<div class="noData"><strong>見つかりません</strong>ユニバースにありません。</div>'; $('#selectedSection').hidden = false; hideSuggestions(); }
  }
}
function updatePeriodUi() {
  for (const b of document.querySelectorAll('[data-period]')) b.classList.toggle('active', b.dataset.period === activePeriod);
  const p = PERIODS[activePeriod];
  $('#periodCurrent').textContent = p.label;
  $('#periodHint').textContent = p.hint;
}
function setPeriod(mode, rerender = true) {
  if (!PERIODS[mode]) return;
  activePeriod = mode;
  updatePeriodUi();
  if (rerender) rebuildAndRender(selectedTicker, false);
}
function rebuildAndRender(ticker, scroll) {
  rebuildRecords();
  renderHealth();
  renderLeaders();
  renderDirectional();
  renderAll();
  const s = coverageStats();
  $('#stamp').textContent = `Universe ${universe.length.toLocaleString()} / 有効 ${s.valid.toLocaleString()} / 詳細 ${s.detail.toLocaleString()} / 履歴のみ ${s.history.toLocaleString()} / ${PERIODS[activePeriod].label}`;
  if (ticker) selectTicker(ticker, scroll);
}

async function init() {
  try {
    const [uniText, leaders, rotSt, st, pos, dhText, shText, intel] = await Promise.all([
      getText('uni'), getJson('leaders').catch(() => null), getJson('rotStatus').catch(() => ({})), getJson('state').catch(() => ({})),
      getJson('pos').catch(() => ({ tickers: {} })), getText('dh').catch(() => ''), getText('sh').catch(() => ''), getJson('intel').catch(() => null)
    ]);
    state = st || {};
    intelMeta = intel || {};
    rotationStatus = rotSt || {};
    parseUniverse(parseCsv(uniText));
    leaderMap = leaders ? collectLeaders(leaders) : {};
    updateLeaderFreshness(leaders || {});
    positioning = pos.tickers || {};
    historyRows = parseCsv(dhText);
    scanRows = parseCsv(shText);
    rebuildAndRender(null, false);
    $('#priceAsOf').textContent = day(state.date || intel?.session_date || pos.session_date) || '—';
    $('#optionsAsOf').textContent = fmtTime(pos.asof || intel?.positioning_asof);
    $('#leaderAsOf').textContent = leaderFresh ? (leaderAsOf || '—') : `${leaderAsOf || '—'} ⚠`;
    $('#marketState').textContent = state.gate ? `${state.gate} / MRI ${state.mri ?? '—'}` : (leaders?.leadership_market?.status || '—');
    updatePeriodUi();
  } catch (e) {
    console.error(e);
    $('#leaders').innerHTML = `<div class="noData"><strong>読み込み失敗</strong>${esc(e.message || e)}</div>`;
    $('#bullish').innerHTML = '';
    $('#bearish').innerHTML = '';
    $('#stamp').textContent = 'load error';
  }
}

$('#search').addEventListener('input', showSuggestions);
$('#search').addEventListener('keydown', e => {
  const b = $('#suggestions'), items = [...b.querySelectorAll('.suggestion')];
  if (e.key === 'ArrowDown' && items.length) {
    e.preventDefault(); activeSuggestion = (activeSuggestion + 1) % items.length; items.forEach((x, i) => x.classList.toggle('active', i === activeSuggestion));
  } else if (e.key === 'ArrowUp' && items.length) {
    e.preventDefault(); activeSuggestion = (activeSuggestion - 1 + items.length) % items.length; items.forEach((x, i) => x.classList.toggle('active', i === activeSuggestion));
  } else if (e.key === 'Enter') {
    e.preventDefault(); if (activeSuggestion >= 0 && items[activeSuggestion]) selectTicker(items[activeSuggestion].dataset.ticker, true); else runSearch();
  } else if (e.key === 'Escape') hideSuggestions();
});
$('#searchBtn').addEventListener('click', runSearch);
$('#closeSelected').addEventListener('click', () => { $('#selectedSection').hidden = true; selectedTicker = null; });
for (const b of document.querySelectorAll('[data-period]')) b.addEventListener('click', () => setPeriod(b.dataset.period, true));
document.addEventListener('click', e => { if (!e.target.closest('.searchBox')) hideSuggestions(); });
init();
})();
