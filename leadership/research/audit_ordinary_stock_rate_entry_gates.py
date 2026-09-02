from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo

SELECTIVE_SLOTS=4
PEAK_PCT=30
PARTIAL_FRAC=.25
END=pd.Timestamp('2026-03-20')
PERIODS={
 'TRAIN_2016_2021':(pd.Timestamp('2016-01-04'),pd.Timestamp('2021-12-31')),
 'HOLDOUT_2022_2026':(pd.Timestamp('2022-01-03'),END),
 '2022_2023':(pd.Timestamp('2022-01-03'),pd.Timestamp('2023-12-31')),
 '2024_2026':(pd.Timestamp('2024-01-01'),END),
}
SCENARIOS={
 'BASE':('NONE',None),
 'POLICY_RECENT20_BLOCK':('BLOCK','policy_recent20_state'),
 'POLICY_RECENT20_CAP4':('CAP4','policy_recent20_state'),
 'POLICY_63_BLOCK':('BLOCK','policy_63_state'),
 'POLICY_RECENT_HIKE_BLOCK':('BLOCK','policy_recent_hike_vs_cut_state'),
 'DGS2_SHOCK_BLOCK':('BLOCK','dgs2_chg5_z252'),
 'REAL10_SHOCK_BLOCK':('BLOCK','real10_chg5_z252'),
 'RATE_SHOCK_BLOCK':('BLOCK','rate_shock_z5'),
 'RATE_SHOCK_CAP4':('CAP4','rate_shock_z5'),
 'DURATION_SHOCK_BLOCK':('BLOCK','duration_shock_z5'),
 'DURATION_SHOCK_CAP4':('CAP4','duration_shock_z5'),
 'DURATION_ACCEL_BLOCK':('BLOCK','duration_accel_z5'),
 'DGS2_HIGH_BLOCK':('BLOCK','dgs2_level_pct252'),
 'DGS10_HIGH_BLOCK':('BLOCK','dgs10_level_pct252'),
 'REAL10_HIGH_BLOCK':('BLOCK','real10_level_pct252'),
}
POLICY_FEATURES={'policy_recent20_state','policy_63_state','policy_recent_hike_vs_cut_state'}
LEVEL_FEATURES={'dgs2_level_pct252','dgs10_level_pct252','real10_level_pct252'}

def safe(x):
    if isinstance(x,dict):return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,list):return [safe(v) for v in x]
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(np.floating,float)):
        v=float(x);return v if np.isfinite(v) else None
    if isinstance(x,pd.Timestamp):return x.isoformat()
    return x

def px(frame,date,sym,fallback=None):
    try:
        x=float(frame.at[date,sym])
        if np.isfinite(x) and x>0:return x
    except Exception:pass
    return fallback

def perf(ret):
    x=pd.to_numeric(ret,errors='coerce').dropna().astype(float)
    if not len(x):return {'n':0}
    nav=(1+x).cumprod();yrs=len(x)/252;dd=nav/nav.cummax()-1
    cagr=nav.iloc[-1]**(1/yrs)-1 if yrs>0 and nav.iloc[-1]>0 else np.nan
    return {'n':len(x),'cagr':cagr,'maxdd':dd.min(),'final_nav':nav.iloc[-1],'calmar':cagr/abs(dd.min()) if dd.min()<0 else np.nan,'mean_daily':x.mean()}

def block_delta(delta,reps=6000,seed=38,block=20):
    x=pd.to_numeric(delta,errors='coerce').dropna().to_numpy(float)
    if not len(x):return {'n':0}
    b=np.arange(len(x))//block; agg=pd.DataFrame({'x':x,'b':b}).groupby('b').x.agg(['sum','count']).to_numpy(float); nb=len(agg)
    out={'n':len(x),'blocks':nb,'mean':float(x.mean())}
    if nb<5:return out
    rng=np.random.default_rng(seed);ix=rng.integers(0,nb,size=(reps,nb));s=agg[ix].sum(axis=1);draw=s[:,0]/s[:,1]
    lo,hi=np.quantile(draw,[.025,.975]);p=2*min((draw<=0).mean(),(draw>=0).mean());out.update({'lo':lo,'hi':hi,'p_two':min(1,float(p))});return out

def build_state_table(idx,rates,policy):
    dates=pd.DatetimeIndex(idx)
    r=rates.set_index('date').sort_index().reindex(dates).ffill(limit=7)
    p=policy.set_index('date').sort_index().reindex(dates).ffill(limit=7)
    cols=['dgs2_chg5_z252','real10_chg5_z252','rate_shock_z5','duration_shock_z5','duration_accel_z5','dgs2_level_pct252','dgs10_level_pct252','real10_level_pct252']
    out=r[cols].copy()
    for c in POLICY_FEATURES:out[c]=p[c]
    return out

