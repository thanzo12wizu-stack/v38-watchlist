from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_leader_factor_horizon_discovery as disc
import audit_early_liquidity_label_sensitivity as ls


CANDIDATE_DDV = 20_000_000.0
TOPKS = (3, 5, 10, 20)
DEV_YEARS = range(2016, 2021)
OOS_YEARS = range(2021, 2026)
LABEL_FLOORS = (0.0, 10_000_000.0, 20_000_000.0, 50_000_000.0)
SELECTION_LABELS = ("LABEL_DDV10", "LABEL_DDV20", "LABEL_DDV50")


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def neutral(x: pd.DataFrame) -> pd.DataFrame:
    return x.fillna(50.0)


def build_features(
    matrices: dict[str, pd.DataFrame],
    base_pool: pd.DataFrame,
    rs: dict[int, pd.DataFrame],
    theme: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    close = matrices["close"]
    high = matrices["high"]
    low = matrices["low"]
    dvol = matrices["dvol"]
    radar = base_pool & (dvol >= CANDIDATE_DDV) & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))

    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, radar)
    acc10 = pct(rs[21] - rs[21].shift(10), radar)
    base_score = (0.50 * neutral(rs[21].where(radar)) + 0.25 * neutral(high63) + 0.25 * neutral(acc10)).astype(np.float32)

    # Liquidity level/acceleration. DDV is observable at the close and already used
    # elsewhere as a tradability control; here it is a ranking signal, not a hard 50M gate.
    liq_level = pct(np.log(dvol.clip(lower=1.0)), radar)
    ddv_acc10 = pct(dvol / dvol.shift(10) - 1.0, radar)
    step40 = pd.DataFrame(np.where((dvol >= 40_000_000.0) & radar, 100.0, 0.0), index=dvol.index, columns=dvol.columns, dtype=np.float32).where(radar)
    step50 = pd.DataFrame(np.where((dvol >= 50_000_000.0) & radar, 100.0, 0.0), index=dvol.index, columns=dvol.columns, dtype=np.float32).where(radar)

    # O'Neil-adjacent price contraction, using only completed prior sessions.
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.DataFrame(np.maximum.reduce([tr1.to_numpy(float), tr2.to_numpy(float), tr3.to_numpy(float)]), index=close.index, columns=close.columns)
    tr5 = tr.shift(1).rolling(5, min_periods=4).mean()
    tr20 = tr.shift(1).rolling(20, min_periods=12).mean()
    tr_contract = pct(-(tr5 / tr20.replace(0.0, np.nan)), radar)
    c5max = prev_close.rolling(5, min_periods=4).max()
    c5min = prev_close.rolling(5, min_periods=4).min()
    close_tight = pct(-(c5max / c5min.replace(0.0, np.nan) - 1.0), radar)
    tight = (0.50 * neutral(tr_contract) + 0.50 * neutral(close_tight)).astype(np.float32)

    theme_level = pct(theme, radar)
    theme_acc20 = pct(theme - theme.shift(20), radar)

    return radar, {
        "BASE": base_score,
        "LIQ": liq_level,
        "DDV_ACC10": ddv_acc10,
        "STEP40": step40,
        "STEP50": step50,
        "TIGHT": tight,
        "THEME": theme_level,
        "THEME_ACC20": theme_acc20,
    }


