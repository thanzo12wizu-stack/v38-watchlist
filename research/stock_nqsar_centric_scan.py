from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np, pandas as pd
import build_dashboard as bd
import build_v38_sleeve_live as sleeve
import build_v38_early1_live as earlylive
from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import preimpl_core11_early1_long as lng

START=pd.Timestamp('2016-01-04'); END=pd.Timestamp('2026-09-04'); CONF=pd.Timestamp('2022-01-03')
DDV10=audit.DDV_POOL; DDV20=audit.DDV_ENTRY
CORE_VARIANTS=['BASE_WEEK_PRIORITY','WEEK_GATE_CURRENT','NQ_PURE_RS189','NQ_PURE_RS63','NQ_PURE_BLEND','NQ_RS85_NO_SMA','NQ_STRUCT_NO_RS','NQ_FRESH10','NQ_DAILY_CONFIRM','NQ_BLUE_FIRST','NQ_GREEN_FIRST','NQ_PURE_MNOTRED']
EARLY_POLICIES=['EARLY1','NQEARLY_FILTER','NQEARLY_BROAD','NQEARLY_DAILY_ONSET']

def finite(x):
    try:return math.isfinite(float(x))
    except Exception:return False

def safe(x):
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return str(x.date())
    return x

def pct(v,p): return v.where(p&v.notna()).rank(axis=1,pct=True,method='average')*100

def exact_colors(high,low,close,min_rows):
    out=pd.DataFrame(index=close.index,columns=close.columns,dtype=object); good=0
    for j,s in enumerate(close.columns,1):
        z=pd.DataFrame({'h':high[s],'l':low[s],'c':close[s]}).dropna()
        if len(z)<min_rows: continue
        h,l,c=z.h.to_numpy(float),z.l.to_numpy(float),z.c.to_numpy(float)
        sar=bd._psar(h,l,c,step=.02,mx=.08); ema=z.c.ewm(span=21,adjust=False).mean().to_numpy(float)
        d=z.c.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0); ru=up.ewm(alpha=1/14,adjust=False).mean(); rd=dn.ewm(alpha=1/14,adjust=False).mean(); rsi=(100-100/(1+ru/rd)).to_numpy(float)
        bd._onimine_state(c,sar,ema,rsi); colors=list(bd._LAST_ONIMINE_SERIES or [])
        if len(colors)!=len(z): continue
        out.loc[z.index,s]=colors; good+=1
        if j%500==0 or j==len(close.columns): print(f'COLOR {j}/{len(close.columns)} good={good}',flush=True)
    return out

def build_extra(ohlcv,mx,bio,allowed):
    close,vol=ohlcv['close'],ohlcv['volume']; sma50=close.rolling(50,min_periods=50).mean(); sma200=close.rolling(200,min_periods=200).mean(); ddv=mx['ddv']
    base=(close>=5)&(ddv>=DDV10); ex=[s for s in bio if s in base.columns]
    if ex: base.loc[:,ex]=False
    struct=base&(sma50>sma200)&(close>sma200); rs85=base&(mx['rs63']>=85)&(mx['rs189']>=85)
    ret21=close/close.shift(21)-1; ret42=close/close.shift(42)-1; ret63=close/close.shift(63)-1
    q21,q42,q63=pct(ret21,base),pct(ret42,base),pct(ret63,base); high=pct(close/close.shift(1).rolling(63,min_periods=40).max(),base); acc=pct(q21-q21.shift(20),base); early_score=.5*q21+.25*high+.25*acc
    radar=(base&((q21>=85)|(q42>=85)|(q63>=85))).fillna(False)
    allowed_set=set(allowed or []); early_ok=radar.copy()
    if allowed_set:
        bad=[s for s in early_ok.columns if s not in allowed_set]
        if bad: early_ok.loc[:,bad]=False
    wb=mx['week_bull'].fillna(False); db=mx['day_bull'].fillna(False); mr=mx['month_red'].fillna(False)
    won=wb&~wb.shift(1).fillna(False); fresh5=won.astype(int).rolling(5,min_periods=1).max().astype(bool)&wb; fresh10=won.astype(int).rolling(10,min_periods=1).max().astype(bool)&wb; fresh20=won.astype(int).rolling(20,min_periods=1).max().astype(bool)&wb
    don=db&~db.shift(1).fillna(False); don5=don.astype(int).rolling(5,min_periods=1).max().astype(bool)
    wh,wl,wc=audit.period_ohlc_completed(ohlcv['high'],ohlcv['low'],close,'W-FRI',END); wcol0=exact_colors(wh,wl,wc,30); wcol=wcol0.reindex(close.index).ffill()
    return {'base':base,'struct':struct,'rs85':rs85,'q21':q21,'q42':q42,'q63':q63,'early_score':early_score,'early_radar':early_ok,'fresh5':fresh5,'fresh10':fresh10,'fresh20':fresh20,'daily_onset5':don5,'week_color':wcol,'week_color_weekly':wcol0,'sma50':sma50,'sma200':sma200}

