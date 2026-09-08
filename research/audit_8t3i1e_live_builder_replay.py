from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import build_v38_8t3i1e_live as live
import build_v38_sleeve_live as sleeve
from research import audit_stock_nqsar_theme30_pit as audit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid

REPLAY_START = pd.Timestamp("2024-01-02")
END = pd.Timestamp("2026-09-04")
REFERENCE_WARM_START = pd.Timestamp("2011-08-01")


def safe(x):
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
        return str(x.date())
    return x


def reference_view(m):
    return {
        "close": m["close"],
        "ddv": m["ddv"],
        "pool": m["pool"],
        "struct": m["struct"],
        "q": m["q"],
        "early_score": m["early_score"],
        "radar_active": m["radar_active"],
        "wb": m["wb"],
    }


def live_view(m):
    return {
        "close": m["close"],
        "ddv": m["ddv"],
        "pool": m["pool"],
        "struct": m["struct"],
        "q": {21: m["q21"], 42: m["q42"], 63: m["q63"], 189: m["q189"]},
        "early_score": m["early_score"],
        "radar_active": m["radar_active"],
        "wb": m["weekly_bull"],
    }


def compare_rows(d, rr, lr):
    out = []
    if [x.get("ticker") for x in rr] != [x.get("ticker") for x in lr]:
        out.append("ticker_order")
    if [x.get("source") for x in rr] != [x.get("source") for x in lr]:
        out.append("source_order")
    if [x.get("final_rank") for x in rr] != [x.get("final_rank") for x in lr]:
        out.append("rank")
    for i, (a, b) in enumerate(zip(rr, lr), 1):
        av = a.get("stock_rs63_pct")
        bv = b.get("stock_rs63_pct")
        if av is None and bv is None:
            continue
        try:
            if not np.isclose(float(av), float(bv), rtol=0.0, atol=1e-10, equal_nan=True):
                out.append(f"rs63_{i}")
        except Exception:
            out.append(f"rs63_{i}")
    return sorted(set(out))


