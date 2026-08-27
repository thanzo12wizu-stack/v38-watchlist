from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact daily hierarchy/tax machinery and aggressive baseline.
src=Path('research/tqqq_stage46_crash_seed_refinement.py').read_text()
prefix=src.split('SPECS=[]')[0]
exec(compile(prefix,'stage46-prefix','exec'),globals())

print('\n=== STAGE51 4H RSI30 ENTRY BACKTEST ===',flush=True)
COST=.0005; TAX=.20315; NSIM=1000; H=2520; BLOCK=120; SEED51=510827
SPEC={'vth':23.0,'s50':-0.50,'ddcut':-0.02,'lookback':30,'maxd':80}
URL_HIST='https://raw.githubusercontent.com/lvrusu/QQQ_price_data/main/QQQ5m_regular_raw_1_2000_to_9_23_24.csv'
URL_EXT='https://raw.githubusercontent.com/lvrusu/QQQ_price_data/main/QQQ5m_Ext_J_23_to_Mar_20a_2026.csv'

# ---------- actual intraday QQQ data ----------
def load5(url):
    print('[intraday] download',url,flush=True)
    x=pd.read_csv(url,usecols=['ds','Open','High','Low','Close'])
    x['ds']=pd.to_datetime(x['ds'],errors='coerce')
    for c in ['Open','High','Low','Close']: x[c]=pd.to_numeric(x[c],errors='coerce')
    return x.dropna().sort_values('ds')

h5=load5(URL_HIST); e5=load5(URL_EXT)
h5=h5[(h5.ds>=pd.Timestamp('2010-01-01'))&(h5.ds<=pd.Timestamp('2024-09-23 23:59:59'))]
e5=e5[(e5.ds>pd.Timestamp('2024-09-23 23:59:59'))&(e5.ds<=pd.Timestamp('2026-03-20 23:59:59'))]
x5=pd.concat([h5,e5],ignore_index=True).drop_duplicates('ds',keep='last').sort_values('ds')
mins=x5.ds.dt.hour*60+x5.ds.dt.minute
x5=x5[(mins>=570)&(mins<960)].copy() # RTH 09:30-16:00 ET, timestamps are local ET
mins=x5.ds.dt.hour*60+x5.ds.dt.minute
x5['date']=x5.ds.dt.normalize(); x5['slot']=np.where(mins<810,0,1) # 09:30-13:30, 13:30-16:00 partial bar
b4=x5.groupby(['date','slot'],sort=True).agg(Open=('Open','first'),High=('High','max'),Low=('Low','min'),Close=('Close','last'),n=('Close','size')).reset_index()
b4=b4[b4.n>=6].copy().sort_values(['date','slot']).reset_index(drop=True)

# TradingView/Pine-style Wilder RMA RSI seed.
def wilder_rsi(a,n=14):
    a=np.asarray(a,float); d=np.diff(a,prepend=np.nan); up=np.where(d>0,d,0.0); dn=np.where(d<0,-d,0.0)
    au=np.full(len(a),np.nan); ad=np.full(len(a),np.nan)
    if len(a)>n:
        au[n]=np.nanmean(up[1:n+1]); ad[n]=np.nanmean(dn[1:n+1])
        for i in range(n+1,len(a)):
            au[i]=(au[i-1]*(n-1)+up[i])/n; ad[i]=(ad[i-1]*(n-1)+dn[i])/n
    rs=au/ad; r=100-100/(1+rs); r[(ad==0)&np.isfinite(au)]=100.; r[(au==0)&(ad==0)]=50.
    return r

