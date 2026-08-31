from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HORIZONS = (20, 40)
COOLDOWN = 20
BOOT_REPS = 5000


def eventize(panel: pd.DataFrame, mask: pd.Series, label: str) -> pd.DataFrame:
    cols = ["date", "sector", *[f"fwd_excess_{h}d" for h in HORIZONS]]
    use = panel[cols].copy()
    use["active"] = mask.fillna(False).to_numpy(bool)
    rows = []
    for sector, grp in use.groupby("sector", sort=False):
        grp = grp.sort_values("date")
        prev = False
        last = -10000
        for pos, row in enumerate(grp.itertuples(index=False)):
            active = bool(row.active)
            if active and not prev and pos - last >= COOLDOWN:
                rec = {"date": pd.Timestamp(row.date), "sector": sector, "config": label}
                for h in HORIZONS:
                    rec[f"fwd_excess_{h}d"] = getattr(row, f"fwd_excess_{h}d")
                rows.append(rec)
                last = pos
            prev = active
    return pd.DataFrame(rows)


def cluster_ci(ev: pd.DataFrame, value: str, cluster: str, calendar: pd.DatetimeIndex, seed: int) -> list[float | None]:
    x = ev[["date", "sector", value]].dropna().copy()
    if x.empty:
        return [None, None]
    if cluster == "block20":
        pos = pd.Series(np.arange(len(calendar)), index=calendar)
        x["block20"] = np.floor(pos.reindex(x.date).to_numpy(float) / 20.0).astype(np.int64)
    agg = x.groupby(cluster, observed=True)[value].agg(["sum", "count"])
    if len(agg) < 2:
        return [None, None]
    sums = agg["sum"].to_numpy(float)
    counts = agg["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    vals = np.empty(BOOT_REPS)
    n = len(agg)
    for r in range(BOOT_REPS):
        ix = rng.integers(0, n, size=n)
        vals[r] = sums[ix].sum() / counts[ix].sum()
    return [float(x) for x in np.quantile(vals, [0.025, 0.975])]


def summary(ev: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(ev)), "sectors": int(ev.sector.nunique()) if not ev.empty else 0, "horizons": {}}
    for j, h in enumerate(HORIZONS):
        col = f"fwd_excess_{h}d"
        vals = pd.to_numeric(ev[col], errors="coerce").dropna() if not ev.empty else pd.Series(dtype=float)
        finite = ev.loc[vals.index].copy() if len(vals) else pd.DataFrame()
        out["horizons"][str(h)] = {
            "n": int(len(vals)),
            "mean": None if vals.empty else float(vals.mean()),
            "median": None if vals.empty else float(vals.median()),
            "negative_rate": None if vals.empty else float((vals < 0).mean()),
            "block20_ci95": [None, None] if vals.empty else cluster_ci(finite, col, "block20", calendar, seed + j * 100),
            "sector_cluster_ci95": [None, None] if vals.empty else cluster_ci(finite, col, "sector", calendar, seed + 1000 + j * 100),
        }
    return out


