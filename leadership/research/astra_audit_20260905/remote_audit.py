"""Read-only source audit. All writes are confined to the research output directory.

Legacy reproduction and a separate causal open-book sensitivity are never ranked together.
The latter retains virtual source-sleeve position decisions, so it is a funded daily
replication experiment, NOT a fully feedback-coupled production implementation.
"""
from pathlib import Path
import sys, json, inspect, hashlib, pickle, gzip, platform, copy, subprocess
import numpy as np
import pandas as pd

ROOT=Path('research_source'); OUT=Path('audit_output');OUT.mkdir(exist_ok=True)
sys.path[:0]=[str(ROOT),str(ROOT/'leadership/research')]
import audit_gross100_ddv_refill_mode as ddv
import audit_gross100_component_series as comp
import audit_gross100_final_reset_component_series as fr
import audit_gross100_early_slot_overlay as early
import audit_gross100_early1_promotion as promotion
import audit_gross100_early1_liq_aligned as aligned
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_staged_leader_liquidity_return as stage
import audit_gross100_allocation as ga

def clean(v):
 if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
 if isinstance(v,(list,tuple,np.ndarray)):return [clean(x) for x in v]
 if isinstance(v,(np.integer,)):return int(v)
 if isinstance(v,(float,np.floating)):return float(v) if np.isfinite(v) else None
 if isinstance(v,(np.bool_,)):return bool(v)
 if isinstance(v,(pd.Timestamp,)):return str(v)
 return v
def save(name,value):
 (OUT/name).write_text(json.dumps(clean(value),ensure_ascii=False,indent=2))
def metrics(r):
 r=np.asarray(r,float);r=r[np.isfinite(r)]
 if not len(r):return {'n':0}
 eq=np.r_[1.,np.cumprod(1+r)];dd=eq/np.maximum.accumulate(eq)-1
 cagr=eq[-1]**(252/len(r))-1 if eq[-1]>0 else -1
 sd=np.std(r,ddof=1);down=np.sqrt(np.mean(np.minimum(r,0)**2))
 return dict(n=len(r),cagr=cagr,mdd=dd.min(),sharpe=np.sqrt(252)*r.mean()/sd if sd else None,
  sortino=np.sqrt(252)*r.mean()/down if down else None,calmar=cagr/abs(dd.min()) if dd.min()<0 else None,
  daily_pf=r[r>0].sum()/-r[r<0].sum() if (r<0).any() else None)
def periods(dates,r):
 dates=pd.DatetimeIndex(dates);periods=[('FULL','2016-01-01','2026-03-20'),('2016_2020','2016-01-01','2020-12-31'),('2021_2025','2021-01-01','2025-12-31'),('2022_2025','2022-01-01','2025-12-31'),('2022_2026_AVAILABLE','2022-01-01','2026-03-20')]
 periods += [(str(y),f'{y}-01-01',f'{y}-12-31') for y in sorted(set(dates.year))]
 return [{ 'period':label,**metrics(np.asarray(r)[(dates>=a)&(dates<=b)])} for label,a,b in periods]

TRACE=[]
def traced(fn,module,reset=False):
 src=inspect.getsource(fn)
 needle='        gross = 0.0\n        nav = cash'
 if src.count(needle)!=1:raise RuntimeError('TRACE injection guard '+fn.__name__)
 if reset:
  expr="[(z['symbol'],z['shares'],'RESET') for z in lots]"
 else:
  expr="[(s,z['shares'],z.get('sleeve','CORE')) for s,z in pos.items()]"
 ins=f'''        _snap=[]
        _open_nav=cash
        for _s,_sh,_layer in {expr}:
            _op=_px(opens,d,_s)
            if _op is None:
                _op=_px(closes,d,_s)
                _missing=True
            else:
                _missing=False
            if _op is not None:
                _value=_sh*_op
                _open_nav+=_value
                _snap.append([_s,_value,_layer,_missing])
        TRACE.append(dict(date=str(d.date()),open_nav=_open_nav,positions=[[_s,_v/_open_nav,_l,_m] for _s,_v,_l,_m in _snap]))
'''
 ns=dict(module.__dict__);ns['TRACE']=TRACE
 exec(src.replace(needle,ins+needle),ns)
 return ns[fn.__name__]

