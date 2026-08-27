from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd
import yfinance as yf

# Reuse Stage51 exactly through the data build + runner/overlay definitions.
src=Path('research/tqqq_stage51_4h_rsi30_entry_backtest.py').read_text()
prefix=src.split('# ---------- event study:')[0]
exec(compile(prefix,'stage51-prefix','exec'),globals())

print('\n=== STAGE53 QQQ vs TQQQ 4H RSI SOURCE ===',flush=True)
SEED53=530827; NSIM53=1000

# Long-history TQQQ 4H proxy. QQQ intraday path is observed 5m data. The leverage transform is
# daily-reset and calibrated so the second bar lands exactly on the observed TQQQ daily close.
# This is explicitly a proxy, not claimed as historical TQQQ intraday truth.
tqo=tq.Open.astype(float).copy(); tqc=tq.Close.astype(float).copy()
for s in (tqo,tqc): s.index=pd.DatetimeIndex(s.index).tz_localize(None).normalize()
qopen=x5.groupby('date').Open.first().astype(float)
proxy=b4[['date','slot','Close']].copy()
proxy['qopen']=qopen.reindex(pd.DatetimeIndex(proxy.date)).to_numpy(float)
proxy['tq_open']=tqo.reindex(pd.DatetimeIndex(proxy.date)).to_numpy(float)
proxy['tq_close']=tqc.reindex(pd.DatetimeIndex(proxy.date)).to_numpy(float)
proxy['q_ratio']=proxy.Close/proxy.qopen
proxy['raw_ratio']=np.maximum(.05,1.0+3.0*(proxy.q_ratio-1.0))
raw_end=proxy.groupby('date').raw_ratio.transform('last')
proxy['daily_ratio']=proxy.tq_close/proxy.tq_open
proxy['corr']=np.where((raw_end>0)&np.isfinite(proxy.daily_ratio),proxy.daily_ratio/raw_end,1.0)
proxy['frac']=np.where(proxy.slot.to_numpy()==0,4.0/6.5,1.0)
proxy['proxy_close']=proxy.tq_open*proxy.raw_ratio*np.power(np.maximum(proxy['corr'],1e-8),proxy.frac)
# exact daily close anchor sanity
endp=proxy.groupby('date').tail(1)
anchor_err=np.nanmax(np.abs(endp.proxy_close/endp.tq_close-1.0))
assert anchor_err < 1e-8, anchor_err
proxy['rsi14']=wilder_rsi(proxy.proxy_close.to_numpy(float),14)
pr=proxy.rsi14.to_numpy(float)
for th in (20,25,30,35):
    proxy[f'touch{th}']=(pr<=th)&np.r_[False,pr[:-1]>th]
pt_daily=proxy.groupby('date')[[f'touch{x}' for x in (20,25,30,35)]].max().astype(bool)
PT={f'touch{x}':pt_daily[f'touch{x}'].reindex(pd.DatetimeIndex(D).normalize()).fillna(False).to_numpy(bool) for x in (20,25,30,35)}

# Recent real-TQQQ intraday validation (Yahoo 1h, normally up to ~730d). Failure is non-fatal.
VALID={'status':'unavailable'}
try:
    z=yf.download('TQQQ',period='729d',interval='1h',auto_adjust=True,prepost=False,progress=False,threads=False)
    if isinstance(z.columns,pd.MultiIndex):
        if 'TQQQ' in z.columns.get_level_values(-1): z=z.xs('TQQQ',axis=1,level=-1)
        else: z.columns=z.columns.get_level_values(0)
    z=z.dropna(subset=['Close']).copy()
    zi=pd.DatetimeIndex(z.index)
    if zi.tz is None: zi=zi.tz_localize('UTC').tz_convert('America/New_York')
    else: zi=zi.tz_convert('America/New_York')
    z['ds']=zi; mins=zi.hour*60+zi.minute
    z=z[(mins>=570)&(mins<960)].copy(); mins=z.ds.dt.hour*60+z.ds.dt.minute
    z['date']=z.ds.dt.tz_localize(None).dt.normalize(); z['slot']=np.where(mins<810,0,1)
    zr=z.groupby(['date','slot'],sort=True).agg(Close=('Close','last'),n=('Close','size')).reset_index()
    zr=zr[zr.n>=2].sort_values(['date','slot']).reset_index(drop=True); zr['real_rsi']=wilder_rsi(zr.Close.to_numpy(float),14)
    vv=zr.merge(proxy[['date','slot','proxy_close','rsi14']],on=['date','slot'],how='inner').dropna(subset=['real_rsi','rsi14'])
    if len(vv)>=30:
        d=(vv.real_rsi-vv.rsi14).abs()
        VALID={'status':'ok','n_bars':int(len(vv)),'start':str(vv.date.min().date()),'end':str(vv.date.max().date()),
               'rsi_corr':float(vv[['real_rsi','rsi14']].corr().iloc[0,1]),'rsi_mae':float(d.mean()),'rsi_p95_abs':float(d.quantile(.95))}
        for th in (20,25,30,35):
            a=(vv.real_rsi<=th).to_numpy(); b=(vv.rsi14<=th).to_numpy()
            VALID[f'below{th}_agreement']=float(np.mean(a==b)); VALID[f'real_below{th}']=int(a.sum()); VALID[f'proxy_below{th}']=int(b.sum())
except Exception as exc:
    VALID={'status':'unavailable','error':type(exc).__name__}
print('[proxy validation]',VALID,flush=True)

