from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage51 data construction, exact daily hierarchy/tax model, 4H bars and overlay engine.
src=Path('research/tqqq_stage51_4h_rsi30_entry_backtest.py').read_text()
prefix=src.split('# ---------- event study:')[0]
exec(compile(prefix,'stage51-prefix', 'exec'), globals())

print('\n=== STAGE52 4H RSI DIVERGENCE BACKTEST ===', flush=True)
NSIM=1000; H=2520; BLOCK=120; SEED52=520827

# -----------------------------------------------------------------------------
# Confirmed-pivot divergence. Critical anti-lookahead rule:
# a pivot at bar p is not tradable until bar p+right has CLOSED.
# The daily flag is assigned to that confirmation date, and portfolio execution
# remains next trading-session open through the Stage51 daily engine.
# -----------------------------------------------------------------------------
LOW=b4.Low.to_numpy(float); RSI=b4.rsi14.to_numpy(float); BDATE=pd.to_datetime(b4.date).to_numpy()


def confirmed_price_pivots(left:int,right:int):
    out=[]
    n=len(LOW)
    for p in range(left,n-right):
        if not np.isfinite(LOW[p]) or not np.isfinite(RSI[p]):
            continue
        neigh=np.r_[LOW[p-left:p],LOW[p+1:p+right+1]]
        neigh=neigh[np.isfinite(neigh)]
        # Strict local low avoids duplicate flat-bottom pivots.
        if len(neigh)==left+right and LOW[p] < float(np.min(neigh)):
            out.append((p,p+right))
    return out


def div_signal(spec):
    piv=confirmed_price_pivots(spec['left'],spec['right'])
    sig=np.zeros(len(b4),bool); events=[]
    for j in range(1,len(piv)):
        p2,c2=piv[j]
        # Deterministic pairing: most recent prior confirmed pivot inside the allowed gap.
        chosen=None
        for k in range(j-1,-1,-1):
            p1,c1=piv[k]; gap=p2-p1
            if gap < spec['mingap']:
                continue
            if gap > spec['maxgap']:
                break
            chosen=(p1,c1); break
        if chosen is None:
            continue
        p1,c1=chosen
        l1,l2=float(LOW[p1]),float(LOW[p2]); r1,r2=float(RSI[p1]),float(RSI[p2])
        if not all(np.isfinite([l1,l2,r1,r2])): continue
        if spec['kind']=='REG':
            ok=(l2 <= l1*(1.0-spec['price_delta'])) and (r2 >= r1+spec['rsi_delta'])
        else: # hidden bullish: higher price low + lower RSI low
            ok=(l2 >= l1*(1.0+spec['price_delta'])) and (r2 <= r1-spec['rsi_delta'])
        if not ok: continue
        f=spec['filter']
        if f=='EITHER30': ok=min(r1,r2)<=30
        elif f=='SECOND30': ok=r2<=30
        elif f=='BOTH35': ok=max(r1,r2)<=35
        elif f=='ANY': ok=True
        else: raise ValueError(f)
        if not ok: continue
        # Confirmation signal. For RECROSS30, if RSI has already recovered above 30 by
        # confirmation, signal now; otherwise wait up to 6 completed 4H bars for the up-cross.
        emit=c2
        if spec.get('recross',False):
            emit=None
            if np.isfinite(RSI[c2]) and RSI[c2]>30:
                emit=c2
            else:
                for q in range(c2+1,min(c2+7,len(RSI))):
                    if np.isfinite(RSI[q]) and np.isfinite(RSI[q-1]) and RSI[q]>30 and RSI[q-1]<=30:
                        emit=q; break
            if emit is None: continue
        sig[emit]=True
        events.append({'signal_key':spec['key'],'kind':spec['kind'],'pivot1_i':p1,'pivot2_i':p2,'confirm_i':c2,'emit_i':emit,
                       'pivot1_date':str(pd.Timestamp(BDATE[p1]).date()),'pivot2_date':str(pd.Timestamp(BDATE[p2]).date()),
                       'confirm_date':str(pd.Timestamp(BDATE[c2]).date()),'signal_date':str(pd.Timestamp(BDATE[emit]).date()),
                       'confirm_delay_bars':int(c2-p2),'gap_bars':int(p2-p1),'price1':l1,'price2':l2,'rsi1':r1,'rsi2':r2})
    return sig,events