def active_condition(row,feature):
    if feature is None:return False
    x=row.get(feature,np.nan)
    if pd.isna(x):return False
    if feature in POLICY_FEATURES:return float(x)>0
    if feature in LEVEL_FEATURES:return float(x)>=66.667
    return float(x)>=.75

def precompute_context(meta,matrices,peer_ctx):
    idx=meta['analysis_idx'];breadth,nq=meta['breadth'],meta['nq'];ctx={};red_run=0
    for i,d0 in enumerate(idx):
        d=pd.Timestamp(d0);prev=None if i==0 else pd.Timestamp(idx[i-1])
        if prev is None:continue
        color=str(nq.at[prev,'nq_color']) if prev in nq.index and pd.notna(nq.at[prev,'nq_color']) else ''
        red_run=red_run+1 if color=='Red' else 0;red_force=color=='Red' and red_run>=1
        b=float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan;bucket=base.breadth_bucket(b);bull=color in ('Blue','Green')
        cap=base.N_PORT if bull and bucket==2 else SELECTIVE_SLOTS if bull and bucket==1 else 0
        candidates=ex.ranked_candidates(prev,matrices,peer_ctx,bucket,base.N_PORT) if (not red_force and cap>0) else []
        ctx[d]={'prev':prev,'color':color,'red_force':red_force,'bucket':bucket,'base_cap':cap,'candidates':candidates}
    return ctx

