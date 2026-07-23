from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _bootstrap_ci(values: pd.Series, *, samples: int = 300, seed: int = 38) -> list[float] | None:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) < 10:
        return None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for index in range(samples):
        means[index] = rng.choice(clean, len(clean), replace=True).mean()
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _profit_factor(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean[clean > 0].sum()); losses = float(-clean[clean < 0].sum())
    if losses <= 0:
        return None if gains <= 0 else 99.0
    return gains / losses


def _qualification(count: int, mean: float | None, ci: list[float] | None, min_samples: int) -> str:
    if count >= max(50, min_samples) and mean is not None and mean > 0 and ci is not None and ci[0] > 0:
        return "QUALIFIED"
    if count >= max(25, int(min_samples * .75)) and mean is not None and mean > 0:
        return "PROMISING"
    return "EXPLORATORY"


def _summary(group: pd.DataFrame, horizon: int, *, min_samples: int, bootstrap_samples: int, seed: int) -> dict[str, Any]:
    excess = pd.to_numeric(group.get(f"excess_{horizon}"), errors="coerce").dropna(); count = int(len(excess))
    if not count:
        return {"samples":0,"qualification":"EXPLORATORY","win_rate":None,"mean_excess_return":None,"median_excess_return":None,"downside_tail_p10":None,"downside_tail_p5":None,"profit_factor":None,"bootstrap_mean_ci95":None,"mean_mfe":None,"mean_mae":None,"stop_rate":None,"target25_rate":None}
    mean = float(excess.mean()); ci = _bootstrap_ci(excess, samples=bootstrap_samples, seed=seed+horizon+count)
    tickers = group.loc[excess.index,"ticker"].astype(str) if "ticker" in group else pd.Series(dtype=str)
    years = pd.to_datetime(group.loc[excess.index,"date"],errors="coerce").dt.year
    result = {
        "samples":count,"qualification":_qualification(count,mean,ci,min_samples),"win_rate":float((excess>0).mean()),
        "mean_excess_return":mean,"median_excess_return":float(excess.median()),"downside_tail_p10":float(excess.quantile(.10)),
        "downside_tail_p5":float(excess.quantile(.05)),"profit_factor":_profit_factor(excess),"bootstrap_mean_ci95":ci,
        "max_ticker_share":float(tickers.value_counts(normalize=True).max()) if not tickers.empty else None,
        "max_year_share":float(years.value_counts(normalize=True).max()) if years.notna().any() else None,
    }
    for source,target in ((f"mfe_{horizon}","mean_mfe"),(f"mae_{horizon}","mean_mae")):
        result[target] = float(pd.to_numeric(group.loc[excess.index].get(source),errors="coerce").mean()) if source in group else None
    for source,target in ((f"stop_hit_{horizon}","stop_rate"),(f"target25_hit_{horizon}","target25_rate")):
        result[target] = float(pd.Series(group.loc[excess.index].get(source),dtype="boolean").mean()) if source in group else None
    return result


def _add_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    out=frame.copy()
    out["rs63_bucket"]=pd.cut(pd.to_numeric(out.get("pct_rs_raw_63"),errors="coerce"),[-np.inf,50,70,85,np.inf],labels=["LT50","50TO70","70TO85","GE85"])
    out["eps_growth_bucket"]=pd.cut(pd.to_numeric(out.get("eps_yoy"),errors="coerce"),[-np.inf,0,.15,.30,np.inf],labels=["NEG","0TO15","15TO30","GE30"])
    out["stop_bucket"]=pd.cut(pd.to_numeric(out.get("stop_risk_pct"),errors="coerce"),[-np.inf,4,7,10,np.inf],labels=["LE4","4TO7","7TO10","GT10"])
    out["rr_bucket"]=pd.cut(pd.to_numeric(out.get("reward_risk_raw"),errors="coerce"),[-np.inf,1.5,2.5,4,np.inf],labels=["LT1.5","1.5TO2.5","2.5TO4","GE4"])
    return out


def _group_specs():
    return [("archetype",["candidate_archetype"]),("archetype_setup",["candidate_archetype","setup"]),("archetype_regime",["candidate_archetype","market_regime"]),("rs_setup",["rs_archetype","setup"]),("financial_setup",["financial_phase","setup"]),("rs_bucket_setup",["rs63_bucket","setup"]),("eps_bucket_setup",["eps_growth_bucket","setup"]),("risk_bucket",["stop_bucket","rr_bucket"])]


