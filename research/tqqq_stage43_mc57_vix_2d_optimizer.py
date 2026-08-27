from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse exact Stage36 hierarchy/data/tax-account machinery without running its grid.
src = Path('research/tqqq_stage36_goal_first_taxaware.py').read_text()
prefix = src.split('SPECS = [{"name":"CURRENT"}')[0]
exec(compile(prefix, 'stage36-prefix', 'exec'), globals())

print('\n=== STAGE43 MC57 x VIX 2D OPTIMIZER ===', flush=True)
NSIM=1000; TAXSIM=300; H=2520; BLOCK=120; SEED=430827

# ---------- VIX point-in-time normalization ----------
# Compare each day's VIX close with the distribution of COMPLETED prior-month VIX highs.
# This is point-in-time: the current month's future high is never used.
vx = pd.DataFrame({'High':vix['High'].astype(float), 'Close':vix['Close'].astype(float)}).copy()
vx.index = pd.DatetimeIndex(vx.index).tz_localize(None)
vx = vx.sort_index()
monthly_high = vx['High'].groupby(vx.index.to_period('M')).max().dropna()

VIXLVL = vx['Close'].reindex(pd.DatetimeIndex(DTS)).ffill().to_numpy(float)
VIXPCT = np.full(len(DTS), np.nan, float)
VIXZ = np.full(len(DTS), np.nan, float)
for i,d in enumerate(pd.DatetimeIndex(DTS)):
    pm = d.to_period('M') - 1
    hist = monthly_high[monthly_high.index <= pm].to_numpy(float)
    hist = hist[np.isfinite(hist) & (hist>0)]
    if len(hist) < 60 or not np.isfinite(VIXLVL[i]):
        continue
    lv = float(VIXLVL[i])
    VIXPCT[i] = float(np.mean(hist <= lv))
    lh = np.log10(hist)
    sd = float(np.std(lh, ddof=1))
    VIXZ[i] = (np.log10(lv) - float(np.mean(lh))) / sd if sd>1e-12 else 0.0

# Exact Stage38 defensive price-structure logic, but dynamic MC/VIX policy replaces the constant .80/.90 normal-sleeve floor.
def current_trace43(B):
    return current_trace(B)

def price_caps(B):
    n=len(B['ret']); cap=np.ones(n,float)
    cap[B['lte21']] = np.minimum(cap[B['lte21']], .45)
    weak=(~B['a50']) & (~B['a63'])
    cap[weak] = np.minimum(cap[weak], .35)
    pre=(B['dd10']<=-.04) & B['lte21']
    cap[pre] = np.minimum(cap[pre], .35)
    return cap

MC_SCHEDULES = {
    'M1': (.55,.70,.85,.95),
    'M2': (.60,.75,.90,1.00),
    'M3': (.65,.80,.90,1.00),
    'M4': (.70,.82,.92,1.00),
    'M5': (.75,.85,.95,1.00),
    'M6': (.80,.88,.96,1.00),
}
MC_THRESHOLDS = {
    'T1': (35.,50.,65.),
    'T2': (35.,55.,70.),
    'T3': (40.,55.,70.),
}
# Caps apply only to the normal 30% sleeve. Explicit StrongBull/RG/GB/Panic and risk locks remain untouched.
VIX_SCHEMES = {
    'P1': {'pct':[(.80,.90),(.90,.70),(.975,.50)]},
    'P2': {'pct':[(.80,.85),(.90,.65),(.975,.45)]},
    'P3': {'pct':[(.85,.90),(.95,.70),(.99,.50)]},
    'Z1': {'z':[(.50,.90),(1.50,.70),(2.50,.50)]},
    'Z2': {'z':[(.50,.85),(1.50,.65),(2.50,.45)]},
    'H1': {'pct':[(.80,.90),(.90,.70),(.975,.50)], 'abs':[(24.,.70),(30.,.50)]},
    'H2': {'pct':[(.80,.85),(.90,.65),(.975,.45)], 'abs':[(24.,.65),(30.,.45)]},
    'H3': {'z':[(.50,.90),(1.50,.70),(2.50,.50)], 'abs':[(24.,.70),(30.,.50)]},
}

