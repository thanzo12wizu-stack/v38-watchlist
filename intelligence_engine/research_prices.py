from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

RS_WINDOWS = (21, 63, 126, 189, 252)


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        for level in range(out.columns.nlevels):
            values = {str(v).lower().replace(" ", "_") for v in out.columns.get_level_values(level)}
            if values & {"open", "high", "low", "close", "adj_close", "adjclose", "volume"}:
                out.columns = out.columns.get_level_values(level)
                break
    out.columns = [str(column).lower().replace(" ", "_") for column in out.columns]
    if "adj_close" in out and "close" not in out:
        out = out.rename(columns={"adj_close": "close"})
    if "adjclose" in out and "close" not in out:
        out = out.rename(columns={"adjclose": "close"})
    if out.columns.duplicated().any():
        merged = {}
        for name in dict.fromkeys(out.columns):
            selected = out.loc[:, out.columns == name]
            merged[name] = selected.bfill(axis=1).iloc[:, 0]
        out = pd.DataFrame(merged, index=out.index)
    required = {"high", "low", "close", "volume"}
    if not required.issubset(out.columns):
        return pd.DataFrame()
    for column in required | {"open"}:
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    index = pd.to_datetime(out.index, errors="coerce")
    if getattr(index, "tz", None) is not None:
        index = index.tz_convert(None)
    out.index = index
    return out.loc[out.index.notna()].sort_index().loc[lambda x: ~x.index.duplicated(keep="last")]


