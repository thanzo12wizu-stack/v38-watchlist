#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_deterioration_validate as base
import market_conditions_deterioration_smoothing_validate as smooth

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_structure_guard_15y.json'
base.START='2009-01-01'; base.END='2026-08-25'; EVAL_START=pd.Timestamp('2011-01-01'); EVAL_END=pd.Timestamp('2026-08-24'); TARGET=pd.Timestamp('2026-08-21')

def dd63(q): return q/q.rolling(63,min_periods=20).max()-1

def sessions(idx,a,b): return max(len(idx[(idx>=a)&(idx<=b)])-1,0)

def assess(name,s,q,guard,eps):
    idx=q.index; out={'name':name,'target':float(s.loc[TARGET]),'latest':float(s.iloc[-1])}
    for th in (65,55,45):
        a=[]
        for e in eps:
            z=s.loc[e['peak']:e['trough']]; h=z[z<th]
            if len(h): a.append(sessions(idx,e['peak'],h.index[0]))
        out[f'below{th}_coverage']=len(a); out[f'below{th}_mean']=float(np.mean(a)) if a else None
    ben=[]
    for y in (2013,2017):
        z=s[s.index.year==y]; ben.append({'year':y,'min':float(z.min()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())})
    out['benign']=ben; out['benign_lt55']=sum(x['lt55'] for x in ben); out['benign_le45']=sum(x['le45'] for x in ben)
    out['guard_pct']=float(guard.mean()*100); out['corr63']=float(s.corr(q/q.shift(63)-1)); out['corr21']=float(s.corr(q/q.shift(21)-1)); out['daily']=float(s.diff().abs().mean())
    hs=s[s.index>=pd.Timestamp('2024-01-01')]; hq=q.reindex(hs.index); out['holdout_corr63']=float(hs.corr(hq/hq.shift(63)-1))
    return out

def main():
    px,failed=base.download_prices(); px=px.loc[:EVAL_END]; m=base.build_metrics(px); q=px.QQQ.loc[EVAL_START:EVAL_END].dropna(); m=m.reindex(q.index)
    core=(.15*m.short+.55*m.medium_level+.20*m.long+.10*m.damage).ewm(span=2,adjust=False).mean()
    pen_base=.5*(-m.breadth_delta10).clip(lower=0)+.5*(m.breadth_core.rolling(20,min_periods=5).max()-m.breadth_core).clip(lower=0)
    pen3=pen_base.ewm(span=3,adjust=False).mean()
    structural=((m.long+m.damage)/2).ewm(span=2,adjust=False).mean()
    qdd=dd63(q); eps=base.drawdown_episodes(q,-.08,-.02); rows=[]
    for alpha in (2.0,2.5,3.0,3.5,4.0):
      unf=(core-.55*alpha*pen3).clip(0,100)
      for floor in (52.5,55.0,57.5):
       for st in (60,65,70,75):
        for release in (-.06,-.07,-.08,-.09):
          guard=(structural>=st)&(qdd>release)&(unf<floor)
          s=unf.where(~guard,floor)
          n=f'a{alpha:g}_f{floor:g}_st{st}_rel{abs(int(release*100))}'
          r=assess(n,s,q,guard,eps); r.update({'alpha':alpha,'floor':floor,'struct_th':st,'release_dd':release})
          tp=0 if 52<=r['target']<=58 else min(abs(r['target']-52),abs(r['target']-58))*1.5
          r['penalty']=tp+(21-r['below65_coverage'])*10+(20-r['below55_coverage'])*5+(18-r['below45_coverage'])*2+r['benign_lt55']*.7+r['benign_le45']*3+max(.58-r['corr63'],0)*100+max(r['daily']-4.5,0)*2
          rows.append(r)
    rows.sort(key=lambda x:x['penalty'])
    feasible=[r for r in rows if 52<=r['target']<=58 and r['below65_coverage']==21 and r['below55_coverage']>=19 and r['below45_coverage']>=17 and r['benign_le45']==0 and r['benign_lt55']<=5 and r['corr63']>=.55]
    out={'definition':{'core':'15/55/20/10 level score','deterioration':'EMA3 of 50% negative 10d breadth change + 50% drop from 20d breadth peak','guard':'if Long+Damage structural strength remains high and QQQ has not exceeded release drawdown, deterioration can lower score only to Neutral floor','NQSAR_VIX':'post-score context only'},'failed_etfs':failed,'episodes':len(eps),'top20':rows[:20],'feasible':feasible[:20]}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'top10':rows[:10],'feasible_n':len(feasible),'feasible_top':feasible[:8]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