b4['rsi14']=wilder_rsi(b4.Close.to_numpy(float),14)
b4['ema10']=pd.Series(b4.Close).ewm(span=10,adjust=False).mean().to_numpy()
b4['ema20']=pd.Series(b4.Close).ewm(span=20,adjust=False).mean().to_numpy()
r=b4.rsi14.to_numpy(float); c=b4.Close.to_numpy(float); e10=b4.ema10.to_numpy(float); e20=b4.ema20.to_numpy(float)
b4['touch25']=(r<=25)&(np.r_[False,r[:-1]>25]); b4['touch30']=(r<=30)&(np.r_[False,r[:-1]>30]); b4['touch35']=(r<=35)&(np.r_[False,r[:-1]>35])
b4['recross25']=(r>25)&(np.r_[False,r[:-1]<=25]); b4['recross30']=(r>30)&(np.r_[False,r[:-1]<=30]); b4['recross35']=(r>35)&(np.r_[False,r[:-1]<=35])
# EMA recovery only after RSI30 was seen in the prior 10 four-hour bars (~5 sessions).
age=10**9; recent30=np.zeros(len(b4),bool)
for i in range(len(b4)):
    age=0 if np.isfinite(r[i]) and r[i]<=30 else age+1; recent30[i]=age<=10
b4['ema10_rec']=recent30&(c>e10)&np.r_[False,c[:-1]<=e10[:-1]]
b4['ema20_rec']=recent30&(c>e20)&np.r_[False,c[:-1]<=e20[:-1]]

# Daily signal map: any qualifying 4H close during the session; execution is next session open.
flagcols=['touch25','touch30','touch35','recross25','recross30','recross35','ema10_rec','ema20_rec']
dsig=b4.groupby('date')[flagcols].max().astype(bool)
dsig['rsi_min']=b4.groupby('date').rsi14.min(); dsig['rsi_last']=b4.groupby('date').rsi14.last()

# ---------- data-quality cross-check against Yahoo daily QQQ already loaded by Stage36 ----------
intra_close=x5.groupby('date').Close.last().astype(float)
yc=qqq.Close.astype(float).copy(); yc.index=pd.DatetimeIndex(yc.index).tz_localize(None).normalize()
qc=pd.concat([intra_close.rename('intraday'),yc.rename('yahoo')],axis=1).dropna(); qr=qc.pct_change().dropna()
qdiff=(qr.intraday-qr.yahoo).abs()
QUALITY={'n_days':int(len(qc)),'return_corr':float(qr.corr().iloc[0,1]),'median_abs_return_diff_bps':float(qdiff.median()*10000),'p99_abs_return_diff_bps':float(qdiff.quantile(.99)*10000),'intraday_start':str(x5.ds.min()),'intraday_end':str(x5.ds.max()),'bars4h':int(len(b4))}
print('[quality]',QUALITY,flush=True)

# Restrict all portfolio comparisons to actual 4H coverage.
DALL=pd.DatetimeIndex(DTS).tz_localize(None).normalize(); lo=max(pd.Timestamp('2011-01-03'),dsig.index.min()); hi=min(pd.Timestamp('2026-03-20'),dsig.index.max())
ids=np.flatnonzero((DALL>=lo)&(DALL<=hi)); D=DTS.iloc[ids].reset_index(drop=True); YY51=pd.to_datetime(D).dt.year.to_numpy(); B0={k:A[k][ids].copy() for k in KEYS}
VX=vix['Close'].astype(float).reindex(pd.DatetimeIndex(D)).ffill().to_numpy(float)
SIG={c:dsig[c].reindex(pd.DatetimeIndex(D).normalize()).fillna(False).to_numpy(bool) for c in flagcols}

# ---------- final cleaned daily Crash->Bull runner ----------
def seed_arr(B,vx): return (B['s50a']<=SPEC['s50'])&(vx>=SPEC['vth'])&(B['dd10']<=SPEC['ddcut'])

