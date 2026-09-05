"""Frozen-input attribution; no production execution or writes."""
from pathlib import Path
import ast,gzip,pickle,json,sys,hashlib
import numpy as np
import pandas as pd
import yfinance as yf
SRC=Path('research_source'); BASE=Path('frozen/audit'); OUT=Path('followup_output');OUT.mkdir(exist_ok=True)
sys.path[:0]=[str(SRC),str(SRC/'leadership/research')]
import audit_gross100_allocation as ga
with gzip.open(BASE/'frozen_research_inputs.pkl.gz','rb') as f:meta,m,peer,ctx,ca,cs,ec=pickle.load(f)
cal=pd.DatetimeIndex(meta['analysis_idx']);dates=cal[:-1]
def save(name,x):
 (OUT/name).write_text(json.dumps(x,indent=2,default=str,allow_nan=True))
def metrics(r):
 r=np.asarray(r,float);eq=np.r_[1,np.cumprod(1+r)];dd=eq/np.maximum.accumulate(eq)-1;c=eq[-1]**(252/len(r))-1
 return dict(n=len(r),cagr=c,mdd=dd.min(),sharpe=np.sqrt(252)*r.mean()/r.std(ddof=1),sortino=np.sqrt(252)*r.mean()/np.sqrt(np.mean(np.minimum(r,0)**2)),calmar=c/abs(dd.min()),daily_pf=r[r>0].sum()/-r[r<0].sum())
def period_rows(label,r):
 cuts=[('FULL','2016-01-01','2026-03-20'),('2016_2020','2016-01-01','2020-12-31'),('2021_2025','2021-01-01','2025-12-31'),('2022_2025','2022-01-01','2025-12-31'),('2022_2026_AVAILABLE','2022-01-01','2026-03-20')]+[(str(y),f'{y}-01-01',f'{y}-12-31') for y in range(2016,2027)]
 return [dict(variant=label,period=p,**metrics(np.asarray(r)[(dates>=a)&(dates<=b)])) for p,a,b in cuts]
ns={'pd':pd,'np':np}
source=Path('dashboard_source/build_dashboard.py').read_text();tree=ast.parse(source)
names={'_drop_unconfirmed_week','w30_breakout','weinstein_stage','W30X','W30X_SCORE','W30X_PB','W30X_RESUME_STAR','W30X_ENTRY','W30X_EXIT'}
nodes=[n for n in tree.body if (getattr(n,'name','') in names or isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in names)]
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'native_w30','exec'),ns)
daily={}
for sym in ['QQQ','SPY','^IXIC','^VIX']:
 z=yf.download(sym,start='2009-01-01',end='2026-09-05',auto_adjust=True,progress=False,threads=False)
 if isinstance(z.columns,pd.MultiIndex):z=z.xs(sym,axis=1,level=1)
 z=z.dropna(subset=['Close']);daily[sym]=z;z.to_csv(OUT/('index_'+sym.replace('^','')+'.csv.gz'),compression='gzip')
 if len(z)<2500:raise RuntimeError('index coverage '+sym)
def weekly_state(c):
 w=c.resample('W-FRI').last().dropna();ma=w.rolling(30).mean();s=pd.DataFrame({'above':w>ma,'below':w<=ma,'rising':ma>=ma.shift(4),'falling':ma<ma.shift(4)})
 s['cross_up']=s.above&~s.above.shift(1,fill_value=False);s['cross_down']=s.below&~s.below.shift(1,fill_value=False)
 st=s.reindex(s.index.union(c.index)).sort_index().ffill().reindex(c.index)
 obs=pd.Series(w.index,index=w.index).reindex(w.index.union(c.index)).sort_index().ffill().reindex(c.index);first=obs.ne(obs.shift(1))
 st['cross_up']&=first;st['cross_down']&=first
 return st
