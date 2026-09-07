from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive
from research import audit_stock_nqsar_theme30_pit as audit
from research import run_stock_nqsar_theme30_pit_fast as fast
from research import preimpl_core11_early1_pit as pit
from research import stock_nqsar_centric_scan as scan

END=audit.ANALYSIS_END

def rank_spec(d,mx,x,variant):
    wb=mx['week_bull'].loc[d].fillna(False); db=mx['day_bull'].loc[d].fillna(False); mr=mx['month_red'].loc[d].fillna(False); rs189=pd.to_numeric(mx['rs189'].loc[d],errors='coerce'); rs63=pd.to_numeric(mx['rs63'].loc[d],errors='coerce'); cur=mx['eligible'].loc[d].fillna(False); base=x['base'].loc[d].fillna(False); struct=x['struct'].loc[d].fillna(False); rs85=x['rs85'].loc[d].fillna(False); fresh=x['fresh10'].loc[d].fillna(False); col=x['week_color'].loc[d]
    if variant=='BASE_WEEK_PRIORITY': return cur,rs189,lambda s,sc:(bool(wb[s]),float(sc[s]))
    if variant=='WEEK_GATE_CURRENT': return cur&wb,rs189,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_PURE_RS189': return base&wb,rs189,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_PURE_RS63': return base&wb,rs63,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_PURE_BLEND': return base&wb,.5*rs189+.5*rs63,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_RS85_NO_SMA': return base&wb&rs85,rs189,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_STRUCT_NO_RS': return struct&wb,rs189,lambda s,sc:(float(sc[s]),)
    if variant=='NQ_FRESH10': return cur&wb,rs189,lambda s,sc:(bool(fresh[s]),float(sc[s]))
    if variant=='NQ_DAILY_CONFIRM': return cur&wb,rs189,lambda s,sc:(bool(db[s]),float(sc[s]))
    if variant=='NQ_BLUE_FIRST': return cur&wb,rs189,lambda s,sc:(str(col[s])=='Blue',float(sc[s]))
    if variant=='NQ_GREEN_FIRST': return cur&wb,rs189,lambda s,sc:(str(col[s])=='Green',float(sc[s]))
    if variant=='NQ_PURE_MNOTRED': return base&wb&~mr,rs189,lambda s,sc:(float(sc[s]),)
    raise ValueError(variant)

def core_rows(d,mx,x,theme,mode,variant):
    mask,metric,key0=rank_spec(d,mx,x,variant); ddv=pd.to_numeric(mx['ddv'].loc[d],errors='coerce'); rs189=pd.to_numeric(mx['rs189'].loc[d],errors='coerce'); ts=theme.get(d,{})
    score=metric.copy()
    if mode=='ATTACK':
        th=pd.Series({s:float(ts.get(str(s),50.0)) for s in metric.index}); score=.7*metric+.3*th
    syms=[s for s in metric.index if bool(mask.get(s,False)) and scan.finite(metric.get(s)) and scan.finite(score.get(s)) and scan.finite(ddv.get(s))]
    # priority components use attack/selective score as the numeric tail key
    wb=mx['week_bull'].loc[d].fillna(False); db=mx['day_bull'].loc[d].fillna(False); fresh=x['fresh10'].loc[d].fillna(False); col=x['week_color'].loc[d]
    def k(s):
        if variant=='BASE_WEEK_PRIORITY': return (bool(wb[s]),float(score[s]),float(rs189[s]) if scan.finite(rs189[s]) else -1e9)
        if variant=='NQ_FRESH10': return (bool(fresh[s]),float(score[s]))
        if variant=='NQ_DAILY_CONFIRM': return (bool(db[s]),float(score[s]))
        if variant=='NQ_BLUE_FIRST': return (str(col[s])=='Blue',float(score[s]))
        if variant=='NQ_GREEN_FIRST': return (str(col[s])=='Green',float(score[s]))
        return (float(score[s]),)
    syms.sort(key=k,reverse=True); out=[]
    for i,s in enumerate(syms,1): out.append({'ticker':str(s),'final_rank':i,'attack_watch_score':float(score[s]),'rs189':float(rs189[s]) if scan.finite(rs189[s]) else None,'daily_dollar_volume_m':float(ddv[s])/1e6,'theme30':float(ts.get(str(s),50.0))})
    return out

def companion(d,mx,x,theme,nq,e,variant,ep):
    color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''; mode=audit.mode(color,mx['breadth'].get(d,np.nan))
    return {'asof':str(d.date()),'market':{'mode':mode},'candidates':core_rows(d,mx,x,theme,mode,variant),'early1':{'status':'READY','entry_allowed_now':mode in {'ATTACK','SELECTIVE'},'candidates':scan.early_rows(d,mx,x,e,ep)}}