# Exact same Crash seed, ANY gate, 100% floor, 10-session early sleeve. Only RSI source changes.
sp={'gate':'ANY','floor':1.00,'maxd':10}
SIG53={'QQQ_RSI30':SIG['touch30']}
for th in (20,25,30,35): SIG53[f'TQQQ_PROXY_RSI{th}']=PT[f'touch{th}']
SIG53['OR_Q30_T25']=SIG['touch30']|PT['touch25']
SIG53['OR_Q30_T30']=SIG['touch30']|PT['touch30']
SIG53['AND_Q30_T30']=SIG['touch30']&PT['touch30']
SIG53['Q35_AND_T25']=SIG['touch35']&PT['touch25']

cur0=current_trace(B0)
targets={'DAILY_R10':daily_runner(B0,VX,cur0,None,False)}
for nm,sig in SIG53.items(): targets[nm]=rsi_overlay(B0,VX,sig,sp,cur0,None,False)
rows=[]
for nm,t in targets.items():
    m,_,_=from_target(B0,t,COST); pre=account_end(B0['ret'],t,COST,0.,D); aft=account_end(B0['ret'],t,COST,TAX,D)
    rows.append({'candidate':nm,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover'],'signal_days':int(SIG53[nm].sum()) if nm in SIG53 else 0})
HIST=pd.DataFrame(rows).sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]); HIST.to_csv('tqqq_stage53_scan.csv',index=False)

# Fixed subperiods and cost sensitivity.
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
sub=[]; costs=[]
for nm,t in targets.items():
    for lab,a,b in PER:
        ix=np.flatnonzero((YY51>=a)&(YY51<=b)); dd=D.iloc[ix].reset_index(drop=True)
        pre=account_end(B0['ret'][ix],t[ix],COST,0.,dd); aft=account_end(B0['ret'][ix],t[ix],COST,TAX,dd)
        sub.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(B0['ret'],t,c,0.,D); aft=account_end(B0['ret'],t,c,TAX,D)
        costs.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
pd.DataFrame(sub).to_csv('tqqq_stage53_subperiods.csv',index=False); pd.DataFrame(costs).to_csv('tqqq_stage53_costs.csv',index=False)

# Matched moving-block Monte Carlo; RSI event stream is bootstrapped on the same dates as market states.
L=len(B0['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED53)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM53,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM53,-1)[:,:H]
bounds=np.arange(BLOCK,H,BLOCK,dtype=int); mc=[]
for zsim,ix in enumerate(paths):
    B={k:B0[k][ix].copy() for k in KEYS}; vx=VX[ix].copy(); cur=current_trace(B)
    tbase=daily_runner(B,vx,cur,bounds,False)
    all_t={'DAILY_R10':tbase}
    for nm,sig0 in SIG53.items(): all_t[nm]=rsi_overlay(B,vx,sig0[ix],sp,cur,bounds,False)
    for nm,t in all_t.items():
        m,_,_=from_target(B,t,COST); pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':zsim,'candidate':nm,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp']})
    if (zsim+1)%100==0: print('[mc53]',zsim+1,'/',NSIM53,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage53_mc.csv',index=False)

def q(x,p): return float(np.quantile(np.asarray(x,float),p))
summ=[]
for nm,g in MC.groupby('candidate'):
    summ.append({'candidate':nm,'n':len(g),'tax_cagr_p05':q(g.tax_cagr,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_end_p05':q(g.tax_end,.05),'tax_end_median':q(g.tax_end,.5),'tax_end_mean':float(g.tax_end.mean()),'pre_mdd_p05':q(g.pre_mdd,.05),'pre_mdd_median':q(g.pre_mdd,.5),'p_tax30':float(np.mean(g.tax_cagr>=.30))})
SUM=pd.DataFrame(summ); SUM.to_csv('tqqq_stage53_mc_summary.csv',index=False)

# Pair every alternative directly against the already validated QQQ_RSI30 on identical paths.
p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd','tax_cagr'])
pair=[]
for nm in targets:
    if nm=='QQQ_RSI30': continue
    ratio=p[('tax_end',nm)]/p[('tax_end','QQQ_RSI30')]
    pair.append({'candidate':nm,'p_end_better_qqq30':float(np.mean(ratio>1)),'terminal_ratio_median':float(np.median(ratio)),'terminal_ratio_p05':float(np.quantile(ratio,.05)),
                 'p_mdd_no_worse_qqq30':float(np.mean(p[('pre_mdd',nm)]>=p[('pre_mdd','QQQ_RSI30')]-1e-12)),
                 'delta_tax_cagr_median':float(np.median(p[('tax_cagr',nm)]-p[('tax_cagr','QQQ_RSI30')]))})
PAIR=pd.DataFrame(pair).sort_values('terminal_ratio_median',ascending=False); PAIR.to_csv('tqqq_stage53_pairwise.csv',index=False)
FINAL=HIST.merge(SUM,on='candidate',how='left').merge(PAIR,on='candidate',how='left').sort_values(['tax_end_mean','tax_cagr'],ascending=[False,False]); FINAL.to_csv('tqqq_stage53_final_rank.csv',index=False)

summary={'proxy_definition':'QQQ observed 5m path -> 3x daily-reset transform, multiplicatively anchored to actual TQQQ daily close; proxy only',
         'proxy_recent_validation':VALID,'anchor_max_relative_error':float(anchor_err),'historical':HIST.to_dict('records'),'pairwise_vs_qqq30':PAIR.to_dict('records'),
         'winner':str(FINAL.iloc[0].candidate),'note':'Do not replace QQQ RSI with TQQQ proxy unless it wins robustly and proxy validation is adequate.'}
Path('tqqq_stage53_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
print('\n=== STAGE53 HISTORICAL ==='); print(HIST.to_string(index=False)); print('\n=== PAIRWISE VS QQQ RSI30 ==='); print(PAIR.to_string(index=False)); print('\n=== FINAL ==='); print(FINAL.head(12).to_string(index=False)); print('\nSUMMARY',json.dumps(summary,ensure_ascii=False,default=str))
