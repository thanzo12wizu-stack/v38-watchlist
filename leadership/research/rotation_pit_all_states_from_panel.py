from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import rotation_distribution_pit_backtest as base
import rotation_divergence_proxy_backtest as proxy

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


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate all Sector Rotation states from audited cov80 PIT panel")
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(args.panel)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = panel.sort_values(["sector", "date"]).reset_index(drop=True)
    panel["internal_delta20"] = panel.groupby("sector", sort=False)["internal_score"].diff(20)
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))

    result_rows: list[dict[str, Any]] = []
    event_frames: list[pd.DataFrame] = []

    for si, state in enumerate(STATES):
        print(f"STATE {state}", flush=True)
        for gi, cfg in enumerate(proxy.grid_configs(state)):
            key = proxy.config_key(cfg)
            mask = proxy.state_mask(panel, state, cfg["p"], cfg["i"], cfg["f"], cfg["delta"])
            events = base.eventize(panel, mask, key)
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

    results = pd.DataFrame(result_rows)
    results.to_csv(args.output / "rotation_pit_all_states_grid_results.csv", index=False)
    if event_frames:
        pd.concat(event_frames, ignore_index=True).sort_values(["date", "state", "config", "sector"]).to_csv(
            args.output / "rotation_pit_all_states_events.csv", index=False, date_format="%Y-%m-%d"
        )

    decisions: dict[str, Any] = {}
    for state in STATES:
        d: dict[str, Any] = {"expected_sign": EXPECTED_SIGN.get(state), "horizons": {}}
        for h in (20, 40):
            sub = results[
                (results.state == state)
                & (results.period == "CONFIRMATION_2024_PLUS")
                & (results.horizon == h)
            ]
            vals = pd.to_numeric(sub["mean_excess"], errors="coerce").dropna()
            sign = EXPECTED_SIGN.get(state)
            d["horizons"][str(h)] = {
                "configs_with_result": int(len(vals)),
                "fraction_positive": float((vals > 0).mean()) if len(vals) else None,
                "fraction_negative": float((vals < 0).mean()) if len(vals) else None,
                "fraction_expected_direction": float(((vals * sign) > 0).mean()) if sign is not None and len(vals) else None,
                "median_config_mean_excess": float(vals.median()) if len(vals) else None,
                "min_config_mean_excess": float(vals.min()) if len(vals) else None,
                "max_config_mean_excess": float(vals.max()) if len(vals) else None,
            }

        bcfg = proxy.config_key(proxy.baseline_config(state))
        b = results[
            (results.state == state)
            & (results.config == bcfg)
            & (results.period == "CONFIRMATION_2024_PLUS")
            & (results.horizon.isin([20, 40]))
        ].copy()
        d["baseline_config"] = bcfg
        d["baseline_confirmation"] = b.to_dict("records")
        if state in EXPECTED_SIGN:
            sign = EXPECTED_SIGN[state]
            grid_ok = all((d["horizons"][str(h)]["fraction_expected_direction"] or 0.0) >= 0.80 for h in (20, 40))
            base_ok = True
            for h in (20, 40):
                r = b[b.horizon == h]
                if r.empty or int(r.iloc[0].n) < 10 or pd.isna(r.iloc[0].mean_excess) or float(r.iloc[0].mean_excess) * sign <= 0:
                    base_ok = False
            d["passes_predictive_robustness"] = bool(grid_ok and base_ok)
        else:
            d["passes_predictive_robustness"] = None
            d["diagnostic_only"] = True
        decisions[state] = d

    # Redemption is a semantic/diagnostic distinction, not assumed bullish.
    # Compare its magnitude with Distribution but do not force a predictive sign.
    dist = decisions["DISTRIBUTION_TRAP"]
    red = decisions["REDEMPTION_DIVERGENCE"]
    report = {
        "schema": 1,
        "research_only": True,
        "source_panel": "rotation-distribution-pit-research artifact 9743199098 / cov80 panel",
        "flow_quality": "EXACT_OFFICIAL_SSGA_SHARES_OUTSTANDING_DERIVED",
        "internal_quality": "DYNAMIC_PIT_EQUAL_WEIGHT_SP500_WITH_HISTORICAL_GICS",
        "decisions": decisions,
        "distribution_vs_redemption": {
            "distribution_fraction_negative_20d": dist["horizons"]["20"]["fraction_negative"],
            "distribution_fraction_negative_40d": dist["horizons"]["40"]["fraction_negative"],
            "redemption_fraction_negative_20d": red["horizons"]["20"]["fraction_negative"],
            "redemption_fraction_negative_40d": red["horizons"]["40"]["fraction_negative"],
            "interpretation": "Redemption Divergence remains a diagnostic label for strong internals despite ETF outflow; it is not presumed bullish and is not treated as equivalent to Distribution without separate magnitude evidence.",
        },
        "guardrails": {"production_adoption": False, "trading_gate": False, "forced_exit": False},
    }
    (args.output / "rotation_pit_all_states_report.json").write_text(json.dumps(base.safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Strict PIT Sector Rotation State Validation",
        "",
        "Research-only. Source panel is the audited cov80 PIT panel from artifact 9743199098.",
        "",
        "| State | 20D baseline | 40D baseline | 20D grid expected | 40D grid expected | Predictive |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for state in STATES:
        bcfg = decisions[state]["baseline_config"]
        b = results[(results.state == state) & (results.config == bcfg) & (results.period == "CONFIRMATION_2024_PLUS")]
        vals = []
        for h in (20, 40):
            r = b[b.horizon == h]
            vals.append("n/a" if r.empty or pd.isna(r.iloc[0].mean_excess) else f"{100*r.iloc[0].mean_excess:+.2f}% (n={int(r.iloc[0].n)})")
        e20 = decisions[state]["horizons"]["20"]["fraction_expected_direction"]
        e40 = decisions[state]["horizons"]["40"]["fraction_expected_direction"]
        p = decisions[state]["passes_predictive_robustness"]
        lines.append(f"| {state} | {vals[0]} | {vals[1]} | {'—' if e20 is None else f'{100*e20:.0f}%'} | {'—' if e40 is None else f'{100*e40:.0f}%'} | {'DIAGNOSTIC' if p is None else ('PASS' if p else 'FAIL')} |")
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DONE PIT ALL STATES FROM PANEL", flush=True)


if __name__ == "__main__":
    main()