def core_rows(d,mx,x,variant):
    wb=mx['week_bull'].loc[d].fillna(False); db=mx['day_bull'].loc[d].fillna(False); mr=mx['month_red'].loc[d].fillna(False); rs189=pd.to_numeric(mx['rs189'].loc[d],errors='coerce'); rs63=pd.to_numeric(mx['rs63'].loc[d],errors='coerce'); ddv=pd.to_numeric(mx['ddv'].loc[d],errors='coerce'); cur=mx['eligible'].loc[d].fillna(False)
    base=x['base'].loc[d].fillna(False); struct=x['struct'].loc[d].fillna(False); rs85=x['rs85'].loc[d].fillna(False); fresh=x['fresh10'].loc[d].fillna(False); col=x['week_color'].loc[d]
    if variant=='BASE_WEEK_PRIORITY': mask=cur; score=rs189; keys=lambda s:(bool(wb[s]),float(score[s]))
    elif variant=='WEEK_GATE_CURRENT': mask=cur&wb; score=rs189; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_PURE_RS189': mask=base&wb; score=rs189; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_PURE_RS63': mask=base&wb; score=rs63; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_PURE_BLEND': mask=base&wb; score=.5*rs189+.5*rs63; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_RS85_NO_SMA': mask=base&wb&rs85; score=rs189; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_STRUCT_NO_RS': mask=struct&wb; score=rs189; keys=lambda s:(float(score[s]),)
    elif variant=='NQ_FRESH10': mask=cur&wb; score=rs189; keys=lambda s:(bool(fresh[s]),float(score[s]))
    elif variant=='NQ_DAILY_CONFIRM': mask=cur&wb; score=rs189; keys=lambda s:(bool(db[s]),float(score[s]))
    elif variant=='NQ_BLUE_FIRST': mask=cur&wb; score=rs189; keys=lambda s:(str(col[s])=='Blue',float(score[s]))
    elif variant=='NQ_GREEN_FIRST': mask=cur&wb; score=rs189; keys=lambda s:(str(col[s])=='Green',float(score[s]))
    elif variant=='NQ_PURE_MNOTRED': mask=base&wb&~mr; score=rs189; keys=lambda s:(float(score[s]),)
    else: raise ValueError(variant)
    syms=[s for s in rs189.index if bool(mask.get(s,False)) and finite(score.get(s)) and finite(ddv.get(s))]
    syms.sort(key=keys,reverse=True); out=[]
    for i,s in enumerate(syms,1): out.append({'ticker':str(s),'final_rank':i,'attack_watch_score':float(score[s]),'rs189':float(rs189[s]) if finite(rs189[s]) else None,'daily_dollar_volume_m':float(ddv[s])/1e6})
    return out

