#!/usr/bin/env python3
from pathlib import Path
import re

P = Path('build_dashboard.py')
s = P.read_text(encoding='utf-8')
orig = s


def sub_once(pattern, repl, *, flags=0, label='pattern'):
    global s
    s2, n = re.subn(pattern, repl, s, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 replacement, got {n}')
    s = s2

# 1) Documentation only: keep the rest of V38 unchanged.
s = s.replace(
    'D. 地合いスコア=4本柱（トレンド30・広がり30・ボラ20・信用20）の合成(raw 0-100)。先導株の強さ温度計/センチメント/レバ環境も',
    'D. Market Conditions=中長期の市場構造（短期15・中期55・長期20・Damage10）。NQSAR=短期、VIX FEAR CYCLE=パニック/底形成として独立表示。')

# 2) Market Conditions 4 blocks.  The existing score plumbing/state key remains `mri`
#    for backward compatibility; only its semantics/calculation are replaced.
sub_once(
    r'STATUS_DEF = \[\n.*?\n\]',
    '''STATUS_DEF = [
    # key, pillar weight, lo, hi, group
    ("short",   15, 0.0, 100.0, "market"),
    ("medium",  55, 0.0, 100.0, "market"),
    ("long",    20, 0.0, 100.0, "market"),
    ("damage",  10, 0.0, 100.0, "market"),
]''',
    flags=re.S, label='STATUS_DEF')

# 3) Ensure the fixed 43-ETF Market Conditions universe is fetched in live builds.
#    No existing macro ticker is removed.
mc_tick_block = '''
# Market Conditions v3: fixed, non-levered cross-sectional ETF universe.
# Broad / GICS sectors / industries are family-balanced; industry ETFs are first
# averaged inside parent groups so Technology/Materials cannot gain votes merely
# because more sub-industry ETFs are present.
MC_BROAD_ETFS = ["SPY","QQQ","DIA","IWM","MDY","RSP"]
MC_SECTOR_ETFS = ["XLK","XLY","VOX","XLF","XLI","XLE","XLB","XLV","XLP","XLU","XLRE"]
MC_INDUSTRY_PARENT = {
    "Technology": ["SOXX","IGV","CIBR","SKYY","FDN"],
    "Health Care": ["XBI","IBB","PPH"],
    "Financials": ["KRE","KBE"],
    "Consumer Discretionary": ["XRT","ITB","XHB"],
    "Industrials": ["IYT","ITA","ROBO","JETS"],
    "Materials": ["XME","COPX","GDX","SIL","LIT"],
    "Energy": ["XOP","OIH","URA"],
    "Clean Energy": ["TAN"],
}
MC_INDUSTRY_ETFS = [t for _xs in MC_INDUSTRY_PARENT.values() for t in _xs]
MC_MARKET_TICKERS = list(dict.fromkeys(MC_BROAD_ETFS + MC_SECTOR_ETFS + MC_INDUSTRY_ETFS))
assert len(MC_MARKET_TICKERS) == 43
MACRO_TICKERS = list(dict.fromkeys(MACRO_TICKERS + MC_MARKET_TICKERS))
'''
anchor = '\ndef _extract(df, tickers, minbars=30):'
pos = s.find(anchor, s.find('MACRO_TICKERS = ['))
if pos < 0:
    raise SystemExit('MACRO_TICKERS insertion anchor missing')
s = s[:pos] + '\n' + mc_tick_block + s[pos:]

# 4) Replace old Trend/Breadth/Vol/Credit score with validated 15/55/20/10 Market Conditions.
mc_func = r'''def _mc_frame_from_macro(macro):
    cols = {}
    for t in MC_MARKET_TICKERS:
        d = macro.get(t)
        if d is None or not hasattr(d, "columns") or "Close" not in d.columns:
            continue
        x = pd.to_numeric(d["Close"], errors="coerce").dropna()
        if len(x) >= 30:
            cols[t] = x
    if not cols:
        return pd.DataFrame()
    c = pd.concat(cols, axis=1).sort_index()
    try:
        c.index = pd.to_datetime(c.index).tz_localize(None)
    except Exception:
        pass
    return c


def _mc_mean_cols(frame, cols):
    have = [c for c in cols if c in frame.columns]
    if not have:
        return pd.Series(np.nan, index=frame.index)
    return frame[have].mean(axis=1, skipna=True)


def _mc_parent_mean(frame):
    parents = []
    for tickers in MC_INDUSTRY_PARENT.values():
        have = [c for c in tickers if c in frame.columns]
        if have:
            parents.append(frame[have].mean(axis=1, skipna=True))
    return pd.concat(parents, axis=1).mean(axis=1, skipna=True) if parents else pd.Series(np.nan, index=frame.index)


def _mc_participation(mask):
    # Each family gets one third.  Industry first gets parent-group balancing.
    pieces = []
    b = _mc_mean_cols(mask, MC_BROAD_ETFS)
    sec = _mc_mean_cols(mask, MC_SECTOR_ETFS)
    ind = _mc_parent_mean(mask)
    for x in (b, sec, ind):
        if x.notna().any():
            pieces.append(x)
    if not pieces:
        return pd.Series(np.nan, index=mask.index)
    return pd.concat(pieces, axis=1).mean(axis=1, skipna=True) * 100.0


def _mc_stratified_median(frame):
    pieces = []
    for cols in (MC_BROAD_ETFS, MC_SECTOR_ETFS):
        have = [c for c in cols if c in frame.columns]
        if have:
            pieces.append(frame[have].median(axis=1, skipna=True))
    parents = []
    for tickers in MC_INDUSTRY_PARENT.values():
        have = [c for c in tickers if c in frame.columns]
        if have:
            parents.append(frame[have].median(axis=1, skipna=True))
    if parents:
        pieces.append(pd.concat(parents, axis=1).mean(axis=1, skipna=True))
    return pd.concat(pieces, axis=1).mean(axis=1, skipna=True) if pieces else pd.Series(np.nan, index=frame.index)


def _mc_linear(series, lo, hi):
    return ((pd.to_numeric(series, errors="coerce") - lo) / (hi - lo)).clip(0.0, 1.0) * 100.0


def mri_frame(macro, W=None):
    """Market Conditions v3 (display/state only; allocation remains NQSAR-driven).

    43 non-levered ETFs, family balanced.  Score is descriptive market health,
    not a forward-return predictor and does not contain NQSAR/VIX/VVIX/credit.
    """
    c = _mc_frame_from_macro(macro)
    if c.empty:
        # Fail visibly but keep downstream rendering alive in degraded/offline fixtures.
        idx = next((d.index for d in macro.values() if hasattr(d, "index") and len(d.index)), pd.DatetimeIndex([pd.Timestamp.today().normalize()]))
        z = pd.Series(50.0, index=idx, dtype=float)
        vals = pd.DataFrame(index=idx)
        for k in ("pillar_short","pillar_medium","pillar_long","pillar_damage"):
            vals[k] = 50.0
        vals["repair_breadth"] = np.nan; vals["repair_thrust10"] = np.nan
        vals["qqq_dd"] = np.nan; vals["bottom_context"] = 0.0; vals["mc_coverage"] = 0.0
        breakdown = [dict(key=k, w=w, group="market", raw=50.0, pts=w*.5, ptsmax=w, frac=.5)
                     for k,w,*_ in STATUS_DEF]
        return z, breakdown, list(MC_MARKET_TICKERS), list(STATUS_DEF), vals

    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma50=c.rolling(50).mean(); ma200=c.rolling(200).mean()
    p = {}
    p["ret5"] = _mc_participation((c/c.shift(5)-1 > 0).where(c.shift(5).notna() & c.notna()))
    p["above10"] = _mc_participation((c > ma10).where(ma10.notna() & c.notna()))
    p["above20"] = _mc_participation((c > ma20).where(ma20.notna() & c.notna()))
    short = pd.concat([p["ret5"],p["above10"],p["above20"]],axis=1).mean(axis=1,skipna=True)

    p["ret21"] = _mc_participation((c/c.shift(21)-1 > 0).where(c.shift(21).notna() & c.notna()))
    p["ret63"] = _mc_participation((c/c.shift(63)-1 > 0).where(c.shift(63).notna() & c.notna()))
    p["above50"] = _mc_participation((c > ma50).where(ma50.notna() & c.notna()))
    p["ma20_gt_50"] = _mc_participation((ma20 > ma50).where(ma20.notna() & ma50.notna()))
    p["ma50_rising"] = _mc_participation((ma50 > ma50.shift(20)).where(ma50.notna() & ma50.shift(20).notna()))
    medium = pd.concat([p[k] for k in ("ret21","ret63","above50","ma20_gt_50","ma50_rising")],axis=1).mean(axis=1,skipna=True)

    p["above200"] = _mc_participation((c > ma200).where(ma200.notna() & c.notna()))
    p["ma50_gt_200"] = _mc_participation((ma50 > ma200).where(ma50.notna() & ma200.notna()))
    long = pd.concat([p["above200"],p["ma50_gt_200"]],axis=1).mean(axis=1,skipna=True)

    hi252 = c.rolling(252,min_periods=200).max()
    dd = c/hi252 - 1.0
    med_dd = _mc_stratified_median(dd)
    dd_score = _mc_linear(med_dd, -0.30, -0.05)
    within10 = _mc_participation((dd >= -0.10).where(dd.notna()))
    damage = pd.concat([dd_score,within10],axis=1).mean(axis=1,skipna=True)

    raw = short*.15 + medium*.55 + long*.20 + damage*.10
    score = raw.ewm(span=2,adjust=False).mean()

    # Recovery telemetry intentionally excludes 5D return/10SMA: this is broader
    # repair after a damaged market, not a second copy of NQSAR.
    repair_breadth = pd.concat([p["above20"],p["ret21"],p["above50"],p["ma20_gt_50"]],axis=1).mean(axis=1,skipna=True)
    repair_thrust10 = repair_breadth - repair_breadth.shift(10)
    qqq = pd.to_numeric(macro.get("QQQ", pd.DataFrame()).get("Close"), errors="coerce") if macro.get("QQQ") is not None else pd.Series(dtype=float)
    qqq = qqq.reindex(score.index).ffill() if len(qqq) else pd.Series(np.nan,index=score.index)
    qqq_dd = qqq/qqq.rolling(252,min_periods=126).max()-1.0
    recent_shock = qqq_dd.rolling(60,min_periods=1).min() <= -0.08
    bottom_context = (recent_shock & (qqq_dd < -0.02)).astype(float)
    coverage = c.notna().sum(axis=1) / float(len(MC_MARKET_TICKERS)) * 100.0

    vals = pd.DataFrame(index=score.index)
    vals["pillar_short"] = short; vals["pillar_medium"] = medium
    vals["pillar_long"] = long; vals["pillar_damage"] = damage
    vals["repair_breadth"] = repair_breadth; vals["repair_thrust10"] = repair_thrust10
    vals["qqq_dd"] = qqq_dd; vals["bottom_context"] = bottom_context; vals["mc_coverage"] = coverage
    for k,v in p.items(): vals[k] = v
    vals["median_dd"] = med_dd*100.0

    last = vals.iloc[-1]
    pmap = {"short":short,"medium":medium,"long":long,"damage":damage}
    breakdown=[]; dropped=[]; active=[]
    for key,w,lo,hi,grp in STATUS_DEF:
        ser=pmap[key]; cur=float(ser.dropna().iloc[-1]) if ser.notna().any() else np.nan
        if not np.isfinite(cur):
            dropped.append(key); continue
        active.append((key,w,lo,hi,grp))
        breakdown.append(dict(key=key,w=w,group=grp,raw=cur,pts=w*cur/100.0,ptsmax=w,frac=cur/100.0))
    return score, breakdown, dropped, active, vals
'''
sub_once(r'def mri_frame\(macro, W=None\):\n.*?\n\ndef mri_auxiliary', mc_func + '\n\ndef mri_auxiliary', flags=re.S, label='mri_frame')

aux_func = r'''def mri_auxiliary(mri, vals, metrics):
    clean = pd.to_numeric(mri, errors="coerce").dropna()
    cur = float(clean.iloc[-1]) if len(clean) else 50.0
    ma10 = clean.rolling(10).mean()
    slope_dir = "→"
    if len(ma10.dropna()) >= 3:
        d = ma10.iloc[-1] - ma10.iloc[-3]
        slope_dir = "↑" if d > 0.4 else ("↓" if d < -0.4 else "→")
    last = vals.reindex(clean.index).iloc[-1] if len(clean) else vals.iloc[-1]
    bvals = [
        ("短期", last.get("pillar_short", np.nan) < 40.0),
        ("中期", last.get("pillar_medium", np.nan) < 40.0),
        ("長期", last.get("pillar_long", np.nan) < 40.0),
        ("Damage", last.get("pillar_damage", np.nan) < 40.0),
    ]
    bear_flags = [(lab, bool(v == True)) for lab,v in bvals]
    bear_n = int(sum(1 for _,v in bear_flags if v))
    hl = float(clean.tail(3).mean()) if len(clean) else cur
    hi20 = float(clean.tail(20).max()) if len(clean) else cur
    drop = hi20-cur
    if drop < 4: peak="高値圏"
    elif drop < 10: peak="押し目"
    else: peak="深押し"
    delta5 = float(cur-clean.iloc[-6]) if len(clean) >= 6 else 0.0
    rb = float(last.get("repair_breadth")) if pd.notna(last.get("repair_breadth")) else np.nan
    rt = float(last.get("repair_thrust10")) if pd.notna(last.get("repair_thrust10")) else np.nan
    med = float(last.get("pillar_medium")) if pd.notna(last.get("pillar_medium")) else np.nan
    ctx = bool(last.get("bottom_context",0.0) >= 0.5)
    recovery = None
    if ctx and np.isfinite(rb) and np.isfinite(rt):
        if cur >= 55.0 and np.isfinite(med) and med >= 50.0 and rb >= 55.0:
            recovery = "CONFIRMED"
        elif cur >= 45.0 and rb >= 45.0 and rt > 0.0:
            recovery = "REPAIRING"
        elif rb >= 35.0 and rt >= 10.0:
            recovery = "EARLY REPAIR"
    cov = float(last.get("mc_coverage")) if pd.notna(last.get("mc_coverage")) else 0.0
    return dict(cur=cur,hl=hl,slope=slope_dir,bear_n=bear_n,bear_flags=bear_flags,
                peak=peak,drop=drop,hi20=hi20,delta5=delta5,recovery=recovery,
                repair_breadth=rb,repair_thrust10=rt,coverage=cov)
'''
sub_once(r'def mri_auxiliary\(mri, vals, metrics\):\n.*?\n\ndef mri_band', aux_func + '\n\ndef mri_band', flags=re.S, label='mri_auxiliary')

old_band = '''def mri_band(v):
    if v >= 70: return ("強気", "bull")
    if v >= 55: return ("やや強気", "bull")
    if v >= 40: return ("中立", "neu")
    if v >= 25: return ("弱含み", "weak")
    return ("弱気", "bear")'''
new_band = '''def mri_band(v):
    if v >= 80: return ("STRONG BULL", "bull")
    if v >= 65: return ("BULL", "bull")
    if v >= 55: return ("WEAK BULL", "bull")
    if v >= 45: return ("NEUTRAL", "neu")
    if v >= 35: return ("WEAK BEAR", "weak")
    if v >= 20: return ("BEAR", "bear")
    return ("STRONG BEAR", "bear")'''
if old_band not in s:
    raise SystemExit('mri_band old block missing')
s = s.replace(old_band,new_band,1)

# 5) Keep the existing layout.  Only labels/one-line telemetry change.
s = s.replace('<div class="lab">トレンド判定 <span id="sarBadge">', '<div class="lab">NQSAR（短期） <span id="sarBadge">', 1)
s = s.replace('VIX反転シーケンス ', 'パニック・底形成 ', 1)
s = s.replace('_gj = {"market":"4本柱"}', '_gj = {"market":"MARKET CONDITIONS"}', 1)
s = s.replace('if k in ("trend", "breadth", "risk", "credit"):', 'if k in ("short", "medium", "long", "damage"):', 1)
s = s.replace('地合いスコアの内訳（4本柱）', 'MARKET CONDITIONS 内訳（短期15 / 中期55 / 長期20 / Damage10）', 1)

# Recovery is not a new card: it is a transient badge inside the existing banner.
needle = '    banner = sar_pill + _ribbon(mkt.get("trend_hist")) + f"""\n'
if needle not in s:
    raise SystemExit('banner anchor missing')
insert = '''    _rec = aux.get("recovery")
    _rcol = {"EARLY REPAIR":"#fbbf24","REPAIRING":"#58a6ff","CONFIRMED":"#34d399"}.get(_rec,"#9aa4b2")
    _recovery_html = (f'<div class="st" style="font-size:12px;color:{_rcol};margin-top:2px">RECOVERY · <b>{_rec}</b></div>' if _rec else "")
'''
s = s.replace(needle, insert + needle, 1)
s = s.replace('マーケットステータス（地合いスコア）<span class="lab-en">MARKET STATUS</span>', 'MARKET CONDITIONS<span class="lab-en">MID / LONG TERM</span>', 1)
s = s.replace('<div class="st">{band_lab}</div>', '<div class="st">{band_lab} <span style="font-size:12px;font-weight:700">5D {aux.get(\'delta5\',0.0):+.1f}</span></div>{_recovery_html}', 1)

# Rename the same score wherever it is displayed; no layout/logic outside MC is changed.
s = s.replace('マーケットステータス推移', 'Market Conditions 推移')
s = s.replace('地合いスコアの推移・', 'Market Conditionsの推移・')
s = s.replace('（70強気/55やや強気/40中立/25弱含み）', '（80 Strong Bull / 65 Bull / 55 Weak Bull / 45 Neutral / 35 Weak Bear / 20 Bear）')
s = s.replace('地合いスコア ・ {band_lab}', 'MARKET CONDITIONS ・ {band_lab}')
s = s.replace('地合いスコア <b>', 'Market Conditions <b>')
s = s.replace('地合いスコア now:', 'Market Conditions now:')

# 6) Update only the regression fingerprint that intentionally pins the score definition.
old_expect = '''_EXPECT = (("trend",30,0.0,1.0,"market"),("breadth",30,0.0,1.0,"market"),
                   ("risk",20,0.0,1.0,"market"),("credit",20,0.0,1.0,"market"))'''
new_expect = '''_EXPECT = (("short",15,0.0,100.0,"market"),("medium",55,0.0,100.0,"market"),
                   ("long",20,0.0,100.0,"market"),("damage",10,0.0,100.0,"market"))'''
if old_expect not in s:
    raise SystemExit('selftest STATUS_DEF fingerprint missing')
s = s.replace(old_expect,new_expect,1)
s = s.replace('地合いスコア4本柱の定義または重みが変更されている', 'Market Conditions 4ブロックの定義または重みが変更されている', 1)
s = s.replace('if "マーケットステータス（地合いスコア）" not in html: errs.append("status banner missing")', 'if "MARKET CONDITIONS" not in html: errs.append("Market Conditions banner missing")', 1)

if s == orig:
    raise SystemExit('no changes applied')
# Idempotency markers / accidental duplicate protection.
if s.count('MC_BROAD_ETFS =') != 1 or s.count('def _mc_frame_from_macro') != 1:
    raise SystemExit('Market Conditions code duplicated')
P.write_text(s,encoding='utf-8')
print('Market Conditions v3 patch applied')
