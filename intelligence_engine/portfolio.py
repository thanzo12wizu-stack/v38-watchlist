from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PORTFOLIO_POLICY_VERSION = "2.0.0"
DEFAULT_POSITION_WEIGHT = 0.08
MAX_POSITIONS = 6
MARKET_EXPOSURE_CAP = {"BLUE":1.00,"GREEN":0.75,"YELLOW":0.35,"RED":0.00}


def load_positions(path:Path)->pd.DataFrame:
    cols=["ticker","weight","shares","cost_basis","entry_date","stop_method","entry_stage","first_pivot_date","second_pivot_date","partial_taken"]
    if not path.exists(): return pd.DataFrame(columns=cols)
    f=pd.read_csv(path); m={str(c).strip().lower():c for c in f.columns}; aliases={"ticker":("ticker","symbol","ティッカー","シンボル"),"weight":("weight","portfolio_weight","比率","ウェイト"),"shares":("shares","quantity","数量","株数"),"cost_basis":("cost_basis","entry_price","取得単価","建値"),"entry_date":("entry_date","start_date","保有開始日"),"stop_method":("stop_method","trail","撤退方法"),"entry_stage":("entry_stage","stage","エントリー段階"),"first_pivot_date":("first_pivot_date","1st_pivot_date"),"second_pivot_date":("second_pivot_date","2nd_pivot_date"),"partial_taken":("partial_taken","partial_profit_taken","部分利確済み")}
    out=pd.DataFrame(index=f.index)
    for target,names in aliases.items():
        src=next((m[n.lower()] for n in names if n.lower() in m),None); out[target]=f[src] if src is not None else None
    out["ticker"]=out["ticker"].astype(str).str.upper().str.strip(); out=out[out.ticker.ne("")&out.ticker.ne("NAN")].drop_duplicates("ticker")
    for c in ("weight","shares","cost_basis"): out[c]=pd.to_numeric(out[c],errors="coerce")
    out["entry_stage"]=pd.to_numeric(out["entry_stage"],errors="coerce").fillna(2).clip(1,2)
    out["partial_taken"]=out["partial_taken"].astype(str).str.lower().isin({"1","true","yes","y","済","済み"})
    if out.weight.notna().sum()==0: out["weight"]=DEFAULT_POSITION_WEIGHT
    else:
        total=float(out.weight.fillna(0).sum())
        if total>1.000001: out["weight"]=out.weight.fillna(0)/total
        else: out["weight"]=out.weight.fillna(0)
    return out.reset_index(drop=True)


def _correlation_cluster(positions,pmap):
    series={}
    for t in positions.ticker:
        f=pmap.get(t)
        if f is None: continue
        c=next((x for x in f.columns if str(x).lower().replace(" ","_") in {"close","adj_close","adjclose"}),None)
        if c is not None:
            s=pd.to_numeric(f[c],errors="coerce").dropna().tail(64)
            if len(s)>=30: series[t]=s.pct_change(fill_method=None)
    if len(series)<2:return {"average_pairwise_correlation":None,"high_correlation_pairs":[],"coverage":len(series)}
    corr=pd.DataFrame(series).corr(min_periods=20); pairs=[]; vals=[]; names=list(corr.columns)
    for i,l in enumerate(names):
        for r in names[i+1:]:
            v=corr.loc[l,r]
            if pd.notna(v):
                vals.append(float(v))
                if v>=.75:pairs.append({"left":l,"right":r,"correlation":round(float(v),3)})
    return {"average_pairwise_correlation":round(float(np.mean(vals)),3) if vals else None,"high_correlation_pairs":sorted(pairs,key=lambda x:-x["correlation"])[:10],"coverage":len(series)}


