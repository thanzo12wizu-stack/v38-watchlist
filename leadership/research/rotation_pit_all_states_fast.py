from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import rotation_distribution_pit_backtest as base
import rotation_divergence_proxy_backtest as proxy

STATES = ["CONFIRMED_ACCUMULATION", "HIDDEN_ACCUMULATION", "DISTRIBUTION_TRAP", "REDEMPTION_DIVERGENCE", "EARLY_ROTATION"]
EXPECTED = {"CONFIRMED_ACCUMULATION": 1, "HIDDEN_ACCUMULATION": 1, "DISTRIBUTION_TRAP": -1, "EARLY_ROTATION": 1}


def periods(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return base.period_frames(events)


def simple_summary(events: pd.DataFrame) -> dict[str, Any]:
    out = {"n": int(len(events)), "horizons": {}}
    for h in base.HORIZONS:
        col = f"fwd_excess_{h}d"
        x = pd.to_numeric(events[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna() if not events.empty else pd.Series(dtype=float)
        out["horizons"][str(h)] = {
            "n": int(len(x)),
            "mean": None if x.empty else float(x.mean()),
            "median": None if x.empty else float(x.median()),
            "negative_rate": None if x.empty else float((x < 0).mean()),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(args.panel)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel = panel.sort_values(["sector", "date"]).reset_index(drop=True)
    panel["internal_delta20"] = panel.groupby("sector", sort=False)["internal_score"].diff(20)
    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))

    rows = []
    baseline_detail = {}
    events_out = []
    for si, state in enumerate(STATES):
        baseline_cfg = proxy.baseline_config(state)
        baseline_key = proxy.config_key(baseline_cfg)
        print(f"STATE {state}", flush=True)
        for gi, cfg in enumerate(proxy.grid_configs(state)):
            key = proxy.config_key(cfg)
            mask = proxy.state_mask(panel, state, cfg["p"], cfg["i"], cfg["f"], cfg["delta"])
            ev = base.eventize(panel, mask, key)
            if key == baseline_key:
                tagged = ev.copy()
                if not tagged.empty:
                    tagged["state"] = state
                    tagged["config"] = key
                    events_out.append(tagged)
                baseline_detail[state] = {
                    name: base.summarize(pev, calendar, 900000 + si * 10000 + j * 1000)
                    for j, (name, pev) in enumerate(periods(ev).items())
                }
            for period, pev in periods(ev).items():
                summary = simple_summary(pev)
                for h in base.HORIZONS:
                    hs = summary["horizons"][str(h)]
                    rows.append({
                        "state": state, "config": key, "p": cfg["p"], "i": cfg["i"], "f": cfg["f"], "delta": cfg["delta"],
                        "period": period, "horizon": h, "n": hs["n"], "mean_excess": hs["mean"], "median_excess": hs["median"], "negative_rate": hs["negative_rate"],
                    })

    results = pd.DataFrame(rows)
    results.to_csv(args.output / "rotation_pit_state_grid.csv", index=False)
    if events_out:
        pd.concat(events_out, ignore_index=True).sort_values(["date", "state", "sector"]).to_csv(args.output / "rotation_pit_baseline_events.csv", index=False, date_format="%Y-%m-%d")

    decisions = {}
    for state in STATES:
        d = {"expected_sign": EXPECTED.get(state), "horizons": {}}
        for h in (20, 40):
            x = results[(results.state == state) & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon == h)]
            vals = pd.to_numeric(x.mean_excess, errors="coerce").dropna()
            sign = EXPECTED.get(state)
            d["horizons"][str(h)] = {
                "configs": int(len(vals)),
                "fraction_positive": None if vals.empty else float((vals > 0).mean()),
                "fraction_negative": None if vals.empty else float((vals < 0).mean()),
                "fraction_expected": None if sign is None or vals.empty else float(((vals * sign) > 0).mean()),
                "median_config_mean": None if vals.empty else float(vals.median()),
                "range": [None, None] if vals.empty else [float(vals.min()), float(vals.max())],
            }
        bcfg = proxy.config_key(proxy.baseline_config(state))
        b = results[(results.state == state) & (results.config == bcfg) & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon.isin([20, 40]))]
        d["baseline_config"] = bcfg
        d["baseline_confirmation"] = b.to_dict("records")
        d["baseline_bootstrap"] = baseline_detail.get(state, {}).get("CONFIRMATION_2024_PLUS", {})
        if state in EXPECTED:
            sign = EXPECTED[state]
            grid_ok = all((d["horizons"][str(h)]["fraction_expected"] or 0.0) >= 0.80 for h in (20, 40))
            base_ok = True
            for h in (20, 40):
                r = b[b.horizon == h]
                if r.empty or int(r.iloc[0].n) < 10 or pd.isna(r.iloc[0].mean_excess) or float(r.iloc[0].mean_excess) * sign <= 0:
                    base_ok = False
            d["predictive_pass"] = bool(grid_ok and base_ok)
        else:
            d["predictive_pass"] = None
            d["role"] = "DIAGNOSTIC_ONLY"
        decisions[state] = d

    report = {
        "schema": 1,
        "research_only": True,
        "source_panel": "audited PIT cov80 panel from artifact 9743199098",
        "flow_quality": "EXACT_OFFICIAL_SSGA_SHARES_OUTSTANDING_DERIVED",
        "internal_quality": "DYNAMIC_PIT_EQUAL_WEIGHT_SP500_WITH_HISTORICAL_GICS",
        "method": "27-neighbor grid direction robustness; 20d sector cooldown; baseline-only 3000x block and sector cluster bootstrap",
        "decisions": decisions,
        "guardrails": {"production_adoption": False, "trading_gate": False, "forced_exit": False},
    }
    (args.output / "rotation_pit_state_report.json").write_text(json.dumps(base.safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = ["# PIT Rotation State Research", "", "| State | 20D baseline | 40D baseline | 20D grid | 40D grid | Result |", "|---|---:|---:|---:|---:|---|"]
    for state in STATES:
        d = decisions[state]
        b = results[(results.state == state) & (results.config == d["baseline_config"]) & (results.period == "CONFIRMATION_2024_PLUS")]
        vals=[]
        for h in (20,40):
            r=b[b.horizon==h]
            vals.append("n/a" if r.empty or pd.isna(r.iloc[0].mean_excess) else f"{100*r.iloc[0].mean_excess:+.2f}% n={int(r.iloc[0].n)}")
        sign=EXPECTED.get(state)
        if sign is None:
            g20=100*(d["horizons"]["20"]["fraction_negative"] or 0)
            g40=100*(d["horizons"]["40"]["fraction_negative"] or 0)
            gres=f"negative {g20:.0f}%"; gres2=f"negative {g40:.0f}%"; status="DIAGNOSTIC"
        else:
            g20=100*(d["horizons"]["20"]["fraction_expected"] or 0); g40=100*(d["horizons"]["40"]["fraction_expected"] or 0)
            gres=f"expected {g20:.0f}%"; gres2=f"expected {g40:.0f}%"; status="PASS" if d["predictive_pass"] else "FAIL"
        lines.append(f"| {state} | {vals[0]} | {vals[1]} | {gres} | {gres2} | {status} |")
    (args.output / "README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print("DONE FAST PIT STATE RESEARCH", flush=True)

if __name__ == "__main__":
    main()
