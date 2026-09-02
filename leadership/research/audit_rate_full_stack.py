from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

CUT=0.75
TRAIN_START=pd.Timestamp('2016-01-04')
TRAIN_END=pd.Timestamp('2021-12-31')
HOLD_START=pd.Timestamp('2022-01-03')
END=pd.Timestamp('2026-03-20')
PERIODS={
 'TRAIN_2016_2021':(TRAIN_START,TRAIN_END),
 'HOLDOUT_2022_2026':(HOLD_START,END),
 '2016_2019':(pd.Timestamp('2016-01-04'),pd.Timestamp('2019-12-31')),
 '2020_2021':(pd.Timestamp('2020-01-01'),pd.Timestamp('2021-12-31')),
 '2022_2023':(pd.Timestamp('2022-01-03'),pd.Timestamp('2023-12-31')),
 '2024_2026':(pd.Timestamp('2024-01-01'),END),
}
PRIMARY_SHOCKS=['dgs2_chg5_z252','real10_chg5_z252','rate_shock_z5','duration_shock_z5','duration_accel_z5']
SECONDARY_SHOCKS=['dgs10_chg5_z252','be10_chg5_z252','curve_chg5_z252','dgs2_chg10_z252','dgs2_chg20_z252','real10_chg10_z252','real10_chg20_z252','dgs10_chg10_z252','dgs10_chg20_z252','real_minus_be_chg5_bp']
LEVELS=['dgs2_level_pct252','dgs10_level_pct252','real10_level_pct252','be10_level_pct252','curve_level_pct252']
POLICY_STATES=['policy_recent20_state','policy_63_state','policy_126_state','policy_recent_hike_vs_cut_state']


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
    if len(x)==0:return {'n':0}
    nav=(1+x).cumprod(); yrs=len(x)/252
    cagr=nav.iloc[-1]**(1/yrs)-1 if yrs>0 and nav.iloc[-1]>0 else np.nan
    dd=nav/nav.cummax()-1
    vol=x.std(ddof=1)*math.sqrt(252) if len(x)>1 else np.nan
    return {'n':len(x),'mean_daily':x.mean(),'cagr':cagr,'maxdd':dd.min(),'ann_vol':vol,'sharpe':x.mean()*252/vol if vol and vol>0 else np.nan,'final_nav':nav.iloc[-1]}

def align_rates(dates,rates):
    idx=pd.DatetimeIndex(dates)
    rr=rates.set_index('date').sort_index().reindex(idx).ffill(limit=7).shift(1)
    rr.index=idx
    return rr

def read_fred_csv(path, series):
    d=pd.read_csv(path)
    dc='DATE' if 'DATE' in d.columns else 'observation_date' if 'observation_date' in d.columns else d.columns[0]
    vc=series if series in d.columns else d.columns[-1]
    d['date']=pd.to_datetime(d[dc],errors='coerce')
    d[series]=pd.to_numeric(d[vc],errors='coerce')
    return d[['date',series]].dropna().drop_duplicates('date').sort_values('date')

def add_policy(rates, upper_path, lower_path):
    up=read_fred_csv(upper_path,'DFEDTARU'); lo=read_fred_csv(lower_path,'DFEDTARL')
    x=pd.merge(up,lo,on='date',how='outer').sort_values('date')
    x[['DFEDTARU','DFEDTARL']]=x[['DFEDTARU','DFEDTARL']].ffill(limit=10)
    x['policy_mid']=(x.DFEDTARU+x.DFEDTARL)/2
    for h in (20,63,126): x[f'policy_chg{h}_bp']=x.policy_mid.diff(h)*100
    x['policy_recent20_state']=np.where(x.policy_chg20_bp>=12.5,1,np.where(x.policy_chg20_bp<=-12.5,-1,0))
    x['policy_63_state']=np.where(x.policy_chg63_bp>=25,1,np.where(x.policy_chg63_bp<=-25,-1,0))
    x['policy_126_state']=np.where(x.policy_chg126_bp>=25,1,np.where(x.policy_chg126_bp<=-25,-1,0))
    delta=x.policy_mid.diff()
    x['hike_event']=delta>=0.10; x['cut_event']=delta<=-0.10
    hike_last=x.date.where(x.hike_event).ffill(); cut_last=x.date.where(x.cut_event).ffill()
    hike_age=(x.date-hike_last).dt.days; cut_age=(x.date-cut_last).dt.days
    x['policy_recent_hike_vs_cut_state']=np.where((hike_age<=20)&((cut_age.isna())|(hike_age<cut_age)),1,np.where((cut_age<=20)&((hike_age.isna())|(cut_age<hike_age)),-1,0))
    out=rates.merge(x,on='date',how='left')
    for c in ['policy_mid','policy_chg20_bp','policy_chg63_bp','policy_chg126_bp','policy_recent20_state','policy_63_state','policy_126_state','policy_recent_hike_vs_cut_state']:
        out[c]=out[c].ffill(limit=7)
    return out, x