def early_rows(d,mx,x,e,policy):
    if policy=='EARLY1': return pit.early_rows(d,e)
    wb=mx['week_bull'].loc[d].fillna(False); db=mx['day_bull'].loc[d].fillna(False); mr=mx['month_red'].loc[d].fillna(False); ddv=pd.to_numeric(mx['ddv'].loc[d],errors='coerce'); score=pd.to_numeric(x['early_score'].loc[d],errors='coerce'); radar=x['early_radar'].loc[d].fillna(False); don5=x['daily_onset5'].loc[d].fillna(False)
    if policy=='NQEARLY_FILTER':
        base={str(r['ticker']):r for r in pit.early_rows(d,e)}; syms=[s for s in base if s in wb.index and (not bool(wb[s])) and bool(db[s]) and (not bool(mr[s]))]; return [{**base[s],'rank':i+1} for i,s in enumerate(syms)]
    mask=radar&~wb&db&~mr
    if policy=='NQEARLY_DAILY_ONSET': mask=mask&don5
    elif policy!='NQEARLY_BROAD': raise ValueError(policy)
    syms=[s for s in score.index if bool(mask.get(s,False)) and finite(score.get(s)) and finite(ddv.get(s)) and float(ddv[s])>=DDV20]
    syms.sort(key=lambda s:float(score[s]),reverse=True)
    return [{'ticker':str(s),'score':float(score[s]),'rank':i+1} for i,s in enumerate(syms[:40])]

def companion(d,mx,x,nq,e,core_variant,early_policy):
    color=str(nq.at[d,'nq_color']) if d in nq.index and pd.notna(nq.at[d,'nq_color']) else ''; mode=audit.mode(color,mx['breadth'].get(d,np.nan))
    return {'asof':str(d.date()),'market':{'mode':mode},'candidates':core_rows(d,mx,x,core_variant),'early1':{'status':'READY','entry_allowed_now':mode in {'ATTACK','SELECTIVE'},'candidates':early_rows(d,mx,x,e,early_policy)}}

def simulate(idx,mx,x,nq,e,core_variant,early_policy):
    first=pd.Timestamp(idx[0]); state={'status':'READY','asof':str(first.date()),'cash':1.0,'positions':[],'pending':{'full_exits':[],'partial25':[],'entries':[]}}; eq=[]; counts={'CORE':0,'EARLY':0,'promotions':0}
    for d0 in idx:
        d=pd.Timestamp(d0); c=companion(d,mx,x,nq,e,core_variant,early_policy); state=sleeve.advance_normal(state,c,str(d.date()),mx['open'],mx['close']); p=state.get('pending',{})
        for z in p.get('entries',[]): counts[str(z.get('sleeve') or 'CORE')]=counts.get(str(z.get('sleeve') or 'CORE'),0)+1
        counts['promotions']+=len(p.get('promotions',[])); eq.append((d,float(state['nav'])))
    return pd.Series(dict(eq),dtype=float),counts

def fwd_matrix(ohlcv,h): return ohlcv['close'].shift(-h)/ohlcv['open'].shift(-1)-1

def summarize_values(v):
    z=pd.to_numeric(pd.Series(v),errors='coerce').dropna();
    return {'n':len(z),'mean':float(z.mean()) if len(z) else None,'median':float(z.median()) if len(z) else None,'win':float((z>0).mean()) if len(z) else None,'p10':float(z.quantile(.1)) if len(z) else None,'p90':float(z.quantile(.9)) if len(z) else None}

def state_stats(idx,ohlcv,mx,x,modes):
    fw={h:fwd_matrix(ohlcv,h) for h in (5,10,20,63)}; rows=[]
    states={'WEEK_BLUE':x['week_color'].eq('Blue'),'WEEK_GREEN':x['week_color'].eq('Green'),'WEEK_YELLOW':x['week_color'].eq('Yellow'),'WEEK_RED':x['week_color'].eq('Red'),'WEEK_FRESH10':x['fresh10'],'WEEK_ESTABLISHED':mx['week_bull']&~x['fresh10'],'DAILY_BULL_WEEK_NONBULL':mx['day_bull']&~mx['week_bull'],'NQEARLY_BROAD':x['early_radar']&~mx['week_bull']&mx['day_bull']&~mx['month_red']}
    universes={'BASE_POOL':x['base'],'CURRENT_ELIG':mx['eligible']}
    for period,pmask in [('DISCOVERY',idx<CONF),('CONFIRMATION',idx>=CONF)]:
        dates=idx[pmask]
        for un,um in universes.items():
            for name,sm in states.items():
                mask=(um&sm).reindex(index=dates).fillna(False)
                row={'period':period,'universe':un,'state':name}
                for h in (5,10,20,63):
                    vals=fw[h].reindex(index=dates).where(mask).stack().values; st=summarize_values(vals); row.update({f'fwd{h}_{k}':v for k,v in st.items()})
                rows.append(row)
        for mode in ('ATTACK','SELECTIVE','STOP','DEFENSE'):
            dm=pd.Series(dates,index=dates).map(lambda d:modes.get(d,'STOP')).eq(mode).to_numpy(); d2=dates[dm]
            for name in ('WEEK_BLUE','WEEK_GREEN','WEEK_FRESH10','DAILY_BULL_WEEK_NONBULL'):
                mask=(mx['eligible']&states[name]).reindex(index=d2).fillna(False); vals=fw[20].reindex(index=d2).where(mask).stack().values; st=summarize_values(vals); rows.append({'period':period,'universe':'CURRENT_ELIG','state':name,'market_mode':mode,**{f'fwd20_{k}':v for k,v in st.items()}})
    return pd.DataFrame(rows)

