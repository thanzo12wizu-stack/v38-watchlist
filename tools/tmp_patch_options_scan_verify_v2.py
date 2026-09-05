#!/usr/bin/env python3
from pathlib import Path
import re
import textwrap


def sub_once(text, pattern, repl, label, flags=0):
    out, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"{label}: expected 1 replacement, got {n}")
    return out


p = Path("tools/build_options_intelligence.py")
s = p.read_text(encoding="utf-8")
if "def _boolish(v):" not in s:
    s = sub_once(
        s,
        r'def _day\(v\):\n    return str\(v or ""\)\[:10\]\n',
        'def _day(v):\n    return str(v or "")[:10]\n\n\ndef _boolish(v):\n    if isinstance(v, bool):\n        return v\n    return str(v or "").strip().lower() in ("1", "true", "yes", "y")\n',
        "backend boolish",
    )

hist_new = textwrap.dedent('''\
def _hist_obs(row, source="HISTORY"):
    if not row: return None
    is_scan = source == "SCAN"
    em = {
        "expected_move": _f(row.get("expected_move")),
        "expected_move_pct": _f(row.get("expected_move_pct")),
        "expected_move_method": row.get("expected_move_method"),
        "expected_low": _f(row.get("expected_low")),
        "expected_high": _f(row.get("expected_high")),
    }
    return {"date": _day(row.get("date")),
            "price_session_date": _day(row.get("price_session_date") or row.get("date")),
            "expected_session_date": _day(row.get("expected_session_date") or (row.get("date") if is_scan else "")),
            "history_session_date": _day(row.get("history_session_date")),
            "price_source": row.get("price_source"), "options_observed_at": row.get("observed_at"),
            "expiry": row.get("expiry"), "spot": _f(row.get("spot")), "atr14": _f(row.get("atr14")),
            "call_wall": _f(row.get("call_wall")), "put_wall": _f(row.get("put_wall")),
            "gamma_flip": _f(row.get("gamma_flip")), "net_gex": _f(row.get("net_gex")),
            "regime": str(row.get("regime") or "UNKNOWN"), "confidence": str(row.get("confidence") or "").upper(),
            "total_oi": _f(row.get("total_oi")), "n_strikes": _f(row.get("n_strikes")),
            "call_oi": _f(row.get("call_oi")), "put_oi": _f(row.get("put_oi")),
            "detail": False, "stale": False,
            "session_consistent": _boolish(row.get("session_consistent")) if is_scan else False,
            "time_quality": "SCAN_PENDING_VERIFY" if is_scan else "UNVERIFIED_HISTORY",
            "expected_move": em if any(v not in (None, "") for v in em.values()) else None}
''')
s = sub_once(s, r'def _hist_obs\(row\):\n.*?\n\n\ndef _current_obs', hist_new.rstrip() + '\n\n\ndef _current_obs', "backend hist", re.S)

tq_new = textwrap.dedent('''\
def _time_quality(cur, session_date, source):
    if not cur: return "PERIOD_UNAVAILABLE"
    if cur.get("refresh_failed") or cur.get("stale"): return "STALE"
    if source not in ("DETAIL", "SCAN"): return "UNVERIFIED_HISTORY"
    pday = _day(cur.get("price_session_date"))
    expected = _day(cur.get("expected_session_date") or session_date)
    if not cur.get("session_consistent"): return "MISMATCH"
    if session_date and pday != session_date: return "MISMATCH"
    if expected and pday != expected: return "MISMATCH"
    if source == "SCAN" and (cur.get("spot") is None or str(cur.get("confidence") or "").upper() == "LOW"):
        return "LOW_QUALITY"
    return "VERIFIED"
''')
s = sub_once(s, r'def _time_quality\(cur, session_date, source\):\n.*?\n\n\ndef _direction_bias', tq_new.rstrip() + '\n\n\ndef _direction_bias', "backend tq", re.S)
s = sub_once(
    s,
    r'latest,previous=sh\.get\(tk\) or dh\.get\(tk\) or \(None,None\); cur=_hist_obs\(latest\); prev=_hist_obs\(previous\); source="SCAN" if tk in sh else "HISTORY"',
    'latest,previous=sh.get(tk) or dh.get(tk) or (None,None); source="SCAN" if tk in sh else "HISTORY"; cur=_hist_obs(latest,source); prev=_hist_obs(previous,source)',
    "backend source order",
)
p.write_text(s, encoding="utf-8")


p = Path("options-intelligence.js")
s = p.read_text(encoding="utf-8")
if "const boolish =" not in s:
    s = sub_once(
        s,
        r"const day = v => String\(v \|\| ''\)\.slice\(0, 10\);",
        "const day = v => String(v || '').slice(0, 10);\nconst boolish = v => v === true || ['1', 'true', 'yes', 'y'].includes(String(v || '').trim().toLowerCase());",
        "frontend boolish",
    )