def mc_floor(mc, vals, th):
    a,b,c=th; v0,v1,v2,v3=vals
    out=np.full(len(mc),v0,float)
    out[mc>=a]=v1; out[mc>=b]=v2; out[mc>=c]=v3
    return out

def vix_cap(vlvl,vpct,vz,scheme):
    cap=np.ones(len(vlvl),float)
    for key,arr in scheme.items():
        x = vpct if key=='pct' else vz if key=='z' else vlvl
        for th,c in arr:
            m=np.isfinite(x)&(x>=th)
            cap[m]=np.minimum(cap[m],c)
    return cap

def make_target43(B, spec, cur=None, vlvl=None, vpct=None, vz=None):
    if cur is None: cur=current_trace43(B)
    if spec['name']=='CURRENT': return cur['target'].copy()
    if spec['name']=='BUYHOLD': return np.ones(len(B['ret']),float)
    t=cur['target'].copy()
    normal=(~cur['risklock']) & np.isclose(t,.30,atol=1e-9)
    if spec['name']=='STAGE38':
        x=np.full(len(t),.80); x=np.minimum(x,price_caps(B));
        t[normal]=np.maximum(t[normal],x[normal])
        hit=normal & B['a200'] & B['a252'] & (B['mc']>=35)
        t[hit]=np.maximum(t[hit],.90)
        return np.clip(t,0,1)
    if spec['name']=='VIX24_60':
        x=np.full(len(t),.80); x=np.minimum(x,price_caps(B)); t[normal]=np.maximum(t[normal],x[normal])
        hit=normal & B['a200'] & B['a252'] & (B['mc']>=35); t[hit]=np.maximum(t[hit],.90)
        hot=normal & (vlvl>=24); t[hot]=np.minimum(t[hot],.60)
        return np.clip(t,0,1)
    vals=MC_SCHEDULES[spec['mcs']]; th=MC_THRESHOLDS[spec['mct']]
    desired=mc_floor(B['mc'],vals,th)
    desired=np.minimum(desired, price_caps(B))
    desired=np.minimum(desired, vix_cap(vlvl,vpct,vz,VIX_SCHEMES[spec['vxs']]))
    t[normal]=np.maximum(t[normal],desired[normal])
    return np.clip(t,0,1)

# ---------- annual drawdown profile ----------
def strat_returns(B,t,cost=COST):
    return from_target(B,t,cost)[1]

def annual_dd_profile(sr,dates):
    r=np.asarray(sr,float); dates=pd.to_datetime(dates); yrs=np.array([d.year for d in dates])
    rows=[]
    for y in sorted(np.unique(yrs)):
        x=r[yrs==y]; eq=np.cumprod(1+np.nan_to_num(x,nan=0.0)); pk=np.maximum.accumulate(eq); dd=eq/pk-1
        rows.append((int(y),float(np.min(dd)),float(np.mean(dd))))
    a=np.array([x[1] for x in rows],float); d=np.array([x[2] for x in rows],float)
    return {'annual_mdd_mean':float(np.mean(a)),'annual_mdd_median':float(np.median(a)),'annual_dailydd_mean':float(np.mean(d)),
            'years_mdd20':int(np.sum(a<-.20)),'years_mdd30':int(np.sum(a<-.30)),'annual_rows':rows}

# ---------- historical scan ----------
SPECS=[{'name':'CURRENT'},{'name':'BUYHOLD'},{'name':'STAGE38'},{'name':'VIX24_60'}]
for mcs in MC_SCHEDULES:
  for mct in MC_THRESHOLDS:
    for vxs in VIX_SCHEMES:
      SPECS.append({'name':f'{mcs}_{mct}_{vxs}','mcs':mcs,'mct':mct,'vxs':vxs})