def transition_stats(idx,ohlcv,x,mx):
    wc=x['week_color_weekly']; fw={h:fwd_matrix(ohlcv,h).reindex(wc.index) for h in (5,10,20,63)}; prev=wc.shift(1); rows=[]
    for period,start,end in [('DISCOVERY',START,pd.Timestamp('2021-12-31')),('CONFIRMATION',CONF,END)]:
        dates=wc.index[(wc.index>=start)&(wc.index<=end)]
        for un,um in [('BASE_POOL',x['base']),('CURRENT_ELIG',mx['eligible'])]:
            u=um.reindex(index=dates).fillna(False)
            for a in ('Red','Yellow','Green','Blue'):
                for b in ('Red','Yellow','Green','Blue'):
                    sig=(prev.reindex(index=dates).eq(a)&wc.reindex(index=dates).eq(b)&u)
                    n=int(sig.sum().sum())
                    if n<5: continue
                    row={'period':period,'universe':un,'from':a,'to':b,'n':n}
                    for h in (5,10,20,63): row.update({f'fwd{h}_{k}':v for k,v in summarize_values(fw[h].where(sig).stack().values).items()})
                    rows.append(row)
    return pd.DataFrame(rows)

def leader_stats(idx,ohlcv,mx,x,e):
    close,op=ohlcv['close'],ohlcv['open']; fut=close.shift(-1).iloc[::-1].rolling(126,min_periods=1).max().iloc[::-1]; lead=(fut/op.shift(-1)-1)>=1.0; rows=[]
    eactive=e['active'].reindex(index=close.index,columns=close.columns,fill_value=False); broad=x['early_radar']&~mx['week_bull']&mx['day_bull']&~mx['month_red']
    for period,dates in [('DISCOVERY',idx[idx<CONF]),('CONFIRMATION',idx[idx>=CONF])]:
        for un,um in [('BASE_POOL',x['base']),('CURRENT_ELIG',mx['eligible'])]:
            flag=(lead&um).reindex(index=dates).fillna(False); seed=flag&~flag.shift(1).fillna(False); n=int(seed.sum().sum())
            row={'period':period,'universe':un,'leader_episode_seeds':n}
            for nm,sm in [('week_bull',mx['week_bull']),('fresh10',x['fresh10']),('daily_bull_week_nonbull',mx['day_bull']&~mx['week_bull']),('nqearly_broad',broad),('early1_active',eactive)]:
                row[nm+'_rate']=float((seed&sm.reindex_like(seed).fillna(False)).sum().sum()/n) if n else None
            rows.append(row)
    return pd.DataFrame(rows)

