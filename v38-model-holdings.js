'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const num = value => {
    const x = Number(value);
    return Number.isFinite(x) ? x : null;
  };
  const pct = value => value == null ? '—' : `${Number(value).toFixed(1)}%`;
  const money = value => value == null ? '—' : `$${Number(value).toFixed(2)}`;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const symOf = row => typeof row === 'string' ? row : String(row?.symbol || row?.ticker || '');

  function injectStyle() {
    if ($('v38ModelHoldingsStyle')) return;
    const style = document.createElement('style');
    style.id = 'v38ModelHoldingsStyle';
    style.textContent = `
      .model-holding-tag{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 7px;font-size:10px;font-weight:800;background:#102038;color:#c5d7ee}
      .model-holding-tag.early{border-color:#6f5d2d;color:#ffe29a;background:#2a2413}
      .model-holding-tag.reset{border-color:#5a3c74;color:#dfc5ff;background:#21162d}
      .model-holding-tag.cash{color:#b7c5d7;background:#141b25}
      .model-holding-note{margin-top:12px}
      .model-holdings-table td:nth-child(2){font-weight:850}
      .model-holdings-table .muted{color:var(--muted)}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    const button = document.querySelector('.tabs button[data-tab="positions"]');
    if (button) button.textContent = '想定保有株';
    const panel = $('positions');
    if (!panel) return null;
    let card = $('v38ModelHoldingsCard');
    if (!card) {
      card = document.createElement('div');
      card.className = 'card';
      card.id = 'v38ModelHoldingsCard';
      card.innerHTML = `
        <div class="hdr"><h2>モデル上の想定保有</h2><span class="badge" id="modelHoldingsAsOf">読込中</span></div>
        <div class="explain" id="modelHoldingsExplain">候補ではなく、V38の正式live state上で現在保有している扱いの銘柄だけを表示します。</div>
        <div class="row">
          <div class="mini"><span>TQQQ</span><b id="modelTqqqPct">—</b><small class="subline" id="modelTqqqSub">—</small></div>
          <div class="mini"><span>本命株</span><b id="modelCorePct">—</b><small class="subline" id="modelCoreSub">—</small></div>
          <div class="mini"><span>先回り株</span><b id="modelEarlyPct">—</b><small class="subline" id="modelEarlySub">—</small></div>
          <div class="mini"><span>RSI Reset</span><b id="modelResetPct">—</b><small class="subline" id="modelResetSub">—</small></div>
          <div class="mini"><span>現金</span><b id="modelCashPct">—</b><small class="subline">未使用資金</small></div>
        </div>
        <div class="scroll" style="margin-top:14px">
          <table class="ranktable model-holdings-table">
            <thead><tr><th>種別</th><th>銘柄</th><th>想定比率</th><th>Entry</th><th>現在値</th><th>損益</th><th>状態</th></tr></thead>
            <tbody id="modelHoldingsRows"><tr><td colspan="7"><div class="empty">読込中</div></td></tr></tbody>
          </table>
        </div>
        <div class="note model-holding-note" id="modelHoldingsPending">次回寄り予定を確認中。</div>
      `;
      panel.insertBefore(card, panel.firstChild);

      const cards = panel.querySelectorAll(':scope > .card');
      if (cards.length > 1) {
        const manual = cards[1];
        const h2 = manual.querySelector('h2');
        const badge = manual.querySelector('.badge');
        if (h2) h2.textContent = '実口座メモ（手入力）';
        if (badge) badge.textContent = '想定保有の計算には未使用';
      }
    }
    return card;
  }

  async function fetchJson(name) {
    const r = await fetch(name, {cache:'no-store'});
    if (!r.ok) throw new Error(`${name} HTTP ${r.status}`);
    return r.json();
  }

  function proportion(mark, gross, allocation, count) {
    const m = num(mark), g = num(gross), a = num(allocation);
    if (a == null) return null;
    if (m != null && g != null && g > 0) return a * m / g;
    return count > 0 ? a / count : 0;
  }

  function normalAction(position, pending) {
    const symbol = String(position.symbol || '');
    const exits = new Set((pending.full_exits || []).map(symOf));
    const partials = new Set((pending.partial25 || []).map(symOf));
    const promotions = new Set((pending.promotions || []).map(symOf));
    if (exits.has(symbol)) return '翌寄り売却予定';
    if (partials.has(symbol)) return '翌寄り25%利確';
    if (promotions.has(symbol)) return '本命へ昇格';
    if (String(position.sleeve || '').toUpperCase() === 'EARLY') return `先回り保有 ${Number(position.early_sessions || 0)}/10日`;
    return 'HOLD';
  }

  function holdingTag(kind) {
    if (kind === 'EARLY') return '<span class="model-holding-tag early">先回り</span>';
    if (kind === 'RESET') return '<span class="model-holding-tag reset">RSI Reset</span>';
    if (kind === 'CASH') return '<span class="model-holding-tag cash">現金</span>';
    if (kind === 'TQQQ') return '<span class="model-holding-tag">TQQQ</span>';
    return '<span class="model-holding-tag">本命</span>';
  }

  function returnText(entry, close) {
    const e = num(entry), c = num(close);
    if (e == null || c == null || e <= 0) return '—';
    const r = (c / e - 1) * 100;
    return `<span class="${r >= 0 ? 'good' : 'bad'}">${r >= 0 ? '+' : ''}${r.toFixed(1)}%</span>`;
  }

  function pendingText(live, sleeve) {
    const normal = sleeve.normal_stock || {};
    const pending = normal.pending || {};
    const reset = sleeve.rsi_reset || {};
    const parts = [];
    const entries = (pending.entries || []).map(symOf).filter(Boolean);
    const exits = (pending.full_exits || []).map(symOf).filter(Boolean);
    const partials = (pending.partial25 || []).map(symOf).filter(Boolean);
    const promotions = (pending.promotions || []).map(symOf).filter(Boolean);
    const resetSignals = (reset.monitor || []).filter(x => x?.status === 'SIGNAL_TODAY_NEXT_OPEN').map(x => x.symbol).filter(Boolean);
    if (entries.length) parts.push(`通常株 Entry：${entries.join(' / ')}`);
    if (exits.length) parts.push(`通常株 Exit：${exits.join(' / ')}`);
    if (partials.length) parts.push(`25%利確：${partials.join(' / ')}`);
    if (promotions.length) parts.push(`先回り→本命昇格：${promotions.join(' / ')}`);
    if (resetSignals.length) parts.push(`RSI Reset Entry：${resetSignals.join(' / ')}`);
    if (!parts.length) {
      const mode = live.market?.mode || '—';
      return `次回寄りの予約注文なし。現在のMarket Modeは ${mode}。候補一覧に出ているだけの銘柄は、ここには保有として含めません。`;
    }
    return `次回寄り予定：${parts.join(' ／ ')}`;
  }

  function render(live, sleeve) {
    ensurePanel();
    const asofLive = String(live?.asof || '');
    const asofSleeve = String(sleeve?.asof || '');
    setText('modelHoldingsAsOf', asofLive && asofLive === asofSleeve ? `as-of ${asofLive}` : 'DATA REQUIRED');
    if (!live || !sleeve || !asofLive || asofLive !== asofSleeve || String(sleeve.status || '').toUpperCase() !== 'READY') {
      setText('modelHoldingsExplain', `V38 live / Sleeve のas-ofが一致していないため想定保有を確定表示しません。Live ${asofLive || '—'} / Sleeve ${asofSleeve || '—'}`);
      $('modelHoldingsRows').innerHTML = '<tr><td colspan="7"><div class="empty">DATA REQUIRED</div></td></tr>';
      return;
    }

    const normal = sleeve.normal_stock || {};
    const reset = sleeve.rsi_reset || {};
    const normalPositions = Array.isArray(normal.positions) ? normal.positions : [];
    const resetPositions = Array.isArray(reset.positions) ? reset.positions : [];
    const corePositions = normalPositions.filter(p => String(p.sleeve || 'CORE').toUpperCase() !== 'EARLY');
    const earlyPositions = normalPositions.filter(p => String(p.sleeve || '').toUpperCase() === 'EARLY');
    const g = live.gross100_allocation || {};
    const allocationReady = String(g.status || '').includes('LIVE ALLOCATION READY');
    const normalAlloc = allocationReady ? num(g.normal_stock_allocated_pct) : num(normal.desired_pct);
    const resetAlloc = allocationReady ? num(g.reset_allocated_pct) : num(reset.desired_pct);
    const tqqqAlloc = allocationReady ? num(g.tqqq_allocated_pct) : num(live.normal_tqqq?.underlying_target_pct);
    const gross = allocationReady ? num(g.gross_allocated_pct) : [normalAlloc, resetAlloc, tqqqAlloc].reduce((a,b) => a + (b || 0), 0);
    const cash = gross == null ? null : Math.max(0, 100 - gross);

    const corePct = corePositions.reduce((sum,p) => sum + (proportion(p.mark, normal.gross_value, normalAlloc, normalPositions.length) || 0), 0);
    const earlyPct = earlyPositions.reduce((sum,p) => sum + (proportion(p.mark, normal.gross_value, normalAlloc, normalPositions.length) || 0), 0);

    setText('modelTqqqPct', pct(tqqqAlloc));
    setText('modelTqqqSub', live.panic_tqqq?.active ? 'Panic F80稼働中' : 'CURRENT30');
    setText('modelCorePct', pct(corePct));
    setText('modelCoreSub', `${corePositions.length}銘柄`);
    setText('modelEarlyPct', pct(earlyPct));
    setText('modelEarlySub', `${earlyPositions.length}銘柄`);
    setText('modelResetPct', pct(resetAlloc));
    setText('modelResetSub', `${resetPositions.length}銘柄`);
    setText('modelCashPct', pct(cash));
    setText('modelHoldingsExplain', `これは実口座ではなく、V38の正式stateが「現在保有している」と扱うモデルポートフォリオです。候補・監視銘柄は含めません。総投資 ${pct(gross)} / 現金 ${pct(cash)}。`);

    const rows = [];
    if ((tqqqAlloc || 0) > 0.001) {
      const tqState = live.panic_tqqq?.active ? 'Panic F80' : live.normal_tqqq?.risk_lock ? 'Risk Lock' : '通常保有';
      rows.push(`<tr><td>${holdingTag('TQQQ')}</td><td>TQQQ</td><td><b>${pct(tqqqAlloc)}</b></td><td>—</td><td>—</td><td>—</td><td>${esc(tqState)}</td></tr>`);
    }

    for (const p of normalPositions) {
      const kind = String(p.sleeve || 'CORE').toUpperCase() === 'EARLY' ? 'EARLY' : 'CORE';
      const weight = proportion(p.mark, normal.gross_value, normalAlloc, normalPositions.length);
      rows.push(`<tr><td>${holdingTag(kind)}</td><td>${esc(p.symbol)}</td><td><b>${pct(weight)}</b></td><td>${money(p.entry_price)}<span class="subline">${esc(p.entry_date || '')}</span></td><td>${money(p.close)}</td><td>${returnText(p.entry_price,p.close)}</td><td>${esc(normalAction(p, normal.pending || {}))}</td></tr>`);
    }

    for (const p of resetPositions) {
      const weight = proportion(p.mark, reset.gross_value, resetAlloc, resetPositions.length);
      rows.push(`<tr><td>${holdingTag('RESET')}</td><td>${esc(p.symbol)}<span class="subline">${esc(p.theme || '')}</span></td><td><b>${pct(weight)}</b></td><td><span class="muted">${esc(p.entry_date || '—')}</span></td><td>${money(p.close)}</td><td>—</td><td>20営業日固定保有</td></tr>`);
    }

    if ((cash || 0) > 0.001) rows.push(`<tr><td>${holdingTag('CASH')}</td><td>現金</td><td><b>${pct(cash)}</b></td><td>—</td><td>—</td><td>—</td><td>待機資金</td></tr>`);
    if (!rows.length) rows.push('<tr><td colspan="7"><div class="empty">現在のモデル保有はありません。</div></td></tr>');
    $('modelHoldingsRows').innerHTML = rows.join('');
    setText('modelHoldingsPending', pendingText(live, sleeve));
  }

  function setText(id, text) {
    const node = $(id);
    if (node) node.textContent = text;
  }

  async function start() {
    injectStyle();
    ensurePanel();
    try {
      const [live, sleeve] = await Promise.all([
        fetchJson('v38-live-state.json'),
        fetchJson('v38-sleeve-state.json')
      ]);
      render(live, sleeve);
    } catch (error) {
      ensurePanel();
      setText('modelHoldingsAsOf', 'DATA REQUIRED');
      setText('modelHoldingsExplain', `想定保有stateの取得に失敗しました：${String(error?.message || error)}`);
      if ($('modelHoldingsRows')) $('modelHoldingsRows').innerHTML = '<tr><td colspan="7"><div class="empty">DATA REQUIRED</div></td></tr>';
    }
  }

  start();
})();
