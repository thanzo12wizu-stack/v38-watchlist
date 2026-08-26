from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_pioneer_leader as pl

DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-01")
HORIZONS = (5, 10, 20)
COOLDOWN = 20
MAX_HOLD = 63
OVERLAP_JACCARD = 0.50


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [safe(x) for x in v]
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v); return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def block_id(dates: pd.Series, calendar: pd.DatetimeIndex, n: int = 20) -> pd.Series:
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    x = pos.reindex(pd.to_datetime(dates)).to_numpy(float)
    return pd.Series(np.floor(x / n).astype("int64"), index=dates.index)


def cluster_ci(df: pd.DataFrame, value: str, cluster: str, seed: int, reps: int = 3000) -> list[float | None]:
    use = df[[cluster, value]].dropna()
    if use.empty: return [None, None]
    g = use.groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(g) < 2: return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(g, size=(reps, len(g)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def summary(df: pd.DataFrame, value: str, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    use = df.dropna(subset=[value]).copy()
    if use.empty: return {"n": 0}
    use["block20"] = block_id(use["date"], calendar, 20)
    return {
        "n": int(len(use)), "dates": int(use.date.nunique()), "themes": int(use.theme.nunique()) if "theme" in use else None,
        "mean": float(use[value].mean()), "median": float(use[value].median()), "positive_rate": float((use[value] > 0).mean()),
        "date_ci95": cluster_ci(use, value, "date", seed),
        "block20_ci95": cluster_ci(use, value, "block20", seed + 1000),
        "theme_ci95": cluster_ci(use, value, "theme", seed + 2000) if "theme" in use else [None, None],
    }


def extract_cross_events(mask: pd.DataFrame, strength: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, cooldown: int = COOLDOWN) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for theme in mask.columns:
        a = mask[theme].fillna(False)
        last = -10000
        for i, (d, on) in enumerate(a.items()):
            if d < start or d > end or not bool(on): continue
            prev = bool(a.iloc[i - 1]) if i > 0 else False
            if prev or i - last < cooldown: continue
            last = i
            rows.append({"date": pd.Timestamp(d), "theme": theme, "strength": float(strength.at[d, theme]) if pd.notna(strength.at[d, theme]) else np.nan})
    return pd.DataFrame(rows).sort_values(["date", "theme"]).reset_index(drop=True) if rows else pd.DataFrame(columns=["date", "theme", "strength"])


def make_rrg_like(theme_ret: pd.DataFrame, spy_ret: pd.Series, theme_pct: pd.DataFrame, breadth: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    # Independent RRG-like phase vector built only from price-relative data; not JdK proprietary formulas.
    rel_log = np.log1p(theme_ret.clip(lower=-0.999999)).sub(np.log1p(spy_ret.clip(lower=-0.999999)), axis=0).fillna(0.0).cumsum()
    slow = rel_log.ewm(span=63, adjust=False, min_periods=30).mean()
    scale = rel_log.diff().rolling(63, min_periods=30).std() * math.sqrt(63)
    trend = ((rel_log - slow) / scale.replace(0.0, np.nan)).clip(-5, 5)
    momentum = trend - trend.shift(5)
    acceleration = momentum - momentum.shift(5)
    trend_slope5 = trend - trend.shift(5)
    common = trend.columns.intersection(theme_pct.columns).intersection(breadth.columns)
    t, m, a, s = trend[common], momentum[common], acceleration[common], trend_slope5[common]
    rp, b = theme_pct[common], breadth[common]
    primary = (t <= 0.25) & (m > 0) & (a > 0) & (s > 0) & rp.between(40, 79.999) & (b >= 50)
    loose = (t <= 0.50) & (m > 0) & (s > 0) & (rp < 80) & (b >= 45)
    strength = (50 + 20 * t.fillna(0) + 120 * m.fillna(0) + 80 * a.fillna(0) + 0.25 * (b.fillna(50) - 50)).clip(0, 100)
    return {"PRIMARY": primary, "LOOSE": loose}, strength


def add_theme_outcomes(events: pd.DataFrame, theme_ret: pd.DataFrame, spy_ret: pd.Series, momentum_events: pd.DataFrame, momentum_mask: pd.DataFrame) -> pd.DataFrame:
    if events.empty: return events.copy()
    tf = {h: er.forward_return(theme_ret, h) for h in HORIZONS}
    sf = {h: er.forward_return(spy_ret, h) for h in HORIZONS}
    calendar = theme_ret.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(calendar)}
    mom_by_theme = {t: sorted(pd.to_datetime(g.date).tolist()) for t, g in momentum_events.groupby("theme", observed=True)} if len(momentum_events) else {}
    rows = []
    for r in events.itertuples(index=False):
        d, t = pd.Timestamp(r.date), str(r.theme)
        rec = {"date": d, "theme": t, "strength": r.strength}
        for h in HORIZONS:
            tr = tf[h].at[d, t] if d in tf[h].index and t in tf[h].columns else np.nan
            sr = sf[h].at[d] if d in sf[h].index else np.nan
            rec[f"spy_excess_{h}"] = tr - sr if pd.notna(tr) and pd.notna(sr) else np.nan
        p = pos.get(d, -1)
        for h in (5, 10, 20):
            future = calendar[p + 1:min(len(calendar), p + h + 1)] if p >= 0 else []
            rec[f"momentum_active_within_{h}"] = bool(any((fd in momentum_mask.index and t in momentum_mask.columns and bool(momentum_mask.at[fd, t])) for fd in future))
            rec[f"momentum_event_within_{h}"] = bool(any(d < md <= (calendar[min(len(calendar)-1, p+h)] if p >= 0 else d) for md in mom_by_theme.get(t, [])))
        rows.append(rec)
    return pd.DataFrame(rows)


def primary_family(theme_members: dict[str, list[str]], industry_map: dict[str, tuple[str, str]]) -> dict[str, str]:
    out = {}
    for t, members in theme_members.items():
        counts: dict[str, int] = defaultdict(int)
        for s in members:
            if s in industry_map and industry_map[s][1]: counts[industry_map[s][1]] += 1
        out[t] = max(counts, key=counts.get) if counts else "UNKNOWN"
    return out


def overlap_dedupe(events: pd.DataFrame, theme_sets: dict[str, set[str]]) -> pd.DataFrame:
    keep = []
    for d, part in events.groupby("date", observed=True):
        chosen: list[str] = []
        for r in part.sort_values("strength", ascending=False).itertuples(index=False):
            s = theme_sets.get(str(r.theme), set())
            bad = False
            for c in chosen:
                z = theme_sets.get(c, set())
                den = len(s | z)
                if den and len(s & z) / den >= OVERLAP_JACCARD:
                    bad = True; break
            if not bad:
                keep.append(r._asdict()); chosen.append(str(r.theme))
    return pd.DataFrame(keep)


def aggregate_modes(events: pd.DataFrame, value: str, family_map: dict[str, str], theme_sets: dict[str, set[str]]) -> dict[str, pd.DataFrame]:
    raw = events.copy()
    date_eq = raw.groupby("date", observed=True)[value].mean().reset_index(); date_eq["theme"] = "DATE_EQ"
    fam = raw.copy(); fam["family"] = fam.theme.map(family_map).fillna("UNKNOWN")
    fam = fam.groupby(["date", "family"], observed=True)[value].mean().reset_index().groupby("date", observed=True)[value].mean().reset_index(); fam["theme"] = "FAMILY_DATE_EQ"
    ded = overlap_dedupe(raw, theme_sets)
    ded_date = ded.groupby("date", observed=True)[value].mean().reset_index() if len(ded) else pd.DataFrame(columns=["date", value]); ded_date["theme"] = "OVERLAP_DEDUP"
    return {"EVENT_WEIGHTED": raw, "DATE_EQUAL": date_eq, "FAMILY_DATE_EQUAL": fam, "OVERLAP_DEDUP_DATE_EQUAL": ded_date}


def trade_entries(events: pd.DataFrame, theme_members: dict[str, list[str]], close: pd.DataFrame, open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = close.rolling(50, min_periods=40).mean()
    tr = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    prev = close.shift(1)
    tr[:] = np.maximum(high-low, np.maximum((high-prev).abs(), (low-prev).abs()))
    atr14 = tr.rolling(14, min_periods=10).mean()
    vwap63 = (close*volume).rolling(63, min_periods=40).sum() / volume.rolling(63, min_periods=40).sum().replace(0, np.nan)
    stock_ret = close.pct_change(fill_method=None)
    rs63 = er.period_return(stock_ret, 63)
    date_pos = {pd.Timestamp(d): i for i,d in enumerate(close.index)}
    last_symbol: dict[str, int] = {}
    candidates = []
    for ev in events.sort_values(["date","strength"], ascending=[True,False]).itertuples(index=False):
        d, theme = pd.Timestamp(ev.date), str(ev.theme)
        p = date_pos.get(d, -1)
        if p < 60 or p + 1 >= len(close): continue
        members = [s for s in theme_members.get(theme, []) if s in close.columns]
        if len(members) < 3: continue
        vals = rs63.loc[d, members].dropna()
        ranks = vals.rank(pct=True)
        eligible = []
        for s in members:
            c = close.at[d,s]; a = atr14.at[d,s]; e = ema21.at[d,s]; sm = sma50.at[d,s]; vw = vwap63.at[d,s]
            if any(pd.isna(x) for x in (c,a,e,sm,vw)) or a <= 0: continue
            if not (c > e and c > sm and c > vw): continue
            if (c-e)/a > 1.5: continue
            if ranks.get(s,0) < 0.80: continue
            eligible.append((s, float(ranks.get(s,0))))
        for s, rank in sorted(eligible, key=lambda x:x[1], reverse=True)[:3]:
            if p - last_symbol.get(s,-10000) < COOLDOWN: continue
            nd = close.index[p+1]; ep = open_.at[nd,s]
            if pd.isna(ep) or ep <= 0: continue
            sw = low.loc[close.index[max(0,p-4):p+1],s].min()
            a = atr14.at[d,s]
            stop = max(float(sw - 0.25*a), float(ep - 1.5*a), float(ep*0.92))
            stop = min(stop, float(ep*0.99))
            if stop <= 0 or stop >= ep: continue
            candidates.append({"signal_date":d,"entry_date":nd,"theme":theme,"symbol":s,"strength":float(ev.strength),"entry":float(ep),"stop0":float(stop),"risk":float(ep-stop),"signal_pos":p})
            last_symbol[s] = p
    if not candidates: return pd.DataFrame()
    x = pd.DataFrame(candidates)
    # Same symbol can be selected by overlapping themes on same signal day: keep strongest theme only.
    x = x.sort_values("strength", ascending=False).drop_duplicates(["signal_date","symbol"], keep="first").sort_values(["entry_date","theme","symbol"]).reset_index(drop=True)
    return x


def simulate_one(row: Any, policy: str, close: pd.DataFrame, open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, ema10: pd.DataFrame, ema21: pd.DataFrame, momentum_mask: pd.DataFrame) -> dict[str, Any]:
    s, theme = str(row.symbol), str(row.theme)
    entry_d = pd.Timestamp(row.entry_date); entry = float(row.entry); stop = float(row.stop0); R = float(row.risk)
    p0 = close.index.get_indexer([entry_d])[0]
    remaining, cash = 1.0, 0.0
    partial_done = False; be_armed = False; inactive_streak = 0
    max_high = entry; min_low = entry; exit_d = entry_d; exit_px = entry; reason = "MAX_HOLD"
    for k in range(0, MAX_HOLD):
        p = p0 + k
        if p >= len(close): break
        d = close.index[p]
        o,h,l,c = open_.at[d,s], high.at[d,s], low.at[d,s], close.at[d,s]
        if any(pd.isna(x) for x in (o,h,l,c)): continue
        max_high = max(max_high, float(h)); min_low = min(min_low, float(l))
        if policy in {"HOLD20","HOLD63"}:
            target_k = 19 if policy == "HOLD20" else 62
            if k >= target_k:
                cash += remaining*float(c); remaining=0; exit_d=d; exit_px=float(c); reason=policy; break
            continue
        if float(l) <= stop:
            px = float(o) if float(o) < stop else stop
            cash += remaining*px; remaining=0; exit_d=d; exit_px=px; reason="STOP"; break
        if policy == "FAST3_RUNNER21_PARTIAL" and not partial_done and float(h) >= entry + 3*R:
            frac = min(0.25, remaining); cash += frac*(entry+3*R); remaining -= frac; partial_done=True
        if k >= 2 and policy in {"FAST3_RUNNER10","FAST3_RUNNER21","FAST3_RUNNER21_PARTIAL","FAST3_THEME_TIGHTEN"}:
            # Early failure: after three sessions, no progress and close <= entry -> next available close exit conservatively now.
            prior_window = close.iloc[p0:p+1][s].dropna()
            if len(prior_window) >= 3 and float(c) <= entry and float(prior_window.max()) < entry + 0.5*R:
                cash += remaining*float(c); remaining=0; exit_d=d; exit_px=float(c); reason="TIME3"; break
        if float(c) >= entry + R: be_armed = True
        if d in momentum_mask.index and theme in momentum_mask.columns and bool(momentum_mask.at[d,theme]): inactive_streak = 0
        else: inactive_streak += 1
        # Stops updated after the close, effective next session only.
        new_stop = stop
        if be_armed: new_stop = max(new_stop, entry)
        trail = None
        if policy == "FAST3_RUNNER10": trail = ema10.at[d,s]
        elif policy in {"FAST3_RUNNER21","FAST3_RUNNER21_PARTIAL"}: trail = ema21.at[d,s]
        elif policy == "FAST3_THEME_TIGHTEN": trail = ema10.at[d,s] if inactive_streak >= 2 else ema21.at[d,s]
        if trail is not None and pd.notna(trail): new_stop = max(new_stop, float(trail))
        stop = new_stop
        if k == MAX_HOLD-1:
            cash += remaining*float(c); remaining=0; exit_d=d; exit_px=float(c); reason="MAX63"
    if remaining > 0:
        c = close.at[exit_d,s]
        cash += remaining*float(c); remaining=0
    ret = cash/entry - 1.0
    mfe = max_high/entry - 1.0; mae = min_low/entry - 1.0
    return {"return":ret,"mfe":mfe,"mae":mae,"exit_date":exit_d,"exit_reason":reason,"hold_days":int(max(1, close.index.get_indexer([exit_d])[0]-p0+1)),"capture":ret/mfe if ret>0 and mfe>0 else np.nan,"tail20":bool(mfe>=0.20),"tail10_realized":bool(ret>=0.10)}


def trade_stats(df: pd.DataFrame, period: str) -> dict[str, Any]:
    x = df.copy()
    if period == "DISCOVERY": x = x[x.entry_date <= DISCOVERY_END]
    elif period == "CONFIRMATION": x = x[x.entry_date >= CONFIRM_START]
    if x.empty: return {"n":0}
    r = x["return"].dropna(); wins=r[r>0]; losses=r[r<=0]
    gross_win=float(wins.sum()); gross_loss=float(-losses.sum())
    cutoff=r.quantile(0.90) if len(r)>=10 else np.nan
    top = r[r>=cutoff] if pd.notna(cutoff) else pd.Series(dtype=float)
    tail = x[x.tail20]
    return {"n":int(len(r)),"win_rate":float((r>0).mean()),"mean":float(r.mean()),"median":float(r.median()),"avg_win":float(wins.mean()) if len(wins) else None,"avg_loss":float(losses.mean()) if len(losses) else None,"profit_factor":gross_win/gross_loss if gross_loss>0 else None,"p90":float(r.quantile(.90)),"p95":float(r.quantile(.95)),"mean_mae":float(x.mae.mean()),"mean_mfe":float(x.mfe.mean()),"median_hold":float(x.hold_days.median()),"positive_capture_median":float(x.capture.dropna().median()) if x.capture.notna().any() else None,"top10_share_of_gross_profit":float(top[top>0].sum()/gross_win) if gross_win>0 and len(top) else None,"mfe20_count":int(len(tail)),"mfe20_realized10_rate":float(tail.tail10_realized.mean()) if len(tail) else None}


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",required=True); ap.add_argument("--analysis-start",default="2016-01-04"); ap.add_argument("--analysis-end",default="2026-06-30"); ap.add_argument("--max-tickers",type=int,default=6000); ap.add_argument("--batch-size",type=int,default=75); ap.add_argument("--min-members",type=int,default=3); args=ap.parse_args()
    root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)
    snap=er.load_json(root/"sector_snapshot.json"); theme_members_all,_=er.extract_theme_members(snap); industry_map=er.read_industry_map(root/"industry_map.json"); universe=er.read_universe_symbols(root/"universe.csv")
    selected=er.stratified_symbols(theme_members_all,set(industry_map)&universe,args.max_tickers); req=selected+(["SPY"] if "SPY" not in selected else [])
    ohlcv,diag=pl.download_ohlcv(req,str((pd.Timestamp(args.analysis_start)-pd.Timedelta(days=620)).date()),str((pd.Timestamp(args.analysis_end)+pd.Timedelta(days=120)).date()),args.batch_size)
    close_all=ohlcv["close"]; stock_cols=[s for s in selected if s in close_all.columns]; close=close_all[stock_cols]; open_=ohlcv["open"][stock_cols]; high=ohlcv["high"][stock_cols]; low=ohlcv["low"][stock_cols]; volume=ohlcv["volume"][stock_cols]
    spy_ret=close_all["SPY"].pct_change(fill_method=None); stock_ret=close.pct_change(fill_method=None)
    theme_members={t:[s for s in m if s in stock_cols] for t,m in theme_members_all.items()}; member_counts={t:len(m) for t,m in theme_members.items()}; theme_ret=er.grouped_equal_weight(stock_ret,theme_members,args.min_members)
    spy63=er.period_return(spy_ret,63); theme63=er.period_return(theme_ret,63); theme_pct=theme63.sub(spy63,axis=0).rank(axis=1,pct=True)*100
    breadth=er.breadth_above_ema21(close,theme_members,args.min_members).reindex(columns=theme_ret.columns)
    # Parent matrix only needed by current Momentum function signature; Momentum itself is theme RS + delta + breadth.
    industry_groups: dict[str,list[str]] = defaultdict(list)
    for s in stock_cols:
        if s in industry_map and industry_map[s][1]: industry_groups[industry_map[s][1]].append(s)
    industry_ret=er.grouped_equal_weight(stock_ret,dict(industry_groups),args.min_members); iw=er.build_parent_weights(theme_members_all,industry_map); ind63=er.period_return(industry_ret,63); indpct=ind63.sub(spy63,axis=0).rank(axis=1,pct=True)*100; parent=er.weighted_matrix(indpct,iw,list(theme_ret.columns)).reindex(columns=theme_ret.columns)
    momentum_mask=cl.momentum_mask(theme_pct,parent,breadth); start,end=pd.Timestamp(args.analysis_start),pd.Timestamp(args.analysis_end); momentum_events=er.extract_events(momentum_mask,theme_pct,parent,breadth,member_counts,start,end)
    masks,strength=make_rrg_like(theme_ret,spy_ret,theme_pct,breadth); family_map=primary_family(theme_members,industry_map); theme_sets={t:set(m) for t,m in theme_members.items()}
    result={"status":"PRELIMINARY_CURRENT_TAXONOMY_RRG_LIKE_TAIL","bias_warning":"Current taxonomy/universe retrospectively applied.","download":diag,"coverage":{"stocks":len(stock_cols),"themes":len(theme_ret.columns),"momentum_events":len(momentum_events)},"rrg":{},"trades":{}}
    primary_out=None
    for j,(name,mask) in enumerate(masks.items()):
        ev=extract_cross_events(mask,strength,start,end); eo=add_theme_outcomes(ev,theme_ret,spy_ret,momentum_events,momentum_mask); result["rrg"][name]={"events":len(eo),"conversion":{str(h):{"event_within":float(eo[f"momentum_event_within_{h}"].mean()) if len(eo) else None,"active_within":float(eo[f"momentum_active_within_{h}"].mean()) if len(eo) else None} for h in (5,10,20)},"returns":{}}
        for h in HORIZONS:
            val=f"spy_excess_{h}"; modes=aggregate_modes(eo,val,family_map,theme_sets); result["rrg"][name]["returns"][str(h)]={k:summary(v,val,theme_ret.index,10000+j*1000+h*10+i) for i,(k,v) in enumerate(modes.items())}
            result["rrg"][name]["returns"][str(h)]["confirmation_event_weighted"] = summary(eo[eo.date>=CONFIRM_START],val,theme_ret.index,20000+j*1000+h)
        if name=="PRIMARY": primary_out=eo
    if primary_out is not None and len(primary_out):
        entries=trade_entries(primary_out,theme_members,close,open_,high,low,volume); ema10=close.ewm(span=10,adjust=False,min_periods=8).mean(); ema21=close.ewm(span=21,adjust=False,min_periods=15).mean(); policies=("HOLD20","HOLD63","FAST3_RUNNER10","FAST3_RUNNER21","FAST3_RUNNER21_PARTIAL","FAST3_THEME_TIGHTEN")
        alltr=[]
        for policy in policies:
            rows=[]
            for r in entries.itertuples(index=False):
                z=simulate_one(r,policy,close,open_,high,low,ema10,ema21,momentum_mask); rows.append({**r._asdict(),"policy":policy,**z})
            td=pd.DataFrame(rows); alltr.append(td); result["trades"][policy]={p:trade_stats(td,p) for p in ("ALL","DISCOVERY","CONFIRMATION")}
        trades=pd.concat(alltr,ignore_index=True) if alltr else pd.DataFrame(); entries.to_csv(out/"entries.csv",index=False); trades.to_csv(out/"trade_results.csv.gz",index=False,compression="gzip")
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8"); print("===RRG_TAIL_RESULT==="); print(json.dumps(safe(result),ensure_ascii=False)); print("===END===",flush=True)

if __name__=="__main__": main()
