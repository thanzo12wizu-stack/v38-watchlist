from pathlib import Path
import json

root = Path('.')

# 1) Future calculations: a resistance must be above spot; a support must be below spot.
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
    """Directional walls only: Call resistance above spot, Put support below spot.

    A large option position on the wrong side of spot can still matter as a pin,
    but it must not be labelled as "upper resistance" or "lower support".
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
if old not in s:
    raise SystemExit('top_walls source block not found')
s = s.replace(old, new, 1)
old2 = '    cw = top_walls(g, "C"); pw = top_walls(g, "P")\n'
new2 = '    cw = top_walls(g, "C", spot=spot); pw = top_walls(g, "P", spot=spot)\n'
if old2 not in s:
    raise SystemExit('top_walls call site not found')
s = s.replace(old2, new2, 1)
p.write_text(s, encoding='utf-8')

# 2) Current snapshot: repair immediately from the already-stored per-strike GEX.
def dist(level, spot, atr):
    if level is None or not spot:
        return {'px': None, 'pct': None, 'atr': None}
    return {
        'px': round(float(level), 2),
        'pct': round(float(level) / float(spot) - 1.0, 5),
        'atr': round((float(level) - float(spot)) / float(atr), 2) if atr and atr > 0 else None,
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
data = json.loads(jpath.read_text(encoding='utf-8'))
changed = 0
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
        changed += 1

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
print(f'REPAIRED_OPTION_RECORDS={changed}')

# 3) Dashboard must rebuild when the options snapshot changes.
dp = root / '.github/workflows/dashboard.yml'
ds = dp.read_text(encoding='utf-8')
needle = "      - 'equity.csv'\n"
insert = "      - 'equity.csv'\n      - 'options_positioning.json'\n"
if "      - 'options_positioning.json'\n" not in ds:
    if needle not in ds:
        raise SystemExit('dashboard push-path anchor not found')
    ds = ds.replace(needle, insert, 1)
dp.write_text(ds, encoding='utf-8')
