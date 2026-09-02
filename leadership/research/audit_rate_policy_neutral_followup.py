from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

END=pd.Timestamp('2026-03-20')
POLICY=['policy_recent20_state','policy_63_state','policy_126_state','policy_recent_hike_vs_cut_state']
PERIODS={
 'TRAIN_2016_2021':(pd.Timestamp('2016-01-04'),pd.Timestamp('2021-12-31')),
 'HOLDOUT_2022_2026':(pd.Timestamp('2022-01-03'),END),
 '2022_2023':(pd.Timestamp('2022-01-03'),pd.Timestamp('2023-12-31')),
 '2024_2026':(pd.Timestamp('2024-01-01'),END),
}

def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,list): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)):
        v=float(x); return v if np.isfinite(v) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x

def perf(r):
    x=pd.to_numeric(r,errors='coerce').dropna().astype(float)
    if not len(x): return {'n':0}
    nav=(1+x).cumprod(); yrs=len(x)/252; dd=nav/nav.cummax()-1
    cagr=nav.iloc[-1]**(1/yrs)-1 if yrs>0 and nav.iloc[-1]>0 else np.nan
    return {'n':len(x),'cagr':cagr,'maxdd':dd.min(),'final_nav':nav.iloc[-1],'mean_daily':x.mean(),
            'calmar':cagr/abs(dd.min()) if dd.min()<0 else np.nan}

def align_policy(dates,policy,shift_daily=True):
    idx=pd.DatetimeIndex(dates)
    p=policy.set_index('date').sort_index()[POLICY].reindex(idx).ffill(limit=7)
    if shift_daily: p=p.shift(1)
    p.index=idx
    return p

