'use strict';

(() => {
  const mainRaw = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/';
  let commandState = null;
  let liveState = null;
  let tqqqState = null;
  let sleeveState = null;
  let sourceErrors = {};

  const $ = id => document.getElementById(id);

  function show(message, bad = true) {
    const wrap = document.querySelector('.wrap');
    if (!wrap) return;
    let node = document.getElementById('v38FreshnessWarning');
    if (!node) {
      node = document.createElement('div');
      node.id = 'v38FreshnessWarning';
      node.className = 'note';
      const top = wrap.querySelector('.top');
      if (top && top.nextSibling) wrap.insertBefore(node, top.nextSibling);
      else wrap.prepend(node);
    }
    node.style.borderLeftColor = bad ? 'var(--bad)' : 'var(--good)';
    node.style.display = message ? '' : 'none';
    node.textContent = message || '';
  }

  function shortDate(value) {
    const m = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m ? `${Number(m[2])}/${Number(m[3])}` : (value || '—');
  }

  function setText(id, text, tone = '') {
    const node = $(id);
    if (!node) return;
    node.textContent = text;
    if (tone) node.className = tone;
  }

  function primeToday() {
    setText('tqqqDecision', '更新状況を確認中', 'warn');
    setText('tqqqDecisionSub', 'TQQQ / CURRENT30 の最新データを確認中');
    setText('resetDecision', '更新状況を確認中', 'warn');
    setText('resetDecisionSub', 'RSI Reset Sleeve の最新データを確認中');
    setText('panicPlain', '更新状況を確認中', 'warn');
    setText('underlyingTarget', '更新状況を確認中', 'warn');
    setText('rsiTrigger', '更新状況を確認中', 'warn');
    setText('mcEntry', '更新状況を確認中', 'warn');
  }

  function tqqqDisplay(expected) {
    const normal = liveState?.normal_tqqq || {};
    const panic = liveState?.panic_tqqq || {};
    const source = tqqqState || {};
    const sourceAsOf = String(source.asof || '');
    const ready = normal.status === 'READY' &&
      normal.underlying_target_pct != null &&
      String(source.live_generation_status || '').toUpperCase().startsWith('READY') &&
      (!expected || sourceAsOf === expected);

    if (!ready) {
      const reason = String(source.reason || normal.status || panic.status || '');
      const latestMatch = reason.match(/latest=(\d{4}-\d{2}-\d{2})/);
      const latest = sourceAsOf || (latestMatch ? latestMatch[1] : '');
      if (latest && expected && latest !== expected) {
        return {
          ready: false,
          kind: 'stale',
          label: '更新待ち',
          detail: `TQQQ/CURRENT30 最終 ${shortDate(latest)} → ${shortDate(expected)}更新待ち`,
          reason: `TQQQ：更新待ち｜最終 ${shortDate(latest)}`
        };
      }
      if (sourceErrors.tqqq) {
        return {
          ready: false,
          kind: 'error',
          label: 'データ取得失敗',
          detail: 'TQQQ/CURRENT30 の更新データを取得できていません',
          reason: 'TQQQ：データ取得失敗'
        };
      }
      return {
        ready: false,
        kind: 'notready',
        label: '更新待ち',
        detail: reason ? `TQQQ/CURRENT30 更新未完了｜${reason}` : 'TQQQ/CURRENT30 の更新完了待ち',
        reason: 'TQQQ：更新待ち'
      };
    }

    const target = Number(normal.underlying_target_pct);
    let label = `${target.toFixed(1).replace(/\.0$/, '')}% 保有`;
    if (target <= 0.01) label = '0% 退避';
    else if (Math.abs(target - 30) < 0.05) label = '30% 保有継続';

    let detail = 'Panic非発動';
    if (panic.active) detail = 'Panic F80稼働中';
    else if (normal.risk_lock) detail = 'risk lock中';

    return {
      ready: true,
      kind: 'ready',
      label,
      detail,
      reason: `TQQQ：${label}${panic.active ? '（Panic F80）' : ''}`
    };
  }

  function resetDisplay(expected) {
    const source = sleeveState || {};
    const reset = source.rsi_reset || {};
    const sourceAsOf = String(reset.asof || source.asof || '');

    if (sourceAsOf && expected && sourceAsOf !== expected) {
      return {
        ready: false,
        kind: 'stale',
        label: '更新待ち',
        detail: `RSI Reset Sleeve 最終 ${shortDate(sourceAsOf)} → ${shortDate(expected)}更新待ち`,
        reason: `RSI Reset：更新待ち｜最終 ${shortDate(sourceAsOf)}`
      };
    }
    if (sourceErrors.sleeve) {
      return {
        ready: false,
        kind: 'error',
        label: 'データ取得失敗',
        detail: 'RSI Reset Sleeve の更新データを取得できていません',
        reason: 'RSI Reset：データ取得失敗'
      };
    }
    if (!String(reset.status || '').toUpperCase().startsWith('READY')) {
      return {
        ready: false,
        kind: 'notready',
        label: '更新待ち',
        detail: 'RSI Reset Sleeve の更新完了待ち',
        reason: 'RSI Reset：更新待ち'
      };
    }

    const rows = Array.isArray(reset.monitor) ? reset.monitor : [];
    const signals = rows.filter(x => x?.status === 'SIGNAL_TODAY_NEXT_OPEN');
    const positions = Number(reset.position_count || 0);
    if (signals.length) {
      return {
        ready: true,
        kind: 'ready',
        label: `翌寄りEntry ${signals.length}銘柄`,
        detail: signals.map(x => x.symbol).filter(Boolean).join(' / ') || '正式Resetシグナルあり',
        reason: `RSI Reset：翌寄りEntry ${signals.length}銘柄`
      };
    }
    if (positions > 0) {
      return {
        ready: true,
        kind: 'ready',
        label: `${positions}銘柄保有中`,
        detail: '新規の正式Resetシグナルなし',
        reason: `RSI Reset：${positions}銘柄保有中`
      };
    }
    return {
      ready: true,
      kind: 'ready',
      label: 'シグナルなし',
      detail: '現在の正式Resetシグナルなし',
      reason: 'RSI Reset：シグナルなし'
    };
  }

  function normalAction(market) {
    const mode = String(market?.mode || '');
    if (mode === 'DEFENSE') return '通常個別株：次回寄りで全退避';
    if (mode === 'STOP') return '通常個別株：新規買付なし';
    if (mode === 'SELECTIVE') return `通常個別株：最大${market?.new_entry_limit ?? 4}枠`;
    if (mode === 'ATTACK') return `通常個別株：最大${market?.new_entry_limit ?? 12}枠`;
    return '通常個別株：市場判定を確認';
  }

  function toneFor(status) {
    if (status?.ready) return '';
    return status?.kind === 'error' ? 'bad' : 'warn';
  }

  function patchToday() {
    if (!liveState) return;
    const expected = String(commandState?.date || liveState.asof || '');
    const market = liveState.market || {};
    const tq = tqqqDisplay(expected);
    const reset = resetDisplay(expected);

    setText('tqqqDecision', tq.label, toneFor(tq));
    setText('tqqqDecisionSub', tq.detail);
    setText('resetDecision', reset.label, toneFor(reset));
    setText('resetDecisionSub', reset.detail);

    const confirmed = [normalAction(market)];
    if (tq.ready) confirmed.push(tq.reason.replace(/^TQQQ：/, 'TQQQ '));
    if (reset.ready) confirmed.push(reset.reason.replace(/^RSI Reset：/, 'Reset '));
    setText('todayAction', confirmed.join(' ／ '));

    const statusParts = [];
    if (!tq.ready) statusParts.push(tq.reason);
    if (!reset.ready) statusParts.push(reset.reason);

    let normalReason = '';
    if (market.mode === 'DEFENSE') normalReason = 'NQSAR Red。通常個別株は次回寄りで全退避します。';
    else if (market.mode === 'STOP') normalReason = `${market.nqsar || 'NQSAR'}のため通常個別株は新規買付なし。`;
    else if (market.mode === 'SELECTIVE') normalReason = '通常個別株はSELECTIVE。空き枠と正式順位の範囲だけ追加します。';
    else if (market.mode === 'ATTACK') normalReason = '通常個別株はATTACK。空き枠と正式順位の範囲だけ追加します。';

    setText('todayReason', [normalReason, ...statusParts].filter(Boolean).join(' '));

    setText('underlyingTarget', tq.label, toneFor(tq));
    if (!tq.ready) {
      setText('tqqqPlain', `${tq.detail}。更新完了まではTQQQ目標とPanic判定を確定扱いしません。`);
      setText('panicPlain', tq.label, toneFor(tq));
      setText('rsiTrigger', tq.label, toneFor(tq));
      setText('mcEntry', tq.label, toneFor(tq));
    } else {
      setText('underlyingTarget', tq.label);
      const panic = liveState.panic_tqqq || {};
      setText('panicPlain', panic.active ? 'F80稼働中' : '未発動');
      setText('rsiTrigger', panic.rsi4h == null ? '更新データ不足' : panic.touch30_today ? 'TOUCH30成立' : `RSI ${Number(panic.rsi4h).toFixed(1)}`);
      setText('mcEntry', panic.mc57 == null ? '更新データ不足' : `${Number(panic.mc57).toFixed(1)} / ${Number(panic.mc57) >= 20 ? 'Entry可' : 'Entry不可'}`);
    }
  }

  function installRenderHook() {
    if (typeof window.renderTqqq !== 'function' || window.renderTqqq.__v38StatusHook) return;
    const base = window.renderTqqq;
    const wrapped = function(...args) {
      const out = base.apply(this, args);
      queueMicrotask(patchToday);
      return out;
    };
    wrapped.__v38StatusHook = true;
    window.renderTqqq = wrapped;
  }

  async function fetchJson(name) {
    try {
      const response = await fetch(mainRaw + name, {cache: 'no-store'});
      if (!response.ok) throw new Error(`${name} HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      sourceErrors[name] = String(error?.message || error || 'fetch failed');
      return null;
    }
  }

  async function loadFreshness() {
    primeToday();
    installRenderHook();

    const [command, live, tqqq, sleeve] = await Promise.all([
      fetchJson('state.json'),
      fetchJson('v38-live-state.json'),
      fetchJson('tqqq-panic-state.json'),
      fetchJson('v38-sleeve-state.json')
    ]);

    commandState = command;
    liveState = live || window.STATE || null;
    tqqqState = tqqq;
    sleeveState = sleeve;
    sourceErrors = {
      command: sourceErrors['state.json'],
      live: sourceErrors['v38-live-state.json'],
      tqqq: sourceErrors['tqqq-panic-state.json'],
      sleeve: sourceErrors['v38-sleeve-state.json']
    };

    const expected = String(commandState?.date || liveState?.asof || '');
    const got = String(liveState?.asof || '');
    const warnings = [];
    if (!commandState) warnings.push('Command Center更新日を確認できません');
    if (!liveState) warnings.push('V38 live stateを取得できません');
    else if (commandState && (!expected || got !== expected)) warnings.push(`Command Center ${expected || '—'} / V38 ${got || '—'}`);

    const tq = tqqqDisplay(expected);
    const reset = resetDisplay(expected);
    if (!tq.ready) warnings.push(tq.reason);
    if (!reset.ready) warnings.push(reset.reason);

    if (warnings.length) show(`更新状況：${warnings.join(' ／ ')}。未更新部分を最新扱いしません。`, true);
    else show('', false);

    patchToday();
    setTimeout(patchToday, 250);
    setTimeout(patchToday, 1000);
  }

  primeToday();
  loadFreshness();
})();
