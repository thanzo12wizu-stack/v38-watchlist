from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

TARGET_COL = "target_M30_TOUCH30_F80_D10"
TAX_RATE = 0.20315
ALLOC_COST_BPS = 10.0
TRADING_DAYS = 252


def safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z=float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def allocator(tqqq: np.ndarray, ordinary: np.ndarray, reset: np.ndarray, floor: float=.80) -> np.ndarray:
    out=np.zeros((len(tqqq),3),float)
    for i,(t,o,r) in enumerate(zip(tqqq,ordinary,reset)):
        t,o,r=max(float(t),0.),max(float(o),0.),max(float(r),0.); rem=1.
        ar=min(r,rem); out[i,2]=ar; rem-=ar
        if t+o<=rem+1e-12:
            out[i,0]=t; out[i,1]=o; continue
        p=min(t,floor,rem); out[i,0]=p; rem-=p
        ao=min(o,rem); out[i,1]=ao; rem-=ao
        out[i,0]+=min(max(t-out[i,0],0.),rem)
    return out


def effective(t: np.ndarray) -> np.ndarray:
    z=np.zeros(len(t),float); z[2:]=np.asarray(t,float)[:-2]; return z


def metrics(ret: np.ndarray, dates: pd.Series) -> dict[str,Any]:
    r=np.nan_to_num(np.asarray(ret,float)); d=pd.DatetimeIndex(pd.to_datetime(dates)); eq=np.cumprod(1+r)
    yrs=max((len(r)-1)/TRADING_DAYS,1/TRADING_DAYS); cagr=float(eq[-1]**(1/yrs)-1) if eq[-1]>0 else -1.
    peak=np.maximum.accumulate(eq); dd=eq/peak-1; ti=int(np.argmin(dd)); pi=int(np.argmax(eq[:ti+1])); sd=float(np.std(r,ddof=1))
    return {"cagr":cagr,"mdd":float(dd.min()),"sharpe":float(np.sqrt(TRADING_DAYS)*r.mean()/sd) if sd>0 else None,"end":float(eq[-1]),"mdd_peak":str(d[pi].date()),"mdd_trough":str(d[ti].date())}


def tax_proxy(ret: np.ndarray, dates: pd.Series) -> dict[str,float]:
    s=pd.Series(np.asarray(ret,float),index=pd.DatetimeIndex(pd.to_datetime(dates))); w=1.; losses=[]; paid=0.
    for _,g in s.groupby(s.index.year):
        start=w; pre=start*float(np.prod(1+np.nan_to_num(g.to_numpy(float)))); pnl=pre-start
        losses=[[rem,amt] for rem,amt in losses if rem>0 and amt>1e-15]; taxable=max(0.,pnl); losses.sort(key=lambda z:z[0])
        for z in losses:
            use=min(taxable,z[1]); taxable-=use; z[1]-=use
            if taxable<=1e-15: break
        losses=[[rem-1,amt] for rem,amt in losses if amt>1e-15 and rem-1>0]
        if pnl<0: losses.append([3,-pnl])
        tx=taxable*TAX_RATE; w=pre-tx; paid+=tx
    yrs=max((len(s)-1)/TRADING_DAYS,1/TRADING_DAYS)
    return {"cagr":float(w**(1/yrs)-1),"end":float(w),"tax_paid":float(paid)}


def monthly(ret: np.ndarray, dates: pd.Series) -> dict[str,float]:
    s=pd.Series(ret,index=pd.DatetimeIndex(pd.to_datetime(dates))); m=(1+s).resample("ME").prod()-1
    return {"geom":float(np.prod(1+m.to_numpy(float))**(1/len(m))-1),"worst":float(m.min()),"ge7":float((m>=.07).mean()),"positive":float((m>0).mean())}


def rolling2(ret: np.ndarray, dates: pd.Series) -> dict[str,float]:
    s=pd.Series(ret,index=pd.DatetimeIndex(pd.to_datetime(dates))); z=((1+s).rolling(504).apply(np.prod,raw=True)-1).dropna()
    return {"worst":float(z.min()),"p10":float(z.quantile(.10)),"median":float(z.median()),"positive":float((z>0).mean())}


