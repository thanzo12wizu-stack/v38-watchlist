#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import market_conditions_deterioration_validate as base

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'market_conditions_structure_guard_15y.json'
base.START='2009-01-01'; base.END='2026-08-25'; EVAL_START=pd.Timestamp('2011-01-01'); EVAL_END=pd.Timestamp('2026-08-24'); TARGET=pd.Timestamp('2026-08-21')

def dd63(q): return q/q.rolling(63,min_periods=20).max()-1

def sessions(idx,a,b): return max(len(idx[(idx>=a)&(idx<=b)])-1,0)

def max_true_run(mask:pd.Series)->int:
    arr=mask.fillna(False).to_numpy(bool); best=cur=0
    for v in arr:
        if v: cur+=1; best=max(best,cur)
        else: cur=0
    return int(best)

def signal_quality(s:pd.Series,eps:list[dict],th:float)->dict:
    decline=pd.Series(False,index=s.index); stress=pd.Series(False,index=s.index)
    for e in eps:
        decline.loc[(decline.index>=e['peak'])&(decline.index<=e['trough'])]=True
        stress.loc[(stress.index>=e['peak'])&(stress.index<=e['end'])]=True
    sig=s<th
    outside=~stress
    false=sig&outside
    total=int(sig.sum()); decline_hits=int((sig&decline).sum()); stress_hits=int((sig&stress).sum())
    return {
        'signal_days':total,
        'decline_phase_days':decline_hits,
        'stress_episode_days':stress_hits,
        'outside_stress_false_days':int(false.sum()),
        'outside_stress_false_pct_of_signal':float(false.sum()/total*100) if total else 0.0,
        'max_consecutive_false_days':max_true_run(false),
        'false_runs':int((false & ~false.shift(1,fill_value=False)).sum()),
    }

def assess(name,s,q,guard,eps):
    idx=q.index; out={'name':name,'target':float(s.loc[TARGET]),'latest':float(s.iloc[-1])}
    for th in (65,55,45):
        a=[]
        for e in eps:
            z=s.loc[e['peak']:e['trough']]; h=z[z<th]
            if len(h): a.append(sessions(idx,e['peak'],h.index[0]))
        out[f'below{th}_coverage']=len(a); out[f'below{th}_mean']=float(np.mean(a)) if a else None
        out[f'quality_below{th}']=signal_quality(s,eps,th)
    ben=[]
    for y in (2013,2017):
        z=s[s.index.year==y]; ben.append({'year':y,'min':float(z.min()),'lt55':int((z<55).sum()),'le45':int((z<=45).sum())})
    out['benign']=ben; out['benign_lt55']=sum(x['lt55'] for x in ben); out['benign_le45']=sum(x['le45'] for x in ben)
    out['guard_pct']=float(guard.mean()*100); out['max_guard_run']=max_true_run(guard)
    out['corr63']=float(s.corr(q/q.shift(63)-1)); out['corr21']=float(s.corr(q/q.shift(21)-1)); out['daily']=float(s.diff().abs().mean())
    hs=s[s.index>=pd.Timestamp('2024-01-01')]; hq=q.reindex(hs.index); out['holdout_corr63']=float(hs.corr(hq/hq.shift(63)-1))
    return out

def main():
    px,failed=base.download_prices(); px=px.loc[:EVAL_END]; m=base.build_metrics(px); q=px.QQQ.loc[EVAL_START:EVAL_END].dropna(); m=m.reindex(q.index)
    core=(.15*m.short+.55*m.medium_level+.20*m.long+.10*m.damage).ewm(span=2,adjust=False).mean()
    pen_base=.5*(-m.breadth_delta10).clip(lower=0)+.5*(m.breadth_core.rolling(20,min_periods=5).max()-m.breadth_core).clip(lower=0)
    pen3=pen_base.ewm(span=3,adjust=False).mean()
    structural=((m.long+m.damage)/2).ewm(span=2,adjust=False).mean()
    qdd=dd63(q); eps=base.drawdown_episodes(q,-.08,-.02); rows=[]
    benchmark_guard=pd.Series(False,index=q.index)
    benchmarks={'core_current':assess('core_current',core,q,benchmark_guard,eps)}
    fast075=(core-.55*.75*pen3).clip(0,100)
    benchmarks['deterioration_alpha0.75']=assess('deterioration_alpha0.75',fast075,q,benchmark_guard,eps)
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
          # penalize false defensive readings outside full >=8% stress episodes as well as benign-bull errors
          false55=r['quality_below55']['outside_stress_false_days']; false45=r['quality_below45']['outside_stress_false_days']
          r['penalty']=tp+(21-r['below65_coverage'])*10+(20-r['below55_coverage'])*5+(18-r['below45_coverage'])*2+r['benign_lt55']*.7+r['benign_le45']*3+false55*.025+false45*.05+max(.58-r['corr63'],0)*100+max(r['daily']-4.5,0)*2
          rows.append(r)
    rows.sort(key=lambda x:x['penalty'])
    feasible=[r for r in rows if 52<=r['target']<=58 and r['below65_coverage']==21 and r['below55_coverage']>=19 and r['below45_coverage']>=17 and r['benign_le45']==0 and r['benign_lt55']<=5 and r['corr63']>=.55 and r['quality_below45']['max_consecutive_false_days']<=10]
    out={'definition':{'core':'15/55/20/10 level score','deterioration':'EMA3 of 50% negative 10d breadth change + 50% drop from 20d breadth peak','guard':'if Long+Damage structural strength remains high and QQQ has not exceeded release drawdown, deterioration can lower score only to Neutral floor','false_detection_test':'signal days outside complete objective QQQ >=8% drawdown stress episodes (peak until recovery to within 2% of peak)','NQSAR_VIX':'post-score context only'},'failed_etfs':failed,'episodes':len(eps),'benchmarks':benchmarks,'top20':rows[:20],'feasible':feasible[:20]}
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'benchmarks':benchmarks,'top5':rows[:5],'feasible_n':len(feasible),'feasible_top':feasible[:5]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