def block_contrast(df,y,state,treated,control=0,reps=6000,seed=38,block=20):
    z=df[['date',y]].copy(); z['state']=pd.to_numeric(state,errors='coerce').values
    z=z.dropna(subset=['date',y,'state']); z=z[z.state.isin([treated,control])]
    if z.empty:return {'n':0}
    g=z.groupby(['date','state'],observed=True)[y].mean().reset_index()
    a=g[g.state.eq(treated)][y]; b=g[g.state.eq(control)][y]
    out={'n':len(g),'n_treated':len(a),'n_control':len(b),'treated_mean':a.mean() if len(a) else np.nan,
         'control_mean':b.mean() if len(b) else np.nan,'diff':a.mean()-b.mean() if len(a) and len(b) else np.nan}
    if not len(a) or not len(b): return out
    dates=pd.DatetimeIndex(sorted(g.date.unique())); pos={d:i for i,d in enumerate(dates)}
    g['block']=g.date.map(lambda d:pos[pd.Timestamp(d)]//block)
    agg=[]
    for _,q in g.groupby('block',observed=True):
        aa=q[q.state.eq(treated)][y]; bb=q[q.state.eq(control)][y]
        agg.append((aa.sum(),len(aa),bb.sum(),len(bb)))
    ar=np.asarray(agg,float); nb=len(ar); out['blocks']=nb
    if nb<5:return out
    rng=np.random.default_rng(seed); ix=rng.integers(0,nb,size=(reps,nb)); s=ar[ix].sum(axis=1)
    good=(s[:,1]>0)&(s[:,3]>0); draws=s[good,0]/s[good,1]-s[good,2]/s[good,3]
    lo,hi=np.quantile(draws,[.025,.975]); p=2*min((draws<=0).mean(),(draws>=0).mean())
    out.update({'lo':lo,'hi':hi,'p_two':min(1,float(p))})
    return out

def bh(rows):
    vals=[(i,r.get('p_two')) for i,r in enumerate(rows) if r.get('p_two') is not None and np.isfinite(r.get('p_two'))]
    if not vals:return
    o=sorted(vals,key=lambda z:z[1]); m=len(o); prev=1.0
    for rank_rev in range(m-1,-1,-1):
        rank=rank_rev+1; idx,p=o[rank_rev]; q=min(prev,p*m/rank); rows[idx]['q_bh']=q; prev=q

def daily_policy_suite(name,daily,policy,outcomes):
    d=daily.copy(); d['date']=pd.to_datetime(d.date); d=d[d.date<=END].sort_values('date').reset_index(drop=True)
    pp=align_policy(d.date,policy,True).reset_index(drop=True)
    for c in POLICY:d[c]=pp[c].values
    rows=[]
    for period,(a,b) in PERIODS.items():
        z=d[(d.date>=a)&(d.date<=b)].copy()
        for feat in POLICY:
            for treated,label in [(1,'HIKE_VS_NEUTRAL'),(-1,'CUT_VS_NEUTRAL')]:
                for y in outcomes:
                    r=block_contrast(z,y,z[feat],treated,0,reps=6000,seed=abs(hash((name,period,feat,label,y)))%(2**32))
                    rows.append({'sleeve':name,'period':period,'feature':feat,'contrast':label,'outcome':y,**r})
        for label in ['HIKE_VS_NEUTRAL','CUT_VS_NEUTRAL']:
            for y in outcomes:
                bh([r for r in rows if r['period']==period and r['contrast']==label and r['outcome']==y])
    return d,rows

def tqqq_scalers(d):
    ret=pd.to_numeric(d.tqqq_ret_usd,errors='coerce').fillna(0)
    base=pd.to_numeric(d.target_M30_TOUCH30_F80_D10,errors='coerce').fillna(0)
    cur=pd.to_numeric(d.target_CURRENT30,errors='coerce').fillna(0); panic=base-cur>1e-6
    rows=[]
    for feat in POLICY:
        for scale in (.75,.50):
            for preserve in (False,True):
                mask=d[feat].eq(1)&(~panic if preserve else True)
                tgt=base.copy(); tgt.loc[mask]*=scale; cand=ret*tgt; br=ret*base
                for period,(a,b) in PERIODS.items():
                    if period=='2024_2026':continue
                    m=(d.date>=a)&(d.date<=b); pb=perf(br[m]); pc=perf(cand[m])
                    rows.append({'feature':feat,'scale':scale,'preserve_panic':preserve,'period':period,
                                 'base_cagr':pb.get('cagr'),'candidate_cagr':pc.get('cagr'),'delta_cagr':pc.get('cagr')-pb.get('cagr'),
                                 'base_maxdd':pb.get('maxdd'),'candidate_maxdd':pc.get('maxdd'),'delta_maxdd':pc.get('maxdd')-pb.get('maxdd'),
                                 'base_calmar':pb.get('calmar'),'candidate_calmar':pc.get('calmar'),'days_scaled':int(mask[m].sum())})
    return rows

def spy_residuals(ordinary,spy,policy):
    d=ordinary.copy(); d['date']=pd.to_datetime(d.date); sp=spy[['date','spy_close']].drop_duplicates('date').copy(); sp['date']=pd.to_datetime(sp.date); sp=sp.sort_values('date'); sp['spy_ret']=sp.spy_close.pct_change(fill_method=None)
    d=d.merge(sp[['date','spy_ret']],on='date',how='left'); pp=align_policy(d.date,policy,True).reset_index(drop=True)
    for c in POLICY:d[c]=pp[c].values
    rows=[]; betas={}
    for period in ['HOLDOUT_2022_2026','2022_2023']:
        a,b=PERIODS[period]; z=d[(d.date>=a)&(d.date<=b)].dropna(subset=['return','gross_exposure','spy_ret']).copy()
        X=np.column_stack([np.ones(len(z)),z.gross_exposure,z.spy_ret,z.gross_exposure*z.spy_ret]); beta=np.linalg.lstsq(X,z['return'].to_numpy(float),rcond=None)[0]; z['residual']=z['return']-X@beta; betas[period]=beta.tolist()
        for feat in POLICY:
            for treated,label in [(1,'HIKE_VS_NEUTRAL'),(-1,'CUT_VS_NEUTRAL')]:
                r=block_contrast(z,'residual',z[feat],treated,0,reps=8000,seed=700+len(rows))
                rows.append({'period':period,'feature':feat,'contrast':label,**r})
        for label in ['HIKE_VS_NEUTRAL','CUT_VS_NEUTRAL']:
            bh([r for r in rows if r['period']==period and r['contrast']==label])
    return rows,betas

def theme_suite(theme,policy):
    t=theme.copy(); t['date']=pd.to_datetime(t.date); t=t[t.method.eq('DAY0_RS63_TOP3')].sort_values('date')
    p=policy[['date']+POLICY].sort_values('date'); t=pd.merge_asof(t,p,on='date',direction='backward',tolerance=pd.Timedelta(days=7))
    rows=[]
    for period in ['HOLDOUT_2022_2026','2022_2023','2024_2026']:
        a,b=PERIODS[period]; z=t[(t.date>=a)&(t.date<=b)].copy()
        for feat in POLICY:
            for treated,label in [(1,'HIKE_VS_NEUTRAL'),(-1,'CUT_VS_NEUTRAL')]:
                for y in ['ret_10','ret_20','vs_spy_10','vs_spy_20']:
                    r=block_contrast(z,y,z[feat],treated,0,reps=6000,seed=900+len(rows))
                    rows.append({'period':period,'feature':feat,'contrast':label,'outcome':y,**r})
        for label in ['HIKE_VS_NEUTRAL','CUT_VS_NEUTRAL']:
            for y in ['ret_10','ret_20','vs_spy_10','vs_spy_20']:
                bh([r for r in rows if r['period']==period and r['contrast']==label and r['outcome']==y])
    return rows

def main():
    ap=argparse.ArgumentParser()
    for k in ['policy','tqqq','ordinary','reset','theme','spy-panel','output']:ap.add_argument('--'+k,required=True)
    a=ap.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    policy=pd.read_csv(a.policy,parse_dates=['date']); tq=pd.read_csv(a.tqqq,parse_dates=['date']); ordinary=pd.read_csv(a.ordinary,parse_dates=['date']); reset=pd.read_csv(a.reset,parse_dates=['date']); theme=pd.read_csv(a.theme,parse_dates=['date']); spy=pd.read_csv(a.spy_panel,parse_dates=['date'])
    tq['strat_ret']=pd.to_numeric(tq.tqqq_ret_usd)*pd.to_numeric(tq.target_M30_TOUCH30_F80_D10)
    tqd,tqr=daily_policy_suite('TQQQ_TOUCH30_F80',tq,policy,['strat_ret','tqqq_ret_usd','target_M30_TOUCH30_F80_D10'])
    ordx,orr=daily_policy_suite('ORDINARY_PEAK30_PART25_R3',ordinary,policy,['return','gross_exposure','positions'])
    rsx,rsr=daily_policy_suite('RSI_RESET',reset,policy,['return','gross_exposure','positions'])
    scalers=tqqq_scalers(tqd); residual,betas=spy_residuals(ordinary,spy,policy); th=theme_suite(theme,policy)
    pd.DataFrame(tqr+orr+rsr).to_csv(out/'policy_neutral_daily_tests.csv',index=False); pd.DataFrame(scalers).to_csv(out/'tqqq_policy_scalers.csv',index=False); pd.DataFrame(residual).to_csv(out/'ordinary_policy_spy_residual.csv',index=False); pd.DataFrame(th).to_csv(out/'theme_policy_neutral.csv',index=False)
    summary={'status':'RESEARCH_ONLY_NO_RULE_CHANGE','timing':'Daily sleeves use previous market close policy state; Theme uses signal-day close before next-open entry.','policy_features':POLICY,'daily_tests':tqr+orr+rsr,'tqqq_scalers':scalers,'ordinary_spy_residual':residual,'ordinary_spy_control_betas':betas,'theme':th}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('===POLICY_NEUTRAL_FOLLOWUP==='); print(json.dumps(safe(summary),ensure_ascii=False,separators=(',',':'))); print('===END===')
if __name__=='__main__':main()