hist_js = textwrap.dedent('''\
function histObs(r, source = 'HISTORY') {
  if (!r) return null;
  const isScan = source === 'SCAN';
  const em = {
    expected_move: num(r.expected_move), expected_move_pct: num(r.expected_move_pct),
    expected_move_method: r.expected_move_method || '', expected_low: num(r.expected_low), expected_high: num(r.expected_high)
  };
  return {
    date: day(r.date), price_session_date: day(r.price_session_date || r.date),
    expected_session_date: day(r.expected_session_date || (isScan ? r.date : '')),
    history_session_date: day(r.history_session_date), price_source: r.price_source || '',
    options_observed_at: r.observed_at || '', expiry: r.expiry || '',
    spot: num(r.spot), atr14: num(r.atr14), call_wall: num(r.call_wall), put_wall: num(r.put_wall),
    gamma_flip: num(r.gamma_flip), net_gex: num(r.net_gex), regime: r.regime || 'UNKNOWN',
    confidence: String(r.confidence || '').toUpperCase(), total_oi: num(r.total_oi), n_strikes: num(r.n_strikes),
    call_oi: num(r.call_oi), put_oi: num(r.put_oi), detail: false, stale: false,
    session_consistent: isScan ? boolish(r.session_consistent) : false,
    expected_move: Object.values(em).some(v => v !== null && v !== '') ? em : null
  };
}
''')
s = sub_once(s, r'function histObs\(r\) \{.*?\n\}\nfunction currentObs', hist_js.rstrip() + '\nfunction currentObs', "frontend hist", re.S)

tq_js = textwrap.dedent('''\
function timeQuality(cur, source, u) {
  if (!cur) return 'PERIOD_UNAVAILABLE';
  if (cur.refresh_failed || cur.stale) return 'STALE';
  const session = day(state.date), pday = cur.price_session_date;
  if (source === 'SCAN') {
    if (!session || !cur.session_consistent || pday !== session) return 'MISMATCH';
    if (cur.spot === null || cur.confidence === 'LOW') return 'LOW_QUALITY';
    return 'VERIFIED';
  }
  if (source !== 'DETAIL') return 'UNVERIFIED_HISTORY';
  if (cur.session_consistent && (!session || pday === session)) return 'VERIFIED';
  if (!cur.expected_session_date && session && pday === session && u?.price && cur.spot && Math.abs(cur.spot / u.price - 1) <= .003) return 'INFERRED_MATCH';
  return 'MISMATCH';
}
''')
s = sub_once(s, r'function timeQuality\(cur, source, u\) \{.*?\n\}\n\nfunction localSignal', tq_js.rstrip() + '\n\nfunction localSignal', "frontend tq", re.S)

branch_new = textwrap.dedent('''\
    } else {
      // Broad daily scan is deliberately 7-21DTE only. Never reuse it for
      // short/medium/multi/exact period rankings.
      if (activePeriod !== 'swing') continue;
      const p = sh[t];
      if (!p) continue;
      source = 'SCAN';
      cur = histObs(p[0], source);
      prev = histObs(p[1], source);
    }
''').rstrip()
s = sub_once(
    s,
    r"    \} else \{\n\s+const p = sh\[t\] \|\| dh\[t\];\n\s+if \(!p\) continue;\n\s+cur = histObs\(p\[0\]\);\n\s+prev = histObs\(p\[1\]\);\n\s+source = sh\[t\] \? 'SCAN' : 'HISTORY';\n\s+\}",
    branch_new,
    "frontend broad branch",
)
p.write_text(s, encoding="utf-8")


p = Path("tests/test_options_time_direction.py")
s = p.read_text(encoding="utf-8")
if "def test_same_session_scan_is_verified_and_preserves_expected_move():" not in s:
    s += textwrap.dedent('''\


def test_same_session_scan_is_verified_and_preserves_expected_move():
    row = {
        "date": "2026-09-04", "price_session_date": "2026-09-04",
        "session_consistent": "True", "spot": "100", "atr14": "4",
        "call_wall": "110", "put_wall": "95", "gamma_flip": "98",
        "net_gex": "1000000", "regime": "POSITIVE_GAMMA", "confidence": "MEDIUM",
        "total_oi": "8000", "n_strikes": "30", "expected_move": "6.5",
        "expected_move_pct": "0.065", "expected_move_method": "atm_iv_1sigma",
        "expected_low": "93.5", "expected_high": "106.5",
        "observed_at": "2026-09-05T07:55:28+00:00",
    }
    cur = intel._hist_obs(row, "SCAN")
    assert cur["session_consistent"] is True
    assert cur["price_session_date"] == "2026-09-04"
    assert cur["expected_move"]["expected_move_pct"] == 0.065
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "VERIFIED"


def test_same_session_scan_low_quality_is_not_verified():
    cur = intel._hist_obs({
        "date": "2026-09-04", "price_session_date": "2026-09-04",
        "session_consistent": "true", "spot": "100", "confidence": "LOW",
    }, "SCAN")
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "LOW_QUALITY"


def test_scan_from_previous_session_is_blocked():
    cur = intel._hist_obs({
        "date": "2026-09-03", "price_session_date": "2026-09-03",
        "session_consistent": "true", "spot": "100", "confidence": "HIGH",
    }, "SCAN")
    assert intel._time_quality(cur, "2026-09-04", "SCAN") == "MISMATCH"
''')
p.write_text(s, encoding="utf-8")
print("patched same-session SCAN verification v2")