def fmp_delisted_pages(max_pages: int=100) -> dict[str,Any]:
    key=os.environ.get("FMP_API_KEY","").strip()
    if not key: return {"status":"UNAVAILABLE","reason":"FMP_API_KEY_NOT_CONFIGURED"}
    rows=[]; page_sizes=[]; endpoint="https://financialmodelingprep.com/stable/delisted-companies"
    try:
        for page in range(max_pages):
            params={"page":page,"limit":100,"apikey":key}
            req=Request(endpoint+"?"+urlencode(params),headers={"User-Agent":"V38-final-audit/1.0"})
            with urlopen(req,timeout=20) as resp: payload=json.loads(resp.read().decode("utf-8"))
            batch=payload if isinstance(payload,list) else []
            page_sizes.append(len(batch))
            if not batch: break
            rows.extend([x for x in batch if isinstance(x,dict)])
            if len(batch)<100: break
        df=pd.DataFrame(rows)
        if df.empty: return {"status":"UNAVAILABLE","reason":"NO_ROWS","page_sizes":page_sizes}
        dt=pd.to_datetime(df.get("delistedDate"),errors="coerce")
        win=(dt>=pd.Timestamp("2016-01-01"))&(dt<=pd.Timestamp("2026-03-20"))
        exch=df.get("exchange",pd.Series("UNKNOWN",index=df.index)).fillna("UNKNOWN").astype(str)
        us=exch.str.upper().isin(["NASDAQ","NYSE","AMEX","NYSE AMERICAN"])
        return {"status":"READY","endpoint":endpoint,"pages_requested":len(page_sizes),"page_sizes":page_sizes,"rows":int(len(df)),"window_2016_2026M3":int(win.sum()),"us_major_exchange_window":int((win&us).sum()),"exchange_counts_window":exch[win].value_counts().head(20).to_dict(),"note":"Count diagnoses omitted historical exits; it does not by itself reconstruct a PIT-eligible historical stock universe."}
    except Exception as exc:
        return {"status":"UNAVAILABLE","reason":f"{type(exc).__name__}: {exc}","rows_partial":len(rows),"page_sizes":page_sizes}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--final-gap-dir",required=True); ap.add_argument("--components-dir",required=True); ap.add_argument("--stage56-dir",required=True); ap.add_argument("--lock-dir",required=True); ap.add_argument("--output",required=True); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    ordinary=pd.read_csv(next(Path(args.components_dir).rglob("ordinary_PEAK30_PART25_R3_daily.csv.gz")),compression="gzip")
    reset=pd.read_csv(next(Path(args.components_dir).rglob("rsi_RESET_RISE30_S029_P4_H20_daily.csv.gz")),compression="gzip")
    tq=pd.read_csv(next(Path(args.stage56_dir).rglob("tqqq_stage56_daily.csv.gz")),compression="gzip")
    gate=pd.read_csv(next(Path(args.lock_dir).rglob("daily_selective_fill_no_zero_override.csv.gz")),compression="gzip")
    exdir=next(Path(args.final_gap_dir).rglob("v38_gap_ordinary"))
    ex={}
    for bps in (0,10,25,50):
        z=pd.read_csv(exdir/f"daily_final_theme_attack_{bps}bp.csv"); z["date"]=pd.to_datetime(z.date).dt.normalize(); z["ret"]=z.nav.pct_change(fill_method=None).fillna(0.); ex[bps]=z
    for z in (ordinary,reset,tq,gate): z["date"]=pd.to_datetime(z.date).dt.normalize()
    d=ordinary.merge(reset,on="date",suffixes=("_ord","_rsi")).merge(tq[["date","tqqq_ret_usd",TARGET_COL]],on="date",validate="one_to_one").merge(gate[["date","gate_attack_or_selective"]],on="date",validate="one_to_one").sort_values("date").reset_index(drop=True)
    # Audit re-run data drift at 0bp; execution stress uses relative factor so frozen baseline remains exact.
    x=ex[0][["date","nav","ret"]].rename(columns={"nav":"nav0","ret":"ret0"})
    for bps in (10,25,50): x=x.merge(ex[bps][["date","nav","ret"]].rename(columns={"nav":f"nav{bps}","ret":f"ret{bps}"}),on="date",validate="one_to_one")
    frozen_ord=d.return_ord.to_numpy(float); frozen_cagr=metrics(frozen_ord,d.date)["cagr"]; rerun0_cagr=metrics(x.ret0.to_numpy(float),x.date)["cagr"]
    stressed={0:frozen_ord.copy()}
    for bps in (10,25,50):
        ratio=np.divide(1+x[f"ret{bps}"].to_numpy(float),1+x.ret0.to_numpy(float),out=np.ones(len(x)),where=np.abs(1+x.ret0.to_numpy(float))>1e-12)
        stressed[bps]=(1+frozen_ord)*ratio-1

    eff=effective(d[TARGET_COL].to_numpy(float)); go=d.gross_exposure_ord.to_numpy(float); gr=d.gross_exposure_rsi.to_numpy(float); od=np.minimum(go,.70)
    alloc=allocator(eff,od,gr); residual=np.maximum(0,1-alloc.sum(axis=1)); fill=d.gate_attack_or_selective.astype(bool).to_numpy()&(eff>1e-12); alloc[:,0]+=residual*fill
    at,ao,ar=alloc.T; so=np.divide(ao,go,out=np.zeros_like(ao),where=go>1e-12); sr=np.divide(ar,gr,out=np.zeros_like(ar),where=gr>1e-12)
    alloc_turn=np.zeros(len(d));
    for a in (at,ao,ar):
        z=np.zeros(len(a)); z[1:]=np.abs(np.diff(a)); alloc_turn+=z
    alloc_drag=alloc_turn*(ALLOC_COST_BPS/10000.)

    results={}; rows=[]
    for bps in (0,10,25,50):
        ret=at*d.tqqq_ret_usd.to_numpy(float)+so*stressed[bps]+sr*d.return_rsi.to_numpy(float)-alloc_drag
        periods={}
        for lab,lo,hi in (("2016_2021","2016-01-04","2021-12-31"),("2022_2026M3","2022-01-01","2026-03-20"),("2022_2023","2022-01-01","2023-12-31"),("2024_2026M3","2024-01-01","2026-03-20")):
            m=((d.date>=lo)&(d.date<=hi)).to_numpy(); periods[lab]=metrics(ret[m],d.date.loc[m])
        results[str(bps)]={"full":metrics(ret,d.date),"tax_proxy":tax_proxy(ret,d.date),"monthly":monthly(ret,d.date),"rolling2y":rolling2(ret,d.date),"periods":periods}
        row={"ordinary_constituent_cost_bps":bps,"cagr":results[str(bps)]["full"]["cagr"],"mdd":results[str(bps)]["full"]["mdd"],"sharpe":results[str(bps)]["full"]["sharpe"],"tax_proxy_cagr":results[str(bps)]["tax_proxy"]["cagr"],"cagr_2016_2021":periods["2016_2021"]["cagr"],"cagr_2022_2026M3":periods["2022_2026M3"]["cagr"],"rolling2y_worst":results[str(bps)]["rolling2y"]["worst"],"geom_month":results[str(bps)]["monthly"]["geom"]}; rows.append(row)
        pd.DataFrame({"date":d.date,"return":ret,"ordinary_stressed_return":stressed[bps],"alloc_tqqq":at,"alloc_ordinary":ao,"alloc_reset":ar}).to_csv(out/f"daily_final_spec_{bps}bp.csv.gz",index=False,compression="gzip")
    pd.DataFrame(rows).to_csv(out/"final_execution_stress.csv",index=False)
    result={"status":"V38_FINAL_EXECUTION_INTEGRATION","spec":"CURRENT30 + Normal Stock cap70 + SELECTIVE_FILL_NO_ZERO_OVERRIDE + Reset + Gross100","method":{"ordinary_execution_stress":"Transfer the multiplicative 0bp->Xbp return-factor drag from the fresh exact-mechanics execution rerun onto the frozen ordinary component path. This isolates transaction-cost sensitivity while preserving the frozen research baseline and avoiding Yahoo history drift.","allocator_cost":"Existing 10bp allocated-sleeve-gross turnover drag retained for direct comparability; constituent execution cost is additional internal Normal Stock trading stress.","overnight_gap":"Already present through actual next-session Open execution; no extra gap penalty."},"drift_check":{"frozen_ordinary_cagr":frozen_cagr,"fresh_rerun_0bp_cagr":rerun0_cagr,"cagr_diff_pp":(rerun0_cagr-frozen_cagr)*100,"frozen_final_nav":float(ordinary.nav.iloc[-1]),"fresh_rerun_final_nav":float(x.nav0.iloc[-1])},"allocation":{"avg_tqqq":float(at.mean()),"avg_ordinary":float(ao.mean()),"avg_reset":float(ar.mean()),"avg_gross":float(alloc.sum(axis=1).mean()),"max_ordinary":float(ao.max()),"ordinary_over70_days":int((ao>.700000000001).sum()),"fill_days":int(fill.sum())},"execution_stress":results,"survivorship_probe":fmp_delisted_pages()}
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False)); print("=== FINAL_EXECUTION_INTEGRATION_JSON ==="); print(json.dumps(safe(result),ensure_ascii=False,indent=2)); print("=== END_FINAL_EXECUTION_INTEGRATION_JSON ===")

if __name__=="__main__": main()
