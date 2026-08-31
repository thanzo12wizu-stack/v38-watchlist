from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import pitindex

import rotation_distribution_pit_backtest as base
import rotation_distribution_pit_cached_backtest as cached
import rotation_divergence_proxy_backtest as proxy
import validate_pioneer_leader as pl

STATES = [
    "CONFIRMED_ACCUMULATION",
    "HIDDEN_ACCUMULATION",
    "DISTRIBUTION_TRAP",
    "REDEMPTION_DIVERGENCE",
    "EARLY_ROTATION",
]
EXPECTED_SIGN = {
    "CONFIRMED_ACCUMULATION": 1,
    "HIDDEN_ACCUMULATION": 1,
    "DISTRIBUTION_TRAP": -1,
    "EARLY_ROTATION": 1,
}


def period_results(events: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    return {period: base.summarize(pev, calendar, seed + i * 10) for i, (period, pev) in enumerate(base.period_frames(events).items())}


def state_mask(panel: pd.DataFrame, state: str, cfg: dict[str, float]) -> pd.Series:
    return proxy.state_mask(panel, state, cfg["p"], cfg["i"], cfg["f"], cfg["delta"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Strict PIT validation of all Sector Rotation states using cached historical GICS snapshots")
    ap.add_argument("--snapshots", type=Path, required=True)
    ap.add_argument("--snapshot-quality", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--analysis-start", default="2022-04-18")
    ap.add_argument("--analysis-end", default="2026-08-17")
    ap.add_argument("--price-download-start", default="2021-01-01")
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-coverage", type=float, default=0.80)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    snapshots, sq = cached.load_cached_snapshots(args.snapshots, args.snapshot_quality)
    if sq["mapping_rate"].min() < 0.98 or sq["jaccard"].min() < 0.98:
        raise RuntimeError("cached PIT source fails 98% quality gate")

    pit_end = pd.Timestamp(pitindex.info(index="sp500")["end_date"]).normalize()
    start = pd.Timestamp(args.analysis_start).normalize()
    end = min(pd.Timestamp(args.analysis_end).normalize(), pit_end)
    sector_start = pd.Timestamp(snapshots["anchor_date"].min()).normalize()

    provisional_dates = pd.bdate_range(sector_start, end)
    provisional_membership, _ = base.membership_by_day(provisional_dates, snapshots)
    tickers = sorted({t for groups in provisional_membership.values() for members in groups.values() for t in members})
    requested = tickers + ["SPY", *base.SECTORS]
    ohlcv, download_diag = pl.download_ohlcv(
        requested,
        args.price_download_start,
        str((end + pd.Timedelta(days=70)).date()),
        args.batch_size,
    )

    trading_dates = ohlcv["close"].index[(ohlcv["close"].index >= sector_start) & (ohlcv["close"].index <= end)]
    membership, map_q = base.membership_by_day(trading_dates, snapshots)
    map_q.to_csv(args.output / "daily_pit_mapping_quality.csv", index=False, date_format="%Y-%m-%d")
    if map_q.empty or map_q["mapping_rate"].min() < 0.98:
        raise RuntimeError("daily PIT mapping fails 98% guard")

    session = requests.Session()
    flows, flow_diag = base.exact_flows(session, pd.Timestamp(args.price_download_start), end)
    flows.to_csv(args.output / "exact_sector_flows.csv", index=False, date_format="%Y-%m-%d")

    components, covdiag = base.build_dynamic_components(ohlcv, membership, map_q, args.min_coverage)
    covdiag.to_csv(args.output / "pit_internal_data_coverage.csv", index=False)
    panel = base.build_panel(ohlcv, components, flows)
    panel = panel[(panel["date"] >= start) & (panel["date"] <= end)].copy()
    panel.to_csv(args.output / "rotation_pit_panel_cov80.csv", index=False, date_format="%Y-%m-%d")
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))

    result_rows: list[dict[str, Any]] = []
    event_frames: list[pd.DataFrame] = []
    baseline_by_state: dict[str, Any] = {}

    for si, state in enumerate(STATES):
        baseline_cfg = proxy.baseline_config(state)
        baseline_key = proxy.config_key(baseline_cfg)
        print(f"STATE {state}", flush=True)
        for gi, cfg in enumerate(proxy.grid_configs(state)):
            key = proxy.config_key(cfg)
            events = base.eventize(panel, state_mask(panel, state, cfg), key)
            if not events.empty:
                tagged = events.copy()
                tagged["state"] = state
                tagged["config"] = key
                tagged["p"] = cfg["p"]
                tagged["i"] = cfg["i"]
                tagged["f"] = cfg["f"]
                tagged["delta"] = cfg["delta"]
                event_frames.append(tagged)
            po = period_results(events, calendar, 10000 + si * 100000 + gi * 1000)
            for period, summary in po.items():
                for h in base.HORIZONS:
                    hs = summary.get("horizons", {}).get(str(h), {})
                    result_rows.append({
                        "state": state,
                        "config": key,
                        "p": cfg["p"],
                        "i": cfg["i"],
                        "f": cfg["f"],
                        "delta": cfg["delta"],
                        "period": period,
                        "horizon": h,
                        "n": hs.get("n", 0),
                        "mean_excess": hs.get("mean"),
                        "median_excess": hs.get("median"),
                        "negative_rate": hs.get("negative_rate"),
                        "block_ci_lo": (hs.get("block20_ci95") or [None, None])[0],
                        "block_ci_hi": (hs.get("block20_ci95") or [None, None])[1],
                        "sector_ci_lo": (hs.get("sector_cluster_ci95") or [None, None])[0],
                        "sector_ci_hi": (hs.get("sector_cluster_ci95") or [None, None])[1],
                    })
            if key == baseline_key:
                baseline_by_state[state] = po

    results = pd.DataFrame(result_rows)
    results.to_csv(args.output / "rotation_pit_all_states_grid_results.csv", index=False)
    if event_frames:
        pd.concat(event_frames, ignore_index=True).sort_values(["date", "state", "config", "sector"]).to_csv(
            args.output / "rotation_pit_all_states_events.csv", index=False, date_format="%Y-%m-%d"
        )

    decisions: dict[str, Any] = {}
    for state in STATES:
        state_dec: dict[str, Any] = {"expected_sign": EXPECTED_SIGN.get(state), "horizons": {}}
        for h in (20, 40):
            sub = results[
                (results["state"] == state)
                & (results["period"] == "CONFIRMATION_2024_PLUS")
                & (results["horizon"] == h)
            ]
            vals = pd.to_numeric(sub["mean_excess"], errors="coerce").dropna()
            if state in EXPECTED_SIGN:
                sign = EXPECTED_SIGN[state]
                fraction_expected = float(((vals * sign) > 0).mean()) if len(vals) else None
            else:
                fraction_expected = None
            state_dec["horizons"][str(h)] = {
                "configs_with_result": int(len(vals)),
                "fraction_expected_direction": fraction_expected,
                "fraction_negative": float((vals < 0).mean()) if len(vals) else None,
                "median_config_mean_excess": float(vals.median()) if len(vals) else None,
                "min_config_mean_excess": float(vals.min()) if len(vals) else None,
                "max_config_mean_excess": float(vals.max()) if len(vals) else None,
            }

        bcfg = proxy.config_key(proxy.baseline_config(state))
        b = results[
            (results["state"] == state)
            & (results["config"] == bcfg)
            & (results["period"] == "CONFIRMATION_2024_PLUS")
            & (results["horizon"].isin([20, 40]))
        ].copy()
        state_dec["baseline_config"] = bcfg
        state_dec["baseline_confirmation"] = b.to_dict("records")

        if state in EXPECTED_SIGN:
            sign = EXPECTED_SIGN[state]
            robust = all(
                state_dec["horizons"][str(h)]["fraction_expected_direction"] is not None
                and state_dec["horizons"][str(h)]["fraction_expected_direction"] >= 0.80
                for h in (20, 40)
            )
            base_ok = True
            for h in (20, 40):
                r = b[b["horizon"] == h]
                if r.empty or int(r.iloc[0]["n"]) < 10 or pd.isna(r.iloc[0]["mean_excess"]) or float(r.iloc[0]["mean_excess"]) * sign <= 0:
                    base_ok = False
            state_dec["passes_predictive_robustness"] = bool(robust and base_ok)
        else:
            state_dec["passes_predictive_robustness"] = None
            state_dec["diagnostic_only"] = True
        decisions[state] = state_dec

    dist = decisions["DISTRIBUTION_TRAP"]
    red = decisions["REDEMPTION_DIVERGENCE"]
    red_distinct = all(
        (red["horizons"][str(h)]["fraction_negative"] or 0.0) < 0.80
        and (dist["horizons"][str(h)]["fraction_negative"] or 0.0) >= 0.80
        for h in (20, 40)
    )

    report = {
        "schema": 1,
        "research_only": True,
        "flow_quality": "EXACT_OFFICIAL_SSGA_SHARES_OUTSTANDING_DERIVED",
        "internal_quality": "DYNAMIC_PIT_EQUAL_WEIGHT_SP500_WITH_HISTORICAL_GICS",
        "pit_sector": "pre-audited historical Wikipedia revisions carried forward only from their as-of date; no future fill",
        "window": {"analysis_start": str(start.date()), "analysis_end": str(end.date())},
        "coverage": float(args.min_coverage),
        "source_quality": {
            "monthly_snapshot_min_mapping": float(sq["mapping_rate"].min()),
            "monthly_snapshot_min_jaccard": float(sq["jaccard"].min()),
            "daily_mapping_min": float(map_q["mapping_rate"].min()),
            "download": download_diag,
            "flow": flow_diag,
        },
        "decisions": decisions,
        "redemption_distinct_from_distribution_on_robust_negative_test": bool(red_distinct),
        "guardrails": {
            "production_adoption": False,
            "trading_gate": False,
            "forced_exit": False,
            "sector_rotation_role": "context/intelligence only",
        },
    }
    (args.output / "rotation_pit_all_states_report.json").write_text(
        json.dumps(base.safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    lines = [
        "# Strict PIT Sector Rotation State Validation",
        "",
        "Research-only. No main/UI/trading-rule changes.",
        "",
        f"- Analysis: {start.date()} to {end.date()}",
        f"- Internal coverage guard: {args.min_coverage:.0%}",
        f"- Monthly PIT sector mapping min: {sq['mapping_rate'].min():.2%}",
        f"- Daily PIT mapping min: {map_q['mapping_rate'].min():.2%}",
        "",
        "## Confirmation 2024+ baselines",
        "",
        "| State | 20D | 40D | Robust predictive test |",
        "|---|---:|---:|---|",
    ]
    for state in STATES:
        vals = []
        bcfg = decisions[state]["baseline_config"]
        b = results[(results.state == state) & (results.config == bcfg) & (results.period == "CONFIRMATION_2024_PLUS")]
        for h in (20, 40):
            r = b[b.horizon == h]
            vals.append("n/a" if r.empty or pd.isna(r.iloc[0].mean_excess) else f"{100*r.iloc[0].mean_excess:+.2f}% (n={int(r.iloc[0].n)})")
        p = decisions[state]["passes_predictive_robustness"]
        status = "diagnostic" if p is None else ("PASS" if p else "FAIL")
        lines.append(f"| {state} | {vals[0]} | {vals[1]} | {status} |")
    lines += [
        "",
        f"- Redemption distinct from Distribution negative pattern: {'YES' if red_distinct else 'NO'}",
        "",
        "All 27 threshold neighbors are retained per state. A positive-looking single cell is never promoted.",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DONE PIT ALL STATES", flush=True)


if __name__ == "__main__":
    main()