def _setup(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series("WATCH", index=frame.index, dtype="object")
    result.loc[frame["hard_block"].fillna(False)] = "AVOID"
    result.loc[(result == "WATCH") & (frame["extension_atr"] >= 3.0)] = "EXTENDED"
    result.loc[(result == "WATCH") & frame["above_pivot"].fillna(False) & (frame["volume_ratio_20d"] >= 1.25)] = "BREAKOUT"
    result.loc[(result == "WATCH") & frame["distance_pivot_pct"].between(-3.0, 0.5) & (frame["contraction_score_raw"] >= 0.5)] = "PRE_BREAKOUT"
    result.loc[(result == "WATCH") & frame["near_ema21_low"].fillna(False)] = "PULLBACK"
    result.loc[(result == "WATCH") & (frame["volume_ratio_20d"] >= 1.5)] = "VOLUME_SURGE"
    result.loc[(result == "WATCH") & (frame["distance_52w_high_pct"] <= -20.0)] = "DEEP_PULLBACK"
    return result


def ticker_price_features(ticker: str, frame: pd.DataFrame, benchmark_close: pd.Series, *, start=None, end=None, stride: int = 1) -> pd.DataFrame:
    prices = _normalize(frame)
    if prices.empty or len(prices) < 260:
        return pd.DataFrame()
    close, high, low, volume = prices["close"], prices["high"], prices["low"], prices["volume"]
    prev = close.shift(1)
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean(); sma10 = close.rolling(10).mean(); sma50 = close.rolling(50).mean(); sma150 = close.rolling(150).mean(); sma200 = close.rolling(200).mean()
    ema21_low = low.ewm(span=21, adjust=False).mean(); pivot20 = high.shift(1).rolling(20).max()
    range5 = (high-low).rolling(5).mean(); range20 = (high-low).rolling(20).mean()
    down_volume = volume.where(close < prev).rolling(10).sum(); total_volume = volume.rolling(10).sum()
    benchmark = pd.to_numeric(benchmark_close, errors="coerce").reindex(close.index).ffill()
    out = pd.DataFrame(index=prices.index)
    out["ticker"] = str(ticker).upper(); out["date"] = out.index; out["price"] = close
    out["adr_pct"] = tr.rolling(20).mean()/close*100; out["dollar_volume_20d"] = (close*volume).rolling(20).mean(); out["volume_ratio_20d"] = volume.rolling(5).mean()/volume.rolling(20).mean()
    out["distance_52w_high_pct"] = (close/close.rolling(252).max()-1)*100
    out["sma10"] = sma10; out["sma50"] = sma50; out["sma150"] = sma150; out["sma200"] = sma200
    out["stop_sma10"] = sma10; out["stop_ema21_low"] = ema21_low; out["pivot_20d"] = pivot20; out["distance_pivot_pct"] = (close/pivot20-1)*100
    out["above_pivot"] = close > pivot20; out["near_ema21_low"] = (close/ema21_low-1).abs() <= .025; out["extension_atr"] = (close-sma50)/atr14
    stop = pd.concat([ema21_low,sma10],axis=1).max(axis=1); out["stop_risk_pct"] = ((close-stop)/close*100).clip(lower=0)
    upside = (close.rolling(252).max()-close)/close*100; out["reward_risk_raw"] = upside/out["stop_risk_pct"].replace(0,np.nan)
    out["trend_alignment"] = pd.concat([(close>s).astype(float) for s in (sma10,sma50,sma150,sma200)],axis=1).mean(axis=1)
    out["contraction_score_raw"] = (1-range5/range20).clip(0,1); out["pivot_quality_raw"] = (1-(close/pivot20-1).abs()/.10).clip(0,1)
    out["participation_score_raw"] = (out["volume_ratio_20d"]/2).clip(0,1); out["supply_risk_raw"] = down_volume/total_volume
    out["hard_block"] = (close<sma150)|(sma150<sma150.shift(20))
    bench_daily = benchmark.pct_change(fill_method=None); stock_daily = close.pct_change(fill_method=None); down_mask = bench_daily < 0
    out["downside_resilience_21d"] = stock_daily.where(down_mask).rolling(21,min_periods=5).mean()-bench_daily.where(down_mask).rolling(21,min_periods=5).mean()
    for window in RS_WINDOWS:
        out[f"rs_raw_{window}"] = close.pct_change(window,fill_method=None)-benchmark.pct_change(window,fill_method=None)
        out[f"rs_change_raw_{window}"] = out[f"rs_raw_{window}"]-out[f"rs_raw_{window}"].shift(21)
        out[f"rs_slope_{window}_21d"] = out[f"rs_raw_{window}"].diff(21)/21
    out["setup"] = _setup(out)
    if start is not None: out = out[out.index >= pd.Timestamp(start)]
    if end is not None: out = out[out.index <= pd.Timestamp(end)]
    if stride > 1 and not out.empty: out = out.iloc[::stride]
    return out.reset_index(drop=True)


def _percentile(frame: pd.DataFrame, column: str, group=None) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if group:
        return frame.assign(_value=values).groupby(group,dropna=False)["_value"].rank(pct=True)*100
    return values.rank(pct=True)*100


def build_price_panel(prices: Mapping[str,pd.DataFrame], universe: pd.DataFrame, *, start: pd.Timestamp, end: pd.Timestamp, stride: int = 1) -> pd.DataFrame:
    qqq = prices.get("QQQ")
    if qqq is None: raise RuntimeError("QQQ benchmark is required for research backfill")
    qqq_normalized = _normalize(qqq)
    if qqq_normalized.empty: raise RuntimeError("QQQ benchmark history is empty")
    benchmark = qqq_normalized["close"]
    meta = universe.copy()
    if "ticker" not in meta.columns: meta["ticker"] = meta.index.astype(str)
    meta["ticker"] = meta["ticker"].astype(str).str.upper().str.strip(); meta_lookup = meta.drop_duplicates("ticker").set_index("ticker")
    pieces=[]
    for ticker, frame in prices.items():
        symbol=str(ticker).upper()
        if symbol=="QQQ" or symbol not in meta_lookup.index: continue
        features=ticker_price_features(symbol,frame,benchmark,start=start,end=end,stride=stride)
        if features.empty: continue
        row=meta_lookup.loc[symbol]; row=row.iloc[0] if isinstance(row,pd.DataFrame) else row
        for column in ("sector","industry","market_cap"): features[column]=row.get(column)
        pieces.append(features)
    if not pieces: return pd.DataFrame()
    panel=pd.concat(pieces,ignore_index=True); panel["date"]=pd.to_datetime(panel["date"],errors="coerce")
    rank_columns=[*(f"rs_raw_{w}" for w in RS_WINDOWS),*(f"rs_change_raw_{w}" for w in (63,126,189)),"downside_resilience_21d","dollar_volume_20d","distance_52w_high_pct"]
    for column in rank_columns:
        if column in panel: panel[f"pct_{column}"]=_percentile(panel,column,["date"])
    if "rs_raw_126" in panel:
        panel["sector_rs_126"]=panel.groupby(["date","sector"],dropna=False)["rs_raw_126"].transform("mean"); panel["industry_rs_126"]=panel.groupby(["date","industry"],dropna=False)["rs_raw_126"].transform("mean")
        panel["sector_rank_pct"]=_percentile(panel,"sector_rs_126",["date"]); panel["industry_rank_pct"]=_percentile(panel,"industry_rs_126",["date"])
    panel=panel.sort_values(["ticker","date"]).reset_index(drop=True)
    panel["rs126_top20"]=panel.get("pct_rs_raw_126",pd.Series(np.nan,index=panel.index))>=80; panel["rs126_top10"]=panel.get("pct_rs_raw_126",pd.Series(np.nan,index=panel.index))>=90
    panel["rs126_top20_persistence_63d"]=panel.groupby("ticker")["rs126_top20"].rolling(63,min_periods=20).mean().reset_index(level=0,drop=True)*100
    panel["rs126_top10_days_63d"]=panel.groupby("ticker")["rs126_top10"].rolling(63,min_periods=20).sum().reset_index(level=0,drop=True)
    panel["rs63_rank_change_21d"]=panel.groupby("ticker")["pct_rs_raw_63"].diff(21); panel["rs126_rank_change_21d"]=panel.groupby("ticker")["pct_rs_raw_126"].diff(21); panel["rs189_rank_change_21d"]=panel.groupby("ticker")["pct_rs_raw_189"].diff(21)
    panel["rs63_rank_prior_21d"]=panel.groupby("ticker")["pct_rs_raw_63"].shift(21)
    return panel


def classify_rs_archetype(row: pd.Series) -> str:
    n=lambda key: pd.to_numeric(row.get(key),errors="coerce")
    r63,r126,r189,change63,change126,persistence,prior63=(n("pct_rs_raw_63"),n("pct_rs_raw_126"),n("pct_rs_raw_189"),n("rs63_rank_change_21d"),n("rs126_rank_change_21d"),n("rs126_top20_persistence_63d"),n("rs63_rank_prior_21d"))
    if pd.notna(r63) and r63>=85 and pd.notna(r126) and r126<50 and (pd.isna(r189) or r189<40): return "FALSE_LEADERSHIP"
    if pd.notna(r189) and r189>=80 and ((pd.notna(r63) and r63<50) or (pd.notna(change63) and change63<=-20)): return "FADING_LEADER"
    if pd.notna(r189) and r189>=80 and pd.notna(r63) and r63>=80 and pd.notna(prior63) and prior63<60: return "REACCELERATING"
    if pd.notna(r189) and r189>=80 and pd.notna(persistence) and persistence>=60: return "ESTABLISHED_LEADER"
    if pd.notna(r126) and r126>=80 and ((pd.notna(change63) and change63>=10) or (pd.notna(change126) and change126>=10)): return "ACCELERATING_LEADER"
    if pd.notna(r63) and r63>=90 and (pd.isna(r189) or r189<80) and pd.notna(change63) and change63>0: return "NEW_LEADER"
    return "UNCLASSIFIED"