def daily_runner(B,vx,cur=None,boundaries=None,trace=False):
    if cur is None: cur=current_trace(B)
    t=target_aggr(B,cur); seed=seed_arr(B,vx); rec=consec_true(B['gte10'],2)&(B['nq']!=0)&(B['mc']>=35)
    bset=set([] if boundaries is None else boundaries); active=False; entry=-1; consumed=-1; age=10**9
    act=np.zeros(len(t),bool); ent=0
    for i in range(len(t)):
        if i in bset: active=False; entry=-1; consumed=-1; age=10**9
        age=0 if seed[i] else age+1; recent=age<=SPEC['lookback']
        if (not active) and recent and rec[i] and (not cur['risklock'][i]):
            last=np.flatnonzero(seed[:i+1]); sid=int(last[-1]) if len(last) else -1
            if sid>consumed: active=True; entry=i; consumed=sid; ent+=1
        if active:
            if seed[i]: consumed=max(consumed,i)
            bad=cur['risklock'][i] or (B['nq'][i]==0) or ((not B['a200'][i]) and (not B['a252'][i])) or (i-entry)>=SPEC['maxd']
            if bad: active=False; entry=-1
            else: t[i]=max(t[i],1.0); act[i]=True
    return {'target':np.clip(t,0,1),'active':act,'seed':seed,'entries':ent} if trace else np.clip(t,0,1)

# 4H RSI is tested as an EARLY sleeve before/alongside the proven daily runner.
# STRUCT gate = at least one long anchor intact and MC>=25. ANY gate = MC>=20 only.
# This intentionally allows Fast/MC lock override for a short tactical sleeve; Slow structural damage is controlled by gate/exit.
def rsi_overlay(B,vx,sig,spec,cur=None,boundaries=None,trace=False):
    if cur is None: cur=current_trace(B)
    dr=daily_runner(B,vx,cur,boundaries,True); t=dr['target'].copy(); seed=dr['seed']
    bset=set([] if boundaries is None else boundaries); age=10**9; active=False; entry=-1; consumed=-1; act=np.zeros(len(t),bool); ent=0
    rawbear=(~B['a200'])&(~B['a252'])
    for i in range(len(t)):
        if i in bset: age=10**9; active=False; entry=-1; consumed=-1
        age=0 if seed[i] else age+1; recent=age<=SPEC['lookback']
        last=np.flatnonzero(seed[:i+1]); sid=int(last[-1]) if len(last) else -1
        allow=(B['mc'][i]>=25 and (not rawbear[i])) if spec['gate']=='STRUCT' else (B['mc'][i]>=20)
        if (not active) and recent and sig[i] and allow and sid>consumed:
            active=True; entry=i; consumed=sid; ent+=1
        if active:
            if seed[i]: consumed=max(consumed,i)
            # Once daily 100% runner is active, the early sleeve has done its job.
            if dr['active'][i]: active=False; entry=-1
            else:
                bad=(B['mc'][i]<20) or (spec['gate']=='STRUCT' and rawbear[i]) or ((i-entry)>=spec['maxd'])
                if bad: active=False; entry=-1
                else: t[i]=max(t[i],spec['floor']); act[i]=True
    return {'target':np.clip(t,0,1),'active':act,'entries':ent,'daily_active':dr['active'],'seed':seed} if trace else np.clip(t,0,1)

# ---------- event study: is 4H RSI30 actually a good buy area? ----------
tqO=tq.Open.astype(float).copy(); tqO.index=pd.DatetimeIndex(tqO.index).tz_localize(None).normalize(); tqL=tq.Low.astype(float).copy(); tqL.index=pd.DatetimeIndex(tqL.index).tz_localize(None).normalize(); tqH=tq.High.astype(float).copy(); tqH.index=pd.DatetimeIndex(tqH.index).tz_localize(None).normalize()
O=tqO.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float); Lw=tqL.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float); Hw=tqH.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float)
seed0=seed_arr(B0,VX); recentseed=np.zeros(len(seed0),bool); age=10**9
for i in range(len(seed0)): age=0 if seed0[i] else age+1; recentseed[i]=age<=SPEC['lookback']
EVENT=[]
def clustered_indices(mask,gap=5):
    z=np.flatnonzero(mask); out=[]; last=-10**9
    for i in z:
        if i-last>gap: out.append(int(i)); last=int(i)
    return out