# A broad but structured parameter grid to test whether divergence has a stable plateau,
# not a single hand-picked pivot definition.
SIG4={}; SPEC4={}; EVENT_RAW=[]
for left,right in ((2,1),(2,2),(3,2),(3,3)):
  for maxgap in (20,30,40): # 10/15/20 sessions at two 4H bars per RTH session
    for rd in (0.0,2.0,4.0):
      for pdlt in (0.0,.0025):
        for filt in ('ANY','EITHER30','SECOND30','BOTH35'):
          key=f'REG_L{left}R{right}_G{maxgap}_RD{int(rd)}_P{int(pdlt*10000)}_{filt}'
          sp={'key':key,'kind':'REG','left':left,'right':right,'mingap':3,'maxgap':maxgap,'rsi_delta':rd,'price_delta':pdlt,'filter':filt,'recross':False}
          sg,ev=div_signal(sp); SIG4[key]=sg; SPEC4[key]=sp; EVENT_RAW+=ev
          if filt in ('EITHER30','SECOND30'):
              key2=key+'_X30'; sp2={**sp,'key':key2,'recross':True}; sg2,ev2=div_signal(sp2); SIG4[key2]=sg2; SPEC4[key2]=sp2; EVENT_RAW+=ev2
# Hidden bullish is tested separately and less aggressively to avoid an unnecessary grid explosion.
for left,right in ((2,2),(3,2)):
  for maxgap in (20,30,40):
    for rd in (0.0,2.0,4.0):
      for filt in ('ANY','EITHER30'):
        key=f'HID_L{left}R{right}_G{maxgap}_RD{int(rd)}_{filt}'
        sp={'key':key,'kind':'HID','left':left,'right':right,'mingap':3,'maxgap':maxgap,'rsi_delta':rd,'price_delta':0.0,'filter':filt,'recross':False}
        sg,ev=div_signal(sp); SIG4[key]=sg; SPEC4[key]=sp; EVENT_RAW+=ev

# Convert confirmed 4H signals to daily booleans. Multiple intraday signals on one day count once.
DIVDAY={}
for key,sg in SIG4.items():
    tmp=pd.Series(sg,index=pd.to_datetime(b4.date)).groupby(level=0).max().astype(bool)
    DIVDAY[key]=tmp.reindex(pd.DatetimeIndex(D).normalize()).fillna(False).to_numpy(bool)

# Baselines from Stage51: RSI30 touch early sleeve and validated daily runner.
cur0=current_trace(B0)
base_spec={'method':'touch30','gate':'ANY','floor':1.0,'maxd':10}
base_struct={'method':'touch30','gate':'STRUCT','floor':1.0,'maxd':10}
CANDS={'AGGR':target_aggr(B0,cur0),
       'DAILY_R10':daily_runner(B0,VX,cur0,None,False),
       'RSI30_ANY':rsi_overlay(B0,VX,SIG['touch30'],base_spec,cur0,None,False),
       'RSI30_STRUCT':rsi_overlay(B0,VX,SIG['touch30'],base_struct,cur0,None,False)}
META={}

# Historical scan. Every divergence candidate still requires a recent validated Crash seed
# inside rsi_overlay; divergence is an entry-timing refinement, not a standalone all-weather buy.
for key,sg in DIVDAY.items():
    for gate in ('ANY','STRUCT'):
      for floor in (.80,1.00):
        for md in (5,10):
          nm=f'{key}_{gate}_F{int(floor*100)}_D{md}'
          sp={'signal_key':key,'gate':gate,'floor':floor,'maxd':md}
          CANDS[nm]=rsi_overlay(B0,VX,sg,sp,cur0,None,False); META[nm]=sp

hist=[]
for nm,t in CANDS.items():
    m,_,_=from_target(B0,t,COST); pre=account_end(B0['ret'],t,COST,0.,D); aft=account_end(B0['ret'],t,COST,TAX,D)
    hist.append({'candidate':nm,**META.get(nm,{}),'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end'],'avg_exp':m['avg_exp'],'turnover':m['turnover']})
HIST=pd.DataFrame(hist); HIST.to_csv('tqqq_stage52_scan.csv',index=False)

# Select return leaders plus DD-frontier candidates and ensure each signal family is represented.
sel=['AGGR','DAILY_R10','RSI30_ANY','RSI30_STRUCT']
R=HIST[~HIST.candidate.isin(sel)].copy()
sel+=R.sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(14).candidate.tolist()
for cap in (.44,.45,.47,.49):
    sel+=R[R.pre_mdd>=-cap].sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(4).candidate.tolist()
# Best regular, regular+oversold, recross, and hidden candidate even if not in global top.
for token in ('REG_','EITHER30','_X30','HID_'):
    g=R[R.candidate.str.contains(token,regex=False)]
    if len(g): sel+=g.sort_values(['tax_cagr','pre_mdd'],ascending=[False,False]).head(3).candidate.tolist()
sel=list(dict.fromkeys(sel)); print('[selected52]',len(sel),sel,flush=True)