print('ASTRA BUILD LOCKED INPUTS',flush=True)
meta,m=ex.build_inputs_ext(ROOT,'2016-01-04','2026-03-20',6000,75)
peer=loo.build_leave_one_out_scores(ROOT,m)
ctx=stage.build_signal_context(ROOT,m);aligned.add_aligned_scores(ctx,m)
ca,cs,ec=stage.precompute_candidates(meta,m,peer,ctx)
cal=pd.DatetimeIndex(meta['analysis_idx'])
rt=fr.prepare_final_reset_trades(Path('frozen/reset/threshold_trade_rows.csv.gz'),cal,m['close'].columns)
TRACE.clear();reset,reset_turn=traced(comp.simulate_reset,comp,True)(cal,m['open'],m['close'],rt);rtrace=copy.deepcopy(TRACE)
reset.to_csv(OUT/'reset_daily.csv.gz',index=False,compression='gzip')
tq=pd.read_csv('frozen/tqqq/tqqq_stage56_daily.csv.gz');tq['date']=pd.to_datetime(tq.date)
manifest={'source_sha':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
 'python':platform.python_version(),'packages':{x:__import__(x).__version__ for x in ('pandas','numpy','scipy','yfinance')},
 'meta':{k:v for k,v in meta.items() if k not in ('analysis_idx','breadth','nq')},
 'start':cal[0],'end':cal[-1],'calendar_n':len(cal),'universe':list(m['close'].columns),
 'source_files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.rglob('*.py')},
 'fixed_inputs':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('frozen').rglob('*.gz')},
 'pit_warning':'Historical universe and theme membership are current static source snapshots; not survivorship-free PIT.'}
save('input_manifest.json',manifest)
with gzip.open(OUT/'frozen_research_inputs.pkl.gz','wb') as f:pickle.dump((meta,m,peer,ctx,ca,cs,ec),f,protocol=5)

variants={};traces={};diags={}
for label,floor,mode in [('CORE_DDV10',1e7,'VACANCY_TOP12'),('EARLY0',2e7,'VACANCY_TOP12'),('CORE_DDV50',5e7,'VACANCY_TOP12'),('CORE_DDV20_REFILL',2e7,'REFILL_TOP40')]:
 print('SIM',label,flush=True);TRACE.clear()
 variants[label],diags[label]=traced(ddv.simulate_ordinary_mode,ddv)(meta,m,peer,floor,mode);traces[label]=copy.deepcopy(TRACE)
for label,slots,score in [('EARLY1',1,'RS21_HIGH_ACCEL'),('EARLY2',2,'RS21_HIGH_ACCEL'),('EARLY1_LEGACY_LIQ',1,'LEGACY_LIQ_ACCEL'),('EARLY1_CURRENT_LIQ',1,'CURRENT_LIQ_ACCEL_PORT')]:
 print('SIM',label,flush=True);early.EARLY_SCORE=score;TRACE.clear()
 variants[label],diags[label]=traced(early.simulate_early_overlay,early)(slots,meta,m,ca,cs,ec);traces[label]=copy.deepcopy(TRACE)
early.EARLY_SCORE='RS21_HIGH_ACCEL'
variants['NO_PROMOTE'],diags['NO_PROMOTE']=promotion.no_promotion_simulator()(1,meta,m,ca,cs,ec)

legacy_rows=[];legacy_returns={}
for label,ordinary in variants.items():
 ordinary.to_csv(OUT/f'ordinary_{label}.csv.gz',index=False,compression='gzip')
 rets,perf,diag=ddv.combine_one(ordinary,reset,tq,'target_M30_TOUCH30_F80_D10')
 dates=ordinary[['date']].merge(reset[['date']],on='date').merge(tq[['date']],on='date').date
 for key,r in rets.items():
  for row in periods(dates,r):legacy_rows.append(dict(engine='LEGACY_GROSS100',variant=label,timing=key[0],cost=key[1],policy=key[2],**row))
 legacy_returns[label]=rets[('SAME_DAY_GROSS','BASE','SELECTIVE_FILL_NO_ZERO_OVERRIDE')]
 pd.DataFrame({'date':dates,**{'|'.join(k):v for k,v in rets.items()}}).to_csv(OUT/f'legacy_returns_{label}.csv.gz',index=False,compression='gzip')
 legacy_exact=perf.loc[(perf.timing=='SAME_DAY_GROSS')&(perf.cost=='BASE')&(perf.policy=='SELECTIVE_FILL_NO_ZERO_OVERRIDE')].to_dict('records')
 print('LEGACY_EXACT',label,json.dumps(clean(legacy_exact)),flush=True)
pd.DataFrame(legacy_rows).to_csv(OUT/'legacy_periods.csv',index=False)
save('diagnostics.json',diags)