for nm in ['touch25','touch30','touch35','recross25','recross30','recross35','ema10_rec','ema20_rec']:
    mask=SIG[nm]&recentseed
    for i in clustered_indices(mask,5):
        j=i+1
        if j>=len(O) or not np.isfinite(O[j]): continue
        row={'signal':nm,'signal_date':str(pd.Timestamp(D.iloc[i]).date()),'entry_date':str(pd.Timestamp(D.iloc[j]).date()),'entry_open':O[j]}
        for h in (1,3,5,10,20,40):
            k=min(j+h,len(O)-1); row[f'ret_{h}d']=float(O[k]/O[j]-1) if np.isfinite(O[k]) else np.nan
            sl=slice(j,min(j+h+1,len(O))); low=np.nanmin(Lw[sl]); high=np.nanmax(Hw[sl]); row[f'mae_{h}d']=float(low/O[j]-1); row[f'mfe_{h}d']=float(high/O[j]-1)
        EVENT.append(row)
EV=pd.DataFrame(EVENT); EV.to_csv('tqqq_stage51_event_study.csv',index=False)
EVSUM=[]
for nm,g in EV.groupby('signal'):
    z={'signal':nm,'n':len(g)}
    for h in (1,3,5,10,20,40):
        z[f'ret_{h}d_med']=float(g[f'ret_{h}d'].median()); z[f'pwin_{h}d']=float((g[f'ret_{h}d']>0).mean()); z[f'mae_{h}d_med']=float(g[f'mae_{h}d'].median()); z[f'mfe_{h}d_med']=float(g[f'mfe_{h}d'].median())
    EVSUM.append(z)
EVS=pd.DataFrame(EVSUM); EVS.to_csv('tqqq_stage51_event_summary.csv',index=False)

# ---------- portfolio scan ----------
cur0=current_trace(B0); candidates={'AGGR':target_aggr(B0,cur0),'DAILY_R10':daily_runner(B0,VX,cur0,None,False)}; specs={}
methods={'TOUCH30':'touch30','RECROSS30':'recross30','EMA10':'ema10_rec','EMA20':'ema20_rec'}
for label,col in methods.items():
  for gate in ('STRUCT','ANY'):
    for floor in (.50,.65,.80,1.00):
      for md in (5,10):
        nm=f'{label}_{gate}_F{int(floor*100)}_D{md}'; sp={'method':col,'gate':gate,'floor':floor,'maxd':md}; specs[nm]=sp
        candidates[nm]=rsi_overlay(B0,VX,SIG[col],sp,cur0,None,False)

