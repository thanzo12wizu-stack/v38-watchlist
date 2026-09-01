from __future__ import annotations

# Frozen-data wrapper for audit_v38_final_gap_portfolio.py. It patches only input loading:
# the historical TQQQ return and CURRENT30+Panic target come from the exact Stage56 artifact
# previously used by Gross100/Lock-Guard. Reconstructed Stage56 data are used only to identify
# Panic-active dates for the counterfactual FIXED30 target and for timing diagnostics.

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS=252; TAX_RATE=.20315; COST_BPS=10.0; TARGET_COL="target_M30_TOUCH30_F80_D10"


def safe(x:Any)->Any:
    if isinstance(x,dict): return {str(k):safe(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [safe(v) for v in x]
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,(np.floating,float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x


def allocator(t,o,r,floor=.80):
    g=np.column_stack([t,o,r]); out=np.zeros_like(g)
    for i,row in enumerate(g):
        tt,oo,rr=[max(float(x),0.) for x in row]; rem=1.
        ar=min(rr,rem); out[i,2]=ar; rem-=ar
        if tt+oo<=rem+1e-12: out[i,0]=tt; out[i,1]=oo; continue
        p=min(tt,floor,rem); out[i,0]=p; rem-=p
        ao=min(oo,rem); out[i,1]=ao; rem-=ao
        out[i,0]+=min(max(tt-out[i,0],0.),rem)
    return out


def effective(t):
    z=np.zeros(len(t),float); z[2:]=np.asarray(t,float)[:-2]; return z


def scaled(a,go,gr,rt,ro,rr,bps=10.):
    at,ao,ar=a.T
    so=np.divide(ao,go,out=np.zeros_like(ao),where=go>1e-12)
    sr=np.divide(ar,gr,out=np.zeros_like(ar),where=gr>1e-12)
    ret=at*rt+so*ro+sr*rr; c=bps/10000.
    turns=[]
    for x in (at,ao,ar):
        q=np.zeros(len(x)); q[1:]=np.abs(np.diff(x)); turns.append(q)
    ret-=(turns[0]+turns[1]+turns[2])*c
    return ret,{"tqqq":float(turns[0].sum()),"ordinary":float(turns[1].sum()),"reset":float(turns[2].sum()),"total":float(sum(x.sum() for x in turns))}


def met(ret,dates):
    r=np.nan_to_num(np.asarray(ret,float)); d=pd.DatetimeIndex(pd.to_datetime(dates)); eq=np.cumprod(1+r)
    yrs=max((len(r)-1)/252.,1/252.); c=float(eq[-1]**(1/yrs)-1) if eq[-1]>0 else -1.
    pk=np.maximum.accumulate(eq); dd=eq/pk-1; ti=int(np.argmin(dd)); pi=int(np.argmax(eq[:ti+1])); sd=float(np.std(r,ddof=1))
    return {"cagr":c,"mdd":float(dd.min()),"sharpe":float(np.sqrt(252)*np.mean(r)/sd) if sd>0 else None,"end":float(eq[-1]),"mdd_peak":str(d[pi].date()),"mdd_trough":str(d[ti].date())}


def tax(ret,dates):
    s=pd.Series(np.asarray(ret,float),index=pd.DatetimeIndex(pd.to_datetime(dates))); w=1.; losses=[]; paid=0.
    for _,g in s.groupby(s.index.year):
        st=w; pre=st*float(np.prod(1+np.nan_to_num(g.to_numpy(float)))); pnl=pre-st
        losses=[[rem,amt] for rem,amt in losses if rem>0 and amt>1e-15]; taxable=max(0.,pnl)
        losses.sort(key=lambda z:z[0])
        for z in losses:
            use=min(taxable,z[1]); taxable-=use; z[1]-=use
            if taxable<=1e-15: break
        losses=[[rem-1,amt] for rem,amt in losses if amt>1e-15 and rem-1>0]
        if pnl<0: losses.append([3,-pnl])
        tx=taxable*TAX_RATE; w=pre-tx; paid+=tx
    yrs=max((len(s)-1)/252.,1/252.)
    return {"cagr":float(w**(1/yrs)-1),"end":float(w),"paid":float(paid)}


def rolling(ret,dates):
    s=pd.Series(np.asarray(ret,float),index=pd.DatetimeIndex(pd.to_datetime(dates))); z=((1+s).rolling(504).apply(np.prod,raw=True)-1).dropna()
    return {"worst":float(z.min()),"median":float(z.median()),"positive":float((z>0).mean())}


def monthly(ret,dates):
    s=pd.Series(np.asarray(ret,float),index=pd.DatetimeIndex(pd.to_datetime(dates))); m=(1+s).resample("ME").prod()-1
    return {"geom":float(np.prod(1+m.to_numpy())**(1/len(m))-1),"worst":float(m.min()),"ge7":float((m>=.07).mean())}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--components-dir",required=True); ap.add_argument("--frozen-tqqq-dir",required=True); ap.add_argument("--tqqq-spec-dir",required=True); ap.add_argument("--lock-guard-dir",required=True); ap.add_argument("--output",required=True); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    o=pd.read_csv(Path(args.components_dir)/"ordinary_PEAK30_PART25_R3_daily.csv.gz",compression="gzip")
    r=pd.read_csv(Path(args.components_dir)/"rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz",compression="gzip")
    fpath=next(Path(args.frozen_tqqq_dir).rglob("tqqq_stage56_daily.csv.gz")); ft=pd.read_csv(fpath,compression="gzip")
    sp=pd.read_csv(Path(args.tqqq_spec_dir)/"tqqq_fixed30_spec_daily.csv.gz",compression="gzip")
    lg=pd.read_csv(Path(args.lock_guard_dir)/"daily_selective_fill_no_zero_override.csv.gz",compression="gzip")
    for x in (o,r,ft,sp,lg): x["date"]=pd.to_datetime(x["date"]).dt.normalize()
    if TARGET_COL not in ft.columns: raise KeyError(TARGET_COL)
    d=o.merge(r,on="date",suffixes=("_ord","_rsi")).merge(ft[["date","tqqq_ret_usd",TARGET_COL]],on="date",validate="one_to_one")
    d=d.merge(sp[["date","panic_active"]],on="date",how="left",validate="one_to_one")
    d=d.merge(lg[["date","gate_attack_or_selective","breadth_prev_close","nqsar_prev_close","return_10bp"]].rename(columns={"return_10bp":"prior_return"}),on="date",validate="one_to_one").sort_values("date").reset_index(drop=True)
    d["panic_active"]=d["panic_active"].fillna(False).astype(bool)
    fixed_raw=np.where(d.panic_active.to_numpy(),.80,.30)
    native={"CURRENT30":effective(d[TARGET_COL].to_numpy(float)),"FIXED30":effective(fixed_raw)}
    go=d.gross_exposure_ord.to_numpy(float); gr=d.gross_exposure_rsi.to_numpy(float); rt=d.tqqq_ret_usd.to_numpy(float); ro=d.return_ord.to_numpy(float); rr=d.return_rsi.to_numpy(float); gate=d.gate_attack_or_selective.astype(bool).to_numpy(); dates=d.date
    variants={}; paths={}
    for tn,et in native.items():
        for cn,od in (("UNCAPPED",go.copy()),("CAP70",np.minimum(go,.70))):
            b=allocator(et,od,gr); resid=np.maximum(0,1-b.sum(axis=1))
            for fn,fill in (("NOFILL",False),("SELECTIVE_FILL",True)):
                a=b.copy()
                if fill: a[:,0]+=resid*(gate&(et>1e-12))
                name=f"{tn}_{cn}_{fn}"
                if a.sum(axis=1).max()>1+1e-9: raise RuntimeError("gross100 "+name)
                ret,turn=scaled(a,go,gr,rt,ro,rr,COST_BPS); paths[name]=ret
                periods={}
                for lab,lo,hi in (("2016_2021","2016-01-04","2021-12-31"),("2022_2026M3","2022-01-01","2026-03-20"),("2022_2023","2022-01-01","2023-12-31"),("2024_2026M3","2024-01-01","2026-03-20")):
                    m=((dates>=lo)&(dates<=hi)).to_numpy(); periods[lab]=met(ret[m],dates.loc[m])
                variants[name]={"full":met(ret,dates),"periods":periods,"tax_proxy":tax(ret,dates),"rolling2y":rolling(ret,dates),"monthly":monthly(ret,dates),"turnover":turn,"allocation":{"avg_tqqq":float(a[:,0].mean()),"avg_ordinary":float(a[:,1].mean()),"avg_reset":float(a[:,2].mean()),"avg_gross":float(a.sum(axis=1).mean()),"max_ordinary":float(a[:,1].max()),"ordinary_over70_days":int((a[:,1]>.700000000001).sum()),"fill_days":int(((a[:,0]-b[:,0])>1e-12).sum())}}
                pd.DataFrame({"date":dates,"return_10bp":ret,"alloc_tqqq":a[:,0],"alloc_ordinary":a[:,1],"alloc_reset":a[:,2],"native_eff_tqqq":et,"ordinary_original":go,"ordinary_demand":od,"gate":gate}).to_csv(out/f"daily_{name.lower()}.csv.gz",index=False,compression="gzip")
    diff=np.abs(paths["CURRENT30_UNCAPPED_SELECTIVE_FILL"]-d.prior_return.to_numpy(float)); mx=float(diff.max()); q99=float(np.quantile(diff,.99))
    # Frozen Stage56 input should reproduce the prior Lock-Guard path to numerical CSV precision.
    if mx>5e-10: raise RuntimeError(f"frozen reproduction failed max={mx} p99={q99}")
    rows=[]
    for n,v in variants.items():
        rows.append({"variant":n,"cagr":v["full"]["cagr"],"mdd":v["full"]["mdd"],"sharpe":v["full"]["sharpe"],"tax_proxy_cagr":v["tax_proxy"]["cagr"],"cagr_2016_2021":v["periods"]["2016_2021"]["cagr"],"cagr_2022_2026M3":v["periods"]["2022_2026M3"]["cagr"],"rolling2y_worst":v["rolling2y"]["worst"],"avg_gross":v["allocation"]["avg_gross"],"avg_tqqq":v["allocation"]["avg_tqqq"],"avg_ordinary":v["allocation"]["avg_ordinary"],"ordinary_over70_days":v["allocation"]["ordinary_over70_days"],"fill_days":v["allocation"]["fill_days"]})
    pd.DataFrame(rows).sort_values("cagr",ascending=False).to_csv(out/"comparison.csv",index=False)
    result={"status":"V38_FINAL_SPEC_FACTORIAL_FROZEN","coverage":{"start":str(d.date.min().date()),"end":str(d.date.max().date()),"sessions":len(d)},"frozen_inputs":{"stage56_artifact":"9649902954","component_artifact":"9739833328","lock_guard_artifact":"9790852808"},"reproduction":{"max_abs_daily_return_diff":mx,"p99_abs_diff":q99,"passed":True},"ordinary_original_gross":{"mean":float(go.mean()),"max":float(go.max()),"days_over70":int((go>.700000000001).sum())},"variants":variants}
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print(pd.DataFrame(rows).sort_values("cagr",ascending=False).to_string(index=False)); print("=== FINAL_SPEC_FROZEN_JSON ==="); print(json.dumps(safe(result),ensure_ascii=False,indent=2)); print("=== END_FINAL_SPEC_FROZEN_JSON ===")

if __name__=="__main__": main()
