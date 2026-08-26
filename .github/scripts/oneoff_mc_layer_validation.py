from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import build_dashboard as d

ROOT = Path('.')

# Concept grouping is diagnostic only. Production MC is never modified.
LAYERS = {
    'Broad': {
        'Core US Cap Weighted': ['SPY', 'VTI'],
        'Nasdaq 100': ['QQQ', 'QQQE'],
        'Equal Weight Large': ['RSP'],
        'Dow': ['DIA'],
        'Small Cap': ['IWM'],
        'Mid Cap': ['MDY'],
    },
    'Sector': {
        'Technology': ['XLK'], 'Consumer Discretionary': ['XLY'], 'Communication': ['VOX'],
        'Financials': ['XLF'], 'Industrials': ['XLI'], 'Energy': ['XLE'], 'Materials': ['XLB'],
        'Health Care': ['XLV'], 'Consumer Staples': ['XLP'], 'Utilities': ['XLU'], 'Real Estate': ['XLRE'],
    },
    'Industry': {
        'Semiconductors': ['SOXX', 'SMH', 'XSD'],
        'Software': ['IGV'], 'Cloud': ['SKYY'], 'Cybersecurity': ['CIBR', 'HACK'], 'Internet': ['FDN'],
        'Biotech': ['XBI', 'IBB'], 'Pharma': ['PPH'], 'Medical Devices': ['IHI'], 'Health Providers': ['IHF'],
        'Regional Banks': ['KRE'], 'Banks': ['KBE'],
        'Retail': ['XRT'], 'Home Construction': ['ITB', 'XHB'],
        'Transportation': ['IYT'], 'Airlines': ['JETS'], 'Defense': ['ITA', 'XAR'], 'Automation': ['ROBO'],
        'Metals Mining': ['XME', 'PICK'], 'Copper': ['COPX'], 'Gold Miners': ['GDX'], 'Silver Miners': ['SIL'],
        'Lithium': ['LIT'], 'Oil Gas E&P': ['XOP'], 'Oil Services': ['OIH'], 'Uranium': ['URA'],
        'Solar': ['TAN'], 'Clean Energy': ['ICLN'], 'Real Estate Industry': ['VNQ'],
        'Agribusiness': ['MOO'], 'Water': ['PHO'], 'Infrastructure': ['PAVE'],
    },
}

EXPECTED = set(d.MC_MARKET_TICKERS)
USED = [t for layer in LAYERS.values() for members in layer.values() for t in members]
if set(USED) != EXPECTED or len(USED) != len(set(USED)):
    missing = sorted(EXPECTED - set(USED))
    extra = sorted(set(USED) - EXPECTED)
    dupes = sorted([x for x, n in Counter(USED).items() if n > 1])
    raise SystemExit(f'Concept map mismatch missing={missing} extra={extra} dupes={dupes}')

SCORE_KEYS = (
    'ret5','ret21','ret63','ret252','above10','above20','above50','above200',
    'ma20_gt_50','ma50_gt_200','dd_score','within10'
)


