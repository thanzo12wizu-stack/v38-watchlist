from __future__ import annotations

import argparse, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

import validate_pioneer_leader as pl
import rotation_theme56_divergence_diagnostics as diag

H=(5,10,20,40)
COOLDOWN=20
SECTORS=['XLC','XLY','XLP','XLE','XLF','XLV','XLI','XLB','XLRE','XLK','XLU']


def safe(v:Any)->Any:
    if isinstance(v,dict): return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [safe(x) for x in v]
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return x if math.isfinite(x) else None
    if isinstance(v,pd.Timestamp): return v.isoformat()
    return v


def norm_members(parts:list[tuple[Path,str]])->pd.DataFrame:
    frames=[]
    for path,source in parts:
        if not path.exists(): continue
        x=pd.read_csv(path)
        if not {'sector_etf','symbol'}.issubset(x.columns): continue
        x=x.copy(); x['sector_etf']=x.sector_etf.astype(str).str.upper().str.strip(); x['symbol']=x.symbol.astype(str).str.upper().str.strip()
        x=x[~x.symbol.isin(['','NAN','-','--'])]
        x['weight_pct']=pd.to_numeric(x.get('weight_pct'),errors='coerce')
        x['source']=source
        frames.append(x[['sector_etf','symbol','weight_pct','source']])
    if not frames:return pd.DataFrame(columns=['sector_etf','symbol','weight_pct','source'])
    x=pd.concat(frames,ignore_index=True); x['has_weight']=x.weight_pct.notna().astype(int)
    x=x.sort_values(['sector_etf','symbol','has_weight'],ascending=[True,True,False]).drop_duplicates(['sector_etf','symbol'],keep='first')
    return x.drop(columns='has_weight').reset_index(drop=True)


def rank_cs(w:pd.DataFrame,min_count:int=15)->pd.DataFrame:
    r=w.rank(axis=1,pct=True,method='average')*100
    return r.where(w.notna().sum(axis=1)>=min_count)


def coverage_mean(mask:pd.DataFrame,n:int,min_cov:float=.60)->pd.Series:
    valid=mask.notna().sum(axis=1); return mask.mean(axis=1,skipna=True).where(valid>=max(5,math.ceil(n*min_cov)))


def theme_components(close:pd.DataFrame,volume:pd.DataFrame,members:list[str],min_cov=.60)->pd.DataFrame:
    members=[s for s in members if s in close.columns and s in volume.columns]
    n=len(members)
    if n<5:return pd.DataFrame(index=close.index)
    c=close[members]; v=volume[members]
    ema21=c.ewm(span=21,adjust=False,min_periods=15).mean(); sma50=c.rolling(50,min_periods=35).mean()
    b21=100*coverage_mean((c>ema21).where(c.notna()&ema21.notna()),n,min_cov)
    b50=100*coverage_mean((c>sma50).where(c.notna()&sma50.notna()),n,min_cov)
    ret=c.pct_change(fill_method=None); valid=ret.notna(); need=max(5,math.ceil(n*min_cov)); cnt=valid.sum(axis=1)
    ad=((ret.gt(0).sum(axis=1)-ret.lt(0).sum(axis=1))/cnt.replace(0,np.nan)).where(cnt>=need)
    ad20=(50*(1+ad.rolling(20,min_periods=15).mean())).clip(0,100)
    signed=v.where(ret>0,-v.where(ret<0,0)).where(valid&v.notna()); obv=signed.fillna(0).cumsum(); obd=obv-obv.shift(20)
    obv20=100*coverage_mean((obd>0).where(obd.notna()),n,min_cov)
    up=v.where(ret>0,0).where(valid&v.notna()).sum(axis=1,min_count=1); dn=v.where(ret<0,0).where(valid&v.notna()).sum(axis=1,min_count=1)
    u20=up.rolling(20,min_periods=15).sum(); d20=dn.rolling(20,min_periods=15).sum(); uvd=(u20/d20.replace(0,np.nan)).where(cnt.rolling(20,min_periods=15).median()>=need)
    pos5=100*coverage_mean((c/c.shift(5)-1).where(c.notna()&c.shift(5).notna())>0,n,min_cov)
    pos10=100*coverage_mean((c/c.shift(10)-1).where(c.notna()&c.shift(10).notna())>0,n,min_cov)
    pos20=100*coverage_mean((c/c.shift(20)-1).where(c.notna()&c.shift(20).notna())>0,n,min_cov)
    return pd.DataFrame({'breadth21':b21,'breadth50':b50,'ad20':ad20,'obv20':obv20,'uvdv20':uvd,'pos5':pos5,'pos10':pos10,'pos20':pos20})