def build_portfolio_doctor(positions:pd.DataFrame,scored:pd.DataFrame,prices:dict[str,pd.DataFrame],market_state:dict[str,Any])->dict[str,Any]:
    if positions.empty:return {"status":"NO_POSITIONS","position_count":0,"positions":[],"warnings":["portfolio_input_missing"]}
    lookup=scored.set_index("ticker",drop=False); records=[]; now=pd.Timestamp.utcnow().tz_localize(None).normalize(); regime=str(market_state.get("regime") or "GREEN"); exposure_cap=MARKET_EXPOSURE_CAP.get(regime,.5)
    for _,p in positions.iterrows():
        t=str(p.ticker); row=lookup.loc[t] if t in lookup.index else pd.Series(dtype=object); price=pd.to_numeric(row.get("price"),errors="coerce"); cost=pd.to_numeric(p.get("cost_basis"),errors="coerce"); method=str(p.get("stop_method") or "21EMA_LOW").upper(); stop=pd.to_numeric(row.get("stop_sma10") if "10" in method else row.get("stop_ema21_low"),errors="coerce")
        gain=float(price/cost-1) if pd.notna(price) and pd.notna(cost) and cost else None; partial_due=bool(gain is not None and gain>=.25 and not bool(p.get("partial_taken")))
        if bool(p.get("partial_taken")) and pd.notna(cost): stop=max(float(stop) if pd.notna(stop) else 0,float(cost))
        stop_distance=float(price/stop-1)*100 if pd.notna(price) and pd.notna(stop) and stop else None; entry=pd.to_datetime(p.get("entry_date"),errors="coerce"); held=int((now-entry.normalize()).days) if pd.notna(entry) else None; fp=pd.to_datetime(p.get("first_pivot_date"),errors="coerce"); sp=pd.to_datetime(p.get("second_pivot_date"),errors="coerce"); first_age=int((now-fp.normalize()).days) if pd.notna(fp) else held; stage=int(p.get("entry_stage") or 2); action="HOLD"; reasons=[]
        if bool(row.get("hard_block",False)) or (stop_distance is not None and stop_distance<=0):action="EXIT";reasons.append("stop_or_hard_block")
        elif stage==1 and first_age is not None and first_age>=10 and pd.isna(sp):action="EXIT";reasons.append("second_pivot_missing_10d")
        elif stage==1 and first_age is not None and first_age>=5 and pd.isna(sp):action="REDUCE";reasons.append("second_pivot_late")
        elif stop_distance is not None and stop_distance<=2:action="REDUCE";reasons.append("stop_near")
        elif row.get("story_phase") in {"DETERIORATING","MARGIN_PRESSURE","DILUTING"} or row.get("theme_phase")=="WEAKENING":action="REDUCE";reasons.append("fundamental_or_theme_weakness")
        elif stage==1 and row.get("setup") in {"PULLBACK","PRE_BREAKOUT"} and market_state.get("entry_gate") in {"ALLOW","SELECTIVE"}:action="ADD";reasons.append("second_half_candidate")
        if partial_due:reasons.append("take_25pct_partial")
        w=float(p.get("weight") or DEFAULT_POSITION_WEIGHT); adr=pd.to_numeric(row.get("adr_pct"),errors="coerce")
        records.append({"ticker":t,"weight":round(w,6),"target_full_weight":DEFAULT_POSITION_WEIGHT,"entry_stage":stage,"price":None if pd.isna(price) else float(price),"cost_basis":None if pd.isna(cost) else float(cost),"gain_pct":None if gain is None else round(gain*100,2),"held_days":held,"first_pivot_age_days":first_age,"sector":row.get("sector"),"theme":row.get("theme"),"adr_pct":None if pd.isna(adr) else float(adr),"stop_method":method,"stop":None if pd.isna(stop) else float(stop),"stop_distance_pct":None if stop_distance is None else round(stop_distance,2),"risk_contribution_pct":round(w*max(0,float(stop_distance or 0)),3),"partial_take_due":partial_due,"action":action,"reasons":reasons})
    weights=pd.Series({r["ticker"]:r["weight"] for r in records}); sector={};theme={}
    for r in records: sector[str(r.get("sector") or "Unknown")]=sector.get(str(r.get("sector") or "Unknown"),0)+r["weight"];theme[str(r.get("theme") or "Unknown")]=theme.get(str(r.get("theme") or "Unknown"),0)+r["weight"]
    corr=_correlation_cluster(positions,prices); total=float(weights.sum()); warnings=[]
    if len(records)>MAX_POSITIONS:warnings.append("max_position_count_exceeded")
    if total>exposure_cap:warnings.append("market_exposure_cap_exceeded")
    if weights.max()>DEFAULT_POSITION_WEIGHT*1.25:warnings.extend(["single_position_above_rule","single_position_concentration"])
    if sector and max(sector.values())>.40:warnings.append("sector_concentration")
    if theme and max(theme.values())>.24:warnings.append("theme_concentration")
    if corr.get("average_pairwise_correlation") is not None and corr["average_pairwise_correlation"]>=.65:warnings.append("correlation_concentration")
    hhi=float((weights**2).sum()) if len(weights) else 0
    return {"status":"OK","policy_version":PORTFOLIO_POLICY_VERSION,"position_count":len(records),"max_positions":MAX_POSITIONS,"gross_exposure":round(total,4),"market_exposure_cap":exposure_cap,"exposure_headroom":round(exposure_cap-total,4),"concentration_hhi":round(hhi,4),"effective_position_count":round(1/hhi,2) if hhi else None,"portfolio_adr_pct":round(sum(r["weight"]*(r["adr_pct"] or 0) for r in records),2),"portfolio_stop_risk_pct":round(sum(r["risk_contribution_pct"] for r in records),2),"sector_weights":sector,"theme_weights":theme,"correlation":corr,"positions":sorted(records,key=lambda r:({"EXIT":0,"REDUCE":1,"ADD":2,"HOLD":3}[r["action"]],-r["weight"])),"warnings":sorted(set(warnings))}
