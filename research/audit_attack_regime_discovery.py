from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid
from research import run_backtest_8t3i1e_tqqq_resilient as resilient
import build_v38_early1_live as earlylive

START = pd.Timestamp("2016-01-04")
DISC_END = pd.Timestamp("2021-12-31")
HORIZONS = (1, 3, 5, 10, 20)


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return str(x.date())
    return x


def breadth_band(x: float) -> str:
    if not np.isfinite(x):
        return "NA"
    if x < 60:
        return "LT60"
    if x < 70:
        return "60_70"
    if x < 80:
        return "70_80"
    return "80_PLUS"


def slope_band(x: float) -> str:
    if not np.isfinite(x):
        return "NA"
    if x <= -5:
        return "DOWN_5PLUS"
    if x < 0:
        return "DOWN_0_5"
    if x < 5:
        return "UP_0_5"
    return "UP_5PLUS"


def forward_compound(ret: pd.Series, horizon: int) -> pd.Series:
    arr = pd.to_numeric(ret, errors="coerce").fillna(0.0).to_numpy(float)
    out = np.full(len(arr), np.nan, float)
    for i in range(len(arr)):
        j = i + 1 + horizon
        if j <= len(arr):
            out[i] = float(np.prod(1.0 + arr[i + 1:j]) - 1.0)
    return pd.Series(out, index=ret.index)


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        rec = {k: v for k, v in zip(group_cols, keys)}
        rec["signal_days"] = int(len(g))
        rec["breadth_mean"] = float(g["breadth"].mean()) if len(g) else None
        rec["breadth_d5_mean"] = float(g["breadth_d5"].mean()) if len(g) else None
        rec["breadth_d10_mean"] = float(g["breadth_d10"].mean()) if len(g) else None
        for h in HORIZONS:
            d = pd.to_numeric(g[f"delta_fwd{h}"], errors="coerce").dropna()
            c = pd.to_numeric(g[f"current_fwd{h}"], errors="coerce").dropna()
            n = pd.to_numeric(g[f"new_fwd{h}"], errors="coerce").dropna()
            rec[f"fwd{h}_n"] = int(len(d))
            rec[f"current_fwd{h}_mean"] = float(c.mean()) if len(c) else None
            rec[f"new_fwd{h}_mean"] = float(n.mean()) if len(n) else None
            rec[f"delta_new_minus_current_fwd{h}_mean"] = float(d.mean()) if len(d) else None
            rec[f"delta_fwd{h}_median"] = float(d.median()) if len(d) else None
            rec[f"new_win_share_fwd{h}"] = float((d > 0).mean()) if len(d) else None
        rows.append(rec)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    audit.download_ohlcv = resilient.resilient_download_ohlcv

    symbols, bio = audit.load_universe(root / "universe.csv")
    allowed = earlylive._industry_symbols(root / "industry_map.json")
    early_excluded = set(bio)
    if allowed:
        early_excluded.update(set(symbols) - set(allowed))

    warm = str((START - pd.Timedelta(days=1600)).date())
    end_download = str((DISC_END + pd.Timedelta(days=1)).date())
    print("DISCOVERY_DOWNLOAD_STOCKS", flush=True)
    ohlcv, diag = audit.download_ohlcv(symbols, warm, end_download, args.batch_size)
    if float(diag.get("coverage") or 0) < 0.85:
        raise RuntimeError(diag)

    print("DISCOVERY_BUILD_INPUTS", flush=True)
    m = broad.build_inputs(ohlcv, bio)
    mx = audit.build_stock_inputs(ohlcv, bio, DISC_END)
    e = pit.early_inputs(ohlcv["close"], ohlcv["volume"], early_excluded)
    nq = audit.market_nqsar(str((START - pd.Timedelta(days=120)).date()), end_download).reindex(mx["close"].index).ffill(limit=2)
    idx = mx["close"].index[(mx["close"].index >= START) & (mx["close"].index <= DISC_END)]

    from research import backtest_8t3i1e_vs_current_with_tqqq as frozen

    print("DISCOVERY_SIM_CURRENT", flush=True)
    cur = frozen.simulate_stock(idx, mx, nq, e, m, "CURRENT")
    print("DISCOVERY_SIM_8T3I1E", flush=True)
    new = frozen.simulate_stock(idx, mx, nq, e, m, "HYBRID8T3I_E1")

    f = pd.DataFrame(index=idx)
    f.index.name = "date"
    f["breadth"] = pd.to_numeric(mx["breadth"].reindex(idx), errors="coerce")
    f["breadth_d5"] = f["breadth"] - f["breadth"].shift(5)
    f["breadth_d10"] = f["breadth"] - f["breadth"].shift(10)
    f["nq_color"] = nq["nq_color"].reindex(idx).astype(object)
    f["market_mode"] = [audit.mode(f.at[d, "nq_color"], f.at[d, "breadth"]) for d in idx]
    f["breadth_band"] = [breadth_band(float(x)) if pd.notna(x) else "NA" for x in f["breadth"]]
    f["slope5_band"] = [slope_band(float(x)) if pd.notna(x) else "NA" for x in f["breadth_d5"]]
    f["slope10_band"] = [slope_band(float(x)) if pd.notna(x) else "NA" for x in f["breadth_d10"]]
    f["current_return"] = cur["return"].reindex(idx).fillna(0.0)
    f["new_return"] = new["return"].reindex(idx).fillna(0.0)
    f["delta_return"] = f["new_return"] - f["current_return"]
    for h in HORIZONS:
        f[f"current_fwd{h}"] = forward_compound(f["current_return"], h)
        f[f"new_fwd{h}"] = forward_compound(f["new_return"], h)
        f[f"delta_fwd{h}"] = f[f"new_fwd{h}"] - f[f"current_fwd{h}"]

    attack = f[f["market_mode"] == "ATTACK"].copy()
    attack.reset_index().to_csv(out / "attack_signal_days_discovery.csv", index=False)

    tables = {
        "by_breadth_band": ["breadth_band"],
        "by_color": ["nq_color"],
        "by_slope5": ["slope5_band"],
        "by_slope10": ["slope10_band"],
        "by_breadth_color": ["breadth_band", "nq_color"],
        "by_breadth_slope5": ["breadth_band", "slope5_band"],
        "by_color_slope5": ["nq_color", "slope5_band"],
    }
    summary_files = {}
    for name, cols in tables.items():
        z = summarize_group(attack, cols)
        z.to_csv(out / f"{name}.csv", index=False)
        summary_files[name] = int(len(z))

    attack["cond_blue_b70_rising5"] = (
        attack["nq_color"].astype(str).str.title().eq("Blue")
        & (attack["breadth"] >= 70.0)
        & (attack["breadth_d5"] >= 0.0)
    )
    attack["cond_blue_b80"] = (
        attack["nq_color"].astype(str).str.title().eq("Blue")
        & (attack["breadth"] >= 80.0)
    )
    cand = summarize_group(attack, ["cond_blue_b70_rising5"])
    cand["candidate_family"] = "BLUE_B70_RISING5"
    cand2 = summarize_group(attack, ["cond_blue_b80"])
    cand2["candidate_family"] = "BLUE_B80"
    cand_all = pd.concat([cand, cand2], ignore_index=True)
    cand_all.to_csv(out / "candidate_condition_diagnostics.csv", index=False)

    def simple_metrics(ret: pd.Series):
        r = pd.to_numeric(ret, errors="coerce").fillna(0.0)
        eq = (1.0 + r).cumprod()
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        dd = eq / eq.cummax() - 1.0
        sd = float(r.std(ddof=1))
        return {
            "cagr": float(eq.iloc[-1] ** (1.0 / max(yrs, 1e-9)) - 1.0),
            "mdd": float(dd.min()),
            "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else None,
            "end_multiple": float(eq.iloc[-1]),
        }

    summary = {
        "purpose": "Discovery-only ATTACK regime decomposition. No switch strategy is selected or backtested in this run.",
        "discovery_period": {"start": str(START.date()), "end": str(DISC_END.date())},
        "holdout_policy": "2022-01-03 onward is intentionally not simulated or summarized here.",
        "frozen_variants": {"current": "CURRENT", "new": "HYBRID8T3I_E1"},
        "attack_definition": "NQSAR Blue/Green and stock breadth >=60, unchanged from frozen engine.",
        "predefined_breadth_bands": ["60-<70", "70-<80", "80+"],
        "predefined_slope_bands_pct_points": ["<=-5", "-5-<0", "0-<5", ">=5"],
        "forward_horizons_sessions": list(HORIZONS),
        "candidate_conditions_diagnostic_only": ["Blue & breadth>=70 & breadth_d5>=0", "Blue & breadth>=80"],
        "stock_download": diag,
        "attack_signal_days": int(len(attack)),
        "tables": summary_files,
        "discovery_reference_metrics": {
            "CURRENT": simple_metrics(cur["return"]),
            "HYBRID8T3I_E1": simple_metrics(new["return"]),
        },
        "production_changed": False,
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DONE_ATTACK_DISCOVERY", json.dumps(safe(summary), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
