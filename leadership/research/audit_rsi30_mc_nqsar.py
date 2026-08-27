from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import build_dashboard as bd

METHOD = "RISE_LE30_W20"
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def pf(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors="coerce").dropna()
    if z.empty:
        return None
    pos = float(z[z > 0].sum())
    neg = float(-z[z < 0].sum())
    return None if neg == 0 else pos / neg


def cluster_ci(df: pd.DataFrame, cluster: str, seed: int, reps: int = 2500) -> list[float | None]:
    z = df[[cluster, "entry_20"]].dropna()
    if z.empty:
        return [None, None]
    means = z.groupby(cluster, observed=True)["entry_20"].mean().to_numpy(float)
    if len(means) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(means, size=(reps, len(means)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def stats(g: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    z = g.dropna(subset=["entry_20"]).copy()
    if z.empty:
        return {"n": 0}
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    p = pos.reindex(pd.to_datetime(z.signal_date)).to_numpy(float)
    good = np.isfinite(p)
    z = z.loc[good].copy()
    p = p[good]
    if z.empty:
        return {"n": 0}
    z["block20"] = np.floor(p / 20.0).astype("int64")
    r = pd.to_numeric(z.entry_20, errors="coerce")
    mae = pd.to_numeric(z.mae_20, errors="coerce")
    mfe = pd.to_numeric(z.mfe_20, errors="coerce")
    q = r.quantile([0.10, 0.90, 0.95])
    return {
        "n": int(len(z)),
        "signal_dates": int(z.signal_date.nunique()),
        "themes": int(z.theme.nunique()),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win": float((r > 0).mean()),
        "pf": pf(r),
        "mae": float(mae.mean()),
        "mfe": float(mfe.mean()),
        "p10": float(q.loc[0.10]),
        "p90": float(q.loc[0.90]),
        "p95": float(q.loc[0.95]),
        "date_ci95": cluster_ci(z, "signal_date", seed),
        "block20_ci95": cluster_ci(z, "block20", seed + 1000),
        "theme_ci95": cluster_ci(z, "theme", seed + 2000),
    }


def rejection_stats(g_all: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    rejected = g_all.loc[~mask].dropna(subset=["entry_20"]).copy()
    accepted = g_all.loc[mask].dropna(subset=["entry_20"]).copy()
    r = pd.to_numeric(rejected.entry_20, errors="coerce")
    return {
        "accepted_n": int(len(accepted)),
        "rejected_n": int(len(rejected)),
        "accept_rate": float(len(accepted) / len(g_all)) if len(g_all) else None,
        "rejected_mean": float(r.mean()) if len(r) else None,
        "rejected_win": float((r > 0).mean()) if len(r) else None,
        "rejected_gt10_n": int((r > 0.10).sum()),
        "rejected_gt20_n": int((r > 0.20).sum()),
        "rejected_lt0_n": int((r < 0).sum()),
        "rejected_ltminus10_n": int((r < -0.10).sum()),
    }


def normalize_index(s: pd.Series) -> pd.Series:
    z = s.copy()
    idx = pd.to_datetime(z.index)
    try:
        idx = idx.tz_localize(None)
    except TypeError:
        idx = idx.tz_convert(None)
    z.index = idx.normalize()
    return z[~z.index.duplicated(keep="last")].sort_index()


def build_mc(asof: str) -> pd.DataFrame:
    # Call the production MC implementation directly. No research reimplementation.
    macro = bd._fetch_mc_long_history(asof=pd.Timestamp(asof))
    if len(macro) < 50:
        raise RuntimeError(f"MC long-history coverage too low: {len(macro)}/57")
    mc, _breakdown, _dropped, _active, _vals = bd.mri_frame(macro, W=None)
    mc = normalize_index(pd.to_numeric(mc, errors="coerce")).rename("mc")
    if mc.dropna().empty:
        raise RuntimeError("production MC returned no finite rows")
    z = pd.DataFrame({"mc": mc})
    z["mc_prev1"] = z.mc.shift(1)
    z["mc_prev2"] = z.mc.shift(2)
    z["mc_up1"] = z.mc > z.mc_prev1
    z["mc_up2"] = (z.mc > z.mc_prev1) & (z.mc_prev1 > z.mc_prev2)
    z["mc_ge20"] = z.mc >= 20.0
    z["mc_primary"] = z.mc_up1 & z.mc_ge20
    z["mc_low5"] = z.mc.rolling(5, min_periods=1).min()
    z["mc_low10"] = z.mc.rolling(10, min_periods=1).min()
    z["mc_rebound5"] = z.mc - z.mc_low5
    z["mc_rebound10"] = z.mc - z.mc_low10
    z["mc_rebound5_3"] = z.mc_up1 & (z.mc_rebound5 >= 3.0)
    z["mc_rebound10_5"] = z.mc_up1 & (z.mc_rebound10 >= 5.0)
    return z


def download_nq(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("NQ=F", start=start, end=end, auto_adjust=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("NQ=F download returned empty frame")
    if isinstance(raw.columns, pd.MultiIndex):
        if "NQ=F" in raw.columns.get_level_values(-1):
            raw = raw.xs("NQ=F", axis=1, level=-1)
        else:
            raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index)
    try:
        raw.index = raw.index.tz_localize(None)
    except TypeError:
        raw.index = raw.index.tz_convert(None)
    raw.index = raw.index.normalize()
    need = ["High", "Low", "Close"]
    if any(c not in raw.columns for c in need):
        raise RuntimeError(f"NQ=F missing columns: {raw.columns.tolist()}")
    return raw[need].astype(float).dropna().sort_index()


def build_nqsar(start: str, end: str) -> pd.DataFrame:
    # Exact reconstructed production FSM on Yahoo NQ=F history.
    df = download_nq(start, end)
    h, l, c = df.High.to_numpy(float), df.Low.to_numpy(float), df.Close.to_numpy(float)
    sar = bd._psar(h, l, c, step=0.02, mx=0.08)
    ema21 = df.Close.ewm(span=21, adjust=False).mean().to_numpy(float)
    d = df.Close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1 / 14, adjust=False).mean()
    rd = dn.ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100.0 - 100.0 / (1.0 + ru / rd)).to_numpy(float)
    bd._onimine_state(c, sar, ema21, rsi)
    colors = list(bd._LAST_ONIMINE_SERIES or [])
    if len(colors) != len(df):
        raise RuntimeError(f"NQSAR series length mismatch: {len(colors)} vs {len(df)}")
    z = pd.DataFrame(index=df.index)
    z["nq_color"] = colors
    z["nq_prev_color"] = z.nq_color.shift(1)
    severity = {"Red": 0, "Yellow": 1, "Green": 2, "Blue": 3}
    z["nq_sev"] = z.nq_color.map(severity)
    z["nq_prev_sev"] = z.nq_prev_color.map(severity)
    z["nq_bull"] = z.nq_color.isin(["Blue", "Green"])
    z["nq_not_red"] = ~z.nq_color.eq("Red")
    z["nq_upgrade"] = z.nq_sev > z.nq_prev_sev
    z["nq_red_exit"] = z.nq_prev_color.eq("Red") & ~z.nq_color.eq("Red")
    red = z.nq_color.eq("Red").astype(int)
    z["nq_recent_red_bull10"] = z.nq_bull & (red.shift(1).rolling(10, min_periods=1).max().fillna(0) > 0)
    return z


def add_market_state(tr: pd.DataFrame, mc: pd.DataFrame, nq: pd.DataFrame) -> pd.DataFrame:
    z = tr.copy()
    z["signal_date"] = pd.to_datetime(z.signal_date).dt.normalize()
    mc2 = mc.reset_index().rename(columns={"index": "signal_date"})
    nq2 = nq.reset_index().rename(columns={"index": "signal_date"})
    z = z.merge(mc2, on="signal_date", how="left", validate="many_to_one")
    z = z.merge(nq2, on="signal_date", how="left", validate="many_to_one")
    mc_cov = float(z.mc.notna().mean())
    nq_cov = float(z.nq_color.notna().mean())
    if mc_cov < 0.98 or nq_cov < 0.98:
        raise RuntimeError(f"signal-date market-state coverage too low: MC={mc_cov:.3%} NQSAR={nq_cov:.3%}")
    for c in [
        "mc_up1", "mc_up2", "mc_ge20", "mc_primary", "mc_rebound5_3", "mc_rebound10_5",
        "nq_bull", "nq_not_red", "nq_upgrade", "nq_red_exit", "nq_recent_red_bull10",
    ]:
        z[c] = z[c].fillna(False).astype(bool)
    z["primary_all"] = True
    z["primary_mc"] = z.mc_primary
    z["primary_nq"] = z.nq_bull
    z["primary_or"] = z.mc_primary | z.nq_bull
    z["primary_and"] = z.mc_primary & z.nq_bull
    return z


def policy_block(g: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    policies = {
        "A_ALL": g.primary_all,
        "B_MC_UP1_GE20": g.primary_mc,
        "C_NQSAR_BLUE_GREEN": g.primary_nq,
        "D_MC_OR_NQSAR": g.primary_or,
        "E_MC_AND_NQSAR": g.primary_and,
    }
    exploratory = {
        "MC_UP1": g.mc_up1,
        "MC_UP2": g.mc_up2,
        "MC_REBOUND5_GE3": g.mc_rebound5_3,
        "MC_REBOUND10_GE5": g.mc_rebound10_5,
        "NQ_NOT_RED": g.nq_not_red,
        "NQ_UPGRADE": g.nq_upgrade,
        "NQ_RED_EXIT": g.nq_red_exit,
        "NQ_RECENT_RED_TO_BULL10": g.nq_recent_red_bull10,
    }
    out: dict[str, Any] = {"primary": {}, "exploratory": {}}
    i = 0
    for name, mask in policies.items():
        out["primary"][name] = {
            "stats": stats(g.loc[mask], calendar, seed + i * 10),
            "rejection": rejection_stats(g, mask),
        }
        i += 1
    for name, mask in exploratory.items():
        out["exploratory"][name] = {
            "stats": stats(g.loc[mask], calendar, seed + 1000 + i * 10),
            "rejection": rejection_stats(g, mask),
        }
        i += 1
    return out


def special_rows(z: pd.DataFrame, start: str, end: str) -> list[dict[str, Any]]:
    cols = [
        "signal_date", "entry_date", "day0_date", "theme", "symbol", "entry_20", "mae_20", "mfe_20",
        "mc", "mc_prev1", "mc_up1", "mc_primary", "mc_rebound5", "mc_rebound10",
        "nq_color", "nq_prev_color", "nq_bull", "nq_upgrade", "nq_red_exit",
        "primary_mc", "primary_nq", "primary_or", "primary_and",
    ]
    q = z[(z.signal_date >= pd.Timestamp(start)) & (z.signal_date <= pd.Timestamp(end))].copy()
    return q[cols].sort_values(["signal_date", "entry_20"]).to_dict(orient="records")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--asof", default="2026-08-27")
    ap.add_argument("--nq-start", default="2010-01-01")
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    tr = pd.read_csv(args.input, compression="gzip", parse_dates=["day0_date", "signal_date", "entry_date"])
    tr = tr[tr.method.eq(METHOD)].copy()
    tr = tr.sort_values(["day0_date", "theme", "symbol", "method", "rank_type"]).drop_duplicates(
        ["day0_date", "theme", "symbol", "method"], keep="first"
    )
    if len(tr) != 638:
        raise RuntimeError(f"expected 638 deduplicated {METHOD} rows, got {len(tr)}")
    tr["period"] = np.where(tr.day0_date <= DISC_END, "DISCOVERY", "CONFIRM")
    tr["signal_year"] = tr.signal_date.dt.year

    print("BUILD_MC", flush=True)
    mc = build_mc(args.asof)
    print("BUILD_NQSAR", flush=True)
    nq_end = (pd.Timestamp(args.asof) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    nq = build_nqsar(args.nq_start, nq_end)
    z = add_market_state(tr, mc, nq)
    z.to_csv(out / "rsi30_mc_nqsar_trades.csv.gz", index=False, compression="gzip")

    # Use MC session calendar for the same style of 20-session block bootstrap.
    calendar = mc.index
    summary: dict[str, Any] = {
        "method": METHOD,
        "n": int(len(z)),
        "dedup_rule": ["day0_date", "theme", "symbol", "method"],
        "market_state_coverage": {
            "mc": float(z.mc.notna().mean()),
            "nqsar": float(z.nq_color.notna().mean()),
        },
        "mc_definition": "production mri_frame: 57 ETFs x 12 equal metrics -> EMA2 Raw -> prior-3780-session MC15 transform",
        "nqsar_definition": "production _psar + _onimine_state on Yahoo NQ=F: PSAR 0.02/0.02/0.08 + EMA21 + Wilder RSI14",
        "periods": {},
        "years": {},
        "special": {},
    }

    seed = 20000
    for period, g in z.groupby("period", observed=True):
        summary["periods"][period] = policy_block(g, calendar, seed)
        seed += 10000

    for y, g in z.groupby("signal_year", observed=True):
        summary["years"][str(int(y))] = policy_block(g, calendar, seed + int(y))

    summary["special"]["2020_March"] = special_rows(z, "2020-03-01", "2020-03-31")
    summary["special"]["2025_April_panic"] = special_rows(z, "2025-04-01", "2025-04-18")
    summary["special"]["2018_February"] = special_rows(z, "2018-02-01", "2018-02-20")
    summary["special"]["2024_August"] = special_rows(z, "2024-08-01", "2024-08-16")

    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")

    print("COVERAGE", json.dumps(summary["market_state_coverage"]), flush=True)
    for period in ("DISCOVERY", "CONFIRM"):
        print(period, json.dumps(safe(summary["periods"][period]["primary"]), ensure_ascii=False), flush=True)
    print("SPECIAL_2020_ROWS", len(summary["special"]["2020_March"]), flush=True)
    print("SPECIAL_2025_ROWS", len(summary["special"]["2025_April_panic"]), flush=True)


if __name__ == "__main__":
    main()