forward=[]
for sym in ['QQQ','SPY','^IXIC']:
 z=daily[sym];c=z.Close;st=weekly_state(c);st=st.loc['2016-01-01':'2026-09-04']
 native=[]
 for d in st.index:native.append(dict(date=d,**ns['w30_breakout'](c.loc[:d],low=z.Low.loc[:d],high=z.High.loc[:d])))
 st=st.join(pd.DataFrame(native).set_index('date'))
 for k in ['NEW','ADV','PB','RESUME','STALL','DEAD']:
  v=st.w30x_status.eq(k);st['native_'+k]=v&~v.shift(1,fill_value=False)
 for k in ['FULL','POS','PARTP','PARTM','CROSS','WEAK']:st['grade_'+k]=st.w30x_grade.eq(k)&st.cross_up
 st['bull']=(c>c.rolling(200).mean())&(c.rolling(200).mean()>c.rolling(200).mean().shift(20));st['bear']=c<c.rolling(200).mean();st['sideways']=~st.bull&~st.bear
 st['high_vix']=daily['^VIX'].Close.reindex(st.index).ffill()>=23;st['low_vix']=daily['^VIX'].Close.reindex(st.index).ffill()<20
 nq=meta['nq']['nq_color'].reindex(st.index).ffill(limit=1);br=meta['breadth'].reindex(st.index)
 regimes={'ALL':pd.Series(True,index=st.index),**{k:st[k] for k in ['bull','bear','sideways','high_vix','low_vix']},**{'NQSAR_'+k:nq.eq(k) for k in ['Blue','Green','Yellow','Red']},'breadth_lt50':br<50,'breadth_50_60':(br>=50)&(br<60),'breadth_ge60':br>=60}
 for sig in ['above','below','cross_up','cross_down','rising','falling']+[k for k in st if k.startswith(('native_','grade_'))]:
  for reg,mask in regimes.items():
   for h in [5,10,20,40,60,126]:
    fr=(c.shift(-h)/c-1).reindex(st.index);v=fr[st[sig].fillna(False)&mask.fillna(False)].dropna();un=fr[mask.fillna(False)].dropna()
    forward.append(dict(symbol=sym,signal=sig,regime=reg,horizon=h,n=len(v),mean=v.mean(),median=v.median(),win=(v>0).mean(),unconditional_mean=un.mean()))
 st.to_csv(OUT/('w30_states_'+sym.replace('^','')+'.csv.gz'),compression='gzip');print('W30',sym,flush=True)
pd.DataFrame(forward).to_csv(OUT/'w30_forward_returns.csv',index=False)
tq=pd.read_csv('frozen/tqqq/tqqq_stage56_daily.csv.gz',parse_dates=['date']).set_index('date').reindex(cal)
native=tq.target_M30_TOUCH30_F80_D10.shift(1).fillna(0);tr=tq.tqqq_ret_usd.shift(-1).fillna(0)
trace=json.loads((BASE/'trace_EARLY1.json').read_text());reset=json.loads((BASE/'trace_reset.json').read_text());ordinary=pd.read_csv(BASE/'ordinary_EARLY1.csv.gz')
syms=sorted({p[0] for t in trace+reset for p in t['positions']});cols=syms+['TQQQ_ETF'];loc={s:i for i,s in enumerate(cols)}
price=m['open'][syms].reindex(cal);bad=price.isna()|price.le(0);price=price.mask(bad,m['close'][syms].reindex(cal).shift(1))
rets=price.shift(-1)/price-1;rets['TQQQ_ETF']=tr;R=rets.iloc[:-1].to_numpy();R=np.nan_to_num(R,nan=0.)
layers={k:np.zeros((len(dates),len(cols))) for k in ['CORE','EARLY','RESET','TQQQ']};missing=0
for i in range(len(dates)):
 go=sum(p[1] for p in trace[i]['positions']);gr=sum(p[1] for p in reset[i]['positions']);g=np.array([[native.iloc[i],min(go,.7),gr]])
 at,ao,ar=ga.selective_fill_no_zero_override(g,np.array([bool(ordinary.iloc[i].selective_fill_allowed)]))[0]
 layers['TQQQ'][i,-1]=at
 for s,v,l,miss in trace[i]['positions']:layers[l][i,loc[s]]+=v*(ao/go if go else 0);missing+=int(miss)
 for s,v,l,miss in reset[i]['positions']:layers['RESET'][i,loc[s]]+=v*(ar/gr if gr else 0);missing+=int(miss)
W=sum(layers.values())
def run(w,bps=5):
 old=np.zeros(len(cols));rr=[];turn=[];count=[]
 for i in range(len(dates)):
  change=np.abs(w[i]-old);t=change.sum();r=(w[i]*R[i]).sum()-t*bps/10000
  rr.append(r);turn.append(t);count.append(int((change>1e-8).sum()));old=w[i]*(1+R[i])/(1+r)
 return np.array(rr),sum(turn)/(len(dates)/252),sum(count)/(len(dates)/252)