def metric_frames(c: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = c.apply(pd.to_numeric, errors='coerce')
    ma10 = c.rolling(10).mean(); ma20 = c.rolling(20).mean(); ma50 = c.rolling(50).mean(); ma200 = c.rolling(200).mean()
    hi252 = c.rolling(252).max()
    dd = c / hi252 - 1.0
    return {
        'ret5': (c.pct_change(5) > 0).astype(float) * 100.0,
        'ret21': (c.pct_change(21) > 0).astype(float) * 100.0,
        'ret63': (c.pct_change(63) > 0).astype(float) * 100.0,
        'ret252': (c.pct_change(252) > 0).astype(float) * 100.0,
        'above10': (c > ma10).astype(float) * 100.0,
        'above20': (c > ma20).astype(float) * 100.0,
        'above50': (c > ma50).astype(float) * 100.0,
        'above200': (c > ma200).astype(float) * 100.0,
        'ma20_gt_50': (ma20 > ma50).astype(float) * 100.0,
        'ma50_gt_200': (ma50 > ma200).astype(float) * 100.0,
        'dd_score': ((dd + 0.30) / 0.25 * 100.0).clip(0.0, 100.0),
        'within10': (c >= 0.90 * hi252).astype(float) * 100.0,
    }


def concept_metric(metric: pd.DataFrame, concepts: dict[str, list[str]]) -> pd.DataFrame:
    out = {}
    for name, members in concepts.items():
        cols = [x for x in members if x in metric.columns]
        if cols:
            out[name] = metric[cols].mean(axis=1, skipna=True)
    return pd.DataFrame(out, index=metric.index)


def raw_from_concepts(metrics: dict[str, pd.DataFrame], concepts: dict[str, list[str]]) -> pd.Series:
    parts = []
    for key in SCORE_KEYS:
        cm = concept_metric(metrics[key], concepts)
        parts.append(cm.mean(axis=1, skipna=True).rename(key))
    raw = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return raw.ewm(span=2, adjust=False).mean()


def temperature(raw: pd.Series):
    return d._mc_temperature_from_raw(raw)


def cross_count(series: pd.Series, level: float, direction: str) -> int:
    s = pd.to_numeric(series, errors='coerce')
    if direction == 'down': return int(((s < level) & (s.shift(1) >= level)).sum())
    return int(((s >= level) & (s.shift(1) < level)).sum())


def occupancy(s: pd.Series, start='2008-01-01'):
    x = pd.to_numeric(s, errors='coerce').loc[start:].dropna()
    return {
        'n': len(x), 'mean': float(x.mean()), 'median': float(x.median()),
        'bull': float((x >= 55).mean()*100),
        'neutral': float(((x >= 45)&(x < 55)).mean()*100),
        'bear': float((x < 45).mean()*100),
        'strong_bull': float((x >= 80).mean()*100), 'strong_bear': float((x < 20).mean()*100),
    }


def fwd_stats(mc: pd.Series, px: pd.Series, start='2008-01-01'):
    m = pd.to_numeric(mc, errors='coerce').loc[start:]
    p = pd.to_numeric(px, errors='coerce').reindex(m.index).ffill()
    bands = [
        ('<20', -np.inf,20), ('20-35',20,35), ('35-45',35,45), ('45-55',45,55),
        ('55-65',55,65), ('65-80',65,80), ('80+',80,np.inf)
    ]
    rows = {}
    for h in (5,10,20,63):
        f = p.shift(-h)/p - 1.0
        vals = []
        for name, lo, hi in bands:
            mask = (m >= lo) & (m < hi)
            z = f[mask].dropna()
            vals.append((name, len(z), float(z.mean()*100) if len(z) else None, float((z>0).mean()*100) if len(z) else None))
        rows[h] = vals
    return rows


def false_deterioration(mc: pd.Series, px: pd.Series, level=45.0, horizon=20, loss=-0.05):
    m = pd.to_numeric(mc, errors='coerce')
    p = pd.to_numeric(px, errors='coerce').reindex(m.index).ffill()
    crosses = (m < level) & (m.shift(1) >= level)
    dates = list(m.index[crosses])
    hit = 0; valid = 0
    samples = []
    for dt in dates:
        loc = p.index.get_loc(dt)
        if isinstance(loc, slice) or loc + horizon >= len(p): continue
        base = float(p.iloc[loc]); future = p.iloc[loc+1:loc+horizon+1]
        if not np.isfinite(base) or future.dropna().empty: continue
        valid += 1
        worst = float((future/base - 1.0).min())
        ok = worst <= loss
        hit += int(ok)
        samples.append((str(pd.Timestamp(dt).date()), worst*100, ok))
    return {'signals': valid, 'true_drawdown': hit, 'false': valid-hit, 'precision': 100*hit/valid if valid else None, 'recent': samples[-10:]}


def crisis_table(series_map):
    windows = [
        ('2008', '2008-09-01','2009-03-31'), ('2011','2011-07-01','2011-10-31'),
        ('2015-16','2015-07-01','2016-02-29'), ('2018Q4','2018-10-01','2018-12-31'),
        ('2020','2020-02-01','2020-04-30'), ('2022','2022-01-01','2022-12-31'),
        ('2024','2024-07-01','2024-09-30'), ('2025','2025-03-01','2025-05-31'),
    ]
    out = {}
    for label, a, b in windows:
        out[label] = {}
        for name, s in series_map.items():
            x = pd.to_numeric(s, errors='coerce').loc[a:b].dropna()
            out[label][name] = None if x.empty else {'min': round(float(x.min()),2), 'date': str(pd.Timestamp(x.idxmin()).date()), 'max': round(float(x.max()),2)}
    return out


def load_industry_map():
    raw = json.loads((ROOT/'industry_map.json').read_text(encoding='utf-8'))
    mp = raw.get('map', raw) if isinstance(raw, dict) else {}
    out = {}
    for sym, pair in mp.items():
        if isinstance(pair, (list,tuple)) and len(pair)>=2: out[sym.upper()] = (str(pair[0]), str(pair[1]))
        elif isinstance(pair, dict): out[sym.upper()] = (str(pair.get('sector') or ''), str(pair.get('industry') or ''))
    return out


def subtheme_audit():
    snap = json.loads((ROOT/'sector_snapshot.json').read_text(encoding='utf-8'))
    s2i = snap.get('s2i', {}) if isinstance(snap, dict) else {}
    imap = load_industry_map()
    groups = defaultdict(list)
    for sym, group in s2i.items():
        g = str(group or '').strip()
        if not g or 'ETF' in g.upper() or 'ETN' in g.upper(): continue
        sec = imap.get(str(sym).upper(), ('',''))[0] or 'Unclassified'
        groups[g].append((str(sym).upper(), sec))
    rows=[]
    for g, members in groups.items():
        cnt = Counter(sec for _,sec in members)
        parent, n = cnt.most_common(1)[0]
        purity = n/len(members)
        rows.append((g,len(members),parent,purity,len(cnt)))
    rows.sort(key=lambda x:x[1], reverse=True)
    sizes = [r[1] for r in rows]
    audit = {
        'top_level_keys': list(snap.keys())[:30],
        'ticker_group_links': len(s2i), 'unique_subthemes': len(rows),
        'groups_ge3': sum(x>=3 for x in sizes), 'groups_ge5': sum(x>=5 for x in sizes), 'groups_ge10': sum(x>=10 for x in sizes),
        'sector_purity_ge80': sum(r[3]>=0.8 for r in rows),
        'sector_purity_ge90': sum(r[3]>=0.9 for r in rows),
        'cross_sector_lt80': [(g,n,p,round(pur*100,1),k) for g,n,p,pur,k in rows if pur<0.8][:40],
        'largest': [(g,n,p,round(pur*100,1)) for g,n,p,pur,_ in rows[:50]],
    }
    try:
        from leadership.build_leadership import build_model
        model, diag = build_model(ROOT)
        audit['leadership_coverage'] = model.get('coverage')
        audit['leadership_group_count'] = len(model.get('groups') or [])
        audit['leadership_top_groups'] = [
            (x.get('name'),x.get('sector'),x.get('score'),x.get('phase'),x.get('members'))
            for x in (model.get('groups') or [])[:25]
        ]
    except Exception as exc:
        audit['leadership_error'] = f'{type(exc).__name__}: {exc}'
    return audit


def main():
    state = json.loads((ROOT/'state.json').read_text(encoding='utf-8'))
    asof = state.get('date') or None
    hist = d._fetch_mc_long_history(asof=asof)
    print('HISTORY', len(hist), '/', len(d.MC_MARKET_TICKERS), 'asof', asof)
    c = d._mc_frame_from_macro(hist)
    print('PRICE_FRAME', c.shape, str(c.index.min().date()), str(c.index.max().date()))
    metrics = metric_frames(c)

    # Production V0 and diagnostic flat reimplementation check.
    prod = d.mri_frame(hist)
    v0 = prod[0] if isinstance(prod, tuple) else prod
    flat_concepts = {t:[t] for t in d.MC_MARKET_TICKERS}
    raw_flat = raw_from_concepts(metrics, flat_concepts)
    v0_re, _, _, _ = temperature(raw_flat)
    common = pd.concat([v0.rename('prod'), v0_re.rename('re')], axis=1).dropna()
    print('V0_REPLICATION latest_prod=%.4f latest_re=%.4f mean_abs=%.4f max_abs=%.4f' % (
        common['prod'].iloc[-1], common['re'].iloc[-1], (common['prod']-common['re']).abs().mean(), (common['prod']-common['re']).abs().max()))

    # V1 Concept Neutral: every semantic concept receives one vote at Raw level.
    all_concepts={}
    for layer, concepts in LAYERS.items():
        for name,members in concepts.items(): all_concepts[f'{layer}:{name}']=members
    raw_v1 = raw_from_concepts(metrics, all_concepts)
    v1, _, _, _ = temperature(raw_v1)

    # V2: normalize each layer independently, then equal-weight the three temperatures.
    layer_temp={}; layer_z={}; layer_raw={}
    for layer, concepts in LAYERS.items():
        rr=raw_from_concepts(metrics, concepts); tt,_,_,zz=temperature(rr)
        layer_raw[layer]=rr; layer_temp[layer]=tt; layer_z[layer]=zz
    v2 = pd.concat(layer_temp, axis=1).mean(axis=1, skipna=False)
    # Diagnostic alternative: equal-weight standardized Z then one logistic map.
    zmean = pd.concat(layer_z,axis=1).mean(axis=1,skipna=False)
    v2z = d._mc_z_to_temperature(zmean)

    series={'V0':v0,'V1':v1,'V2':v2,'V2Z':v2z}
    latest = {name: round(float(pd.to_numeric(s,errors='coerce').dropna().iloc[-1]),2) for name,s in series.items()}
    latest.update({f'{k}_layer': round(float(v.dropna().iloc[-1]),2) for k,v in layer_temp.items()})
    print('LATEST', json.dumps(latest, ensure_ascii=False, sort_keys=True))
    print('OCCUPANCY', json.dumps({k:occupancy(v) for k,v in series.items()}, ensure_ascii=False, sort_keys=True))
    print('CRISES', json.dumps(crisis_table({**series, **{f'L_{k}':v for k,v in layer_temp.items()}}), ensure_ascii=False, sort_keys=True))

    spy=c['SPY']; qqq=c['QQQ']
    for name,s in series.items():
        print('FALSE_DETERIORATION', name, json.dumps(false_deterioration(s,spy), ensure_ascii=False))
        print('CROSSES', name, 'down45', cross_count(s,45,'down'), 'up45', cross_count(s,45,'up'), 'down35',cross_count(s,35,'down'),'up55',cross_count(s,55,'up'))
        for bench,px in [('SPY',spy),('QQQ',qqq)]:
            fs=fwd_stats(s,px)
            print('FWD',name,bench,json.dumps(fs,ensure_ascii=False))

    div=pd.DataFrame({'V0':v0,'V2':v2, **{f'L_{k}':v for k,v in layer_temp.items()}}).dropna()
    div['gap']=div['V2']-div['V0']; div['abs_gap']=div['gap'].abs()
    top=div.loc[div.index>='2008-01-01'].nlargest(30,'abs_gap')
    print('TOP_DIVERGENCES')
    for dt,row in top.iterrows():
        print(str(pd.Timestamp(dt).date()), 'gap=%.2f V0=%.2f V2=%.2f Broad=%.2f Sector=%.2f Industry=%.2f' % (
            row['gap'],row['V0'],row['V2'],row['L_Broad'],row['L_Sector'],row['L_Industry']))

    print('CONCEPTS', json.dumps({k:{n:v for n,v in x.items()} for k,x in LAYERS.items()}, ensure_ascii=False))
    print('SUBTHEME_AUDIT', json.dumps(subtheme_audit(), ensure_ascii=False, sort_keys=True))

if __name__=='__main__':
    main()