# Subperiod and cost stability.
PER=[('2011-2018',2011,2018),('2019-2022',2019,2022),('2023-2026',2023,2026)]
sub=[]; costs=[]
for nm in sel:
    t=CANDS[nm]
    for lab,a,b in PER:
        ix=np.flatnonzero((YY51>=a)&(YY51<=b)); dd=D.iloc[ix].reset_index(drop=True)
        pre=account_end(B0['ret'][ix],t[ix],COST,0.,dd); aft=account_end(B0['ret'][ix],t[ix],COST,TAX,dd)
        sub.append({'candidate':nm,'period':lab,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr']})
    for bps in (5,10,20):
        cc=bps/10000.; pre=account_end(B0['ret'],t,cc,0.,D); aft=account_end(B0['ret'],t,cc,TAX,D)
        costs.append({'candidate':nm,'cost_bps':bps,'pre_cagr':pre['cagr'],'pre_mdd':pre['mdd'],'tax_cagr':aft['cagr'],'tax_end':aft['end']})
pd.DataFrame(sub).to_csv('tqqq_stage52_subperiods.csv',index=False); pd.DataFrame(costs).to_csv('tqqq_stage52_costs.csv',index=False)

# Event study for selected unique signals, plus RSI30 baseline. All events require recent Crash seed.
seed0=seed_arr(B0,VX); recentseed=np.zeros(len(seed0),bool); age=10**9
for i in range(len(seed0)): age=0 if seed0[i] else age+1; recentseed[i]=age<=SPEC['lookback']
tqO=tq.Open.astype(float).copy(); tqO.index=pd.DatetimeIndex(tqO.index).tz_localize(None).normalize(); tqL=tq.Low.astype(float).copy(); tqL.index=pd.DatetimeIndex(tqL.index).tz_localize(None).normalize(); tqH=tq.High.astype(float).copy(); tqH.index=pd.DatetimeIndex(tqH.index).tz_localize(None).normalize()
O=tqO.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float); LW=tqL.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float); HW=tqH.reindex(pd.DatetimeIndex(D).normalize()).to_numpy(float)

def clustered(mask,gap=5):
    z=np.flatnonzero(mask); out=[]; last=-10**9
    for i in z:
        if i-last>gap: out.append(int(i)); last=int(i)
    return out

sigkeys={'RSI30_TOUCH':'touch30'}
for nm in sel:
    if nm in META: sigkeys[META[nm]['signal_key']]=META[nm]['signal_key']
evrows=[]
for label,key in sigkeys.items():
    sg=SIG['touch30'] if key=='touch30' else DIVDAY[key]
    mask=sg&recentseed
    for i in clustered(mask,5):
        j=i+1
        if j>=len(O) or not np.isfinite(O[j]): continue
        row={'signal':label,'signal_date':str(pd.Timestamp(D.iloc[i]).date()),'entry_date':str(pd.Timestamp(D.iloc[j]).date()),'entry_open':O[j]}
        for h in (1,3,5,10,20,40):
            k=min(j+h,len(O)-1); row[f'ret_{h}d']=float(O[k]/O[j]-1) if np.isfinite(O[k]) else np.nan
            sl=slice(j,min(j+h+1,len(O))); row[f'mae_{h}d']=float(np.nanmin(LW[sl])/O[j]-1); row[f'mfe_{h}d']=float(np.nanmax(HW[sl])/O[j]-1)
        evrows.append(row)
EV=pd.DataFrame(evrows); EV.to_csv('tqqq_stage52_event_study.csv',index=False)
EVS=[]
for nm,g in EV.groupby('signal'):
    z={'signal':nm,'n':len(g)}
    for h in (1,3,5,10,20,40):
        z[f'ret_{h}d_med']=float(g[f'ret_{h}d'].median()); z[f'pwin_{h}d']=float((g[f'ret_{h}d']>0).mean()); z[f'mae_{h}d_med']=float(g[f'mae_{h}d'].median()); z[f'mfe_{h}d_med']=float(g[f'mfe_{h}d'].median())
    EVS.append(z)
EVS=pd.DataFrame(EVS); EVS.to_csv('tqqq_stage52_event_summary.csv',index=False)

# Matched 10-year moving-block bootstrap. Reset runner/early-sleeve state at each synthetic
# block boundary. Precomputed divergence flags travel with their source blocks, so no pivot is
# invented across synthetic joins.
N=len(B0['ret']); nb=int(np.ceil(H/BLOCK)); offs=np.arange(BLOCK); rng=np.random.default_rng(SEED52)
starts=rng.integers(0,N-BLOCK+1,size=(NSIM,nb)); paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:H]; bounds=list(range(BLOCK,H,BLOCK))
mc=[]
for z in range(NSIM):
    ix=paths[z]; B={k:B0[k][ix].copy() for k in KEYS}; vx=VX[ix].copy(); cur=current_trace(B)
    tg={'AGGR':target_aggr(B,cur),'DAILY_R10':daily_runner(B,vx,cur,bounds,False),
        'RSI30_ANY':rsi_overlay(B,vx,SIG['touch30'][ix].copy(),base_spec,cur,bounds,False),
        'RSI30_STRUCT':rsi_overlay(B,vx,SIG['touch30'][ix].copy(),base_struct,cur,bounds,False)}
    for nm in sel:
        if nm in tg: continue
        sp=META[nm]; sg=DIVDAY[sp['signal_key']][ix].copy(); tg[nm]=rsi_overlay(B,vx,sg,sp,cur,bounds,False)
    for nm,t in tg.items():
        pre=account_end(B['ret'],t,COST,0.,None); aft=account_end(B['ret'],t,COST,TAX,None)
        mc.append({'sim':z,'candidate':nm,'tax_end':aft['end'],'tax_cagr':aft['cagr'],'pre_mdd':pre['mdd']})
    if (z+1)%50==0: print('[mc52]',z+1,'/',NSIM,flush=True)