base,_,_=run(W);previous=pd.read_csv(BASE/'causal_EARLY1_5bp.csv.gz').return_net.to_numpy();assert np.max(np.abs(base-previous))<1e-11
variants={'BASE':W,**{'WITHOUT_'+k:W-v for k,v in layers.items()},**{'ONLY_'+k:v for k,v in layers.items()}}
qq=weekly_state(daily['QQQ'].Close).reindex(cal).ffill().shift(1)
variants['QQQ_W30_ABOVE_ALL']=W*qq.above.iloc[:-1].fillna(False).to_numpy()[:,None]
variants['QQQ_W30_ABOVE_TQQQ']=W-layers['TQQQ']+layers['TQQQ']*qq.above.iloc[:-1].fillna(False).to_numpy()[:,None]
variants['QQQ_W30_RISING_TQQQ']=W-layers['TQQQ']+layers['TQQQ']*qq.rising.iloc[:-1].fillna(False).to_numpy()[:,None]
stockmask=np.ones_like(W)
for s in syms:stockmask[:,loc[s]]=weekly_state(m['close'][s].dropna()).above.reindex(m['close'].index).ffill().reindex(cal).shift(1).iloc[:-1].fillna(False)
variants['STOCK_OWN_W30_ABOVE_CORE_EARLY']=layers['RESET']+layers['TQQQ']+(layers['CORE']+layers['EARLY'])*stockmask
variants['ALL_TARGETS_DELAY_1']=np.vstack([np.zeros(len(cols)),W[:-1]])
rows=[];series={};boots=[]
for label,w in variants.items():
 r,t,n=run(w);series[label]=r;pr=period_rows(label,r)
 for x in pr:x.update(engine='CAUSAL_OPEN_REPLICATION_ABLATION',turnover_per_year_full=t,security_rebalances_per_year_full=n)
 rows+=pr
 if label.startswith(('QQQ_','STOCK_','ALL_')):
  for block in [20,60]:boots.append(dict(variant=label,**ga.block_boot_pair(r,base,block,3000,20260905+block)))
pd.DataFrame(rows).to_csv(OUT/'attribution_periods.csv',index=False);pd.DataFrame({'date':dates,**series}).to_csv(OUT/'attribution_returns.csv.gz',index=False,compression='gzip');save('overlay_bootstrap.json',boots)
rng=np.random.default_rng(20260905);yearboots=[]
for label in ['EARLY1','EARLY0','CORE_DDV10','EARLY2']:
 a=pd.read_csv(BASE/f'causal_{label}_5bp.csv.gz',parse_dates=['date']);b=pd.read_csv(BASE/'causal_EARLY0_5bp.csv.gz');keep=a.date.dt.year<=2025;aa=a.return_net[keep].to_numpy();bb=b.return_net[keep].to_numpy();yy=a.date[keep].dt.year.to_numpy();groups=[np.flatnonzero(yy==y) for y in sorted(set(yy))];diff=[]
 for _ in range(5000):
  idx=np.concatenate([groups[j] for j in rng.integers(0,len(groups),len(groups))]);diff.append(metrics(aa[idx])['cagr']-metrics(bb[idx])['cagr'])
 yearboots.append(dict(variant=label,baseline='EARLY0',years=10,p_gt0=float(np.mean(np.array(diff)>0)),p05=float(np.quantile(diff,.05)),p95=float(np.quantile(diff,.95))))
save('year_cluster.json',yearboots)
qc={'universe_columns':len(m['close'].columns),'all_nan_symbols':list(m['close'].columns[m['close'].notna().sum()==0]),'trace_same_day_close_fallbacks':missing,'base_reproduction_max_abs_error':float(np.max(np.abs(base-previous))),'frozen_input_sha256':hashlib.sha256((BASE/'frozen_research_inputs.pkl.gz').read_bytes()).hexdigest(),'held_next_open_missing_count':int(sum(((bad.shift(-1).iloc[:-1].to_numpy()) & (W[:,:-1]>0)).sum(axis=0)))}
qc['annual_coverage']=[dict(year=int(y),median_symbols_with_close=int(m['close'].loc[str(y)].notna().sum(axis=1).median())) for y in range(2016,2027)]
save('quality.json',qc)
save('limits.json',['Ablations remove funded positions to cash without reallocation or feedback; not causal additive CAGR contributions.','W30 overlays are new hypotheses on native exact weekly SMA30; Dashboard does not currently apply them to exposure.','One-day delay shifts all targets, not only new entries.','PF is daily return PF; trade-level PF and symbol-cluster inference require separate trade reconstruction.','Frozen static universe/theme classifications are not historical PIT; current downloaded indices are frozen separately.','NQSAR/breadth strata stop at March20 for frozen portfolio data; index returns continue through September4.','No threshold or week-length optimization; no new OOS claim.'])
print('FOLLOWUP_DONE',json.dumps(qc),flush=True)