curA=current_trace43(A); hist=[]; targets={}
for s in SPECS:
    t=make_target43(A,s,curA,VIXLVL,VIXPCT,VIXZ); targets[s['name']]=t
    m,_,_=from_target(A,t,COST); pre=account_end(A['ret'],t,COST,0.,DTS); aft=account_end(A['ret'],t,COST,TAX,DTS)
    ap=annual_dd_profile(strat_returns(A,t,COST),DTS)
    hist.append({'candidate':s['name'],'mcs':s.get('mcs',''),'mct':s.get('mct',''),'vxs':s.get('vxs',''),
                 'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],
                 'avg_exp':m['avg_exp'],'turnover':m['turnover'],
                 'annual_mdd_mean':ap['annual_mdd_mean'],'annual_mdd_median':ap['annual_mdd_median'],'annual_dailydd_mean':ap['annual_dailydd_mean'],
                 'years_mdd20':ap['years_mdd20'],'years_mdd30':ap['years_mdd30']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage43_scan.csv',index=False)

# Robust preselection: best tax CAGR under DD caps + best efficiency score.
sel=['CURRENT','BUYHOLD','STAGE38','VIX24_60']
for capdd in (.30,.325,.35,.375,.40):
    g=HIST[(~HIST.candidate.isin(sel))&(HIST.pre_mdd>=-capdd)].sort_values(['tax_cagr','annual_mdd_mean'],ascending=[False,False])
    sel += g.head(4).candidate.tolist()
scan=HIST[~HIST.candidate.isin(['BUYHOLD'])].copy()
scan['scan_score']=scan.tax_cagr - 1.8*np.maximum(0.,-scan.pre_mdd-.35) - .7*np.maximum(0.,-scan.annual_mdd_mean-.23) - .25*np.maximum(0.,-scan.annual_mdd_median-.22)
sel += scan.sort_values('scan_score',ascending=False).head(12).candidate.tolist()
sel=list(dict.fromkeys(sel)); SMAP={s['name']:s for s in SPECS if s['name'] in sel}
print('SELECTED',sel,flush=True)

# Fixed-subperiod stability.
PER=[('2011-2015',2011,2015),('2016-2018',2016,2018),('2019-2021',2019,2021),('2022-2024',2022,2024),('2025-2026',2025,2026)]
YY=DTS.dt.year.to_numpy(); WF=[]
for nm in sel:
    t=targets[nm]
    for lab,a,b in PER:
        ids=np.flatnonzero((YY>=a)&(YY<=b)); rr=A['ret'][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True)
        pre=account_end(rr,tt,COST,0.,dd); aft=account_end(rr,tt,COST,TAX,dd)
        WF.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
WF=pd.DataFrame(WF); WF.to_csv('tqqq_stage43_subperiods.csv',index=False)

# Cost sensitivity.
CC=[]
for nm in sel:
    t=targets[nm]
    for bps in (5,10,20):
        c=bps/10000.; pre=account_end(A['ret'],t,c,0.,DTS); aft=account_end(A['ret'],t,c,TAX,DTS)
        CC.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
COSTS=pd.DataFrame(CC); COSTS.to_csv('tqqq_stage43_costs.csv',index=False)

# Normal moving-block bootstrap: market state, return, VIX absolute level and normalized VIX are sampled together.
L=len(A['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]
normal=[]; ntax=[]
for z in range(NSIM):
    ix=paths[z]; B={k:A[k][ix].copy() for k in KEYS}; vl=VIXLVL[ix]; vp=VIXPCT[ix]; vz=VIXZ[ix]; cur=current_trace43(B)
    for nm,s in SMAP.items():
        t=make_target43(B,s,cur,vl,vp,vz); m,_,_=from_target(B,t,COST); normal.append({'sim':z,'candidate':nm,**m})
        if z<TAXSIM:
            pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
            ntax.append({'sim':z,'candidate':nm,'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%100==0: print('[normal43]',z+1,'/',NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv('tqqq_stage43_normal_mc.csv',index=False)
NTAX=pd.DataFrame(ntax); NTAX.to_csv('tqqq_stage43_normal_tax_mc.csv',index=False)

def q(x,p): return float(np.quantile(np.asarray(x,float),p))
SUM=[]
for nm,g in NORMAL.groupby('candidate'):
    SUM.append({'candidate':nm,'cagr_p05':q(g.cagr,.05),'cagr_median':q(g.cagr,.5),'mdd_p05':q(g.mdd,.05),'mdd_median':q(g.mdd,.5),
                'p_mdd35':float(np.mean(g.mdd<-.35)),'p_mdd40':float(np.mean(g.mdd<-.40)),'p_cagr30':float(np.mean(g.cagr>=.30))})
SUM=pd.DataFrame(SUM); SUM.to_csv('tqqq_stage43_mc_summary.csv',index=False)
TS=[]
for nm,g in NTAX.groupby('candidate'):
    TS.append({'candidate':nm,'tax_p05':q(g.tax_cagr,.05),'tax_median':q(g.tax_cagr,.5),'tax_p95':q(g.tax_cagr,.95),'prob_tax30':float(np.mean(g.tax_cagr>=.30)),
               'mdd_p05':q(g.pre_mdd,.05),'mdd_median':q(g.pre_mdd,.5)})
TAXMC=pd.DataFrame(TS); TAXMC.to_csv('tqqq_stage43_tax_mc_summary.csv',index=False)

# Final goal-first efficiency rank: after-tax growth first, then historical/typical DD penalties.
R=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]; tx=TAXMC[TAXMC.candidate.eq(nm)].iloc[0]; sm=SUM[SUM.candidate.eq(nm)].iloc[0]
    score=(h.tax_cagr + .85*tx.tax_median + .15*tx.tax_p05
           -2.0*max(0.,-h.pre_mdd-.35) -.85*max(0.,-sm.mdd_median-.40)
           -.55*max(0.,-h.annual_mdd_mean-.23) -.25*max(0.,-h.annual_mdd_median-.22))
    R.append({'candidate':nm,'hist_tax_cagr':h.tax_cagr,'hist_pre_cagr':h.pre_cagr,'hist_mdd':h.pre_mdd,
              'annual_mdd_mean':h.annual_mdd_mean,'annual_mdd_median':h.annual_mdd_median,'annual_dailydd_mean':h.annual_dailydd_mean,
              'years_mdd20':int(h.years_mdd20),'years_mdd30':int(h.years_mdd30),
              'tax_mc_median':tx.tax_median,'tax_mc_p05':tx.tax_p05,'prob_tax30':tx.prob_tax30,
              'normal_mdd_median':sm.mdd_median,'normal_mdd_p05':sm.mdd_p05,'score':score})
R=pd.DataFrame(R).sort_values('score',ascending=False); R.to_csv('tqqq_stage43_final_rank.csv',index=False)

print('\n=== HIST TOP ===')
print(HIST.sort_values('tax_cagr',ascending=False).head(30)[['candidate','pre_cagr','pre_mdd','tax_cagr','annual_mdd_mean','annual_mdd_median','annual_dailydd_mean','years_mdd20','years_mdd30','avg_exp']].to_string(index=False))
print('\n=== FINAL RANK ==='); print(R.to_string(index=False))
print('\n=== TAX MC ==='); print(TAXMC.sort_values('tax_median',ascending=False).to_string(index=False))

Path('tqqq_stage43_summary.json').write_text(json.dumps({
    'historical':HIST.to_dict('records'),'selected':sel,'subperiods':WF.to_dict('records'),'costs':COSTS.to_dict('records'),
    'mc_summary':SUM.to_dict('records'),'tax_mc_summary':TAXMC.to_dict('records'),'final_rank':R.to_dict('records'),
    'vix_normalization':'Each day compares signal-time VIX close with completed prior-month VIX high distribution; expanding percentile and log10 z-score, minimum 60 months. No current-month future high.',
    'policy':'Only exact CURRENT normal 30% sleeve is replaced by MC57 target floor, then capped by point-in-time VIX regime and Stage38 price-structure caps. Existing risk locks, StrongBull, RG, GB, VIX Panic remain untouched.',
    'caveats':['MC57 point-in-time/survivorship audit unresolved.','NQSAR history is reconstruction proxy.','USDJPY/dividend tax not modeled.','Bootstrap is a robustness stress, not a probability forecast.']
},ensure_ascii=False,indent=2,default=str))