# Separate causal daily-open replication. All holdings earn the next open return
# before the next rebalance. Turnover is security-level after price drift.
op=m['open'].reindex(cal);cl=m['close'].reindex(cal)
price=op.copy();bad=price.isna()|price.le(0)
# A missing future open is explicitly flagged; carried preceding close is a
# sensitivity fallback, not an asserted executable quote.
price=price.mask(bad,cl.shift(1));next_r=price.shift(-1)/price-1
tq=tq.set_index('date').reindex(cal)
native=tq['target_M30_TOUCH30_F80_D10'].shift(1).fillna(0)
# Artifact return row t+1 is open[t+1]/open[t]-1.
tr=tq['tqqq_ret_usd'].shift(-1).fillna(0)
save('trace_reset.json',rtrace)
cash_results=[];cash_returns={};trade_summaries=[]
for label,trace in traces.items():
 save('trace_'+label+'.json',trace)
 for bps in [0,5,10,20]:
  old={};ret=[];turn=[];missing=0
  for i in range(len(cal)-1):
   ow={s:w for s,w,l,miss in trace[i]['positions']};rw={s:w for s,w,l,miss in rtrace[i]['positions']}
   go=sum(ow.values());gr=sum(rw.values());g=np.array([[native.iloc[i],min(go,.70),gr]])
   gate=bool(variants[label].iloc[i].selective_fill_allowed)
   at,ao,ar=ga.selective_fill_no_zero_override(g,np.array([gate]))[0]
   w={'TQQQ_ETF':at}
   for s,v in ow.items():w[s]=w.get(s,0)+v*(ao/go if go else 0)
   for s,v in rw.items():w[s]=w.get(s,0)+v*(ar/gr if gr else 0)
   assert sum(w.values())<=1+1e-8
   t=sum(abs(w.get(s,0)-old.get(s,0)) for s in set(w)|set(old))
   returns={s:(tr.iloc[i] if s=='TQQQ_ETF' else next_r.at[cal[i],s]) for s in w}
   for s,r in returns.items():
    if not np.isfinite(r):missing+=1;returns[s]=0.
   gain=sum(w[s]*returns[s] for s in w);cost=t*bps/10000
   rr=gain-cost;ret.append(rr);turn.append(t)
   old={s:w[s]*(1+returns[s])/(1+rr) for s in w}
  rr=np.asarray(ret);cash_returns[(label,bps)]=rr
  for row in periods(cal[:-1],rr):cash_results.append(dict(engine='CAUSAL_OPEN_REPLICATION',variant=label,cost_bps=bps,**row))
  trade_summaries.append(dict(variant=label,cost_bps=bps,turnover_total=sum(turn),turnover_per_year=sum(turn)/(len(ret)/252),missing_returns=missing))
  pd.DataFrame(dict(date=cal[:-1],return_net=rr,turnover=turn)).to_csv(OUT/f'causal_{label}_{bps}bp.csv.gz',index=False,compression='gzip')
pd.DataFrame(cash_results).to_csv(OUT/'causal_periods.csv',index=False);save('causal_turnover.json',trade_summaries)

boots=[]
for engine,source in [('LEGACY_GROSS100',legacy_returns),('CAUSAL_OPEN_REPLICATION',{k[0]:v for k,v in cash_returns.items() if k[1]==5})]:
 for candidate in ['EARLY1','CORE_DDV10','CORE_DDV50','EARLY2']:
  if candidate not in source:continue
  for block in [20,60]:boots.append(dict(engine=engine,a=candidate,b='EARLY0',**ga.block_boot_pair(source[candidate],source['EARLY0'],block,5000,20260905+block)))
save('bootstrap.json',boots)
save('summary.json',dict(status='RESEARCH_ONLY_AUDIT_COMPLETE',source_manifest='input_manifest.json',
 legacy_full=[r for r in legacy_rows if r['period']=='FULL' and r['timing']=='SAME_DAY_GROSS' and r['cost']=='BASE' and r['policy']=='SELECTIVE_FILL_NO_ZERO_OVERRIDE'],
 causal_full=[r for r in cash_results if r['period']=='FULL' and r['cost_bps']==5],
 bootstrap=boots,
 limits=['Causal replication uses virtual independent-sleeve decisions; not full feedback-coupled production.',
 'New 2026 history is not new OOS. Fixed Stage56 ends 2026-03-20.',
 'Static universe/theme snapshots are not true PIT.','Native W30 is a dashboard stock signal; no implicit 150-day substitution.']))
print('ASTRA_FINAL_JSON', (OUT/'summary.json').read_text(),flush=True)
