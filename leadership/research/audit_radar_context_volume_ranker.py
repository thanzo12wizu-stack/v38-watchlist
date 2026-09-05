from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_radar_cohort_discriminator as disc
import validate_early_rotation as er
import validate_ignition_quality as iq

WINDOWS = (5, 10, 20)
TOPKS = (3, 5, 10)
RANKERS = (
    "HIGH_ACCEL",
    "RS21_HIGH63",
    "RS21_TREND_HIGH",
    "MOM_EQ",
    "MOM_VCON",
    "MOM_THEME",
    "MOM_SECTOR",
    "MOM_INDUSTRY",
    "MOM_ALL_CONTEXT",
)


def safe(v: Any) -> Any:
    return base.safe(v)


def pct(frame: pd.DataFrame, mask: pd.DataFrame, ascending: bool = True) -> pd.DataFrame:
    x = frame.where(mask)
    return (x.rank(axis=1, pct=True, method="average", ascending=ascending) * 100.0).astype(np.float32)


def group_equal_weight_return(stock_ret: pd.DataFrame, groups: dict[str, list[str]], min_members: int = 3) -> pd.DataFrame:
    out: dict[str, pd.Series] = {}
    for name, members in groups.items():
        cols = [s for s in members if s in stock_ret.columns]
        if len(cols) < min_members:
            continue
        z = stock_ret[cols]
        n = z.notna().sum(axis=1)
        out[name] = z.mean(axis=1, skipna=True).where(n >= min_members)
    return pd.DataFrame(out)


def group_breadth(close: pd.DataFrame, groups: dict[str, list[str]], min_members: int = 3) -> pd.DataFrame:
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid = close.notna() & ema21.notna()
    above = (close > ema21).where(valid)
    out: dict[str, pd.Series] = {}
    for name, members in groups.items():
        cols = [s for s in members if s in close.columns]
        if len(cols) < min_members:
            continue
        z = above[cols]
        n = z.notna().sum(axis=1)
        out[name] = (z.mean(axis=1, skipna=True) * 100.0).where(n >= min_members)
    return pd.DataFrame(out)


def period_return(ret: pd.DataFrame, window: int) -> pd.DataFrame:
    min_periods = int(np.ceil(window * 0.8))
    z = np.log1p(ret.where(ret > -0.999999))
    return np.expm1(z.rolling(window, min_periods=min_periods).sum())


def group_context(close: pd.DataFrame, stock_ret: pd.DataFrame, groups: dict[str, list[str]]) -> pd.DataFrame:
    gr = group_equal_weight_return(stock_ret, groups)
    if gr.empty:
        return gr
    r63 = period_return(gr, 63)
    rs63 = r63.rank(axis=1, pct=True, method="average") * 100.0
    accel20 = rs63 - rs63.shift(20)
    accel_pct = accel20.rank(axis=1, pct=True, method="average") * 100.0
    breadth = group_breadth(close, groups)
    breadth_pct = breadth.rank(axis=1, pct=True, method="average") * 100.0
    common = rs63.columns.intersection(accel_pct.columns).intersection(breadth_pct.columns)
    return ((rs63[common] + accel_pct[common] + breadth_pct[common]) / 3.0).astype(np.float32)


def map_group_score(ctx: pd.DataFrame, symbol_to_group: dict[str, str], stock_cols: list[str], index: pd.DatetimeIndex) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=index, columns=stock_cols, dtype=np.float32)
    by_group: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        g = symbol_to_group.get(sym)
        if g:
            by_group[g].append(sym)
    for g, syms in by_group.items():
        if g not in ctx.columns:
            continue
        vals = ctx[g].reindex(index).to_numpy(np.float32)
        out.loc[:, syms] = np.repeat(vals[:, None], len(syms), axis=1)
    return out


def active_from_fresh(fresh: pd.DataFrame, window: int) -> pd.DataFrame:
    return fresh.rolling(window, min_periods=1).max().fillna(0).astype(bool)


