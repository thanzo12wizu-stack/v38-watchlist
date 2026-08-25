#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_deterioration_validate as base

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_dynamic_structure_floor_15y.json'
base.START='2009-01-01'; base.END='2026-08-25'; START=pd.Timestamp('2011-01-01'); END=pd.Timestamp('2026-08-24'); TARGET=pd.Timestamp('2026-08-21')

def runs(mask):
    a=mask.fillna(False).to_numpy(bool); best=cur=0
    for v in a:
        if v: cur+=1; best=max(best,cur)
        else: cur=0
    return int(best)

def sessions(idx,a,b): return max(len(idx[(idx>=a)&(idx<=b)])-1,0)

def quality(s,eps,th):
    stress=pd.Series(False,index=s.index)
    for e in eps: stress.loc[e['peak']:e['end']]=True
    sig=s<th; false=sig&~stress; n=int(sig.sum())
    return {'signal_days':n,'false_days':int(false.sum()),'false_pct':float(false.sum()/n*100) if n else 0.0,'max_false_run':runs(false),'false_runs':int((false&~false.shift(1,fill_value=False)).sum())}

def assess(name,s,q,bound,eps):
    idx=q.index; r={'name':name,'target':float(s.loc[TARGET]),'latest':float(s.iloc[-1]),'bound_target':float(bound.loc[TARGET]),'bound_latest':float(bound.iloc[-1]),'bound_active_pct':float((s.sub(bound).abs()<1e-9).mean()*100),'max_bound_run':runs(s.sub(bound).abs()<1e-9)}
    for th in (65,55,45):
        arr=[]
        for e in eps:
            h=s.loc[e['peak']:e['trough']]; h=h[h<th]
            if len(h): arr.append(sessions(idx,e['peak'],h.index[0]))
        r[f'below{th}_coverage']=len(arr); r[f'below{th}_mean']=float(np.mean(arr)) if arr else None; r[f'quality{th}']=quality(s,eps,th)
    ben=[]
    for y in (2013,2017):
        z=s[s.index.year==y]; ben.append({'year':y,'min':float(z.min()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())})
    r['benign']=ben; r['benign_lt55']=sum(x['lt55'] for x in ben); r['benign_le45']=sum(x['le45'] for x in ben)
    r['corr63']=float(s.corr(q/q.shift(63)-1)); r['corr21']=float(s.corr(q/q.shift(21)-1)); r['daily']=float(s.diff().abs().mean())
    hs=s[s.index>=pd.Timestamp('2024-01-01')]; hq=q.reindex(hs.index); r['holdout_corr63']=float(hs.corr(hq/hq.shift(63)-1))
    return r

def main():
    px,failed=base.download_prices(); px=px.loc[:END]; m=base.build_metrics(px); q=px.QQQ.loc[START:END].dropna(); m=m.reindex(q.index)
    core=(.15*m.short+.55*m.medium_level+.20*m.long+.10*m.damage).ewm(span=2,adjust=False).mean()
    pen=(.5*(-m.breadth_delta10).clip(lower=0)+.5*(m.breadth_core.rolling(20,min_periods=5).max()-m.breadth_core).clip(lower=0)).ewm(span=3,adjust=False).mean()
    structural=((m.long+m.damage)/2).ewm(span=2,adjust=False).mean()
    eps=base.drawdown_episodes(q,-.08,-.02); rows=[]
    for alpha in (2.5,3.0,3.5,4.0,4.5):
        unf=(core-.55*alpha*pen).clip(0,100)
        for offset in (27.5,30.0,32.5,35.0,37.5,40.0):
            bound=(structural-offset).clip(0,100)
            s=pd.concat([unf,bound],axis=1).max(axis=1)
            name=f'a{alpha:g}_off{offset:g}'
            r=assess(name,s,q,bound,eps); r.update({'alpha':alpha,'offset':offset})
            target_pen=0 if 52<=r['target']<=58 else min(abs(r['target']-52),abs(r['target']-58))*1.5
            r['penalty']=target_pen+(21-r['below65_coverage'])*10+(20-r['below55_coverage'])*5+(18-r['below45_coverage'])*2+r['benign_lt55']*.8+r['benign_le45']*3+r['quality55']['false_days']*.03+r['quality45']['false_days']*.06+max(.58-r['corr63'],0)*100+max(r['daily']-4.5,0)*2+max(r['bound_active_pct']-20,0)*.1
            rows.append(r)
    rows.sort(key=lambda x:x['penalty'])
    feasible=[r for r in rows if 52<=r['target']<=58 and r['below65_coverage']==21 and r['below55_coverage']>=19 and r['below45_coverage']>=17 and r['benign_lt55']<=5 and r['benign_le45']==0 and r['corr63']>=.55 and r['quality45']['max_false_run']<=10]
    out={'definition':{'core':'existing 15/55/20/10','deterioration':'EMA3 negative 10d breadth change + drop from 20d breadth peak','dynamic_floor':'EMA2((Long+Damage)/2) - offset; no QQQ, NQSAR or VIX inside score','final':'max(unfloored deterioration-sensitive score, dynamic structural floor)'},'failed_etfs':failed,'episodes':len(eps),'top20':rows[:20],'feasible':feasible[:20]}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'top8':rows[:8],'feasible_n':len(feasible),'feasible_top':feasible[:8]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