def state_for(df,feature):
    z=pd.to_numeric(df[feature],errors='coerce')
    if feature in LEVELS: return pd.Series(np.where(z>=66.667,1,np.where(z<=33.333,-1,0)),index=df.index)
    if feature in POLICY_STATES: return z.fillna(0).astype(int)
    if feature=='real_minus_be_chg5_bp':
        mu=z.shift(1).rolling(252,min_periods=126).mean(); sd=z.shift(1).rolling(252,min_periods=126).std()
        z=(z-mu)/sd.replace(0,np.nan)
    return pd.Series(np.where(z>=CUT,1,np.where(z<=-CUT,-1,0)),index=df.index)

def block_diff(df,y,state,date='date',reps=5000,seed=38,block=20):
    z=df[[date,y]].copy(); z['state']=state.values
    z=z.dropna(subset=[date,y]); z=z[z.state.isin([-1,1])]
    if z.empty:return {'n':0}
    g=z.groupby([date,'state'],observed=True)[y].mean().reset_index()
    dates=pd.DatetimeIndex(sorted(g[date].unique())); pos={d:i for i,d in enumerate(dates)}
    g['block']=g[date].map(lambda d:pos[pd.Timestamp(d)]//block)
    hi=g[g.state.eq(1)][y]; lo=g[g.state.eq(-1)][y]
    obs=float(hi.mean()-lo.mean()) if len(hi) and len(lo) else np.nan
    if not np.isfinite(obs):return {'n':len(g),'n_hi':len(hi),'n_lo':len(lo)}
    agg=[]
    for b,q in g.groupby('block',observed=True):
        h=q[q.state.eq(1)][y]; l=q[q.state.eq(-1)][y]
        agg.append((h.sum(),len(h),l.sum(),len(l)))
    a=np.array(agg,float); nb=len(a)
    if nb<5:return {'n':len(g),'n_hi':len(hi),'n_lo':len(lo),'hi_mean':hi.mean(),'lo_mean':lo.mean(),'diff':obs,'blocks':nb}
    rng=np.random.default_rng(seed)
    ix=rng.integers(0,nb,size=(reps,nb))
    sums=a[ix].sum(axis=1)
    good=(sums[:,1]>0)&(sums[:,3]>0)
    draws=sums[good,0]/sums[good,1]-sums[good,2]/sums[good,3]
    loq,hiq=np.quantile(draws,[.025,.975]); p=2*min((draws<=0).mean(),(draws>=0).mean())
    return {'n':len(g),'n_hi':len(hi),'n_lo':len(lo),'hi_mean':hi.mean(),'lo_mean':lo.mean(),'diff':obs,'blocks':nb,'lo':loq,'hi':hiq,'p_two':min(1,float(p))}

def bh(rows,key='p_two'):
    vals=[(i,r.get(key)) for i,r in enumerate(rows) if r.get(key) is not None and np.isfinite(r.get(key))]
    if not vals:return rows
    order=sorted(vals,key=lambda x:x[1]); m=len(order); qs=[0]*m; prev=1.0
    for j in range(m-1,-1,-1):
        rank=j+1; q=min(prev,order[j][1]*m/rank); qs[j]=q; prev=q
    for j,(idx,p) in enumerate(order): rows[idx]['q_bh']=qs[j]
    return rows

def daily_suite(name,daily,rates,ret_col,gross_col=None,extra_outcomes=None):
    d=daily.copy(); d['date']=pd.to_datetime(d.date); d=d[(d.date>=TRAIN_START)&(d.date<=END)].sort_values('date')
    rr=align_rates(d.date,rates).reset_index(drop=True); d=d.reset_index(drop=True)
    for c in rr.columns:d[c]=rr[c].values
    outcomes=[ret_col]+(extra_outcomes or [])
    if gross_col:
        d['return_per_gross']=pd.to_numeric(d[ret_col],errors='coerce')/pd.to_numeric(d[gross_col],errors='coerce').where(pd.to_numeric(d[gross_col],errors='coerce')>=0.05)
        outcomes.append('return_per_gross')
    features=PRIMARY_SHOCKS+SECONDARY_SHOCKS+LEVELS+POLICY_STATES
    rows=[]
    for period,(a,b) in PERIODS.items():
        z=d[(d.date>=a)&(d.date<=b)].copy()
        for feature in features:
            if feature not in z.columns:continue
            st=state_for(z,feature)
            for outcome in outcomes:
                r=block_diff(z,outcome,st,reps=3000,seed=abs(hash((name,period,feature,outcome)))%(2**32))
                rows.append({'sleeve':name,'period':period,'feature':feature,'outcome':outcome,**r})
    for period in PERIODS:
        for outcome in outcomes:
            subset=[r for r in rows if r['period']==period and r['outcome']==outcome and r['feature'] in PRIMARY_SHOCKS+POLICY_STATES]
            bh(subset)
    return d,rows

def tqqq_scalers(d):
    base_target=pd.to_numeric(d['target_M30_TOUCH30_F80_D10'],errors='coerce').fillna(0)
    current=pd.to_numeric(d['target_CURRENT30'],errors='coerce').fillna(0)
    ret=pd.to_numeric(d['tqqq_ret_usd'],errors='coerce').fillna(0)
    panic=(base_target-current)>1e-6
    rows=[]
    for feature in ['dgs2_chg5_z252','real10_chg5_z252','rate_shock_z5','duration_shock_z5']:
        st=state_for(d,feature)
        for scale in (.75,.50):
            for preserve in (False,True):
                tgt=base_target.copy(); mask=st.eq(1)&(~panic if preserve else True)
                tgt.loc[mask]=tgt.loc[mask]*scale
                rr=ret*tgt
                for period,(a,b) in PERIODS.items():
                    if period not in ['TRAIN_2016_2021','HOLDOUT_2022_2026','2022_2023','2024_2026']:continue
                    m=(d.date>=a)&(d.date<=b)
                    pb=perf(ret[m]*base_target[m]); pc=perf(rr[m])
                    rows.append({'feature':feature,'scale':scale,'preserve_panic':preserve,'period':period,
                                 'base_cagr':pb.get('cagr'),'candidate_cagr':pc.get('cagr'),'delta_cagr':(pc.get('cagr')-pb.get('cagr')) if pb.get('cagr') is not None and pc.get('cagr') is not None else np.nan,
                                 'base_maxdd':pb.get('maxdd'),'candidate_maxdd':pc.get('maxdd'),'delta_maxdd':(pc.get('maxdd')-pb.get('maxdd')) if pb.get('maxdd') is not None and pc.get('maxdd') is not None else np.nan,
                                 'base_calmar':pb.get('cagr')/abs(pb.get('maxdd')) if pb.get('maxdd') and pb.get('maxdd')<0 else np.nan,
                                 'candidate_calmar':pc.get('cagr')/abs(pc.get('maxdd')) if pc.get('maxdd') and pc.get('maxdd')<0 else np.nan,
                                 'days_scaled':int(mask[m].sum())})
    return rows

def tqqq_panic_interaction(d):
    d=d.copy(); d['panic_uplift']=pd.to_numeric(d.target_M30_TOUCH30_F80_D10)-pd.to_numeric(d.target_CURRENT30)
    d['panic_active']=d.panic_uplift>1e-6; d['strat_ret']=pd.to_numeric(d.tqqq_ret_usd)*pd.to_numeric(d.target_M30_TOUCH30_F80_D10)
    rows=[]
    for period,(a,b) in PERIODS.items():
        if period not in ['TRAIN_2016_2021','HOLDOUT_2022_2026','2022_2023','2024_2026']:continue
        z=d[(d.date>=a)&(d.date<=b)]
        for pflag,label in [(True,'PANIC_UPLIFT_ACTIVE'),(False,'NO_PANIC_UPLIFT')]:
            q=z[z.panic_active.eq(pflag)].copy()
            for f in PRIMARY_SHOCKS:
                if len(q)==0:continue
                rows.append({'period':period,'panic_scope':label,'feature':f,**block_diff(q,'strat_ret',state_for(q,f),reps=3000,seed=123+len(rows))})
    return rows

def ordinary_spy_residual(d,spy_panel):
    sp=spy_panel[['date','spy_close']].drop_duplicates('date').copy(); sp['date']=pd.to_datetime(sp.date); sp=sp.sort_values('date'); sp['spy_ret']=sp.spy_close.pct_change(fill_method=None)
    x=d.merge(sp[['date','spy_ret']],on='date',how='left')
    train=x[(x.date>=pd.Timestamp('2022-01-03'))&(x.date<=pd.Timestamp('2023-12-31'))].dropna(subset=['return','gross_exposure','spy_ret'])
    X=np.column_stack([np.ones(len(train)),train.gross_exposure,train.spy_ret,train.gross_exposure*train.spy_ret])
    beta=np.linalg.lstsq(X,train['return'].to_numpy(float),rcond=None)[0]
    h=x[(x.date>=pd.Timestamp('2024-01-01'))&(x.date<=END)].dropna(subset=['return','gross_exposure','spy_ret']).copy()
    Xh=np.column_stack([np.ones(len(h)),h.gross_exposure,h.spy_ret,h.gross_exposure*h.spy_ret]); h['residual']=h['return']-Xh@beta
    rows=[]
    for f in PRIMARY_SHOCKS+POLICY_STATES:
        rows.append({'feature':f,**block_diff(h,'residual',state_for(h,f),reps=5000,seed=700+len(rows))})
    return rows,beta

def theme_suite(theme,rates):
    th=theme.copy(); th['date']=pd.to_datetime(th.date); th=th[th.method.eq('DAY0_RS63_TOP3')].copy()
    rr=rates.sort_values('date')
    m=pd.merge_asof(th.sort_values('date'),rr.sort_values('date'),on='date',direction='backward',tolerance=pd.Timedelta(days=7))
    rows=[]
    for period,(a,b) in PERIODS.items():
        if period not in ['HOLDOUT_2022_2026','2022_2023','2024_2026']:continue
        z=m[(m.date>=a)&(m.date<=b)].copy()
        for f in PRIMARY_SHOCKS+POLICY_STATES:
            for y in ['ret_10','ret_20','vs_spy_10','vs_spy_20']:
                rows.append({'period':period,'feature':f,'outcome':y,**block_diff(z,y,state_for(z,f),reps=3000,seed=900+len(rows))})
    return rows

def sector_policy_suite(panel,rates):
    p=panel.copy(); p['date']=pd.to_datetime(p.date); rr=rates.sort_values('date')
    if 'rel_fwd1' not in p.columns:return []
    p=p.merge(rr[['date']+POLICY_STATES],on='date',how='left')
    top=['XLF','XLE']; bot=['XLRE','XLV']; rows=[]
    for period,(a,b) in PERIODS.items():
        if period not in ['HOLDOUT_2022_2026','2022_2023','2024_2026']:continue
        z=p[(p.date>=a)&(p.date<=b)&p.sector.isin(top+bot)].copy()
        q=z.pivot(index='date',columns='sector',values='rel_fwd1')
        gap=q[top].mean(axis=1)-q[bot].mean(axis=1)
        day=z.groupby('date',observed=True)[POLICY_STATES].first()
        for f in POLICY_STATES:
            t=pd.DataFrame({'date':gap.index,'gap':gap.values,'state':day[f].reindex(gap.index).values})
            rows.append({'period':period,'feature':f,**block_diff(t,'gap',t.state,date='date',reps=3000,seed=1100+len(rows))})
    return rows

def main():
    ap=argparse.ArgumentParser()
    for k in ['rates','policy-upper','policy-lower','tqqq','ordinary','reset','theme','spy-panel','sector-panel','output']:
        ap.add_argument('--'+k,required=True)
    args=ap.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    rates=pd.read_csv(args.rates,parse_dates=['date']); rates,policy_raw=add_policy(rates,args.policy_upper,args.policy_lower)
    if rates.policy_mid.notna().sum()<1000: raise RuntimeError('policy target range coverage too small')
    tq=pd.read_csv(args.tqqq,parse_dates=['date']); ordinary=pd.read_csv(args.ordinary,parse_dates=['date']); reset=pd.read_csv(args.reset,parse_dates=['date'])
    theme=pd.read_csv(args.theme,parse_dates=['date']); spy=pd.read_csv(args.spy_panel,parse_dates=['date']); sector=pd.read_csv(args.sector_panel,parse_dates=['date'])
    tq['strat_ret']=pd.to_numeric(tq.tqqq_ret_usd)*pd.to_numeric(tq.target_M30_TOUCH30_F80_D10)
    tqm,tqrows=daily_suite('TQQQ_TOUCH30_F80',tq,rates,'strat_ret',extra_outcomes=['tqqq_ret_usd','target_M30_TOUCH30_F80_D10','target_CURRENT30'])
    ordd,orows=daily_suite('ORDINARY_PEAK30_PART25_R3',ordinary,rates,'return','gross_exposure',extra_outcomes=['gross_exposure','positions'])
    rsid,rrows=daily_suite('RSI_RESET_RISE30_S029_P4_H20',reset,rates,'return','gross_exposure',extra_outcomes=['gross_exposure','positions'])
    spyres,beta=ordinary_spy_residual(ordd,spy)
    scalers=tqqq_scalers(tqm); panic=tqqq_panic_interaction(tqm); throws=theme_suite(theme,rates); secpol=sector_policy_suite(sector,rates)
    pd.DataFrame(tqrows+orows+rrows).to_csv(out/'daily_feature_tests.csv',index=False)
    pd.DataFrame(scalers).to_csv(out/'tqqq_rate_scalers.csv',index=False); pd.DataFrame(panic).to_csv(out/'tqqq_panic_interactions.csv',index=False)
    pd.DataFrame(spyres).to_csv(out/'ordinary_spy_residual_tests.csv',index=False); pd.DataFrame(throws).to_csv(out/'theme_rate_full_tests.csv',index=False); pd.DataFrame(secpol).to_csv(out/'sector_policy_tests.csv',index=False)
    policy_raw.to_csv(out/'policy_target_history.csv',index=False)
    def primary_extract(rows,sleeve,outcome='strat_ret'):
        return [r for r in rows if r.get('sleeve')==sleeve and r.get('period') in ['TRAIN_2016_2021','HOLDOUT_2022_2026','2022_2023','2024_2026'] and r.get('outcome')==outcome and r.get('feature') in PRIMARY_SHOCKS+POLICY_STATES]
    summary={
      'status':'RESEARCH_ONLY_NO_RULE_CHANGE',
      'timing':'Daily sleeve returns on t use rate/policy data known by prior market close. Theme signals enter next open and may use signal-day close rates.',
      'policy_source':'Federal Funds Target Range upper/lower (DFEDTARU/DFEDTARL); kept separate from 2Y market repricing.',
      'primary_hypotheses':PRIMARY_SHOCKS+POLICY_STATES,
      'tqqq_primary':primary_extract(tqrows,'TQQQ_TOUCH30_F80','strat_ret'),
      'ordinary_primary':primary_extract(orows,'ORDINARY_PEAK30_PART25_R3','return'),
      'ordinary_per_gross_primary':primary_extract(orows,'ORDINARY_PEAK30_PART25_R3','return_per_gross'),
      'reset_primary':primary_extract(rrows,'RSI_RESET_RISE30_S029_P4_H20','return'),
      'ordinary_spy_residual_2024_26':spyres,
      'ordinary_spy_beta_train_2022_23':beta.tolist(),
      'tqqq_scalers':scalers,
      'tqqq_panic_interactions':panic,
      'theme_tests':throws,
      'sector_policy_tests':secpol,
      'coverage':{'rates_start':rates.date.min(),'rates_end':rates.date.max(),'policy_nonnull':int(rates.policy_mid.notna().sum())},
    }
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print('===RATE_FULL_STACK==='); print(json.dumps(safe(summary),ensure_ascii=False,separators=(',',':'))); print('===END===')
if __name__=='__main__':main()
