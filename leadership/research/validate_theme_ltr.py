from __future__ import annotations

import argparse, json, math
from collections import defaultdict
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_post_ignition_leaders as base
import validate_ignition_quality as iq
import validate_rrg_tail_system as rt

TRAIN_END = pd.Timestamp('2021-12-31')
TEST_START = pd.Timestamp('2022-01-01')
HORIZONS = (20, 40, 63)
MIN_POOL = 3
MIN_PRICE = 5.0
MIN_DV20 = 5_000_000.0
COST_BPS_SIDE = 5.0


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def retmat(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return close / close.shift(n) - 1.0


def make_features(ohlcv: dict[str, pd.DataFrame], cols: list[str]) -> dict[str, pd.DataFrame]:
    close, high, low, vol = (ohlcv[k][cols] for k in ('close','high','low','volume'))
    r = close.pct_change(fill_method=None)
    tr = iq.true_range(high, low, close)
    atr14 = tr.rolling(14, min_periods=10).mean()
    out = iq.compute_feature_matrices(ohlcv, cols, r)
    for n in (5,10,20,63,126,189): out[f'ret{n}'] = retmat(close, n)
    out['vol20'] = r.rolling(20, min_periods=14).std()
    out['vol63'] = r.rolling(63, min_periods=40).std()
    out['atr_pct'] = atr14 / close.replace(0,np.nan)
    out['dist_high252'] = close / high.shift(1).rolling(252, min_periods=180).max() - 1.0
    out['dollar_volume20_log'] = np.log1p((close*vol).rolling(20, min_periods=15).mean().clip(lower=0))
    out.pop('stock252', None)
    return out


def pool_at(d: pd.Timestamp, theme: str, members: dict[str,list[str]], close: pd.DataFrame, dv20: pd.DataFrame, ema21: pd.DataFrame, sma50: pd.DataFrame) -> list[str]:
    out=[]
    for s in members.get(theme,[]):
        if s not in close.columns: continue
        vals=(close.at[d,s],dv20.at[d,s],ema21.at[d,s],sma50.at[d,s])
        if any(pd.isna(x) for x in vals): continue
        c,dv,e,sm=map(float,vals)
        if c>=MIN_PRICE and dv>=MIN_DV20 and c>e and c>sm: out.append(s)
    return out


def rel_label(x: pd.Series) -> pd.Series:
    z=x.dropna()
    if len(z)<MIN_POOL: return pd.Series(dtype=int)
    p=z.rank(pct=True,method='average')
    return np.floor(np.minimum(p,0.999999)*5).astype(int).clip(0,4)


def future_ret(open_: pd.DataFrame, close: pd.DataFrame, pool:list[str], p:int, h:int) -> pd.Series:
    return base.buy_hold_returns_from_open(open_,close,pool,p+1,p+h)


def future_mfe(open_: pd.DataFrame, high: pd.DataFrame, pool:list[str], p:int) -> pd.Series:
    e=open_.loc[high.index[p+1],pool]
    mx=high.loc[high.index[p+1:p+64],pool].max(axis=0)
    return (mx/e-1.0).replace([np.inf,-np.inf],np.nan)


def build_rows(events:pd.DataFrame, close:pd.DataFrame, open_:pd.DataFrame, high:pd.DataFrame,
               stock_ret:pd.DataFrame, spy_close:pd.Series, theme_ret:pd.DataFrame,
               parent:pd.DataFrame, members:dict[str,list[str]], feats:dict[str,pd.DataFrame],
               dv20:pd.DataFrame, ema21:pd.DataFrame, sma50:pd.DataFrame) -> pd.DataFrame:
    pos={pd.Timestamp(d):i for i,d in enumerate(close.index)}
    spy={n:retmat(spy_close.to_frame('SPY'),n)['SPY'] for n in (5,10,20,63,126,189)}
    rows=[]
    for i,ev in enumerate(events.itertuples(index=False)):
        d,t=pd.Timestamp(ev.date),str(ev.theme); p=pos.get(d,-1)
        if p<210 or p+64>=len(close): continue
        pool=pool_at(d,t,members,close,dv20,ema21,sma50)
        if len(pool)<MIN_POOL: continue
        fwd={h:future_ret(open_,close,pool,p,h) for h in HORIZONS}; mfe=future_mfe(open_,high,pool,p)
        labs={f'label_ret{h}':rel_label(fwd[h]) for h in HORIZONS}; labs['label_mfe63']=rel_label(mfe)
        if any(len(v)<MIN_POOL for v in labs.values()): continue
        snap={k:pd.to_numeric(m.loc[d,pool],errors='coerce') for k,m in feats.items()}
        td=theme_ret[t] if t in theme_ret.columns else pd.Series(index=close.index,dtype=float)
        tr={}
        for n in (5,10,20,63,126,189):
            seg=td.iloc[max(0,p-n+1):p+1].dropna(); tr[n]=float(np.expm1(np.log1p(seg.clip(lower=-.999999)).sum())) if len(seg)>=max(1,int(.8*n)) else np.nan
            x=snap[f'ret{n}']; snap[f'ret{n}_rank']=x.rank(pct=True); snap[f'ret{n}_theme']=x-tr[n]; snap[f'ret{n}_spy']=x-float(spy[n].at[d])
        snap['vol20_rank']=snap['vol20'].rank(pct=True); snap['rvol20_rank']=snap['rvol20'].rank(pct=True)
        snap['compression_rank']=snap['compression_5v20'].rank(pct=True); snap['high63_rank']=snap['dist_prior_high63'].rank(pct=True)
        context={
            'theme_rs_pct':float(getattr(ev,'theme_rs_pct',np.nan)),
            'theme_rank_delta20':float(getattr(ev,'rank_delta20',np.nan)),
            'theme_breadth':float(getattr(ev,'breadth',np.nan)),
            'parent_rs_pct':float(parent.at[d,t]) if t in parent.columns and pd.notna(parent.at[d,t]) else np.nan,
            'theme_member_count':float(len(pool)),
            'theme_disp20':float(snap['ret20'].std()), 'theme_disp63':float(snap['ret63'].std()),
        }
        maps={k:v.to_dict() for k,v in labs.items()}
        for s in pool:
            if any(s not in mp for mp in maps.values()): continue
            r={'date':d,'theme':t,'symbol':s,'event_pos':p,**context}
            for k,x in snap.items(): r[k]=float(x.get(s,np.nan)) if pd.notna(x.get(s,np.nan)) else np.nan
            for k,mp in maps.items(): r[k]=int(mp[s])
            for h in HORIZONS: r[f'fwd_ret{h}']=float(fwd[h].get(s,np.nan))
            r['fwd_mfe63']=float(mfe.get(s,np.nan))
            rows.append(r)
        if (i+1)%500==0: print(f'LTR_ROWS {i+1}/{len(events)} rows={len(rows)}',flush=True)
    return pd.DataFrame(rows)


def feature_cols(df:pd.DataFrame)->list[str]:
    bad={'date','theme','symbol','event_pos'}|{c for c in df if c.startswith('label_') or c.startswith('fwd_')}
    return [c for c in df if c not in bad]


def purge(rows:pd.DataFrame, cal:pd.DatetimeIndex):
    first=int(np.where(cal>=TEST_START)[0][0])
    train=rows[(rows.date<=TRAIN_END)&((rows.event_pos+63)<first)].copy(); test=rows[rows.date>=TEST_START].copy()
    return train,test,{'first_test_date':str(cal[first].date()),'train_last_event':str(train.date.max().date()),'test_first_event':str(test.date.min().date()),'rule':'train event +63 sessions must end before 2022'}


def grouped(df:pd.DataFrame):
    z=df.sort_values(['date','theme','symbol']).reset_index(drop=True)
    g=z.groupby(['date','theme'],sort=False,observed=True).size().astype(int).tolist()
    return z,g


def params(seed:int,n:int):
    return dict(objective='lambdarank',metric='ndcg',n_estimators=n,learning_rate=.03,num_leaves=15,max_depth=5,min_child_samples=50,subsample=.85,subsample_freq=1,colsample_bytree=.8,reg_alpha=.1,reg_lambda=1.,random_state=seed,n_jobs=-1,verbosity=-1)


def fit_ranker(train:pd.DataFrame,features:list[str],label:str,seed:int,cal:pd.DatetimeIndex):
    fv=int(np.where(cal>=pd.Timestamp('2020-01-01'))[0][0]); sub=train[(train.date<pd.Timestamp('2020-01-01'))&((train.event_pos+63)<fv)]; val=train[train.date>=pd.Timestamp('2020-01-01')]
    a,ag=grouped(sub); b,bg=grouped(val)
    probe=lgb.LGBMRanker(**params(seed,700)); probe.fit(a[features],a[label].astype(int),group=ag,eval_set=[(b[features],b[label].astype(int))],eval_group=[bg],eval_at=[1,3],callbacks=[lgb.early_stopping(60,verbose=False)])
    best=int(probe.best_iteration_ or 350); full,fg=grouped(train); model=lgb.LGBMRanker(**params(seed,best)); model.fit(full[features],full[label].astype(int),group=fg)
    return model,best


def add_preds(test:pd.DataFrame,features:list[str],models:dict[str,lgb.LGBMRanker]):
    z=test.copy()
    for name,m in models.items():
        z[f'pred_{name}']=m.predict(z[features]); z[f'rank_{name}']=z.groupby(['date','theme'],observed=True)[f'pred_{name}'].rank(pct=True)
    z['pred_ensemble']=z[[f'rank_{n}' for n in models]].mean(axis=1)
    return z


def choose(g:pd.DataFrame,col:str,n:int): return list(g.sort_values([col,'symbol'],ascending=[False,True]).head(n).symbol)

def cost(r:float): return float(r)-2*COST_BPS_SIDE/10000 if pd.notna(r) else np.nan


def evaluate(test:pd.DataFrame,close:pd.DataFrame,open_:pd.DataFrame,high:pd.DataFrame,low:pd.DataFrame,spy_open:pd.Series,spy_close:pd.Series):
    pos={pd.Timestamp(d):i for i,d in enumerate(close.index)}; rows=[]
    specs={'THEME_EQ':None,'RS63_TOP3':('ret63',3),'RS189_TOP3':('ret189',3),'AI20_TOP3':('pred_ret20',3),'AI40_TOP3':('pred_ret40',3),'AI63_TOP3':('pred_ret63',3),'AIMFE63_TOP3':('pred_mfe63',3),'AI_ENSEMBLE_TOP3':('pred_ensemble',3),'AI_ENSEMBLE_TOP1':('pred_ensemble',1)}
    for (d,t),g in test.groupby(['date','theme'],observed=True,sort=True):
        d=pd.Timestamp(d); p=pos.get(d,-1); pool=list(g.symbol)
        if p<0 or p+63>=len(close) or len(pool)<MIN_POOL: continue
        for method,spec in specs.items():
            sel=pool if spec is None else choose(g.dropna(subset=[spec[0]]),spec[0],spec[1])
            if not sel: continue
            rec={'date':d,'theme':str(t),'method':method,'strength':float(g.theme_rs_pct.iloc[0]),'pool_count':len(pool),'selected_count':len(sel)}; ep=p+1; ed=close.index[ep]
            for h in HORIZONS:
                sr=base.buy_hold_returns_from_open(open_,close,sel,ep,p+h); tr=base.buy_hold_returns_from_open(open_,close,pool,ep,p+h)
                raw=float(sr.mean()) if len(sr)==len(sel) else np.nan; theme=float(tr.mean()) if len(tr)>=MIN_POOL else np.nan
                se=spy_open.at[ed]; sz=spy_close.iloc[p+h]; spr=float(sz/se-1) if pd.notna(se) and pd.notna(sz) and se>0 else np.nan
                rec[f'ret_{h}']=raw; rec[f'ret_cost_{h}']=cost(raw); rec[f'vs_theme_{h}']=raw-theme if pd.notna(raw) and pd.notna(theme) else np.nan; rec[f'vs_spy_{h}']=raw-spr if pd.notna(raw) and pd.notna(spr) else np.nan
                allr=base.buy_hold_returns_from_open(open_,close,pool,ep,p+h); ranks=allr.rank(pct=True) if len(allr)>=MIN_POOL else pd.Series(dtype=float); picked=[s for s in sel if s in ranks.index]
                rec[f'top_third_hit_{h}']=float((ranks.loc[picked]>=2/3).mean()) if picked else np.nan; rec[f'winner_capture_{h}']=float(str(allr.idxmax()) in picked) if len(allr)>=MIN_POOL else np.nan
            future=close.index[ep:p+64]; mf=[]; ma=[]
            for s in sel:
                e=float(open_.at[ed,s]); hs=high.loc[future,s].dropna(); ls=low.loc[future,s].dropna()
                if e>0 and len(hs): mf.append(float(hs.max()/e-1));
                if e>0 and len(ls): ma.append(float(ls.min()/e-1))
            rec['mfe63']=float(np.mean(mf)) if mf else np.nan; rec['mae63']=float(np.mean(ma)) if ma else np.nan; rows.append(rec)
    return pd.DataFrame(rows)


def ss(s:pd.Series):
    x=pd.to_numeric(s,errors='coerce').dropna()
    if x.empty:return {'n':0}
    return {'n':int(len(x)),'mean':float(x.mean()),'median':float(x.median()),'positive_rate':float((x>0).mean()),'p10':float(x.quantile(.1)),'p90':float(x.quantile(.9)),'p95':float(x.quantile(.95))}


def paired(ev:pd.DataFrame,method:str,baseline:str,metric:str,cal:pd.DatetimeIndex,fam:dict[str,str],sets:dict[str,set[str]],seed:int):
    a=ev[ev.method==method][['date','theme','strength',metric]].rename(columns={metric:'a'}); b=ev[ev.method==baseline][['date','theme',metric]].rename(columns={metric:'b'}); m=a.merge(b,on=['date','theme']); m[metric]=m.a-m.b
    modes=rt.aggregate_modes(m,metric,fam,sets); return {'point':ss(m[metric]),'robust':{k:rt.summary(v,metric,cal,seed+i) for i,(k,v) in enumerate(modes.items())}}


def importance(models:dict[str,lgb.LGBMRanker],test:pd.DataFrame,features:list[str]):
    sample=test.sort_values(['date','theme','symbol']).head(20000); agg=pd.Series(0.,index=features); out={}
    for name,m in models.items():
        arr=np.asarray(m.booster_.predict(sample[features],pred_contrib=True)); vals=pd.Series(np.nanmean(np.abs(arr[:,:len(features)]),axis=0),index=features).sort_values(ascending=False); norm=vals/vals.sum(); agg=agg.add(norm,fill_value=0)
        out[name]={'mean_abs_shap_top25':[{'feature':k,'value':float(v)} for k,v in vals.head(25).items()]}
    agg=(agg/len(models)).sort_values(ascending=False); out['ensemble_top30']=[{'feature':k,'value':float(v)} for k,v in agg.head(30).items()]; return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output',required=True); ap.add_argument('--analysis-start',default='2016-01-04'); ap.add_argument('--analysis-end',default='2026-06-30'); ap.add_argument('--max-tickers',type=int,default=6000); ap.add_argument('--batch-size',type=int,default=75); ap.add_argument('--min-members',type=int,default=3); args=ap.parse_args()
    root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)
    snap=er.load_json(root/'sector_snapshot.json'); all_members,tax=er.extract_theme_members(snap); ind=er.read_industry_map(root/'industry_map.json'); universe=er.read_universe_symbols(root/'universe.csv'); selected=er.stratified_symbols(all_members,set(ind)&universe,args.max_tickers); req=selected+(['SPY'] if 'SPY' not in selected else [])
    ohlcv,diag=base.rtv2.download_ohlcvo(req,str((pd.Timestamp(args.analysis_start)-pd.Timedelta(days=900)).date()),str((pd.Timestamp(args.analysis_end)+pd.Timedelta(days=140)).date()),args.batch_size)
    ca,oa,ha,la,va=(ohlcv[k] for k in ('close','open','high','low','volume')); cols=[s for s in selected if s in ca.columns]; close,open_,high,low,vol=ca[cols],oa[cols],ha[cols],la[cols],va[cols]; stock_ret=close.pct_change(fill_method=None); spy_ret=ca.SPY.pct_change(fill_method=None)
    members={t:[s for s in m if s in cols] for t,m in all_members.items()}; counts={t:len(m) for t,m in members.items()}; theme_ret=er.grouped_equal_weight(stock_ret,members,args.min_members); spy63=er.period_return(spy_ret,63); theme63=er.period_return(theme_ret,63); theme_pct=theme63.sub(spy63,axis=0).rank(axis=1,pct=True)*100; breadth=er.breadth_above_ema21(close,members,args.min_members).reindex(columns=theme_ret.columns)
    ig=defaultdict(list)
    for s in cols:
        if s in ind and ind[s][1]: ig[ind[s][1]].append(s)
    ir=er.grouped_equal_weight(stock_ret,dict(ig),args.min_members); iw=er.build_parent_weights(all_members,ind); ip=er.period_return(ir,63).sub(spy63,axis=0).rank(axis=1,pct=True)*100; parent=er.weighted_matrix(ip,iw,list(theme_ret.columns)).reindex(columns=theme_ret.columns)
    events=er.extract_events(cl.momentum_mask(theme_pct,parent,breadth),theme_pct,parent,breadth,counts,pd.Timestamp(args.analysis_start),pd.Timestamp(args.analysis_end)).sort_values(['date','theme']).reset_index(drop=True)
    feats=make_features(ohlcv,cols); ema21=close.ewm(span=21,adjust=False,min_periods=15).mean(); sma50=close.rolling(50,min_periods=35).mean(); dv20=(close*vol).rolling(20,min_periods=15).mean(); rows=build_rows(events,close,open_,high,stock_ret,ca.SPY,theme_ret,parent,members,feats,dv20,ema21,sma50)
    if rows.empty: raise RuntimeError('No rows'); rows.to_csv(out/'ltr_event_stock_rows.csv.gz',index=False,compression='gzip')
    features=feature_cols(rows); train,test,pdiag=purge(rows,close.index); train_events=train[['date','theme']].drop_duplicates().shape[0]; test_events=test[['date','theme']].drop_duplicates().shape[0]
    models={}; best={}; labels={'ret20':'label_ret20','ret40':'label_ret40','ret63':'label_ret63','mfe63':'label_mfe63'}
    for i,(n,lbl) in enumerate(labels.items()): print('FIT',n,flush=True); models[n],best[n]=fit_ranker(train,features,lbl,38+i,close.index)
    pred=add_preds(test,features,models); pred.to_csv(out/'ltr_holdout_predictions.csv.gz',index=False,compression='gzip'); ev=evaluate(pred,close,open_,high,low,oa.SPY,ca.SPY); ev.to_csv(out/'ltr_holdout_method_rows.csv.gz',index=False,compression='gzip')
    fam=rt.primary_family(members,ind); sets={t:set(m) for t,m in members.items()}; methods=sorted(ev.method.unique()); result={'status':'PRELIMINARY_CURRENT_TAXONOMY_THEME_LTR_HOLDOUT','bias_warning':'Current universe/current taxonomy are retrospectively applied; absolute returns are not survivorship-free. Method comparisons use identical holdout events/pools.','design':{'train':'2016-2021 purged; no 63-session label crosses into 2022','internal_validation':'purged pre-2020 train vs 2020-2021 validation only for best iteration','test':'untouched 2022-2026','model':'LightGBM LambdaMART ranking four targets (20d/40d/63d return relevance + 63d MFE relevance) plus equal-rank ensemble','best_iterations':best,'features':features,'cost_bps_per_side':COST_BPS_SIDE},'download':diag,'taxonomy':tax,'purge':pdiag,'coverage':{'stocks':len(cols),'theme_events':int(len(events)),'event_stock_rows':int(len(rows)),'train_rows':int(len(train)),'train_events':int(train_events),'test_rows':int(len(test)),'test_events':int(test_events)},'methods':{},'paired_vs_rs63':{},'paired_vs_rs189':{},'paired_vs_theme_eq':{},'feature_importance':importance(models,pred)}
    for m in methods:
        part=ev[ev.method==m]; result['methods'][m]={'events':int(len(part)),'mfe63':ss(part.mfe63),'mae63':ss(part.mae63),'horizons':{str(h):{k:ss(part[f'{k}_{h}']) for k in ('ret','ret_cost','vs_theme','vs_spy','top_third_hit','winner_capture')} for h in HORIZONS}}
    for i,m in enumerate(('AI_ENSEMBLE_TOP3','AI_ENSEMBLE_TOP1')):
        for b,key in (('RS63_TOP3','paired_vs_rs63'),('RS189_TOP3','paired_vs_rs189'),('THEME_EQ','paired_vs_theme_eq')):
            result[key][m]={str(h):paired(ev,m,b,f'ret_cost_{h}',close.index,fam,sets,500000+i*10000+h*100) for h in HORIZONS}
    (out/'summary.json').write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding='utf-8'); print('===THEME_LTR_RESULT==='); print(json.dumps(safe(result),ensure_ascii=False,separators=(',',':'))); print('===END===',flush=True)


if __name__=='__main__': main()