def score_specs(f: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    b = f["BASE"]
    specs: dict[str, dict[str, Any]] = {
        "BASE": {"score": b, "selection_eligible": True, "family": "baseline"},
        "LIQ10": {"score": (0.90 * b + 0.10 * neutral(f["LIQ"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_level"},
        "LIQ20": {"score": (0.80 * b + 0.20 * neutral(f["LIQ"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_level"},
        "STEP40_10": {"score": (0.90 * b + 0.10 * neutral(f["STEP40"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_step"},
        "STEP50_10": {"score": (0.90 * b + 0.10 * neutral(f["STEP50"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_step"},
        "DDV_ACCEL10": {"score": (0.90 * b + 0.10 * neutral(f["DDV_ACC10"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_acceleration"},
        "LIQ_ACCEL": {"score": (0.80 * b + 0.10 * neutral(f["LIQ"]) + 0.10 * neutral(f["DDV_ACC10"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_level_acceleration"},
        "TIGHT10": {"score": (0.90 * b + 0.10 * neutral(f["TIGHT"])).astype(np.float32), "selection_eligible": True, "family": "price_contraction"},
        "LIQ_TIGHT": {"score": (0.80 * b + 0.10 * neutral(f["LIQ"]) + 0.10 * neutral(f["TIGHT"])).astype(np.float32), "selection_eligible": True, "family": "liquidity_plus_contraction"},
        # Theme level/acceleration are retained as diagnostics because their OOS behavior
        # was already inspected in the prior reranker audit; they cannot win selection here.
        "LIQ_THEME_DIAG": {"score": (0.80 * b + 0.10 * neutral(f["LIQ"]) + 0.10 * neutral(f["THEME"])).astype(np.float32), "selection_eligible": False, "family": "theme_diagnostic"},
        "LIQ_THEMEACC_DIAG": {"score": (0.80 * b + 0.10 * neutral(f["LIQ"]) + 0.10 * neutral(f["THEME_ACC20"])).astype(np.float32), "selection_eligible": False, "family": "theme_diagnostic"},
    }
    return specs


def selection_rows(variants: dict[str, Any]) -> list[dict[str, Any]]:
    base_q = variants["BASE"]["top5_event_quality"]["dev_2016_2020"]
    base_super = float(base_q.get("future126_superleader_rate") or 0.0)
    base_ret126 = float(base_q.get("ret126_median") or 0.0)
    rows: list[dict[str, Any]] = []
    for name, item in variants.items():
        if not item["selection_eligible"]:
            continue
        t330, t350, t550 = [], [], []
        for lkey in SELECTION_LABELS:
            d = item["annual_labels"][lkey]["dev_2016_2020"]
            t330.append(float(d["top3_le30_rate"]))
            t350.append(float(d["top3_le50_rate"]))
            t550.append(float(d["top5_le50_rate"]))
        q = item["top5_event_quality"]["dev_2016_2020"]
        sr = float(q.get("future126_superleader_rate") or 0.0)
        r126 = float(q.get("ret126_median") or -99.0)
        # Noise guard: do not accept an early-capture improvement that sacrifices more
        # than 10% of BASE forward-superleader precision or >2 percentage points median 126d return.
        noise_guard = bool(sr >= 0.90 * base_super and r126 >= base_ret126 - 0.02)
        rows.append({
            "variant": name,
            "family": item["family"],
            "noise_guard_pass": noise_guard,
            "top3_le30_worst": float(min(t330)),
            "top3_le30_avg": float(np.mean(t330)),
            "top3_le50_avg": float(np.mean(t350)),
            "top5_le50_worst": float(min(t550)),
            "top5_le50_avg": float(np.mean(t550)),
            "future126_superleader_rate": sr,
            "ret126_median": r126,
            "events": int(q.get("n", 0)),
        })
    rows.sort(key=lambda x: (
        bool(x["noise_guard_pass"]),
        x["top3_le30_worst"],
        x["top3_le30_avg"],
        x["top3_le50_avg"],
        x["top5_le50_worst"],
        x["top5_le50_avg"],
        x["future126_superleader_rate"],
    ), reverse=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2025-12-31")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    close = matrices["close"]
    common = disc.build_common(root, matrices)
    rs = disc.build_rs(close, common["BASE_POOL"])

    print("BUILD leave-one-out theme diagnostics", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    theme = disc.theme_frame(peer_ctx, close)

    print("BUILD frozen annual label sensitivities", flush=True)
    label_frames: dict[str, pd.DataFrame] = {}
    for floor in LABEL_FLOORS:
        key = f"LABEL_DDV{int(floor / 1_000_000)}"
        all20 = ls.build_annual_leaders_floor(matrices, pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end), floor)
        label_frames[key] = all20.loc[pd.to_numeric(all20["rank"], errors="coerce") <= 5].copy()

    radar, features = build_features(matrices, common["BASE_POOL"], rs, theme)
    specs = score_specs(features)

    result: dict[str, Any] = {
        "status": "EARLY_PRECISION_SIGNAL_AUDIT",
        "design": {
            "candidate_floor": CANDIDATE_DDV,
            "purpose": "Keep DDV20 eligibility and test liquidity as ranking information, alongside price contraction and peer-theme diagnostics, instead of hard-gating Early at DDV50.",
            "base_score": "50% RS21 + 25% 63d-high proximity + 25% RS21 10-session acceleration.",
            "selection_labels": list(SELECTION_LABELS),
            "label_ddv0": "stress test only; not used for model selection because its annual Top5 median early DDV is far below the intended tradable universe.",
            "selection_split": "2016-2020 selects among new eligible variants; 2021-2025 is robustness. Theme variants are diagnostics only because their OOS behavior was previously inspected.",
            "noise_guard": "Dev Top5 event forward-superleader rate must retain >=90% of BASE and median 126d return cannot fall >2 percentage points below BASE.",
            "market_gate": False,
            "full_eligibility": False,
            "no_portfolio_change": True,
            "no_main_change": True,
        },
        "coverage": {"downloaded": int(meta["downloaded"]), "sessions": int(len(close)), "symbols": int(len(close.columns))},
        "variants": {},
        "dev_order": [],
        "dev_selected": None,
    }

    for name, spec in specs.items():
        print(f"RANK {name}", flush=True)
        ranks = disc.top_rank_matrix(spec["score"], radar, maxk=max(TOPKS))
        item: dict[str, Any] = {
            "family": spec["family"],
            "selection_eligible": bool(spec["selection_eligible"]),
            "annual_labels": {},
            "top5_event_quality": ls.event_quality(ranks, close, common["BASE_POOL"], k=5, cooldown=20),
        }
        for lkey, leaders in label_frames.items():
            item["annual_labels"][lkey] = ls.evaluate_leaders(ranks, radar, leaders, close)
        result["variants"][name] = item

    order = selection_rows(result["variants"])
    result["dev_order"] = order
    result["dev_selected"] = order[0]["variant"] if order else None

    p = out / "summary_early_precision_signals.json"
    p.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_PRECISION_SIGNALS_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_PRECISION_SIGNALS_JSON ===", flush=True)


if __name__ == "__main__":
    main()