def simulate(meta,matrices,ctx,states,scenario):
    mode,feature=SCENARIOS[scenario];idx=meta['analysis_idx'];opens,closes=matrices['open'],matrices['close'];cash=1.0;pos={};rows=[];entries=[];blocked_days=0
    def close_position(sym,price):
        nonlocal cash
        p=pos.pop(sym);cash+=p['shares']*price
    for i,d0 in enumerate(idx):
        d=pd.Timestamp(d0)
        if i>0:
            c=ctx[d];prev=c['prev'];red_force=c['red_force']
            if red_force:
                for sym in list(pos):
                    op=px(opens,d,sym,px(closes,prev,sym,pos[sym]['entry_price']))
                    if op is not None:close_position(sym,op)
            else:
                for sym in list(pos):
                    p=pos[sym];pc=px(closes,prev,sym,p['entry_price'])
                    if pc is None:continue
                    if (not p['partial_done']) and pc>=p['entry_price']*1.24:
                        op=px(opens,d,sym,pc)
                        if op is not None:
                            sold=p['shares']*PARTIAL_FRAC;cash+=sold*op;p['shares']-=sold;p['partial_done']=True
                    stop=max(p['entry_price']*.92,p['peak_close']*(1-PEAK_PCT/100))
                    if pc<=stop:
                        op=px(opens,d,sym,pc)
                        if op is not None:close_position(sym,op)
            cap=c['base_cap'];active=active_condition(states.loc[prev] if prev in states.index else pd.Series(dtype=float),feature)
            if active:
                if mode=='BLOCK':cap=0
                elif mode=='CAP4':cap=min(cap,4)
            if c['base_cap']>0 and cap==0 and len(pos)<c['base_cap'] and c['candidates']:blocked_days+=1
            if (not red_force) and cap>0 and len(pos)<cap:
                nav_open=cash
                for sym,p in pos.items():
                    op=px(opens,d,sym,px(closes,prev,sym,p['entry_price']))
                    if op is not None:nav_open+=p['shares']*op
                slot_cash=nav_open/base.N_PORT
                for sym,cdat in c['candidates']:
                    if len(pos)>=cap or cash<=0:break
                    if sym in pos:continue
                    op=px(opens,d,sym,px(closes,prev,sym,None))
                    if op is None:continue
                    alloc=min(slot_cash,cash)
                    if alloc<=1e-10:break
                    cash-=alloc;pos[sym]={'shares':alloc/op,'entry_price':op,'entry_date':d,'peak_close':op,'partial_done':False,**cdat};entries.append({'date':d,'symbol':sym})
        gross=0.0;nav=cash
        for sym,p in pos.items():
            cp=px(closes,d,sym,px(opens,d,sym,p['entry_price']))
            if cp is None:cp=p['entry_price']
            p['peak_close']=max(p['peak_close'],cp);mark=p['shares']*cp;gross+=mark;nav+=mark
        rows.append({'date':d,'nav':nav,'gross_exposure':gross/nav if nav>0 else np.nan,'positions':len(pos)})
    q=pd.DataFrame(rows).set_index('date');q['return']=q.nav.pct_change(fill_method=None).fillna(0);q['scenario']=scenario
    return q.reset_index(),len(entries),blocked_days

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--rates',required=True);ap.add_argument('--policy',required=True);ap.add_argument('--frozen-baseline',required=True);ap.add_argument('--output',required=True);ap.add_argument('--analysis-start',default='2016-01-04');ap.add_argument('--analysis-end',default='2026-03-20');ap.add_argument('--max-tickers',type=int,default=6000);ap.add_argument('--batch-size',type=int,default=75);a=ap.parse_args()
    root=Path(a.root);out=Path(a.output);out.mkdir(parents=True,exist_ok=True);rates=pd.read_csv(a.rates,parse_dates=['date']);policy=pd.read_csv(a.policy,parse_dates=['date']);frozen=pd.read_csv(a.frozen_baseline,parse_dates=['date'])
    meta,matrices=ex.build_inputs_ext(root,a.analysis_start,a.analysis_end,a.max_tickers,a.batch_size);peer=loo.build_leave_one_out_scores(root,matrices);ctx=precompute_context(meta,matrices,peer);states=build_state_table(meta['analysis_idx'],rates,policy)
    sims={};info={}
    for s in SCENARIOS:
        print('SIM',s,flush=True);q,e,b=simulate(meta,matrices,ctx,states,s);sims[s]=q;info[s]={'entries':e,'blocked_days':b}
    baseq=sims['BASE'][['date','return','nav']].rename(columns={'return':'rerun_return','nav':'rerun_nav'});cmp=baseq.merge(frozen[['date','return','nav']],on='date',how='inner',suffixes=('','_frozen'))
    repro={'n':len(cmp),'return_corr':cmp.rerun_return.corr(cmp['return']),'return_mae':float((cmp.rerun_return-cmp['return']).abs().mean()),'final_nav_rerun':float(cmp.rerun_nav.iloc[-1]),'final_nav_frozen':float(cmp.nav.iloc[-1])}
    rows=[];daily=sims['BASE'][['date','return']].rename(columns={'return':'BASE'})
    for s,q in sims.items():
        if s!='BASE':daily=daily.merge(q[['date','return']].rename(columns={'return':s}),on='date',how='inner')
        for period,(aa,bb) in PERIODS.items():
            z=q[(q.date>=aa)&(q.date<=bb)];zb=sims['BASE'][(sims['BASE'].date>=aa)&(sims['BASE'].date<=bb)];pc=perf(z['return']);pb=perf(zb['return']);dlt=pd.Series(z['return'].to_numpy()-zb['return'].to_numpy(),index=z.date)
            bt=block_delta(dlt,reps=5000,seed=abs(hash((s,period)))%(2**32)) if s!='BASE' else {'n':len(z),'mean':0.0}
            rows.append({'scenario':s,'period':period,'entries':info[s]['entries'],'blocked_days':info[s]['blocked_days'],'cagr':pc.get('cagr'),'maxdd':pc.get('maxdd'),'calmar':pc.get('calmar'),'base_cagr':pb.get('cagr'),'base_maxdd':pb.get('maxdd'),'delta_cagr':pc.get('cagr')-pb.get('cagr'),'delta_maxdd':pc.get('maxdd')-pb.get('maxdd'),'delta_daily_mean':bt.get('mean'),'delta_lo':bt.get('lo'),'delta_hi':bt.get('hi'),'delta_p_two':bt.get('p_two')})
    pd.DataFrame(rows).to_csv(out/'ordinary_rate_entry_gate_performance.csv',index=False);daily.to_csv(out/'ordinary_rate_entry_gate_daily.csv.gz',index=False,compression='gzip');pd.DataFrame([repro]).to_csv(out/'baseline_reproduction.csv',index=False)
    summary={'status':'RESEARCH_ONLY_NO_RULE_CHANGE','mechanic':'Existing holdings/exits unchanged. Only new-entry capacity is blocked or capped at 4 when the pre-specified rate/policy condition is active at signal-day close.','scenarios':SCENARIOS,'baseline_reproduction':repro,'scenario_info':info,'performance':rows}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2),encoding='utf-8');print('===ORDINARY_RATE_GATE===');print(json.dumps(safe(summary),ensure_ascii=False,separators=(',',':')));print('===END===')
if __name__=='__main__':main()