def simulate(idx,mx,x,theme,nq,e,variant,ep):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],'pending':{'full_exits':[],'partial25':[],'entries':[]}}; eq=[]; selected=[]
    for d0 in idx:
        d=pd.Timestamp(d0); c=companion(d,mx,x,theme,nq,e,variant,ep); selected.extend([(d,r['ticker'],i+1) for i,r in enumerate(c['candidates'][:12])]); state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close']); eq.append((d,float(state['nav'])))
    s=pd.Series(dict(eq),dtype=float); r=s.pct_change(fill_method=None).dropna(); dd=s/s.cummax()-1
    return s,{'days':len(s),'total_return':float(s.iloc[-1]/s.iloc[0]-1),'mdd':float(dd.min()),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if len(r)>2 and r.std(ddof=1)>0 else None},selected

def sel_forward(selected,ohlcv):
    vals={5:[],10:[],20:[]}; op=ohlcv['open']; cl=ohlcv['close']; pos={d:i for i,d in enumerate(cl.index)}
    for d,s,_ in selected:
        if s not in cl.columns or d not in pos: continue
        i=pos[d]
        if i+1>=len(cl.index) or not scan.finite(op.iloc[i+1][s]): continue
        en=float(op.iloc[i+1][s])
        for h in vals:
            j=i+h
            if j<len(cl.index) and scan.finite(cl.iloc[j][s]): vals[h].append(float(cl.iloc[j][s])/en-1)
    out={}
    for h,v in vals.items(): out[h]=scan.summarize_values(v)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    hist=json.loads((root/'v38-strict-loo-history.json').read_text()); snaps=hist.get('taxonomy_snapshots',[])
    if len(snaps)!=1 or str(snaps[0].get('effective_asof'))!=str(audit.PIT_EFFECTIVE.date()): raise RuntimeError('verified PIT taxonomy required')
    s2t=snaps[0]['s2t']; symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    end='2026-09-05'; print('DOWNLOAD STOCK',flush=True); ohlcv,sd=audit.download_ohlcv(symbols,'2024-01-01',end,a.batch_size)
    if sd['coverage']<.85: raise RuntimeError(sd)
    print('DOWNLOAD THEME',flush=True); tc,td=audit.loo.download_adjusted_close(sorted(s2t),'2026-01-01',end,a.batch_size)
    cov=float(td.get('coverage') or (td.get('downloaded',0)/max(1,td.get('requested',1))))
    if cov<.85: raise RuntimeError(td)
    mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded); x=scan.build_extra(ohlcv,mx,bio,allowed); theme,pdgn=audit.theme_scores_by_date(tc,s2t,END,list(ohlcv['close'].columns)); nq=audit.market_nqsar('2026-03-01',end).reindex(mx['close'].index).ffill(limit=2)
    first=max(min(theme),audit.PIT_EFFECTIVE); idx=mx['close'].index[(mx['close'].index>=first)&(mx['close'].index<=END)]; results={}; rows=[]
    specs=[(v,'EARLY1') for v in scan.CORE_VARIANTS]+[('WEEK_GATE_CURRENT',ep) for ep in scan.EARLY_POLICIES[1:]]
    for v,ep in specs:
        name=v if ep=='EARLY1' else f'{v}__{ep}'; print('SIM',name,flush=True); eq,m,sel=simulate(idx,mx,x,theme,nq,e,v,ep); results[name]=eq; fw=sel_forward(sel,ohlcv); rows.append({'variant':v,'early_policy':ep,**m,**{f'sel_fwd{h}_{k}':vv for h,st in fw.items() for k,vv in st.items()}}); eq.rename('equity').to_csv(out/f'equity_{name}.csv')
    base=results['BASE_WEEK_PRIORITY']
    for r in rows:
        name=r['variant'] if r['early_policy']=='EARLY1' else f"{r['variant']}__{r['early_policy']}"; r['boot1_vs_base']=scan.bootstrap(results[name],base,block=1,reps=3000); r['boot3_vs_base']=scan.bootstrap(results[name],base,block=3,reps=3000); r['boot5_vs_base']=scan.bootstrap(results[name],base,block=5,reps=3000)
    pd.DataFrame(rows).to_csv(out/'pit_metrics.csv',index=False); (out/'summary.json').write_text(json.dumps(scan.safe({'method':'true PIT Strict LOO Theme30 NQSAR-centric A/B','stock':sd,'theme':td,'pit':pdgn,'period':[str(idx.min().date()),str(idx.max().date())]}),ensure_ascii=False,indent=2)); print('DONE',flush=True)
if __name__=='__main__':main()