def bootstrap(a,b,start=None,block=20,reps=1000):
    if start is not None: a,b=a.loc[a.index>=start],b.loc[b.index>=start]
    x=(a.pct_change(fill_method=None)-b.pct_change(fill_method=None)).dropna().to_numpy(float)
    if len(x)<30:return None
    rng=np.random.default_rng(20260907+block+(100 if start is not None else 0)); starts=np.arange(max(1,len(x)-block+1)); win=0
    for _ in range(reps):
        z=[]
        while len(z)<len(x):
            st=int(rng.choice(starts)); z.extend(x[st:st+block])
        win+=np.mean(z[:len(x)])>0
    return win/reps

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=100); a=ap.parse_args(); root=Path(a.root); out=root/a.output; out.mkdir(parents=True,exist_ok=True)
    symbols,bio=audit.load_universe(root/'universe.csv'); allowed=earlylive._industry_symbols(root/'industry_map.json'); early_excluded=set(bio)
    if allowed: early_excluded.update(set(symbols)-set(allowed))
    warm=str((START-pd.Timedelta(days=1600)).date()); end='2026-09-05'; print('DOWNLOAD',flush=True); ohlcv,diag=audit.download_ohlcv(symbols,warm,end,a.batch_size)
    if diag['coverage']<.85: raise RuntimeError(diag)
    print('BUILD',flush=True); mx=audit.build_stock_inputs(ohlcv,bio,END); e=pit.early_inputs(ohlcv['close'],ohlcv['volume'],early_excluded); x=build_extra(ohlcv,mx,bio,allowed)
    nq=audit.market_nqsar(str((START-pd.Timedelta(days=90)).date()),end).reindex(mx['close'].index).ffill(limit=2); idx=mx['close'].index[(mx['close'].index>=START)&(mx['close'].index<=END)]; modes={d:audit.mode(nq.at[d,'nq_color'] if d in nq.index else '',mx['breadth'].get(d,np.nan)) for d in idx}
    print('STATS',flush=True); state_stats(idx,ohlcv,mx,x,modes).to_csv(out/'state_stats.csv',index=False); transition_stats(idx,ohlcv,x,mx).to_csv(out/'transition_stats.csv',index=False); leader_stats(idx,ohlcv,mx,x,e).to_csv(out/'leader_stats.csv',index=False)
    results={}; rows=[]
    for v in CORE_VARIANTS:
        print('SIM CORE',v,flush=True); eq,c=simulate(idx,mx,x,nq,e,v,'EARLY1'); results[v]=eq; sl=lng.slices(eq); rows.append({'variant':v,'early_policy':'EARLY1',**{f'full_{k}':vv for k,vv in sl['full'].items()},**{f'disc_{k}':vv for k,vv in sl['discovery_2016_2021'].items()},**{f'conf_{k}':vv for k,vv in sl['confirmation_2022_plus'].items()},**c}); eq.rename('equity').to_csv(out/f'equity_{v}.csv')
    anchor='WEEK_GATE_CURRENT'
    for ep in EARLY_POLICIES[1:]:
        name=f'{anchor}__{ep}'; print('SIM EARLY',name,flush=True); eq,c=simulate(idx,mx,x,nq,e,anchor,ep); results[name]=eq; sl=lng.slices(eq); rows.append({'variant':anchor,'early_policy':ep,**{f'full_{k}':vv for k,vv in sl['full'].items()},**{f'disc_{k}':vv for k,vv in sl['discovery_2016_2021'].items()},**{f'conf_{k}':vv for k,vv in sl['confirmation_2022_plus'].items()},**c}); eq.rename('equity').to_csv(out/f'equity_{name}.csv')
    base=results['BASE_WEEK_PRIORITY'];
    for r in rows:
        key=r['variant'] if r['early_policy']=='EARLY1' else f"{r['variant']}__{r['early_policy']}"; r['boot_full_vs_base']=bootstrap(results[key],base); r['boot_conf_vs_base']=bootstrap(results[key],base,CONF)
    pd.DataFrame(rows).to_csv(out/'portfolio_metrics.csv',index=False)
    summary={'method':'NQSAR-centric architecture scan; long history uses neutral Theme to avoid hindsight; all portfolio variants use production advance_normal / Core11+Early1 slots and existing exits','universe':diag,'variants':CORE_VARIANTS,'early_policies':EARLY_POLICIES,'notes':['NQ_PURE replaces current SMA/RS eligibility with liquid+non-biotech+Weekly Bull then ranks by RS','NQ_RS85_NO_SMA keeps RS thresholds but removes SMA filters','NQ_STRUCT_NO_RS keeps SMA structure but removes RS thresholds','Fresh/Daily/Blue/Green are ranking priorities, not exits','NQEarly never changes Core exit rules']}
    (out/'summary.json').write_text(json.dumps(safe(summary),ensure_ascii=False,indent=2)); print('DONE',flush=True)
if __name__=='__main__':main()
