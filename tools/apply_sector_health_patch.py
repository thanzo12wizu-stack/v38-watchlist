from pathlib import Path
import re

p = Path("build_dashboard.py")
text = p.read_text(encoding="utf-8")
if "def _sector_health_series(" in text:
    raise SystemExit("sector health already applied")

# Sector Health uses the same 12 components as Market Conditions v4, including
# 200/252-day components, so the theme ETF history must cover them.
old = 'def load_market_extras(period="9mo", asof_date=None):'
if text.count(old) != 1:
    raise SystemExit(f"load_market_extras anchor count={text.count(old)}")
text = text.replace(old, 'def load_market_extras(period="2y", asof_date=None):', 1)

rank_new = r'''def _sector_health_series(c):
    """Per-ETF absolute health using the same 12 equal-weight components as Market Conditions v4."""
    c = pd.to_numeric(c, errors="coerce").dropna().sort_index()
    if c.empty:
        return pd.Series(dtype=float)
    ma10 = c.rolling(10).mean(); ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean(); ma200 = c.rolling(200).mean()
    p = {}
    def _bool100(cond, valid):
        return cond.where(valid).astype(float) * 100.0
    p["ret5"] = _bool100(c/c.shift(5)-1 > 0, c.shift(5).notna() & c.notna())
    p["ret21"] = _bool100(c/c.shift(21)-1 > 0, c.shift(21).notna() & c.notna())
    p["ret63"] = _bool100(c/c.shift(63)-1 > 0, c.shift(63).notna() & c.notna())
    p["ret252"] = _bool100(c/c.shift(252)-1 > 0, c.shift(252).notna() & c.notna())
    p["above10"] = _bool100(c > ma10, ma10.notna() & c.notna())
    p["above20"] = _bool100(c > ma20, ma20.notna() & c.notna())
    p["above50"] = _bool100(c > ma50, ma50.notna() & c.notna())
    p["above200"] = _bool100(c > ma200, ma200.notna() & c.notna())
    p["ma20_gt_50"] = _bool100(ma20 > ma50, ma20.notna() & ma50.notna())
    p["ma50_gt_200"] = _bool100(ma50 > ma200, ma50.notna() & ma200.notna())
    hi252 = c.rolling(252, min_periods=200).max()
    dd = c / hi252 - 1.0
    p["dd_score"] = ((dd + 0.30) / 0.25 * 100.0).clip(0.0, 100.0)
    p["within10"] = _bool100(dd >= -0.10, dd.notna())
    keys = ("ret5","ret21","ret63","ret252",
            "above10","above20","above50","above200",
            "ma20_gt_50","ma50_gt_200","dd_score","within10")
    raw = pd.concat([p[k] for k in keys], axis=1).mean(axis=1, skipna=True)
    return raw.ewm(span=2, adjust=False).mean()


def _rank_etfs(close_dict, etf_list, minbars=22):
    """{tk: Close系列} と [(tk,ja)] から d1/w1/m1・中長期リターン・Sector Healthを計算。"""
    recs = []
    for tk, ja in etf_list:
        c = close_dict.get(tk)
        if c is None:
            continue
        c = c.dropna()
        if len(c) < minbars:
            continue
        last = float(c.iloc[-1])
        def r(d):
            return (last/float(c.iloc[-d-1]) - 1) if len(c) > d else np.nan
        hs = _sector_health_series(c)
        hv = float(hs.iloc[-1]) if len(hs) and np.isfinite(float(hs.iloc[-1])) else np.nan
        h10 = float(hs.iloc[-11]) if len(hs) > 10 and np.isfinite(float(hs.iloc[-11])) else np.nan
        recs.append(dict(tk=tk, ja=ja, d1=r(1), w1=r(5), m1=r(21),
                         ret63=r(63), ret126=r(126), ret189=r(189),
                         health=hv, health_d10=(hv-h10 if np.isfinite(hv) and np.isfinite(h10) else np.nan)))
    return recs

'''
pat = r"def _rank_etfs\(close_dict, etf_list, minbars=22\):.*?(?=def build_sector_ranks\(macro, extras\):)"
text, n = re.subn(pat, rank_new, text, count=1, flags=re.S)
if n != 1:
    raise SystemExit(f"_rank_etfs replacement count={n}")