def load_flows(exact:Path,fallback:Path)->pd.DataFrame:
    frames=[]
    for path,q in ((exact,'EXACT_OR_PROVIDER_QA'),(fallback,'ETFCOM_VALIDATED_ACTUAL')):
        if not path.exists():continue
        try:x=pd.read_csv(path)
        except Exception:continue
        if 'date' not in x or 'ticker' not in x:continue
        x=x.copy(); x['date']=pd.to_datetime(x.date,errors='coerce').dt.normalize(); x['ticker']=x.ticker.astype(str).str.upper()
        val=None
        for c in ('flow_20d_pct_aum','flow20_pct_aum','flow_20d_aum_pct'):
            if c in x: val=c; break
        if val is None:continue
        x['flow20_pct_aum']=pd.to_numeric(x[val],errors='coerce'); x['flow_quality']=q; frames.append(x[['date','ticker','flow20_pct_aum','flow_quality']])
    if not frames:return pd.DataFrame(columns=['date','ticker','flow20_pct_aum','flow_quality'])
    x=pd.concat(frames,ignore_index=True); x['priority']=x.flow_quality.eq('EXACT_OR_PROVIDER_QA').astype(int)
    return x.sort_values(['date','ticker','priority'],ascending=[True,True,False]).drop_duplicates(['date','ticker'],keep='first').drop(columns='priority')