def fast_means(ev: pd.DataFrame) -> dict[str, Any]:
    x = ev[ev.date >= pd.Timestamp("2024-01-01")] if not ev.empty else ev
    out: dict[str, Any] = {"n": int(len(x))}
    for h in HORIZONS:
        vals = pd.to_numeric(x[f"fwd_excess_{h}d"], errors="coerce").dropna() if not x.empty else pd.Series(dtype=float)
        out[str(h)] = {"n": int(len(vals)), "mean": None if vals.empty else float(vals.mean()), "negative_rate": None if vals.empty else float((vals < 0).mean())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="PIT internal-delta Distribution validation from audited cov80 panel")
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.panel, parse_dates=["date"]).sort_values(["sector", "date"]).reset_index(drop=True)
    required = {"date", "sector", "price_score", "internal_score", "flow20_pct_aum", "fwd_excess_20d", "fwd_excess_40d"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"audited panel missing columns: {sorted(missing)}")
    df["internal_delta20"] = df.groupby("sector", sort=False)["internal_score"].diff(20)
    calendar = pd.DatetimeIndex(sorted(df.date.unique()))

    rows = []
    events = []
    grid = [(p, d, f) for p in (65.0, 70.0, 75.0) for d in (-10.0, -20.0, -30.0) for f in (0.0, 0.5, 1.0)]
    for p, delta, flow_cut in grid:
        label = f"P{int(p)}_D{abs(int(delta))}_F{flow_cut:g}"
        mask = (df.price_score >= p) & (df.internal_delta20 <= delta) & (df.flow20_pct_aum <= -flow_cut)
        ev = eventize(df, mask, label)
        if not ev.empty:
            events.append(ev)
        s = fast_means(ev)
        for h in HORIZONS:
            x = s[str(h)]
            rows.append({"config": label, "price_cut": p, "delta_cut": delta, "flow_cut_pct_aum": flow_cut, "period": "CONFIRMATION_2024_PLUS", "horizon": h, "n": x["n"], "mean_excess": x["mean"], "negative_rate": x["negative_rate"]})

    grid_df = pd.DataFrame(rows)
    grid_df.to_csv(args.output / "distribution_delta_grid.csv", index=False)
    if events:
        pd.concat(events, ignore_index=True).to_csv(args.output / "distribution_delta_events.csv", index=False, date_format="%Y-%m-%d")

    baseline_label = "P70_D20_F0"
    baseline_mask = (df.price_score >= 70) & (df.internal_delta20 <= -20) & (df.flow20_pct_aum <= 0)
    base_ev = eventize(df, baseline_mask, baseline_label)
    periods: dict[str, Any] = {}
    periods["ALL"] = summary(base_ev, calendar, 8000)
    periods["DISCOVERY_2022_2023"] = summary(base_ev[(base_ev.date >= pd.Timestamp("2022-01-01")) & (base_ev.date <= pd.Timestamp("2023-12-31"))], calendar, 9000)
    periods["CONFIRMATION_2024_PLUS"] = summary(base_ev[base_ev.date >= pd.Timestamp("2024-01-01")], calendar, 10000)
    for year in range(2022, 2027):
        periods[str(year)] = summary(base_ev[base_ev.date.dt.year == year], calendar, 11000 + year)

    confirm = grid_df[grid_df.period == "CONFIRMATION_2024_PLUS"]
    robust = {}
    for h in HORIZONS:
        x = pd.to_numeric(confirm.loc[confirm.horizon == h, "mean_excess"], errors="coerce").dropna()
        robust[str(h)] = {"configs": int(len(x)), "fraction_negative": None if x.empty else float((x < 0).mean()), "median_config_mean_excess": None if x.empty else float(x.median())}

    base40 = periods["CONFIRMATION_2024_PLUS"]["horizons"]["40"]
    context_candidate = bool(
        robust["20"]["fraction_negative"] == 1.0
        and robust["40"]["fraction_negative"] == 1.0
        and base40["mean"] is not None and base40["mean"] < 0
        and base40["block20_ci95"][1] is not None and base40["block20_ci95"][1] < 0
        and base40["sector_cluster_ci95"][1] is not None and base40["sector_cluster_ci95"][1] < 0
    )
    report = {
        "schema": 1,
        "research_only": True,
        "input": "audited PIT cov80 Sector panel",
        "definition": "Price score >= P; Internal score 20-session change <= negative delta threshold; exact official 20D Flow/AUM <= negative flow threshold; state-transition events; 20-session Sector cooldown.",
        "baseline": {"price_cut": 70, "internal_delta20_cut": -20, "flow20_pct_aum_cut": 0},
        "baseline_periods": periods,
        "grid_2024plus": robust,
        "decision": {
            "survives_as_distribution_deterioration_context_candidate": context_candidate,
            "trading_gate": False,
            "forced_exit": False,
            "production_adoption": False,
            "interpretation": "If it survives, use only as an earlier deterioration warning context alongside the stricter Internal<50 Distribution Warning. Do not call it a buy/sell rule.",
        },
    }
    (args.output / "distribution_delta_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    c = periods["CONFIRMATION_2024_PLUS"]["horizons"]
    lines = [
        "# PIT Distribution Internal-Delta Validation",
        "",
        f"Decision: {'SURVIVES AS CONTEXT CANDIDATE' if context_candidate else 'REJECT'}",
        "",
        f"- Baseline 20D: {100*c['20']['mean']:+.2f}% (n={c['20']['n']}) | block CI {c['20']['block20_ci95']} | sector CI {c['20']['sector_cluster_ci95']}",
        f"- Baseline 40D: {100*c['40']['mean']:+.2f}% (n={c['40']['n']}) | block CI {c['40']['block20_ci95']} | sector CI {c['40']['sector_cluster_ci95']}",
        f"- 27-grid negative fraction 20D: {robust['20']['fraction_negative']:.0%}",
        f"- 27-grid negative fraction 40D: {robust['40']['fraction_negative']:.0%}",
        "",
        "Research context only. Never a V38 forced exit or trading Gate.",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE DISTRIBUTION DELTA PIT context_candidate={context_candidate}", flush=True)


if __name__ == "__main__":
    main()