def ranker_frame(name: str, f: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if name == "HIGH_ACCEL":
        return (0.50 * f["RS21"] + 0.25 * f["HIGH63"] + 0.25 * f["ACC21"]).astype(np.float32)
    if name == "RS21_HIGH63":
        return (0.75 * f["RS21"] + 0.25 * f["HIGH63"]).astype(np.float32)
    if name == "RS21_TREND_HIGH":
        return (0.55 * f["RS21"] + 0.25 * f["HIGH63"] + 0.20 * f["TREND50"]).astype(np.float32)
    if name == "MOM_EQ":
        return ((f["RS21"] + f["HIGH63"] + f["ACC21"]) / 3.0).astype(np.float32)
    if name == "MOM_VCON":
        return ((f["RS21"] + f["HIGH63"] + f["ACC21"] + f["VCON"]) / 4.0).astype(np.float32)
    if name == "MOM_THEME":
        return ((f["RS21"] + f["HIGH63"] + f["ACC21"] + f["THEME"].fillna(50.0)) / 4.0).astype(np.float32)
    if name == "MOM_SECTOR":
        return ((f["RS21"] + f["HIGH63"] + f["ACC21"] + f["SECTOR"].fillna(50.0)) / 4.0).astype(np.float32)
    if name == "MOM_INDUSTRY":
        return ((f["RS21"] + f["HIGH63"] + f["ACC21"] + f["INDUSTRY"].fillna(50.0)) / 4.0).astype(np.float32)
    if name == "MOM_ALL_CONTEXT":
        return (
            (
                f["RS21"] + f["HIGH63"] + f["ACC21"] + f["VCON"]
                + f["THEME"].fillna(50.0) + f["SECTOR"].fillna(50.0) + f["INDUSTRY"].fillna(50.0)
            ) / 7.0
        ).astype(np.float32)
    raise ValueError(name)


def selections(score: pd.DataFrame, active: pd.DataFrame, idx: pd.DatetimeIndex) -> dict[pd.Timestamp, list[str]]:
    out: dict[pd.Timestamp, list[str]] = {}
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        s = pd.to_numeric(score.loc[d].where(active.loc[d]), errors="coerce").dropna().nlargest(max(TOPKS))
        out[d] = [str(x) for x in s.index]
        if (i + 1) % 600 == 0:
            print(f"SELECT {i+1}/{len(idx)}", flush=True)
    return out


def period_name(d: pd.Timestamp) -> str:
    y = int(pd.Timestamp(d).year)
    if y <= 2020:
        return "DEV_2016_2020"
    if y <= 2023:
        return "CONF_2021_2023"
    return "HOLDOUT_2024_2026"


def split_events(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if events.empty:
        return {k: events.copy() for k in ("ALL", "DEV_2016_2020", "CONF_2021_2023", "HOLDOUT_2024_2026")}
    years = pd.to_datetime(events["anchor_date"]).dt.year
    return {
        "ALL": events,
        "DEV_2016_2020": events.loc[years <= 2020],
        "CONF_2021_2023": events.loc[years.between(2021, 2023)],
        "HOLDOUT_2024_2026": events.loc[years >= 2024],
    }


def event_pack(events: pd.DataFrame, sel: dict[pd.Timestamp, list[str]], close: pd.DataFrame, k: int) -> dict[str, Any]:
    if events.empty:
        return {"n": 0}
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    rows = []
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol)
        a = pd.Timestamp(ev.anchor_date)
        e = pd.Timestamp(ev.final_date)
        ap = delay.px(close, a, sym, None)
        if ap is None or a not in pos:
            continue
        found = None
        gain = np.nan
        for d0 in idx[(idx >= a) & (idx <= e)]:
            d = pd.Timestamp(d0)
            cp = delay.px(close, d, sym, None)
            if cp is None:
                continue
            if sym in sel.get(d, [])[:k]:
                found = d
                gain = float(cp / ap - 1.0)
                break
        rows.append({"captured": found is not None, "gain": gain})
    x = pd.DataFrame(rows)
    if x.empty:
        return {"n": 0}
    g = pd.to_numeric(x["gain"], errors="coerce")
    return {
        "n": int(len(x)),
        "captured_n": int(x["captured"].sum()),
        "captured_rate": float(x["captured"].mean()),
        "within_20pct_all": float((g <= 0.20).fillna(False).mean()),
        "within_30pct_all": float((g <= 0.30).fillna(False).mean()),
        "within_50pct_all": float((g <= 0.50).fillna(False).mean()),
        "within_100pct_all": float((g <= 1.00).fillna(False).mean()),
        "median_first_gain_captured": float(g[x["captured"]].median()) if x["captured"].any() else None,
    }


def quality(sel: dict[pd.Timestamp, list[str]], fresh: pd.DataFrame, close: pd.DataFrame, k: int = 5) -> dict[str, Any]:
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    seen: set[tuple[str, pd.Timestamp]] = set()
    rows = []
    for d0, syms in sel.items():
        d = pd.Timestamp(d0)
        i = pos.get(d)
        if i is None:
            continue
        for sym in syms[:k]:
            hits = fresh[sym].loc[:d]
            hits = hits.index[hits.fillna(False)]
            ep = pd.Timestamp(hits[-1]) if len(hits) else d
            key = (sym, ep)
            if key in seen:
                continue
            seen.add(key)
            p0 = delay.px(close, d, sym, None)
            p63 = delay.px(close, pd.Timestamp(idx[i + 63]), sym, None) if i + 63 < len(idx) else None
            p126 = delay.px(close, pd.Timestamp(idx[i + 126]), sym, None) if i + 126 < len(idx) else None
            rows.append({
                "date": d,
                "fwd63": float(p63 / p0 - 1.0) if p0 and p63 else np.nan,
                "fwd126": float(p126 / p0 - 1.0) if p0 and p126 else np.nan,
            })
    x = pd.DataFrame(rows)
    out = {}
    if x.empty:
        return out
    x["period"] = x["date"].map(period_name)
    for p, z in x.groupby("period"):
        r63 = pd.to_numeric(z["fwd63"], errors="coerce").dropna()
        r126 = pd.to_numeric(z["fwd126"], errors="coerce").dropna()
        out[p] = {
            "n": int(len(z)),
            "fwd63_n": int(len(r63)),
            "fwd63_median": float(r63.median()) if len(r63) else None,
            "fwd63_positive": float((r63 > 0).mean()) if len(r63) else None,
            "fwd126_n": int(len(r126)),
            "fwd126_median": float(r126.median()) if len(r126) else None,
            "fwd126_positive": float((r126 > 0).mean()) if len(r126) else None,
            "fwd126_ge50": float((r126 >= 0.50).mean()) if len(r126) else None,
        }
    return out


def dev_key(rec: dict[str, Any]) -> tuple:
    a5 = rec["annual_top5"]["DEV_2016_2020"]["Top5"]
    r5 = rec["rolling126_top10"]["DEV_2016_2020"]["Top5"]
    med = a5.get("median_first_gain_captured")
    return (
        a5.get("within_30pct_all") or 0.0,
        a5.get("within_50pct_all") or 0.0,
        r5.get("within_30pct_all") or 0.0,
        r5.get("within_50pct_all") or 0.0,
        a5.get("captured_rate") or 0.0,
        -(med if med is not None else 99.0),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("LOAD TAXONOMY", flush=True)
    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, theme_diag = er.extract_theme_members(snapshot)
    imap = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    allowed = set(imap) & universe
    selected = er.stratified_symbols(theme_members_all, allowed, args.max_tickers)

    warmup = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=1150)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=10)).date())
    print("DOWNLOAD OHLCV ONCE", flush=True)
    ohlcv, diag = iq.download_ohlcv(selected, warmup, download_end, args.batch_size)
    close = ohlcv["close"]
    volume = ohlcv["volume"]
    cols = [s for s in selected if s in close.columns and s in volume.columns]
    close = close[cols].copy()
    volume = volume[cols].copy()
    if len(cols) < 500:
        raise RuntimeError(f"coverage too small: {len(cols)}")

    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    excluded = base.read_structural_bio_exclusions(root, cols)
    if excluded:
        pool.loc[:, [s for s in excluded if s in pool.columns]] = False

    idx = close.index[(close.index >= pd.Timestamp(args.analysis_start)) & (close.index <= pd.Timestamp(args.analysis_end))]
    rs = delay.rs_matrices(close, pool)
    radar = (pool & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))).fillna(False)
    fresh = (radar & ~radar.shift(1).fillna(False)).fillna(False)

    print("BUILD STOCK FEATURES", flush=True)
    high63_raw = close / close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(high63_raw, pool)
    acc21 = pct(rs[21] - rs[21].shift(20), pool)
    sma50 = close.rolling(50, min_periods=35).mean()
    trend50 = pct(close / sma50.replace(0.0, np.nan), pool)
    prior_vol10 = volume.shift(1).rolling(10, min_periods=8).mean()
    prior_vol20 = volume.shift(1).rolling(20, min_periods=15).mean()
    vcon_ratio = prior_vol10 / prior_vol20.replace(0.0, np.nan)
    vcon = pct(vcon_ratio, pool, ascending=False)

    print("BUILD LOO THEME", flush=True)
    peer = loo.build_leave_one_out_scores(root, {"close": close})
    theme = pd.DataFrame(np.asarray(peer["best_score"], dtype=np.float32), index=close.index, columns=close.columns)

    print("BUILD SECTOR / INDUSTRY CONTEXT", flush=True)
    sector_groups: dict[str, list[str]] = defaultdict(list)
    industry_groups: dict[str, list[str]] = defaultdict(list)
    sym_sector: dict[str, str] = {}
    sym_industry: dict[str, str] = {}
    for sym in cols:
        pair = imap.get(sym)
        if not pair:
            continue
        sec, ind = pair
        if sec:
            sector_groups[sec].append(sym)
            sym_sector[sym] = sec
        if ind:
            industry_groups[ind].append(sym)
            sym_industry[sym] = ind
    stock_ret = close.pct_change(fill_method=None).where(lambda x: x > -0.999999)
    sec_ctx_raw = group_context(close, stock_ret, dict(sector_groups))
    ind_ctx_raw = group_context(close, stock_ret, dict(industry_groups))
    sector = map_group_score(sec_ctx_raw, sym_sector, cols, close.index)
    industry = map_group_score(ind_ctx_raw, sym_industry, cols, close.index)

    features = {
        "RS21": rs[21].astype(np.float32),
        "HIGH63": high63,
        "ACC21": acc21,
        "TREND50": trend50,
        "VCON": vcon,
        "THEME": theme,
        "SECTOR": sector,
        "INDUSTRY": industry,
    }

    annual = delay.annual_leader_events(close, pool, idx, include_partial_2026=False)
    annual = annual.loc[annual["top5"]].copy()
    rolling = disc.rolling126_top10(close, pool, idx)
    labels = {"annual_top5": annual, "rolling126_top10": rolling}

    result: dict[str, Any] = {
        "status": "RADAR_CONTEXT_VOLUME_RANKER_AUDIT",
        "scope": "research only; main/UI/live untouched",
        "design": {
            "radar": "base tradability pool (DDV>=10M) and Any(RS21,RS42,RS63)>=85",
            "execution_note": "recognition audit only; DDV20 and portfolio execution are deferred until a ranker survives holdout",
            "windows": list(WINDOWS),
            "topks": list(TOPKS),
            "rankers": list(RANKERS),
            "winner_selection": "DEV 2016-2020 only; lexicographic: annual Top5 Top5 within30, within50, rolling Top10 Top5 within30, within50, annual capture, lower median gain",
            "confirmation": "2021-2023 untouched",
            "holdout": "2024-2026 untouched; annual labels use complete years only, rolling labels may include 2026 if 126d outcome exists",
            "market_gate": "ignored in recognition audit because prior audit showed it delays leader capture",
            "taxonomy_caveat": "Sector/Industry and Theme membership use current repository taxonomy; any surviving context rule requires a later PIT-taxonomy audit before adoption",
            "volume_contraction": "prior-day mean volume10 / prior-day mean volume20; lower ratio receives higher cross-sectional percentile",
            "context_score": "group 63d RS percentile + 20d RS-rank acceleration percentile + group EMA21 breadth percentile, equal-weighted",
        },
        "coverage": {
            "selected": len(selected),
            "downloaded": len(cols),
            "download": diag,
            "bio_excluded": len(excluded),
            "theme_diagnostics": theme_diag[-3:],
            "sectors": len(sec_ctx_raw.columns),
            "industries": len(ind_ctx_raw.columns),
            "annual_top5_n": int(len(annual)),
            "rolling126_top10_n": int(len(rolling)),
        },
        "variants": {},
    }

    flat_rows = []
    for window in WINDOWS:
        active = active_from_fresh(fresh, window)
        for name in RANKERS:
            print(f"RANK {name} W{window}", flush=True)
            score = ranker_frame(name, features)
            sel = selections(score, active, idx)
            rec: dict[str, Any] = {
                "window": window,
                "ranker": name,
                "annual_top5": {},
                "rolling126_top10": {},
                "selection_quality_top5": quality(sel, fresh, close, k=5),
            }
            for lname, events in labels.items():
                for p, evs in split_events(events).items():
                    rec[lname][p] = {}
                    for k in TOPKS:
                        pack = event_pack(evs, sel, close, k)
                        rec[lname][p][f"Top{k}"] = pack
                        flat_rows.append({
                            "window": window, "ranker": name, "label": lname, "period": p, "topk": k, **pack
                        })
            result["variants"][f"W{window}_{name}"] = rec

    winner_key = max(result["variants"], key=lambda k: dev_key(result["variants"][k]))
    result["development_winner"] = winner_key
    result["development_winner_detail"] = result["variants"][winner_key]

    pd.DataFrame(flat_rows).to_csv(out / "grid_metrics.csv", index=False)
    (out / "summary_radar_context_volume_ranker.json").write_text(
        json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== RADAR_CONTEXT_VOLUME_RANKER_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False), flush=True)
    print("=== END_RADAR_CONTEXT_VOLUME_RANKER_JSON ===", flush=True)


if __name__ == "__main__":
    main()