def static_concentration(members:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for t,g in members.groupby('sector_etf'):
        w=pd.to_numeric(g.weight_pct,errors='coerce').dropna(); known=w.sum(); cov=len(w)/len(g) if len(g) else 0
        rows.append({'ticker':t,'member_count':len(g),'weighted_members':len(w),'weight_member_coverage':cov,'reported_weight_sum':known,'top5_weight':w.nlargest(5).sum() if len(w)>=5 else np.nan,'effective_holdings':(known**2/(w.pow(2).sum())) if known>0 and (w.pow(2).sum())>0 else np.nan,'weight_ready':bool(len(w)>=5 and cov>=.70 and known>=60)})
    return pd.DataFrame(rows)


def top5_move_share(close:pd.DataFrame,members:pd.DataFrame,h:int=5)->pd.DataFrame:
    outs={}
    ret=(close/close.shift(h)-1).abs()
    for t,g in members.groupby('sector_etf'):
        gg=g.dropna(subset=['weight_pct']).copy(); gg=gg[gg.symbol.isin(close.columns)]
        if len(gg)<5 or gg.weight_pct.sum()<60:continue
        gg=gg.sort_values('weight_pct',ascending=False); syms=gg.symbol.tolist(); w=pd.Series(gg.weight_pct.to_numpy(float),index=syms); w=w/w.sum()
        contrib=ret[syms].mul(w,axis=1); total=contrib.sum(axis=1,min_count=max(5,math.ceil(len(syms)*.6))); top=contrib[gg.head(5).symbol.tolist()].sum(axis=1,min_count=3)
        outs[t]=100*top/total.replace(0,np.nan)
    return pd.DataFrame(outs)


def eventize(panel:pd.DataFrame,mask:pd.Series)->pd.DataFrame:
    z=panel.assign(_s=mask.fillna(False).to_numpy()); rows=[]
    for t,g in z.groupby('ticker',sort=False):
        g=g.sort_values('date').reset_index(drop=True); last=-99999
        for i,r in g.iterrows():
            if bool(r._s) and i-last>=COOLDOWN: rows.append(r.drop(labels='_s').to_dict()); last=i
    return pd.DataFrame(rows)


def match(panel:pd.DataFrame,ev:pd.DataFrame,base:pd.Series)->pd.DataFrame:
    if ev.empty:return ev
    b=panel.assign(_b=base.fillna(False).to_numpy()); out=[]
    for _,r in ev.iterrows():
        same=b[(b.date==r.date)&b._b&(b.ticker!=r.ticker)]; z=r.to_dict()
        for h in H:
            x=pd.to_numeric(same[f'fwd_excess_{h}d'],errors='coerce').dropna(); z[f'matched_{h}d']=r[f'fwd_excess_{h}d']-x.mean() if len(x)>=5 and pd.notna(r[f'fwd_excess_{h}d']) else np.nan
        out.append(z)
    return pd.DataFrame(out)


def boot_cluster(ev:pd.DataFrame,col:str,reps=2000,seed=3):
    z=ev[['ticker',col]].dropna(); keys=z.ticker.unique()
    if len(keys)<8:return [None,None]
    rng=np.random.default_rng(seed); vals=[]
    for _ in range(reps):
        ks=rng.choice(keys,len(keys),replace=True); a=[]
        for k in ks:a.extend(z.loc[z.ticker==k,col].tolist())
        vals.append(np.mean(a))
    q=np.quantile(vals,[.025,.975]); return [float(q[0]),float(q[1])]


def parent_map(etf_close:pd.DataFrame)->pd.DataFrame:
    themes=[c for c in etf_close.columns if c not in {'SPY',*SECTORS}]; sec=[c for c in SECTORS if c in etf_close]
    ret20=etf_close.pct_change(20,fill_method=None); rows=[]
    for t in themes:
        for d in etf_close.index:
            loc=etf_close.index.get_loc(d)
            if loc<126:continue
            hist=etf_close.iloc[loc-125:loc+1].pct_change(fill_method=None)
            cor=hist[sec].corrwith(hist[t]).dropna()
            if cor.empty:continue
            p=cor.idxmax(); rows.append({'date':d,'ticker':t,'parent':p,'parent_corr126':cor[p],'theme_parent_ret20_gap':ret20.at[d,t]-ret20.at[d,p] if pd.notna(ret20.at[d,t]) and pd.notna(ret20.at[d,p]) else np.nan})
    return pd.DataFrame(rows)


def main():
    ap=argparse.ArgumentParser();
    for a in ('config','base','expansion','fallback','dram','exact_flows','etfcom_flows','output'): ap.add_argument('--'+a.replace('_','-'),dest=a,type=Path,required=True)
    ap.add_argument('--start',default='2022-01-01'); ap.add_argument('--end',default='2026-09-04'); ap.add_argument('--batch-size',type=int,default=80); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(args.config.read_text()); themes=[x['ticker'] for x in cfg['themes']]
    members=norm_members([(args.base,'BASE_EXACT'),(args.expansion,'EXPANSION_EXACT'),(args.dram,'DRAM_SUPPLEMENT'),(args.fallback,'VALIDATED_FALLBACK')]); members=members[members.sector_etf.isin(themes)]
    symbols=sorted(set(members.symbol)); requested=symbols+themes+['SPY',*SECTORS]
    ohlcv,dl=pl.download_ohlcv(requested,args.start,args.end,args.batch_size); close=ohlcv['close']; volume=ohlcv['volume']; dates=close.index
    comp={}; coverage=[]
    for t in themes:
        g=members[members.sector_etf==t]; avail=[s for s in g.symbol if s in close]; coverage.append({'ticker':t,'members':len(g),'downloaded':len(avail),'coverage':len(avail)/len(g) if len(g) else 0})
        comp[t]=theme_components(close,volume,g.symbol.tolist(),.60)
    fields=['breadth21','breadth50','ad20','obv20','uvdv20']; ranks={}
    for f in fields:ranks[f]=rank_cs(pd.DataFrame({t:comp[t].get(f,pd.Series(index=dates,dtype=float)) for t in themes}))
    stack=np.stack([ranks[f].reindex(dates).to_numpy(float) for f in fields],axis=2); internal=pd.DataFrame(np.nanmedian(stack,axis=2),index=dates,columns=themes); internal=internal.where(sum(r.notna().astype(int) for r in ranks.values())>=4)
    etf=close.reindex(columns=[*themes,'SPY',*SECTORS]); spy=etf.SPY; trel63=etf[themes].pct_change(63,fill_method=None).sub(spy.pct_change(63,fill_method=None),axis=0); trel189=etf[themes].pct_change(189,fill_method=None).sub(spy.pct_change(189,fill_method=None),axis=0); price=(rank_cs(trel63)+rank_cs(trel189))/2
    flows=load_flows(args.exact_flows,args.etfcom_flows); flowwide=flows.pivot(index='date',columns='ticker',values='flow20_pct_aum').reindex(index=dates,columns=themes)
    conc=static_concentration(members).set_index('ticker'); move5=top5_move_share(close,members,5).reindex(index=dates,columns=themes); pm=parent_map(etf)
    rows=[]
    for t in themes:
        f=pd.DataFrame(index=dates); f['date']=dates; f['ticker']=t; f['price_score']=price.get(t); f['internal_score']=internal.get(t); f['flow20_pct_aum']=flowwide.get(t); f['top5_move_share5']=move5.get(t); f['top5_weight']=conc.top5_weight.get(t,np.nan); f['weight_ready']=conc.weight_ready.get(t,False)
        for h in (5,10,20): f[f'internal_delta{h}']=f.internal_score-f.internal_score.shift(h); f[f'breadth21_delta{h}']=comp[t].get('breadth21',pd.Series(index=dates,dtype=float))-comp[t].get('breadth21',pd.Series(index=dates,dtype=float)).shift(h); f[f'pos{h}']=comp[t].get(f'pos{h}')
        for h in H:f[f'fwd_excess_{h}d']=(etf[t].shift(-h)/etf[t]-1)-(spy.shift(-h)/spy-1) if t in etf else np.nan
        rows.append(f.reset_index(drop=True))
    panel=pd.concat(rows,ignore_index=True).merge(pm,on=['date','ticker'],how='left')
    panel['parent_ret20_gap_pct']=100*panel.theme_parent_ret20_gap
    defs={
      'PRICE_LEAD_INTERNAL_WEAK':((panel.price_score>=70)&(panel.internal_score<50),panel.price_score>=70,-1),
      'INTERNAL_DETERIORATION':((panel.price_score>=70)&(panel.internal_delta20<=-20),panel.price_score>=70,-1),
      'INTERNAL_IGNITION_5D':((panel.internal_delta5>=20)&(panel.internal_score<70),panel.internal_score<70,+1),
      'INTERNAL_IGNITION_10D':((panel.internal_delta10>=20)&(panel.internal_score<70),panel.internal_score<70,+1),
      'INTERNAL_LEAD':((panel.price_score<60)&(panel.internal_score>=60),panel.price_score<60,+1),
      'TOP5_MOVE_CONCENTRATED':((panel.price_score>=65)&panel.weight_ready&(panel.top5_move_share5>=55)&(panel.pos5<50),panel.price_score>=65,-1),
      'BROAD_CONFIRMED':((panel.price_score>=70)&(panel.internal_score>=60),panel.price_score>=70,+1),
      'PARENT_UNCONFIRMED_LEAD':((panel.price_score>=60)&(panel.parent_ret20_gap_pct>=5)&(panel.parent_corr126>=.35),panel.price_score>=60,+1),
    }
    flowcov=panel.flow20_pct_aum.notna().mean();
    if flowcov>=.30:
        defs['DISTRIBUTION_WITH_FLOW']=((panel.price_score>=70)&(panel.internal_score<50)&(panel.flow20_pct_aum<=0),panel.price_score>=70,-1)
        defs['EARLY_ROTATION_WITH_FLOW']=((panel.price_score<60)&(panel.internal_score>=50)&(panel.internal_delta20>=10)&(panel.flow20_pct_aum>=0),panel.price_score<60,+1)
    report={'schema':1,'research_only':True,'evidence_grade':'CURRENT_MEMBERSHIP_RETROSPECTIVE_NOT_PIT','guardrail':'Historical Theme56 membership unavailable. Never label these results PIT.','download':dl,'flow_panel_coverage':flowcov,'signals':{}}
    all_ev=[]
    for name,(mask,base,sign) in defs.items():
        ev=match(panel,eventize(panel,mask),base); ev['signal']=name; all_ev.append(ev); s={'expected_sign':sign,'periods':{}}
        for pname,lo in [('ALL_2023_PLUS','2023-01-01'),('CONFIRMATION_2024_PLUS','2024-01-01'),('RECENT_2025_PLUS','2025-01-01')]:
            e=ev[ev.date>=pd.Timestamp(lo)]; po={}
            for h in H:
                x=pd.to_numeric(e[f'fwd_excess_{h}d'],errors='coerce').dropna(); m=pd.to_numeric(e[f'matched_{h}d'],errors='coerce').dropna(); po[str(h)]={'n':len(x),'mean_excess':x.mean() if len(x) else None,'median_excess':x.median() if len(x) else None,'matched_n':len(m),'matched_mean':m.mean() if len(m) else None,'cluster_ci95':boot_cluster(e,f'fwd_excess_{h}d',seed=100+h) if h in (20,40) else [None,None],'matched_cluster_ci95':boot_cluster(e,f'matched_{h}d',seed=200+h) if h in (20,40) else [None,None]}
            s['periods'][pname]=po
        report['signals'][name]=s
    evall=pd.concat(all_ev,ignore_index=True) if all_ev else pd.DataFrame(); evall.to_csv(args.output/'theme56_retrospective_events.csv',index=False); panel.to_parquet(args.output/'theme56_retrospective_panel.parquet',index=False); pd.DataFrame(coverage).to_csv(args.output/'theme56_membership_download_coverage.csv',index=False)
    # continuous cross-sectional IC + FDR
    feats=['price_score','internal_score','internal_delta5','internal_delta10','internal_delta20','breadth21_delta5','breadth21_delta10','breadth21_delta20','top5_move_share5','parent_ret20_gap_pct']
    if flowcov>=.30:feats+=['flow20_pct_aum']
    ic=[]; d=panel[panel.date>=pd.Timestamp('2024-01-01')]
    for feat in feats:
        for h in H:
            vals=[]
            for _,g in d.groupby('date'):
                z=g[[feat,f'fwd_excess_{h}d']].dropna()
                if len(z)>=20 and z[feat].nunique()>=5: vals.append(stats.spearmanr(z[feat],z[f'fwd_excess_{h}d']).statistic)
            a=np.array([v for v in vals if np.isfinite(v)])
            if len(a)>=30:
                tt,p=stats.ttest_1samp(a,0); ic.append({'feature':feat,'horizon':h,'n_dates':len(a),'mean_ic':a.mean(),'p':p})
    ict=pd.DataFrame(ic)
    if len(ict):ict['fdr_q']=multipletests(ict.p,method='fdr_bh')[1]
    ict.to_csv(args.output/'theme56_retrospective_ic.csv',index=False); report['continuous_ic']=ict.to_dict('records')
    (args.output/'theme56_retrospective_report.json').write_text(json.dumps(safe(report),ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Theme56 Current-Membership Retrospective Validation','', '**NOT PIT.** Historical membership is unavailable; current membership is held fixed backward.','',f"Downloaded constituent coverage: median {pd.DataFrame(coverage).coverage.median():.1%}; Flow panel coverage: {flowcov:.1%}.",'','| Signal | 2024+ 20D | 2024+ 40D | matched 20D | matched 40D |','|---|---:|---:|---:|---:|']
    for n,s in report['signals'].items():
        p=s['periods']['CONFIRMATION_2024_PLUS']; c=lambda h,k: 'n/a' if p[str(h)][k] is None else f"{100*p[str(h)][k]:+.2f}%"
        lines.append(f"| {n} | {c(20,'mean_excess')} | {c(40,'mean_excess')} | {c(20,'matched_mean')} | {c(40,'matched_mean')} |")
    (args.output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'download':dl,'median_membership_coverage':pd.DataFrame(coverage).coverage.median(),'flow_panel_coverage':flowcov,'signals':list(defs)},indent=2,default=str))

if __name__=='__main__':main()