MC=pd.DataFrame(mc); MC.to_csv('tqqq_stage52_mc.csv',index=False)
def q(a,p): return float(np.quantile(np.asarray(a,float),p))
sm=[]
for nm,g in MC.groupby('candidate'):
    sm.append({'candidate':nm,'tax_end_mean':float(g.tax_end.mean()),'tax_end_median':q(g.tax_end,.5),'tax_end_p05':q(g.tax_end,.05),'tax_cagr_median':q(g.tax_cagr,.5),'tax_cagr_p05':q(g.tax_cagr,.05),'mdd_median':q(g.pre_mdd,.5),'mdd_p05':q(g.pre_mdd,.05),'p_tax30':float(np.mean(g.tax_cagr>=.30))})
SUM=pd.DataFrame(sm); SUM.to_csv('tqqq_stage52_mc_summary.csv',index=False)
p=MC.pivot(index='sim',columns='candidate',values=['tax_end','pre_mdd']); pair=[]
for nm in sel:
    if nm=='RSI30_ANY': continue
    ratio=p[('tax_end',nm)]/p[('tax_end','RSI30_ANY')]; dm=p[('pre_mdd',nm)]-p[('pre_mdd','RSI30_ANY')]
    pair.append({'candidate':nm,'p_end_better_rsi30':float(np.mean(ratio>1)),'median_ratio_vs_rsi30':float(np.median(ratio)),'p05_ratio_vs_rsi30':q(ratio,.05),'p_mdd_no_worse_rsi30':float(np.mean(dm>=0)),'mdd_delta_median':float(np.median(dm))})
PAIR=pd.DataFrame(pair); PAIR.to_csv('tqqq_stage52_pairwise.csv',index=False)
FINAL=HIST[HIST.candidate.isin(sel)].merge(SUM,on='candidate',how='left').merge(PAIR,on='candidate',how='left').sort_values('tax_end_mean',ascending=False)
FINAL.to_csv('tqqq_stage52_final_rank.csv',index=False)

# Save raw confirmed divergence events for a direct lookahead audit.
pd.DataFrame(EVENT_RAW).drop_duplicates().to_csv('tqqq_stage52_divergence_events_raw.csv',index=False)
out={'quality':QUALITY,'coverage':{'start':str(pd.Timestamp(D.iloc[0]).date()),'end':str(pd.Timestamp(D.iloc[-1]).date()),'days':int(len(D))},
     'selected':sel,'event_summary':EVS.to_dict('records'),'final':FINAL.to_dict('records'),
     'notes':['Regular bullish divergence = confirmed lower price pivot low with higher RSI14 at the second price pivot.','Hidden bullish divergence = confirmed higher price pivot low with lower RSI14.','Pivot signal date is p+right after the required future bars have closed; portfolio entry is next session open. No pivot is backdated to p.','All divergence early sleeves still require the Stage51 recent Crash seed: VIX close>=23, QQQ SMA50 ATR distance<=-0.5, 10d drawdown<=-2% within 30 sessions.','RSI14 uses Wilder RMA on the same 4H RTH bars as Stage51.'],
     'caveats':['Intraday QQQ source is the same public third-party dataset audited in Stage51; quality metrics are carried forward.','RTH 4H construction is 09:30-13:30 plus a 13:30-16:00 partial second bar; TradingView bar partition may differ.','Intraday coverage ends 2026-03-20.','MC57 PIT/survivorship audit unresolved.','NQSAR historical state is proxy.','USDJPY/dividend tax not modeled.','Moving-block bootstrap is not a forecast probability distribution.']}
Path('tqqq_stage52_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print('\n=== HIST TOP ==='); print(HIST.sort_values('tax_cagr',ascending=False).head(25).to_string(index=False))
print('\n=== EVENT SUMMARY ==='); print(EVS.to_string(index=False))
print('\n=== FINAL ==='); print(FINAL.to_string(index=False))
print('\n=== PAIRWISE VS RSI30 ==='); print(PAIR.to_string(index=False))