def engine_tests(sample_rows):
    tests = {}
    tests["market_mode_unchanged"] = (
        audit.mode("Blue", 60) == "ATTACK"
        and audit.mode("Green", 50) == "SELECTIVE"
        and audit.mode("Blue", 49.99) == "STOP"
        and audit.mode("Yellow", 80) == "STOP"
        and audit.mode("Red", 80) == "DEFENSE"
    )
    rows = [
        {"ticker": f"X{i:02d}", "final_rank": i, "daily_dollar_volume_m": 10.0 if i == 4 else 30.0}
        for i in range(1, 16)
    ]
    p = sleeve._normal_pending(
        {"positions": []},
        {
            "asof": "2026-09-04",
            "market": {"mode": "ATTACK"},
            "candidates": rows,
            "early1": {"status": "READY", "entry_allowed_now": False, "candidates": []},
        },
        {},
    )
    core = [x["symbol"] for x in p["entries"] if x.get("sleeve") == "CORE"]
    tests["top12_then_ddv20_no_refill"] = "X04" not in core and "X13" not in core and len(core) == 11

    crows = [
        {"ticker": r["ticker"], "final_rank": i, "daily_dollar_volume_m": 30.0}
        for i, r in enumerate(sample_rows[:12], 1)
    ]
    p = sleeve._normal_pending(
        {"positions": []},
        {
            "asof": "2026-09-04",
            "market": {"mode": "SELECTIVE"},
            "candidates": crows,
            "early1": {
                "status": "READY",
                "entry_allowed_now": True,
                "candidates": [{"ticker": "EARLY_TEST", "score": 99.0, "rank": 1}],
            },
        },
        {},
    )
    cores = [x["symbol"] for x in p["entries"] if x.get("sleeve") == "CORE"]
    early = [x["symbol"] for x in p["entries"] if x.get("sleeve") == "EARLY"]
    tests["selective_3_plus_1"] = len(cores) == 3 and early == ["EARLY_TEST"]
    tests["selective_first3_trend"] = len(sample_rows) >= 3 and all(r.get("source") == "TREND" for r in sample_rows[:3])
    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    a = ap.parse_args()
    root = Path(a.root)
    out = root / a.output
    out.mkdir(parents=True, exist_ok=True)

    symbols, bio = audit.load_universe(root / "universe.csv")
    print("DOWNLOAD FULL RESEARCH WARM HISTORY", flush=True)
    ohlcv, diag = audit.download_ohlcv(symbols, str(REFERENCE_WARM_START.date()), "2026-09-05", a.batch_size)
    if float(diag.get("coverage") or 0.0) < 0.85:
        raise RuntimeError(diag)

    print("BUILD RESEARCH REFERENCE", flush=True)
    ref_full = broad.build_inputs(ohlcv, bio)
    ref = reference_view(ref_full)

    print("BUILD DEDICATED LIVE FRAMES", flush=True)
    lm = live.build_feature_frames(ohlcv, bio, END)
    lv = live_view(lm)
    idx = ref["close"].index[(ref["close"].index >= REPLAY_START) & (ref["close"].index <= END)]

    frame_checks = {}
    common_idx = idx.intersection(lv["close"].index)
    common_cols = ref["close"].columns.intersection(lv["close"].columns)
    for name, a1, b1 in (
        ("pool", ref["pool"], lv["pool"]),
        ("struct", ref["struct"], lv["struct"]),
        ("radar_active", ref["radar_active"], lv["radar_active"]),
        ("weekly_bull", ref["wb"], lv["wb"]),
    ):
        xa = a1.reindex(index=common_idx, columns=common_cols).fillna(False).astype(bool)
        xb = b1.reindex(index=common_idx, columns=common_cols).fillna(False).astype(bool)
        mism = int((xa.to_numpy() != xb.to_numpy()).sum())
        frame_checks[name] = {"cells": int(xa.size), "mismatches": mism, "pass": mism == 0}
    for p in (21, 42, 63, 189):
        xa = ref["q"][p].reindex(index=common_idx, columns=common_cols).to_numpy(float)
        xb = lv["q"][p].reindex(index=common_idx, columns=common_cols).to_numpy(float)
        same = np.isclose(xa, xb, rtol=0.0, atol=1e-10, equal_nan=True)
        mism = int((~same).sum())
        frame_checks[f"q{p}"] = {"cells": int(same.size), "mismatches": mism, "pass": mism == 0}

    row_mismatches = []
    source_counts = []
    selected_below_rs189_85 = 0
    selected_below_rs63_85 = 0
    selected_ddv20_fail = 0
    latest_rows = []
    for n, d0 in enumerate(idx, 1):
        d = pd.Timestamp(d0)
        rr = hybrid.hybrid_rows(d, ref, "HYBRID8T3I_E1")
        lr = live.candidate_rows(d, lm)
        reasons = compare_rows(d, rr, lr)
        if reasons:
            row_mismatches.append(
                {
                    "date": str(d.date()),
                    "reasons": "|".join(reasons),
                    "reference": "|".join(str(x.get("ticker")) for x in rr),
                    "live": "|".join(str(x.get("ticker")) for x in lr),
                    "reference_sources": "|".join(str(x.get("source")) for x in rr),
                    "live_sources": "|".join(str(x.get("source")) for x in lr),
                }
            )
        first11 = lr[:11]
        source_counts.append(
            {
                "date": str(d.date()),
                "trend_first11": sum(x.get("source") == "TREND" for x in first11),
                "ignition_first11": sum(x.get("source") == "IGNITION" for x in first11),
                "rows": len(lr),
            }
        )
        for row in lr:
            sym = row["ticker"]
            q189 = lv["q"][189].at[d, sym] if sym in lv["q"][189].columns else np.nan
            q63 = lv["q"][63].at[d, sym] if sym in lv["q"][63].columns else np.nan
            if pd.notna(q189) and float(q189) < 85.0:
                selected_below_rs189_85 += 1
            if pd.notna(q63) and float(q63) < 85.0:
                selected_below_rs63_85 += 1
            if not bool(row.get("entry_ddv20_pass")):
                selected_ddv20_fail += 1
        latest_rows = lr
        if n % 100 == 0 or n == len(idx):
            print(f"REPLAY {n}/{len(idx)} mismatch={len(row_mismatches)}", flush=True)

    # Validate the live single-date state contract at the latest session.
    latest_state = live.build_state(ohlcv, bio, str(END.date()), diag)
    (out / "latest_live_state.json").write_text(json.dumps(safe(latest_state), ensure_ascii=False, indent=2), encoding="utf-8")
    state_tickers = [x["ticker"] for x in latest_state["candidates"]]
    latest_tickers = [x["ticker"] for x in latest_rows]
    state_exact = state_tickers == latest_tickers

    # Shortened-week release audit using the live calendar and research reference.
    cal = live.nyse_sessions(REPLAY_START, END)
    periods = pd.Series(cal, index=cal.to_period("W-FRI")).groupby(level=0).max()
    shortened = [pd.Timestamp(x) for x in periods if pd.Timestamp(x).weekday() < 4]
    shortened_checks = []
    for d in shortened:
        if d not in idx:
            continue
        rr = hybrid.hybrid_rows(d, ref, "HYBRID8T3I_E1")
        lr = live.candidate_rows(d, lm)
        shortened_checks.append(
            {
                "date": str(d.date()),
                "weekday": int(d.weekday()),
                "match": [x["ticker"] for x in rr] == [x["ticker"] for x in lr]
                and [x.get("source") for x in rr] == [x.get("source") for x in lr],
            }
        )

    tests = engine_tests(latest_rows)
    source_df = pd.DataFrame(source_counts)
    pd.DataFrame(row_mismatches).to_csv(out / "daily_replay_mismatches.csv", index=False)
    source_df.to_csv(out / "source_counts_daily.csv", index=False)
    pd.DataFrame(shortened_checks).to_csv(out / "shortened_week_checks.csv", index=False)

    all_frames_pass = all(bool(v["pass"]) for v in frame_checks.values())
    all_rows_pass = len(row_mismatches) == 0
    all_short_pass = bool(shortened_checks) and all(bool(x["match"]) for x in shortened_checks)
    all_engine_pass = all(bool(x) for x in tests.values())
    hard_gate_removed_observed = selected_below_rs189_85 > 0 or selected_below_rs63_85 > 0
    pass_all = all_frames_pass and all_rows_pass and state_exact and all_short_pass and all_engine_pass and hard_gate_removed_observed

    summary = {
        "method": "Dedicated build_v38_8t3i1e_live.py vs exact research HYBRID8T3I_E1 replay. Full research warm history starts 2011-08; daily comparison 2024-01-02 through 2026-09-04.",
        "coverage": diag,
        "sessions_compared": len(idx),
        "frame_checks": frame_checks,
        "daily_replay_mismatch_sessions": len(row_mismatches),
        "latest_state_contract_exact": state_exact,
        "shortened_week_checks": shortened_checks,
        "engine_tests": tests,
        "selected_rows_below_rs189_85": selected_below_rs189_85,
        "selected_rows_below_rs63_85": selected_below_rs63_85,
        "selected_rows_failing_ddv20_but_retained_in_top12": selected_ddv20_fail,
        "hard_gate_removed_observed": hard_gate_removed_observed,
        "first11_exact_8T3I_sessions": int(((source_df.trend_first11 == 8) & (source_df.ignition_first11 == 3)).sum()) if len(source_df) else 0,
        "first11_other_source_mix_sessions": int((~((source_df.trend_first11 == 8) & (source_df.ignition_first11 == 3))).sum()) if len(source_df) else 0,
        "audit_verdict": "PASS_FOR_PRODUCTION_CHANGE_PROPOSAL" if pass_all else "FAIL_NOT_READY",
        "production_changed": False,
        "production_change_proposal_allowed": bool(pass_all),
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE_REPLAY_AUDIT", json.dumps(safe(summary), ensure_ascii=False), flush=True)
    if not pass_all:
        raise RuntimeError(f"8T3I1E_LIVE_REPLAY_AUDIT_FAILED {summary}")


if __name__ == "__main__":
    main()