rows_new = r'''def _sec_rows(recs, tf, topbottom=False):
    rs = [x for x in recs if x.get(tf) is not None and not (isinstance(x[tf], float) and np.isnan(x[tf]))]
    rs.sort(key=lambda x: x[tf], reverse=True)
    def row(i, s):
        cells = ""
        for k in ("d1", "w1", "m1"):
            hl = " hl" if k == tf else ""
            cells += f'<td class="{color_pct(s[k])}{hl}">{fmt_pct(s[k])}</td>'
        hv = s.get("health", np.nan)
        dv = s.get("health_d10", np.nan)
        hok = hv is not None and np.isfinite(float(hv))
        dok = dv is not None and np.isfinite(float(dv))
        hcls = ("pos" if float(hv) >= 65 else ("neg" if float(hv) < 45 else "mut")) if hok else "mut"
        dcls = ("pos" if float(dv) >= 2 else ("neg" if float(dv) <= -2 else "mut")) if dok else "mut"
        htxt = f'{float(hv):.0f}' if hok else '—'
        dtxt = f'{float(dv):+.0f}' if dok else '—'
        return (f'<tr><td class="l mut">{i}</td>'
                f'<td class="l tk" style="font-size:12px">{_h(s["ja"])}'
                f'<span class="mut" style="font-size:10px"> {s["tk"]}</span></td>{cells}'
                f'<td class="{hcls}" title="Market Conditionsと同型の12指標等加重・0〜100">{htxt}</td>'
                f'<td class="{dcls}" title="Sector Healthの10営業日前比">{dtxt}</td></tr>')
    if topbottom and len(rs) > 10:
        top, bot = rs[:5], rs[-5:]
        h = lambda lab: f'<tr class="secsub"><td colspan="7" class="l">{lab}</td></tr>'
        return (h("強い") + "".join(row(i + 1, s) for i, s in enumerate(top))
                + h("弱い") + "".join(row(len(rs) - 4 + i, s) for i, s in enumerate(bot)))
    return "".join(row(i + 1, s) for i, s in enumerate(rs))

'''
pat = r"def _sec_rows\(recs, tf, topbottom=False\):.*?(?=def _rotation_card\(sectors, m\):)"
text, n = re.subn(pat, rows_new, text, count=1, flags=re.S)
if n != 1:
    raise SystemExit(f"_sec_rows replacement count={n}")

old_head = "head = ('<table><tr><th class=\"l\">#</th><th class=\"l\">セクター</th>'\n                    '<th>日</th><th>週</th><th>月</th></tr>')"
new_head = "head = ('<table><tr><th class=\"l\">#</th><th class=\"l\">セクター</th>'\n                    '<th>日</th><th>週</th><th>月</th><th>Health</th><th>10日Δ</th></tr>')"
if text.count(old_head) != 1:
    raise SystemExit(f"sector header anchor count={text.count(old_head)}")
text = text.replace(old_head, new_head, 1)

old_sub = "f'<div class=\"sub\">S&amp;P500の11セクターETFと業種テーマETFの騰落率（下のサブテーマ別RSは個別株のRS中央値・別物）</div>'"
new_sub = "f'<div class=\"sub\">S&amp;P500の11セクターETFと業種テーマETFの騰落率。Health＝Market Conditionsと同型12指標の等加重・絶対健全度（0〜100）、10日Δ＝10営業日前比。（下のサブテーマ別RSは個別株のRS中央値・別物）</div>'"
if text.count(old_sub) != 1:
    raise SystemExit(f"sector sub anchor count={text.count(old_sub)}")
text = text.replace(old_sub, new_sub, 1)

p.write_text(text, encoding="utf-8")
print("sector health patch applied")
