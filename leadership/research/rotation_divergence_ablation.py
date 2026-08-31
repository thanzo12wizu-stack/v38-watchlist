from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20, 40)
COOLDOWN = 20
BOOT_REPS = 3000


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def eventize(panel: pd.DataFrame, mask: pd.Series, label: str) -> pd.DataFrame:
    cols = ["date", "sector", *[f"fwd_excess_{h}d" for h in HORIZONS]]
    use = panel[cols].copy()
    use["active"] = mask.fillna(False).to_numpy(bool)
    rows: list[dict[str, Any]] = []
    for sector, grp in use.groupby("sector", sort=False):
        grp = grp.sort_values("date")
        prev = False
        last = -10000
        for pos, row in enumerate(grp.itertuples(index=False)):
            active = bool(row.active)
            if active and not prev and pos - last >= COOLDOWN:
                rec = {"date": pd.Timestamp(row.date), "sector": sector, "condition": label}
                for h in HORIZONS:
                    rec[f"fwd_excess_{h}d"] = getattr(row, f"fwd_excess_{h}d")
                rows.append(rec)
                last = pos
            prev = active
    return pd.DataFrame(rows)


def block_ids(dates: pd.Series, calendar: pd.DatetimeIndex) -> np.ndarray:
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    ix = pos.reindex(pd.to_datetime(dates)).to_numpy(float)
    return np.floor(ix / 20.0).astype(np.int64)


