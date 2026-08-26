from __future__ import annotations

import json, math, re
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

ROOT=Path('.')


def entropy(counts):
    vals=np.array(list(counts.values()),dtype=float)
    vals=vals[vals>0]
    if vals.size<=1:return 0.0
    p=vals/vals.sum(); return float(-(p*np.log(p)).sum()/np.log(len(vals)))


def main():
    snap=json.loads((ROOT/'sector_snapshot.json').read_text(encoding='utf-8'))
    s2t=snap.get('s2t') or {}; s2i=snap.get('s2i') or {}; e2j=snap.get('e2j') or {}; j2rs=snap.get('j2rs') or {}

    pairs=defaultdict(list); major_subs=defaultdict(set); major_tickers=Counter(); invalid=[]
    for sym,val in s2t.items():
        if not isinstance(val,(list,tuple)) or len(val)<2:
            invalid.append((sym,val)); continue
        major=str(val[0]).strip(); sub=str(val[1]).strip()
        if not major or not sub: continue
        pairs[(major,sub)].append(str(sym).upper()); major_subs[major].add(sub); major_tickers[major]+=1

    # Is the same subtheme name reused under different majors?
    sub_to_maj=defaultdict(set)
    for major,sub in pairs: sub_to_maj[sub].add(major)
    dup_sub={k:sorted(v) for k,v in sub_to_maj.items() if len(v)>1}

    print('THEME_COUNTS',json.dumps({
        'ticker_assignments':len(s2t),'valid_pairs':len(pairs),'unique_subtheme_names':len(sub_to_maj),
        'major_count':len(major_subs),'invalid_rows':len(invalid),'duplicated_subtheme_names':len(dup_sub)
    },ensure_ascii=False,sort_keys=True))
    print('MAJORS',json.dumps({m:{'subthemes':len(major_subs[m]),'tickers':major_tickers[m]} for m in sorted(major_subs)},ensure_ascii=False,sort_keys=True))
    if dup_sub: print('DUP_SUBTHEME_NAMES',json.dumps(dict(list(dup_sub.items())[:40]),ensure_ascii=False))

    # Build detailed-industry exposure per subtheme from actual member tickers.
    rows=[]
    for (major,sub),members in pairs.items():
        inds=Counter(); rsvals=[]; etfish=0
        for sym in members:
            ind=str(s2i.get(sym) or '').strip()
            if not ind: ind='Unclassified'
            if 'ETF' in ind.upper() or 'ETN' in ind.upper(): etfish+=1
            inds[ind]+=1
            jp=e2j.get(ind)
            if jp in j2rs:
                try:
                    v=float(j2rs[jp]);
                    if np.isfinite(v):rsvals.append(v)
                except Exception:pass
        n=len(members); top=inds.most_common(5)
        top1=top[0][1]/n if n else 0; top3=sum(x[1] for x in top[:3])/n if n else 0
        rows.append({
            'major':major,'sub':sub,'n':n,'industry_n':len(inds),'top1':top1,'top3':top3,'entropy':entropy(inds),
            'top':top,'etfish':etfish,'industry_rs_median':None if not rsvals else round(float(np.median(rsvals)),2),
            'industry_rs_mean':None if not rsvals else round(float(np.mean(rsvals)),2),'rs_cov':round(len(rsvals)/n*100,1) if n else 0.0
        })
    rows.sort(key=lambda r:(-r['n'],r['major'],r['sub']))
    sizes=[r['n'] for r in rows]
    print('SUBTHEME_SIZE',json.dumps({
        'n':len(rows),'median':float(np.median(sizes)),'p25':float(np.quantile(sizes,.25)),'p75':float(np.quantile(sizes,.75)),
        'ge3':sum(x>=3 for x in sizes),'ge5':sum(x>=5 for x in sizes),'ge10':sum(x>=10 for x in sizes),'ge20':sum(x>=20 for x in sizes),
        'singletons':sum(x==1 for x in sizes)
    },sort_keys=True))
    print('BRIDGE_PURITY',json.dumps({
        'top1_ge80':sum(r['top1']>=.8 for r in rows),'top1_ge60':sum(r['top1']>=.6 for r in rows),
        'top1_lt50':sum(r['top1']<.5 for r in rows),'top3_ge80':sum(r['top3']>=.8 for r in rows),
        'median_industry_count':float(np.median([r['industry_n'] for r in rows])),
        'median_entropy':round(float(np.median([r['entropy'] for r in rows])),3),
        'themes_with_etfish_members':sum(r['etfish']>0 for r in rows),
        'median_industry_rs_coverage':round(float(np.median([r['rs_cov'] for r in rows])),1)
    },sort_keys=True))
    print('LARGEST_SUBTHEMES',json.dumps([{
        'major':r['major'],'sub':r['sub'],'n':r['n'],'industry_n':r['industry_n'],'top1_pct':round(r['top1']*100,1),
        'top3_pct':round(r['top3']*100,1),'top':r['top'][:4],'rs_cov':r['rs_cov'],'ind_rs_med':r['industry_rs_median']
    } for r in rows[:40]],ensure_ascii=False))
    mixed=sorted(rows,key=lambda r:(r['top1'],-r['n']))
    print('MOST_CROSS_INDUSTRY',json.dumps([{
        'major':r['major'],'sub':r['sub'],'n':r['n'],'industry_n':r['industry_n'],'top1_pct':round(r['top1']*100,1),
        'top3_pct':round(r['top3']*100,1),'entropy':round(r['entropy'],2),'top':r['top'][:5]
    } for r in mixed if r['n']>=5][:50],ensure_ascii=False))
    pure=sorted([r for r in rows if r['n']>=5],key=lambda r:(-r['top1'],-r['n']))
    print('MOST_PURE',json.dumps([{
        'major':r['major'],'sub':r['sub'],'n':r['n'],'top1_pct':round(r['top1']*100,1),'top':r['top'][:3]
    } for r in pure[:40]],ensure_ascii=False))

    # Inspect how the dashboard currently consumes s2t/j2rs without dumping the full source.
    src=(ROOT/'build_dashboard.py').read_text(encoding='utf-8').splitlines()
    hits=[]
    for i,line in enumerate(src):
        if any(tok in line for tok in ('s2t','j2rs','subtheme','サブテーマ')):
            lo=max(0,i-3);hi=min(len(src),i+4)
            block='\n'.join(f'{j+1}: {src[j]}' for j in range(lo,hi))
            if block not in hits:hits.append(block)
    print('SOURCE_HIT_COUNT',len(hits))
    for idx,block in enumerate(hits[:35],1):
        print(f'SOURCE_HIT_{idx}\n{block}\n---')

if __name__=='__main__':main()