def _walk_forward(data: pd.DataFrame, horizons: tuple[int,...], min_samples: int) -> list[dict[str,Any]]:
    results=[]; dates=pd.to_datetime(data["date"],errors="coerce"); years=sorted(int(v) for v in dates.dt.year.dropna().unique())
    for horizon in horizons:
        outcome_dates=pd.to_datetime(data.get(f"outcome_date_{horizon}"),errors="coerce")
        for test_year in years:
            cutoff=pd.Timestamp(test_year,1,1); next_year=pd.Timestamp(test_year+1,1,1); train=data[outcome_dates<cutoff]; test=data[(dates>=cutoff)&(dates<next_year)]
            if train.empty or test.empty: continue
            candidates=[]
            for archetype,group in train.groupby("candidate_archetype",dropna=False):
                values=pd.to_numeric(group.get(f"excess_{horizon}"),errors="coerce").dropna()
                if len(values)>=min_samples: candidates.append((str(archetype),float(values.mean()),int(len(values))))
            if not candidates: continue
            candidates.sort(key=lambda value:(-value[1],-value[2],value[0])); selected,train_mean,train_samples=candidates[0]
            observed=pd.to_numeric(test[test["candidate_archetype"].astype(str)==selected].get(f"excess_{horizon}"),errors="coerce").dropna()
            results.append({"horizon":horizon,"test_year":test_year,"selected_archetype":selected,"train_samples":train_samples,"train_mean_excess":train_mean,"test_samples":int(len(observed)),"test_mean_excess":float(observed.mean()) if len(observed) else None,"test_win_rate":float((observed>0).mean()) if len(observed) else None,"training_cutoff":cutoff.date().isoformat()})
    return results


def _leave_one_year_out(data: pd.DataFrame, horizons: tuple[int,...]) -> list[dict[str,Any]]:
    results=[]; years=pd.to_datetime(data["date"],errors="coerce").dt.year
    for horizon in horizons:
        for omitted in sorted(int(v) for v in years.dropna().unique()):
            values=pd.to_numeric(data[years!=omitted].get(f"excess_{horizon}"),errors="coerce").dropna()
            results.append({"horizon":horizon,"omitted_year":omitted,"samples":int(len(values)),"mean_excess_return":float(values.mean()) if len(values) else None,"win_rate":float((values>0).mean()) if len(values) else None})
    return results


def build_research_expectancy(outcomes: pd.DataFrame, *, horizons: tuple[int,...]=(5,10,21,63), min_samples: int=40, bootstrap_samples: int=300, seed: int=38) -> dict[str,Any]:
    if outcomes is None or outcomes.empty:
        return {"status":"NO_SAMPLES","groups":[],"walk_forward":[],"leave_one_year_out":[],"excluding_2020":[]}
    data=_add_buckets(outcomes); groups=[]
    for group_type,columns in _group_specs():
        if any(column not in data for column in columns): continue
        for values,group in data.groupby(columns,dropna=False,observed=True):
            if not isinstance(values,tuple): values=(values,)
            dimensions={column:(None if pd.isna(value) else str(value)) for column,value in zip(columns,values)}
            for horizon in horizons: groups.append({"group_type":group_type,**dimensions,"horizon":horizon,**_summary(group,horizon,min_samples=min_samples,bootstrap_samples=bootstrap_samples,seed=seed)})
    groups.sort(key=lambda row:(row["group_type"],row["horizon"],-(row.get("mean_excess_return") or -999),-row.get("samples",0)))
    years=pd.to_datetime(data["date"],errors="coerce").dt.year; filtered=data[years!=2020]
    excluding=[{"horizon":horizon,**_summary(filtered,horizon,min_samples=min_samples,bootstrap_samples=bootstrap_samples,seed=seed+2020)} for horizon in horizons]
    return {"status":"OK","sample_count":int(len(data)),"ticker_count":int(data["ticker"].nunique()) if "ticker" in data else 0,"years":sorted(int(v) for v in years.dropna().unique()),"groups":groups,"walk_forward":_walk_forward(data,horizons,min_samples),"leave_one_year_out":_leave_one_year_out(data,horizons),"excluding_2020":excluding}
