from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf


def norm(x):
    z=pd.DatetimeIndex(pd.to_datetime(x))
    if z.tz is not None: z=z.tz_convert('America/New_York').tz_localize(None)
    return z.normalize()


def cooldown(cond,c=10):
    x=cond.fillna(False).astype(bool); raw=x & ~x.shift(1,fill_value=False)
    out=np.zeros(len(x),bool); last=-10**9
    for i,z in enumerate(raw.to_numpy(bool)):
        if z and i-last>c: out[i]=1; last=i
    return pd.Series(out,index=x.index)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--legacy-state',required=True); ap.add_argument('--output',required=True)
    a=ap.parse_args(); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(a.legacy_state,compression='gzip',parse_dates=['date']).set_index('date').sort_index(); d.index=norm(d.index)
    syms=['QQQ','PSQ','QID','SQQQ']
    x=yf.download(syms,start='2010-01-01',end='2026-04-01',auto_adjust=True,actions=False,progress=False,threads=False)
    op=x['Open'].copy(); op.index=norm(op.index); op=op[~op.index.duplicated(keep='last')].sort_index().reindex(d.index)
    r=pd.DataFrame(index=d.index)
    for s in syms: r[s]=pd.to_numeric(op[s],errors='coerce').shift(-1)/pd.to_numeric(op[s],errors='coerce')-1
    r['PSQ_SYNTH']=-1*r.QQQ; r['QID_SYNTH']=-2*r.QQQ; r['SQQQ_SYNTH']=-3*r.QQQ
    periods={'PRE_2011_2015':('2011-01-03','2015-12-31'),'OVERLAP_2016_2026':('2016-01-04','2026-03-20')}
    daily=[]
    for lab,(aa,bb) in periods.items():
        m=(r.index>=aa)&(r.index<=bb)
        for p,sp in [('PSQ','PSQ_SYNTH'),('QID','QID_SYNTH'),('SQQQ','SQQQ_SYNTH')]:
            z=r.loc[m,[p,sp]].dropna(); diff=z[p]-z[sp]
            daily.append({'period':lab,'product':p,'n':len(z),'corr_actual_synth':float(z.corr().iloc[0,1]),'mean_actual':float(z[p].mean()),'mean_synth':float(z[sp].mean()),'tracking_diff_mean_bp':float(diff.mean()*10000),'tracking_diff_median_abs_bp':float(diff.abs().median()*10000),'tracking_diff_p99_abs_bp':float(diff.abs().quantile(.99)*10000)})
    pd.DataFrame(daily).to_csv(out/'daily_tracking_crosscheck.csv',index=False)

    core=d.core_mc.fillna(False).astype(bool); guard=d.guard.fillna(False).astype(bool); ev=cooldown(core,10)&~guard
    rows=[]; led=[]
    for lab,(aa,bb) in periods.items():
        eidx=np.flatnonzero((ev&(d.index>=aa)&(d.index<=bb)).to_numpy(bool))
        for h in [1,2,3,4]:
            for p,sp in [('PSQ','PSQ_SYNTH'),('QID','QID_SYNTH'),('SQQQ','SQQQ_SYNTH')]:
                act=[]; syn=[]
                for i in eidx:
                    za=r[p].iloc[i+1:i+1+h]; zs=r[sp].iloc[i+1:i+1+h]
                    if len(za)==h and len(zs)==h and za.notna().all() and zs.notna().all():
                        va=float(np.prod(1+za)-1); vs=float(np.prod(1+zs)-1); act.append(va); syn.append(vs)
                        if p=='QID' and h in [1,2]: led.append({'period':lab,'hold':h,'signal_date':d.index[i],'actual_qid':va,'synth_qid':vs,'diff':va-vs,'mc57':d.mc57.iloc[i],'mc_chg5':d.mc_chg5.iloc[i]})
                aa1=np.asarray(act,float); ss1=np.asarray(syn,float)
                rows.append({'period':lab,'hold':h,'product':p,'n':len(aa1),'actual_mean':float(aa1.mean()) if len(aa1) else None,'synth_mean':float(ss1.mean()) if len(ss1) else None,'actual_win':float((aa1>0).mean()) if len(aa1) else None,'synth_win':float((ss1>0).mean()) if len(ss1) else None,'event_corr':float(np.corrcoef(aa1,ss1)[0,1]) if len(aa1)>1 else None,'mean_actual_minus_synth':float((aa1-ss1).mean()) if len(aa1) else None})
    pd.DataFrame(rows).to_csv(out/'event_tracking_crosscheck.csv',index=False); pd.DataFrame(led).to_csv(out/'qid_event_tracking_ledger.csv',index=False)
    summary={'status':'RESEARCH_ONLY_NO_PRODUCTION_CHANGE','daily':daily,'qid_events':[x for x in rows if x['product']=='QID']}
    (out/'summary_v8.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
