from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

EXPECTANCY_POLICY_VERSION = "1.0.0"
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


def build_expectancy(prices: dict[str, pd.DataFrame], min_samples: int = 30, stride: int = 5) -> dict[str, Any]:
    qqq = prices.get("QQQ")
    if qqq is None:
        return {"status":"NO_BENCHMARK","policy_version":EXPECTANCY_POLICY_VERSION,"setup_stats":[],"calibration":[]}
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
            rec={"ticker":ticker,"date":str(common[i])[:10],"setup":setup,"entry_score_raw":float(row["entry_score_raw"])}
            for h in HORIZONS:
                stock_ret=float(close.iloc[i+h]/close.iloc[i]-1)
                bench_ret=float(bench.iloc[i+h]/bench.iloc[i]-1)
                rec[f"excess_{h}"]=stock_ret-bench_ret
            samples.append(rec)
    data=pd.DataFrame(samples)
    if data.empty:
        return {"status":"NO_SAMPLES","policy_version":EXPECTANCY_POLICY_VERSION,"setup_stats":[],"calibration":[]}
    setup_stats=[]
    for setup, group in data.groupby("setup"):
        for h in HORIZONS:
            values=group[f"excess_{h}"].dropna()
            setup_stats.append({"setup":setup,"horizon":h,"samples":int(len(values)),"win_rate":round(float((values>0).mean()),4),"mean_excess_return":round(float(values.mean()),6),"median_excess_return":round(float(values.median()),6),"downside_tail_p10":round(float(values.quantile(.10)),6),"usable":bool(len(values)>=min_samples)})
    data["score_bucket"] = pd.qcut(data["entry_score_raw"], q=min(10, data["entry_score_raw"].nunique()), duplicates="drop")
    calibration=[]
    for bucket, group in data.groupby("score_bucket", observed=True):
        lo=float(group["entry_score_raw"].min()); hi=float(group["entry_score_raw"].max())
        n=len(group)
        metrics={}
        for h in HORIZONS:
            values=group[f"excess_{h}"].dropna(); prior=float(data[f"excess_{h}"].mean())
            shrink=(n/(n+50))*float(values.mean())+(50/(n+50))*prior
            metrics[str(h)]={"samples":int(len(values)),"expected_excess_return":round(shrink,6),"win_rate":round(float((values>0).mean()),4),"median":round(float(values.median()),6),"p10":round(float(values.quantile(.10)),6)}
        calibration.append({"score_min":round(lo,2),"score_max":round(hi,2),"samples":n,"metrics":metrics})
    calibration.sort(key=lambda x:x["score_min"])
    return {"status":"OK","policy_version":EXPECTANCY_POLICY_VERSION,"sample_count":len(data),"ticker_count":int(data["ticker"].nunique()),"stride":stride,"setup_stats":sorted(setup_stats,key=lambda x:(x["setup"],x["horizon"])),"calibration":calibration}


def calibrate_candidates(candidates: list[dict], expectancy: dict[str, Any]) -> list[dict]:
    setup_map={(r["setup"],r["horizon"]):r for r in expectancy.get("setup_stats",[]) if r.get("usable")}
    buckets=expectancy.get("calibration",[])
    out=[]
    for item in candidates:
        rec=dict(item); score=float(rec.get("score_entry") or 0); bucket=next((b for b in buckets if b["score_min"]<=score<=b["score_max"]),None)
        rec["expectancy"]={}
        for h in HORIZONS:
            base=setup_map.get((rec.get("setup"),h)); cal=(bucket or {}).get("metrics",{}).get(str(h))
            rec["expectancy"][str(h)]={"setup":base,"score_calibration":cal}
        rec["entry_score_calibrated"] = round(50+500*float((bucket or {}).get("metrics",{}).get("10",{}).get("expected_excess_return",0)),2) if bucket else None
        out.append(rec)
    return out
