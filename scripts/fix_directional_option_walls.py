from pathlib import Path
import csv
import io
import json
import re

root = Path('.')

# -----------------------------------------------------------------------------
# 1) Future option calculations: resistance must be above spot; support below.
# -----------------------------------------------------------------------------
p = root / 'tools/build_options_positioning.py'
s = p.read_text(encoding='utf-8')
old = '''def top_walls(g, kind, n=3):
    sub = g[g["kind"] == kind].groupby("strike")["gex"].sum()
    if sub.empty:
        return []
    sub = sub.abs().sort_values(ascending=False).head(n)
    return [dict(strike=float(k), gex=float(v)) for k, v in sub.items()]
'''
new = '''def top_walls(g, kind, n=3, spot=None):
    """Return directional walls only.

    Call resistance must be above spot and Put support must be below spot.
    Wrong-side concentrations can be pins, but must not be labelled as a wall.
    """
    sub = g[g["kind"] == kind].groupby("strike")["gex"].sum()
    if spot is not None and not sub.empty:
        spot = float(spot)
        sub = sub[sub.index > spot] if kind == "C" else sub[sub.index < spot]
    if sub.empty:
        return []
    sub = sub.abs().sort_values(ascending=False).head(n)
    return [dict(strike=float(k), gex=float(v)) for k, v in sub.items()]
'''
if old in s:
    s = s.replace(old, new, 1)
elif 'sub = sub[sub.index > spot] if kind == "C" else sub[sub.index < spot]' not in s:
    raise SystemExit('top_walls source block not found; refusing broad edit')

old2 = '    cw = top_walls(g, "C"); pw = top_walls(g, "P")\n'
new2 = '    cw = top_walls(g, "C", spot=spot); pw = top_walls(g, "P", spot=spot)\n'
if old2 in s:
    s = s.replace(old2, new2, 1)
elif new2 not in s:
    raise SystemExit('top_walls call site not found; refusing broad edit')
p.write_text(s, encoding='utf-8')

# -----------------------------------------------------------------------------
# 2) Existing detailed options snapshot: repair from stored per-strike GEX.
# -----------------------------------------------------------------------------
def dist(level, spot, atr):
    if level is None or not spot:
        return {'px': None, 'pct': None, 'atr': None}
    return {
        'px': round(float(level), 2),
        'pct': round(float(level) / float(spot) - 1.0, 5),
        'atr': round((float(level) - float(spot)) / float(atr), 2) if atr and float(atr) > 0 else None,
    }

def conf(level, tech, spot, atr):
    if level is None or not spot:
        return []
    tol = max(float(spot) * 0.005, float(atr or 0) * 0.35)
    out = []
    for name, v in (tech or {}).items():
        try:
            v = float(v)
        except Exception:
            continue
        if abs(v - level) <= tol:
            out.append({'name': name, 'px': round(v, 2), 'diff': round(v / level - 1.0, 4)})
    return out

def directional(rows, spot, side):
    vals = []
    for r in rows or []:
        try:
            k = float(r.get('k'))
            v = float(r.get('call' if side == 'call' else 'put') or 0)
        except Exception:
            continue
        if side == 'call' and k > spot and abs(v) > 0:
            vals.append((abs(v), k))
        if side == 'put' and k < spot and abs(v) > 0:
            vals.append((abs(v), k))
    vals.sort(reverse=True)
    return vals

jpath = root / 'options_positioning.json'
json_changed = 0
if jpath.exists():
    data = json.loads(jpath.read_text(encoding='utf-8'))
    for tk, rec in (data.get('tickers') or {}).items():
        try:
            spot = float(rec.get('spot'))
        except Exception:
            continue
        nearest = rec.get('nearest')
        exp = (rec.get('expiries') or {}).get(nearest) or {}
        rows = exp.get('strikes') or []
        calls = directional(rows, spot, 'call')
        puts = directional(rows, spot, 'put')
        cw = calls[0][1] if calls else None
        pw = puts[0][1] if puts else None

        old_cw = (rec.get('call_wall') or {}).get('px')
        old_pw = (rec.get('put_wall') or {}).get('px')
        if old_cw != cw or old_pw != pw:
            json_changed += 1

        exp['call_wall'] = cw
        exp['put_wall'] = pw
        exp['call_walls'] = [{'strike': k, 'gex': g} for g, k in calls[:3]]
        exp['put_walls'] = [{'strike': k, 'gex': g} for g, k in puts[:3]]

        atr = rec.get('atr14')
        rec['call_wall'] = dist(cw, spot, atr)
        rec['put_wall'] = dist(pw, spot, atr)
        rec.setdefault('confluence', {})['call_wall'] = conf(cw, rec.get('tech'), spot, atr)
        rec.setdefault('confluence', {})['put_wall'] = conf(pw, rec.get('tech'), spot, atr)
        if cw is not None and pw is not None and cw > pw:
            rec['range_pos'] = round(max(0.0, min(1.0, (spot - pw) / (cw - pw))) * 100, 1)
        else:
            rec['range_pos'] = None

        ex = rec.setdefault('explain', {})
        ex['call_wall'] = '現値より上にあるコール建玉/GEXの最大集中。上値抵抗候補。' + (f' 現値から{(cw/spot-1)*100:+.1f}%。' if cw else ' 該当なし。')
        ex['put_wall'] = '現値より下にあるプット建玉/GEXの最大集中。下値支持候補。' + (f' 現値から{(pw/spot-1)*100:+.1f}%。' if pw else ' 該当なし。')

    jpath.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
