'use strict';

(() => {
  const mainRaw = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/';
  let commandState = null;
  let liveState = null;
  let tqqqState = null;
  let sleeveState = null;

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

  function tqqqDisplay(expected) {
    const normal = liveState?.normal_tqqq || {};
    const panic = liveState?.panic_tqqq || {};
    const source = tqqqState || {};
    const ready = normal.status === 'READY' &&
      normal.underlying_target_pct != null &&
      String(source.live_generation_status || '').toUpperCase().startsWith('READY');

    if (!ready) {
      const reason = String(source.reason || normal.status || panic.status || '');
      const latestMatch = reason.match(/latest=(\d{4}-\d{2}-\d{2})/);
      const latest = latestMatch ? latestMatch[1] : '';
      const stale = latest && expected && latest !== expected;
      if (stale) {
        return {
          ready: false,
          label: '更新待ち',
          detail: `CURRENT30 最終 ${shortDate(latest)} → ${shortDate(expected)}更新待ち`,
          reason: `TQQQ：更新待ち｜CURRENT30 最終 ${shortDate(latest)}`
        };
      }
      return {
        ready: false,
        label: 'データ取得失敗',
        detail: 'TQQQデータを更新できていません',
        reason: 'TQQQ：データ取得失敗'
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
      label,
      detail,
      reason: `TQQQ：${label}${panic.active ? '（Panic F80）' : ''}`
    };
  }

  function resetDisplay(expected) {
    const source = sleeveState || {};
    const reset = source.rsi_reset || {};
    const sourceAsOf = String(reset.asof || source.asof || '');

    if (expected && sourceAsOf !== expected) {
      return {
        ready: false,
        label: '更新待ち',
        detail: `Sleeve 最終 ${shortDate(sourceAsOf)} → ${shortDate(expected)}更新待ち`,
        reason: `RSI Reset：更新待ち｜Sleeve 最終 ${shortDate(sourceAsOf)}`
      };
    }
    if (!String(reset.status || '').toUpperCase().startsWith('READY')) {
      return {
        ready: false,
        label: 'データ取得失敗',
        detail: 'RSI Resetデータを更新できていません',
        reason: 'RSI Reset：データ取得失敗'
      };
    }

    const rows = Array.isArray(reset.monitor) ? reset.monitor : [];
    const signals = rows.filter(x => x?.status === 'SIGNAL_TODAY_NEXT_OPEN');
    const positions = Number(reset.position_count || 0);
    if (signals.length) {
      return {
        ready: true,
        label: `翌寄りEntry ${signals.length}銘柄`,
        detail: signals.map(x => x.symbol).filter(Boolean).join(' / ') || '正式Resetシグナルあり',
        reason: `RSI Reset：翌寄りEntry ${signals.length}銘柄`
      };
    }
    if (positions > 0) {
      return {
        ready: true,
        label: `${positions}銘柄保有中`,
        detail: '新規の正式Resetシグナルなし',
        reason: `RSI Reset：${positions}銘柄保有中`
      };
    }
    return {
      ready: true,
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

  function patchToday() {
    if (!liveState) return;
    const expected = String(liveState.asof || commandState?.date || '');
    const market = liveState.market || {};
    const tq = tqqqDisplay(expected);
    const reset = resetDisplay(expected);

    setText('tqqqDecision', tq.label, tq.ready ? '' : (tq.label === '更新待ち' ? 'warn' : 'bad'));
    setText('tqqqDecisionSub', tq.detail);
    setText('resetDecision', reset.label, reset.ready ? '' : (reset.label === '更新待ち' ? 'warn' : 'bad'));
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

    setText('underlyingTarget', tq.label, tq.ready ? '' : (tq.label === '更新待ち' ? 'warn' : 'bad'));
    if (!tq.ready) {
      setText('tqqqPlain', `${tq.detail}。日付が揃うまでTQQQ目標とPanic判定は確定扱いしません。`);
      setText('panicPlain', tq.label, tq.label === '更新待ち' ? 'warn' : 'bad');
      setText('rsiTrigger', tq.label, tq.label === '更新待ち' ? 'warn' : 'bad');
      setText('mcEntry', tq.label, tq.label === '更新待ち' ? 'warn' : 'bad');
    } else {
      setText('underlyingTarget', tq.label);
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

  async function loadFreshness() {
    try {
      const urls = ['state.json', 'v38-live-state.json', 'tqqq-panic-state.json', 'v38-sleeve-state.json'];
      const responses = await Promise.all(urls.map(name => fetch(mainRaw + name, {cache: 'no-store'})));
      if (responses.some(r => !r.ok)) throw new Error('freshness source unavailable');
      [commandState, liveState, tqqqState, sleeveState] = await Promise.all(responses.map(r => r.json()));

      const expected = String(commandState.date || '');
      const got = String(liveState.asof || '');
      if (!expected || got !== expected) {
        show(`更新遅延：Command Center ${expected || '—'} / V38 ${got || '—'}。日付が揃うまでV38の数値は最新扱いしません。`, true);
      } else {
        show('', false);
      }

      installRenderHook();
      patchToday();
      setTimeout(patchToday, 250);
      setTimeout(patchToday, 1000);
    } catch (_) {
      show('V38の更新状況を確認できません。数値を最新扱いしないでください。', true);
    }
  }

  loadFreshness();
})();