def cluster_boot_mean(df: pd.DataFrame, value_col: str, cluster_col: str, seed: int) -> list[float | None]:
    use = df[[cluster_col, value_col]].dropna()
    if use.empty:
        return [None, None]
    agg = use.groupby(cluster_col, observed=True)[value_col].agg(["sum", "count"])
    if len(agg) < 2:
        return [None, None]
    sums = agg["sum"].to_numpy(float)
    counts = agg["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    vals = np.empty(BOOT_REPS, dtype=float)
    n = len(agg)
    for i in range(BOOT_REPS):
        idx = rng.integers(0, n, size=n)
        vals[i] = sums[idx].sum() / counts[idx].sum()
    return [float(x) for x in np.quantile(vals, [0.025, 0.975])]


def summarize(events: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    if events.empty:
        return {"n": 0, "horizons": {}}
    ev = events.copy()
    ev["block20"] = block_ids(ev["date"], calendar)
    out: dict[str, Any] = {"n": int(len(ev)), "dates": int(ev.date.nunique()), "sectors": int(ev.sector.nunique()), "horizons": {}}
    for j, h in enumerate(HORIZONS):
        col = f"fwd_excess_{h}d"
        x = pd.to_numeric(ev[col], errors="coerce")
        finite = ev[np.isfinite(x.to_numpy(float))].copy()
        if finite.empty:
            out["horizons"][str(h)] = {"n": 0}
            continue
        vals = finite[col].astype(float)
        out["horizons"][str(h)] = {
            "n": int(len(vals)), "mean": float(vals.mean()), "median": float(vals.median()),
            "positive_rate": float((vals > 0).mean()),
            "block20_ci95": cluster_boot_mean(finite, col, "block20", seed + j * 100),
            "sector_cluster_ci95": cluster_boot_mean(finite, col, "sector", seed + 1000 + j * 100),
        }
    return out


def period_frames(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if events.empty:
        return {"ALL": events}
    d = pd.to_datetime(events.date)
    out = {
        "ALL_2022_PLUS": events[d >= pd.Timestamp("2022-01-01")],
        "DISCOVERY_2022_2023": events[(d >= pd.Timestamp("2022-01-01")) & (d <= pd.Timestamp("2023-12-31"))],
        "CONFIRMATION_2024_PLUS": events[d >= pd.Timestamp("2024-01-01")],
    }
    for year in range(2022, 2027):
        out[str(year)] = events[d.dt.year == year]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(args.panel, parse_dates=["date"])
    panel = panel[panel["date"] >= pd.Timestamp("2022-01-01")].copy()
    calendar = pd.DatetimeIndex(sorted(panel.date.unique()))

    p70 = panel["price_score"] >= 70
    p60 = panel["price_score"] >= 60
    plag60 = panel["price_score"] < 60
    i60 = panel["internal_score"] >= 60
    iw50 = panel["internal_score"] < 50
    fin = panel["flow20_pct_aum"] > 0
    fout = panel["flow20_pct_aum"] < 0
    delta10 = panel["internal_delta20"] >= 10

    families: dict[str, dict[str, pd.Series]] = {
        "DISTRIBUTION": {
            "PRICE_STRONG_ONLY": p70,
            "INTERNAL_WEAK_ONLY": iw50,
            "FLOW_OUT_ONLY": fout,
            "PRICE_INTERNAL": p70 & iw50,
            "PRICE_FLOW": p70 & fout,
            "INTERNAL_FLOW": iw50 & fout,
            "FULL_DISTRIBUTION": p70 & iw50 & fout,
        },
        "HIDDEN": {
            "PRICE_LAG_ONLY": plag60,
            "INTERNAL_STRONG_ONLY": i60,
            "FLOW_IN_ONLY": fin,
            "PRICE_INTERNAL": plag60 & i60,
            "PRICE_FLOW": plag60 & fin,
            "INTERNAL_FLOW": i60 & fin,
            "FULL_HIDDEN": plag60 & i60 & fin,
            "FULL_EARLY_DELTA10": plag60 & i60 & fin & delta10,
        },
        "CONFIRMED": {
            "PRICE_STRONG_ONLY": p70,
            "INTERNAL_STRONG_ONLY": i60,
            "FLOW_IN_ONLY": fin,
            "PRICE_INTERNAL": p70 & i60,
            "PRICE_FLOW": p70 & fin,
            "INTERNAL_FLOW": i60 & fin,
            "FULL_CONFIRMED": p70 & i60 & fin,
        },
        "REDEMPTION": {
            "PRICE_STRONG60_ONLY": p60,
            "INTERNAL_STRONG_ONLY": i60,
            "FLOW_OUT_ONLY": fout,
            "PRICE_INTERNAL": p60 & i60,
            "PRICE_FLOW": p60 & fout,
            "INTERNAL_FLOW": i60 & fout,
            "FULL_REDEMPTION": p60 & i60 & fout,
        },
    }

    report: dict[str, Any] = {
        "schema": 1,
        "research_only": True,
        "purpose": "Ablate Price/Internal/Exact Flow combinations before spending effort on point-in-time constituent reconstruction.",
        "internal_quality": "PROXY_RESEARCH_ONLY_FIXED_CURRENT_HOLDINGS",
        "flow_quality": "EXACT_OFFICIAL_SHARES_OUTSTANDING_DERIVED",
        "families": {},
    }
    rows: list[dict[str, Any]] = []
    all_events: list[pd.DataFrame] = []
    seed = 70000
    for fi, (family, conditions) in enumerate(families.items()):
        report["families"][family] = {}
        for ci, (label, mask) in enumerate(conditions.items()):
            events = eventize(panel, mask, label)
            if not events.empty:
                events["family"] = family
                all_events.append(events)
            period_out: dict[str, Any] = {}
            for pi, (period, pev) in enumerate(period_frames(events).items()):
                s = summarize(pev, calendar, seed + fi * 10000 + ci * 1000 + pi * 10)
                period_out[period] = s
                for h in HORIZONS:
                    hs = s.get("horizons", {}).get(str(h), {})
                    rows.append({
                        "family": family, "condition": label, "period": period, "horizon": h,
                        "n": hs.get("n", 0), "mean_excess": hs.get("mean"), "median_excess": hs.get("median"),
                        "positive_rate": hs.get("positive_rate"),
                        "block_ci_lo": (hs.get("block20_ci95") or [None, None])[0],
                        "block_ci_hi": (hs.get("block20_ci95") or [None, None])[1],
                        "sector_ci_lo": (hs.get("sector_cluster_ci95") or [None, None])[0],
                        "sector_ci_hi": (hs.get("sector_cluster_ci95") or [None, None])[1],
                    })
            report["families"][family][label] = period_out

    result_rows = pd.DataFrame(rows)
    result_rows.to_csv(args.output / "ablation_results.csv", index=False)
    if all_events:
        pd.concat(all_events, ignore_index=True).sort_values(["date", "family", "condition", "sector"]).to_csv(args.output / "ablation_events.csv", index=False, date_format="%Y-%m-%d")

    # Exact Flow alone: cross-sectional percentile ranks, top/bottom transition events.
    flow_wide = panel.pivot(index="date", columns="sector", values="flow20_pct_aum").sort_index()
    flow_rank = flow_wide.rank(axis=1, pct=True, method="average") * 100.0
    flow_panel = panel[["date", "sector", *[f"fwd_excess_{h}d" for h in HORIZONS]]].copy()
    rank_long = flow_rank.stack().dropna().rename("flow_rank").reset_index()
    flow_panel = flow_panel.merge(rank_long, on=["date", "sector"], how="left")
    exact_flow_tests = {}
    for label, mask in {
        "FLOW_TOP20_RANK": flow_panel["flow_rank"] >= 80,
        "FLOW_BOTTOM20_RANK": flow_panel["flow_rank"] <= 20,
    }.items():
        ev = eventize(flow_panel, mask, label)
        exact_flow_tests[label] = {p: summarize(e, calendar, 99000 + k * 100) for k, (p, e) in enumerate(period_frames(ev).items())}
    report["exact_flow_rank_tests"] = exact_flow_tests

    (args.output / "ablation_report.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Rotation Divergence Ablation", "", "Research-only. Internals use fixed-current holdings and remain PROXY_RESEARCH_ONLY.", "", "## Confirmation 2024+ baseline component comparison (20D / 40D)", "", "| Family | Condition | 20D | 40D |", "|---|---|---:|---:|"]
    for family, conditions in families.items():
        for label in conditions:
            sub = result_rows[(result_rows.family == family) & (result_rows.condition == label) & (result_rows.period == "CONFIRMATION_2024_PLUS")]
            vals = []
            for h in (20, 40):
                r = sub[sub.horizon == h]
                if r.empty or pd.isna(r.iloc[0].mean_excess):
                    vals.append("n/a")
                else:
                    vals.append(f"{100*r.iloc[0].mean_excess:+.2f}% (n={int(r.iloc[0].n)})")
            lines.append(f"| {family} | {label} | {vals[0]} | {vals[1]} |")
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE rows={len(result_rows)}", flush=True)


if __name__ == "__main__":
    main()