print(f'REPAIRED_OPTION_JSON_RECORDS={json_changed}')

# -----------------------------------------------------------------------------
# 3) Existing compact history fallback: blank wrong-side walls immediately.
#    This is the path that produced NBIS $250 / $250 at spot $248.43.
# -----------------------------------------------------------------------------
hpath = root / 'options_scan_history.csv'
history_changed = 0
if hpath.exists():
    raw = hpath.read_text(encoding='utf-8')
    rdr = csv.DictReader(io.StringIO(raw))
    fields = list(rdr.fieldnames or [])
    rows = list(rdr)
    required = {'spot', 'call_wall', 'put_wall', 'call_wall_pct', 'put_wall_pct'}
    if not required.issubset(fields):
        raise SystemExit(f'options history columns missing: {sorted(required - set(fields))}')

    def fnum(v):
        try:
            return float(v)
        except Exception:
            return None

    for r in rows:
        spot = fnum(r.get('spot'))
        cw = fnum(r.get('call_wall'))
        pw = fnum(r.get('put_wall'))
        if spot is None:
            continue
        if cw is not None and cw <= spot:
            r['call_wall'] = ''
            r['call_wall_pct'] = ''
            history_changed += 1
        if pw is not None and pw >= spot:
            r['put_wall'] = ''
            r['put_wall_pct'] = ''
            history_changed += 1

    out = io.StringIO()
    wr = csv.DictWriter(out, fieldnames=fields, lineterminator='\n')
    wr.writeheader()
    wr.writerows(rows)
    hpath.write_text(out.getvalue(), encoding='utf-8')
print(f'REPAIRED_OPTION_HISTORY_FIELDS={history_changed}')

# -----------------------------------------------------------------------------
# 4) Multi VWAP presentation: keep the existing 24-row ranking for 63/252,
#    but never let that presentation cap silently remove a valid inception-
#    VWAP candidate. No ticker hard-code; no new score/filter.
# -----------------------------------------------------------------------------
bp = root / 'build_dashboard.py'
bs = bp.read_text(encoding='utf-8')
marker = '# INCEPTION_VWAP_BYPASS_PRESENTATION_CAP_V1'
if marker not in bs:
    # Current implementation caps the already-ranked iterable directly:
    # ordered = sorted(... )[:cap]
    pat = re.compile(
        r'(?m)^(?P<indent>[ \t]*)ordered\s*=\s*sorted\(sub\.iterrows\(\),\s*key=lambda x:\s*_action_rank\(x\[1\]\)\)\[:cap\]\s*$'
    )
    matches = list(pat.finditer(bs))
    if len(matches) != 1:
        raise SystemExit(
            f'expected one Multi VWAP ordered=sorted(... )[:cap] truncation, found {len(matches)}; refusing broad edit'
        )
    m0 = matches[0]
    indent = m0.group('indent')
    repl = (
        f"{indent}{marker}\n"
        f"{indent}_all_ordered = sorted(sub.iterrows(), key=lambda x: _action_rank(x[1]))\n"
        f"{indent}ordered = _all_ordered[:cap]\n"
        f"{indent}_inception_idx = set(m.index[keep_all])\n"
        f"{indent}_already = {{t for t, _r in ordered}}\n"
        f"{indent}ordered += [(t, r) for t, r in _all_ordered if t in _inception_idx and t not in _already]\n"
    )
    bs = bs[:m0.start()] + repl + bs[m0.end():]

# Regression invariants: existing adaptive near rule and separate inception gate stay intact.
if '_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))' not in bs:
    raise SystemExit('adaptive VWAP near threshold missing after patch')
if 'keep_all = setup_eligible_core(m) & loc_all' not in bs:
    raise SystemExit('inception VWAP core-only eligibility missing after patch')
if marker not in bs:
    raise SystemExit('inception presentation-cap bypass not installed')
bp.write_text(bs, encoding='utf-8')
print('INCEPTION_VWAP_PRESENTATION_CAP_BYPASS_OK')