hist=[]
for nm,t in candidates.items():
    m,_,_=from_target(B0,t,COST); pre=account_end(B0['ret'],t,COST,0.,D); aft=account_end(B0['ret'],t,COST,TAX,D)
    hist.append({'candidate':nm,**(specs.get(nm,{})),'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage51_scan.csv',index=False)

# Fixed subperiods for leaders.
sel=['AGGR','DAILY_R10']
R=HIST[~HIST.candidate.isin(sel)].copy(); sel+=R.sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(10).candidate.tolist()
for cap in (.49,.50): sel+=R[R.pre_mdd>=-cap].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(4).candidate.tolist()
sel=list(dict.fromkeys(sel)); print('[selected]',sel,flush=True)
PER=[('2011-2018',2011,2018),('2019-2022',2019,2022),('2023-2026',2023,2026)]
sub=[]; costs=[]
for nm in sel:
    t=candidates[nm]
    for lab,a,b in PER:
        ix=np.flatnonzero((YY51>=a)&(YY51<=b)); dd=D.iloc[ix].reset_index(drop=True); pre=account_end(B0['ret'][ix],t[ix],COST,0.,dd); aft=account_end(B0['ret'][ix],t[ix],COST,TAX,dd)
        sub.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
    for bps in (5,10,20):
        cc=bps/10000.; pre=account_end(B0['ret'],t,cc,0.,D); aft=account_end(B0['ret'],t,cc,TAX,D); costs.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
pd.DataFrame(sub).to_csv('tqqq_stage51_subperiods.csv',index=False); pd.DataFrame(costs).to_csv('tqqq_stage51_costs.csv',index=False)

# Matched 10y block bootstrap; reset RSI/daily runner state at synthetic block boundaries.
N=len(B0['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED51); starts=rng.integers(0,N-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]; bounds=list(range(BLOCK,H,BLOCK))
mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:B0[k][ix].copy() for k in KEYS}; vx=VX[ix].copy(); cur=current_trace(B)
    tg={'AGGR':target_aggr(B,cur),'DAILY_R10':daily_runner(B,vx,cur,bounds,False)}
    for nm in sel:
        if nm in tg: continue
        sp=specs[nm]; sg=SIG[sp['method']][ix].copy(); tg[nm]=rsi_overlay(B,vx,sg,sp,cur,bounds,False)
    for nm,t in tg.items():
        pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None); mc.append({'sim':z,'candidate':nm,'tax_end':aft['end'],'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%50==0: print('[mc51]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage51_mc.csv',index=False)
def q(a,p): return float(np.quantile(np.asarray(a,float),p))
sm=[]
for nm,g in MC.groupby('candidate'):
    sm.append({'candidate':nm,'tax_end_mean':float(g.tax_end.mean()),'tax_end_median':q(g.tax_end,.5),'tax_end_p05':q(g.tax_end,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_p05':q(g.tax_cagr,.05),'mdd_median':q(g.pre_mdd,.5),'mdd_p05':q(g.pre_mdd,.05),'p_tax30':float(np.mean(g.tax_cagr>=.30))})
SUM=pd.DataFrame(sm); SUM.to_csv('tqqq_stage51_mc_summary.csv',index=False)
p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd']); pair=[]
for nm in sel:
    if nm=='DAILY_R10': continue
    ratio=p[('tax_end',nm)]/p[('tax_end','DAILY_R10')]; dm=p[('pre_mdd',nm)]-p[('pre_mdd','DAILY_R10')]
    pair.append({'candidate':nm,'p_end_better_daily':float(np.mean(ratio>1)),'median_ratio_vs_daily':float(np.median(ratio)),'p05_ratio_vs_daily':q(ratio,.05),'p_mdd_no_worse_daily':float(np.mean(dm>=0)),'mdd_delta_median':float(np.median(dm))})
PAIR=pd.DataFrame(pair); PAIR.to_csv('tqqq_stage51_pairwise.csv',index=False)
FINAL=HIST[HIST.candidate.isin(sel)].merge(SUM,on='candidate',how='left').merge(PAIR,on='candidate',how='left').sort_values('tax_end_mean',ascending=False); FINAL.to_csv('tqqq_stage51_final_rank.csv',index=False)

out={'quality':QUALITY,'coverage':{'start':str(pd.Timestamp(D.iloc[0]).date()),'end':str(pd.Timestamp(D.iloc[-1]).date()),'days':int(len(D))},'event_summary':EVS.to_dict('records'),'selected':sel,'final':FINAL.to_dict('records'),'notes':['4H bars are built from regular-session 5-minute QQQ data: 09:30-13:30 and 13:30-16:00 ET (second bar is partial).','All 4H signals are executed at the next trading-session open; no same-bar fill is assumed.','RSI14 uses Wilder RMA.','Daily Crash seed is VIX close>=23, QQQ SMA50 ATR distance<=-0.5, and 10d drawdown<=-2%.','RSI overlays are temporary early sleeves; the validated daily EMA10/MC57/NQSAR recovery runner remains the path to sustained 100%.'], 'caveats':['Intraday QQQ source is a public third-party GitHub dataset; daily-return agreement with Yahoo is reported in quality metrics.','Intraday coverage ends 2026-03-20, so portfolio comparisons use only that window.','MC57 PIT/survivorship audit unresolved.','NQSAR historical state is proxy.','USDJPY/dividend tax not modeled.','Moving-block bootstrap is not a forecast distribution.']}
Path('tqqq_stage51_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print('\n=== EVENT SUMMARY ==='); print(EVS.to_string(index=False)); print('\n=== HIST TOP ==='); print(HIST.sort_values('tax_cagr',ascending=False).head(20).to_string(index=False)); print('\n=== FINAL ==='); print(FINAL.to_string(index=False)); print('\n=== PAIR ==='); print(PAIR.to_string(index=False))
