from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

EXPECTANCY_POLICY_VERSION = "1.1.0"
HORIZONS = (5, 10, 21)


def _close(frame: pd.DataFrame) -> pd.Series:
    col = next((c for c in frame.columns if str(c).lower().replace(" ", "_") in {"close", "adj_close", "adjclose"}), None)
    return pd.to_numeric(frame[col], errors="coerce").dropna() if col is not None else pd.Series(dtype=float)


def _series(frame: pd.DataFrame, name: str) -> pd.Series:
    col = next((c for c in frame.columns if str(c).lower().replace(" ", "_") == name), None)
    return pd.to_numeric(frame[col], errors="coerce") if col is not None else pd.Series(index=frame.index, dtype=float)


def _point_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = _series(frame, "close")
    high = _series(frame, "high")
    low = _series(frame, "low")
    volume = _series(frame, "volume")
    out = pd.DataFrame(index=frame.index)
    out["close"] = close
    out["sma10"] = close.rolling(10).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma150"] = close.rolling(150).mean()
    out["sma200"] = close.rolling(200).mean()
    out["ema21_low"] = low.ewm(span=21, adjust=False).mean()
    out["pivot20"] = high.shift(1).rolling(20).max()
    tr = pd.concat([(high-low), (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    out["adr_pct"] = tr.rolling(20).mean() / close * 100
    out["extension_atr"] = (close-out["sma50"])/atr
    out["distance_pivot_pct"] = (close/out["pivot20"]-1)*100
    out["volume_ratio"] = volume.rolling(5).mean()/volume.rolling(20).mean()
    out["contraction"] = 1-(high-low).rolling(5).mean()/(high-low).rolling(20).mean()
    out["near_ema21"] = (close/out["ema21_low"]-1).abs() <= .025
    out["above_pivot"] = close > out["pivot20"]
    out["hard_block"] = (close < out["sma150"]) | (out["sma150"] < out["sma150"].shift(20))
    trend = pd.concat([(close>out[x]).astype(float) for x in ("sma10","sma50","sma150","sma200")], axis=1).mean(axis=1)
    pivot_quality = (1-(close/out["pivot20"]-1).abs()/.10).clip(0,1)
    participation = (out["volume_ratio"]/2).clip(0,1)
    risk = ((close-out["ema21_low"])/close*100).clip(lower=0)
    risk_quality = (1-risk/12).clip(0,1)
    extension_quality = (1-out["extension_atr"].clip(lower=0)/4).clip(0,1)
    out["entry_score_raw"] = 100*(.30*trend+.25*out["contraction"].clip(0,1)+.25*pivot_quality+.10*participation+.10*(.6*risk_quality+.4*extension_quality))
    return out


def _classify(row: pd.Series) -> str:
    if bool(row.get("hard_block")): return "AVOID"
    if pd.notna(row.get("extension_atr")) and row["extension_atr"] >= 3: return "EXTENDED"
    if bool(row.get("above_pivot")) and row.get("volume_ratio", 0) >= 1.25: return "BREAKOUT"
    if -3 <= row.get("distance_pivot_pct", -99) <= .5 and row.get("contraction", 0) >= .5: return "PRE_BREAKOUT"
    if bool(row.get("near_ema21")): return "PULLBACK"
    if row.get("volume_ratio", 0) >= 1.5: return "VOLUME_SURGE"
    return "WATCH"


def _regime(bench: pd.Series, i: int) -> str:
    history = bench.iloc[: i + 1]
    if len(history) < 50:
        return "UNKNOWN"
    latest = history.iloc[-1]
    sma20 = history.rolling(20).mean().iloc[-1]
    sma50 = history.rolling(50).mean().iloc[-1]
    sma200 = history.rolling(200).mean().iloc[-1] if len(history) >= 200 else np.nan
    points = int(latest > sma20) + int(latest > sma50) + int(pd.notna(sma200) and latest > sma200)
    if points == 3: return "BLUE"
    if points == 2: return "GREEN"
    if points == 1: return "YELLOW"
    return "RED"


def _adr_bucket(value: Any) -> str | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number): return None
    if number < 2: return "LT2"
    if number < 4: return "2TO4"
    if number < 6: return "4TO6"
    return "GE6"


def _bootstrap(values: pd.Series, seed: int = 38, n: int = 500) -> list[float] | None:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) < 10:
        return None
    rng = np.random.default_rng(seed)
    means = [float(rng.choice(clean, len(clean), replace=True).mean()) for _ in range(n)]
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _summary(values: pd.Series, min_samples: int) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    count = int(len(clean))
    if not count:
        return {"samples": 0, "sample_count": 0, "usable": False, "qualified": False, "win_rate": None, "mean_excess_return": None, "median_excess_return": None, "downside_tail_p10": None, "bootstrap_mean_ci95": None}
    return {
        "samples": count,
        "sample_count": count,
        "usable": bool(count >= min_samples),
        "qualified": bool(count >= min_samples),
        "win_rate": round(float((clean > 0).mean()), 4),
        "mean_excess_return": round(float(clean.mean()), 6),
        "median_excess_return": round(float(clean.median()), 6),
        "downside_tail_p10": round(float(clean.quantile(.10)), 6),
        "bootstrap_mean_ci95": _bootstrap(clean),
    }


def build_expectancy(prices: dict[str, pd.DataFrame], min_samples: int = 30, stride: int = 5) -> dict[str, Any]:
    qqq = prices.get("QQQ")
    if qqq is None:
        return {"status":"NO_BENCHMARK","policy_version":EXPECTANCY_POLICY_VERSION,"setup_stats":[],"rankings":[],"calibration":[],"walk_forward":[]}
    qclose = _close(qqq)
    samples=[]
    for ticker, frame in prices.items():
        if ticker == "QQQ" or len(frame) < 230: continue
        feat = _point_features(frame)
        close = _close(frame)
        common = close.index.intersection(qclose.index)
        feat = feat.reindex(common); close = close.reindex(common); bench = qclose.reindex(common)
        for i in range(220, len(common)-max(HORIZONS), stride):
            row=feat.iloc[i]
            if pd.isna(row.get("entry_score_raw")): continue
            setup=_classify(row)
            rec={"ticker":ticker,"date":str(common[i])[:10],"year":int(str(common[i])[:4]),"setup":setup,"entry_score_raw":float(row["entry_score_raw"]),"regime":_regime(bench,i),"adr_bucket":_adr_bucket(row.get("adr_pct"))}
            for h in HORIZONS:
                stock_ret=float(close.iloc[i+h]/close.iloc[i]-1)
                bench_ret=float(bench.iloc[i+h]/bench.iloc[i]-1)
                rec[f"excess_{h}"]=stock_ret-bench_ret
            samples.append(rec)
    data=pd.DataFrame(samples)
    if data.empty:
        return {"status":"NO_SAMPLES","policy_version":EXPECTANCY_POLICY_VERSION,"setup_stats":[],"rankings":[],"calibration":[],"walk_forward":[]}

    setup_stats=[]
    for setup, group in data.groupby("setup"):
        for h in HORIZONS:
            summary=_summary(group[f"excess_{h}"],min_samples)
            setup_stats.append({"setup":setup,"horizon":h,**summary})

    data["score_bucket"] = pd.qcut(data["entry_score_raw"], q=min(10, data["entry_score_raw"].nunique()), duplicates="drop")
    calibration=[]
    for bucket, group in data.groupby("score_bucket", observed=True):
        lo=float(group["entry_score_raw"].min()); hi=float(group["entry_score_raw"].max())
        n=len(group); metrics={}
        for h in HORIZONS:
            values=group[f"excess_{h}"].dropna(); prior=float(data[f"excess_{h}"].mean())
            shrink=(n/(n+50))*float(values.mean())+(50/(n+50))*prior
            metrics[str(h)]={"samples":int(len(values)),"expected_excess_return":round(shrink,6),"win_rate":round(float((values>0).mean()),4),"median":round(float(values.median()),6),"p10":round(float(values.quantile(.10)),6)}
        calibration.append({"score_min":round(lo,2),"score_max":round(hi,2),"samples":n,"metrics":metrics})
    calibration.sort(key=lambda x:x["score_min"])

    walk_forward=[]
    years=sorted(int(year) for year in data["year"].dropna().unique())
    for horizon in HORIZONS:
        for test_year in years:
            train=data[data["year"]<test_year]
            test=data[data["year"]==test_year]
            if train.empty or test.empty: continue
            train_stats=[]
            for setup, group in train.groupby("setup"):
                values=group[f"excess_{horizon}"].dropna()
                if len(values)>=min_samples:
                    train_stats.append((setup,float(values.mean()),len(values)))
            if not train_stats: continue
            train_stats.sort(key=lambda item:(-item[1],-item[2],item[0]))
            selected=train_stats[0][0]
            observed=test[test["setup"]==selected][f"excess_{horizon}"].dropna()
            walk_forward.append({"horizon":horizon,"test_year":test_year,"selected_setup":selected,"train_samples":train_stats[0][2],"test_samples":int(len(observed)),"mean_excess":None if observed.empty else float(observed.mean()),"median_excess":None if observed.empty else float(observed.median()),"win_rate":None if observed.empty else float((observed>0).mean())})

    excluding_2020=[]
    filtered=data[data["year"]!=2020]
    for setup, group in filtered.groupby("setup"):
        for horizon in HORIZONS:
            excluding_2020.append({"setup":setup,"horizon":horizon,**_summary(group[f"excess_{horizon}"],min_samples)})

    regime_stats=[]
    for (regime,setup),group in data.groupby(["regime","setup"]):
        for horizon in HORIZONS:
            regime_stats.append({"regime":regime,"setup":setup,"horizon":horizon,**_summary(group[f"excess_{horizon}"],min_samples)})

    rankings=[row for row in setup_stats if row.get("usable")]
    rankings.sort(key=lambda row:(row["horizon"],-(row.get("mean_excess_return") or -999),-row.get("samples",0),row["setup"]))
    return {"status":"OK","policy_version":EXPECTANCY_POLICY_VERSION,"sample_count":len(data),"ticker_count":int(data["ticker"].nunique()),"years":years,"stride":stride,"setup_stats":sorted(setup_stats,key=lambda x:(x["setup"],x["horizon"])),"rankings":rankings,"regime_stats":regime_stats,"calibration":calibration,"walk_forward":walk_forward,"excluding_2020":excluding_2020}


def calibrate_candidates(candidates: list[dict], expectancy: dict[str, Any]) -> list[dict]:
    setup_map={(r["setup"],r["horizon"]):r for r in expectancy.get("setup_stats",[]) if r.get("usable")}
    buckets=expectancy.get("calibration",[])
    out=[]
    for item in candidates:
        rec=dict(item); score=float(rec.get("score_entry") or 0); bucket=next((b for b in buckets if b["score_min"]<=score<=b["score_max"]),None)
        rec["expectancy"]={}
        qualified_scores=[]
        for h in HORIZONS:
            base=setup_map.get((rec.get("setup"),h)); cal=(bucket or {}).get("metrics",{}).get(str(h))
            rec["expectancy"][str(h)]={"setup":base,"score_calibration":cal}
            if base and base.get("mean_excess_return") is not None:
                qualified_scores.append(float(base["mean_excess_return"]))
        ten=rec["expectancy"].get("10",{})
        ten_base=ten.get("setup") or {}
        ten_cal=ten.get("score_calibration") or {}
        expected=ten_base.get("mean_excess_return")
        if expected is None: expected=ten_cal.get("expected_excess_return")
        rec["expectancy_qualified"]=bool(ten_base.get("usable"))
        rec["expectancy_sample_count"]=int(ten_base.get("samples") or ten_cal.get("samples") or 0)
        rec["expected_excess_10d"]=expected
        rec["expectancy_rank_adjustment"]=round(max(-15.0,min(15.0,float(expected or 0)*500.0)),2) if expected is not None and rec["expectancy_sample_count"]>=50 else 0.0
        rec["entry_score_calibrated"] = round(max(0.0,min(100.0,score+rec["expectancy_rank_adjustment"])),2)
        out.append(rec)
    return out
