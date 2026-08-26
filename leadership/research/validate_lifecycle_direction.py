from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact
from sklearn.tree import DecisionTreeClassifier

import discover_stock_interactions as base
import discover_stock_interactions_v2  # noqa: F401  # installs finite-value tree preprocessing

# Fresh period was not used in the prior interaction discovery.
ORIGINAL_END = pd.Timestamp("2026-06-20")
FRESH_START = pd.Timestamp("2026-06-22")
FRESH_END = pd.Timestamp("2026-07-28")
ANALYSIS_END = FRESH_END
COOLDOWN = 20
MIN_LEAF = 250
MAX_DEPTH = 3

# Frozen from the prior Discovery->Validation interaction run. Do not tune here.
LIFECYCLE_RULES = {
    "BROAD_LIFECYCLE": "dist_52w_high <= -0.299178 OR w30_distance > 0.403923",
    "DEEP_ACCEL": "dist_52w_high <= -0.426211 AND w30_slope4 > 0.0417902",
    "MID_ACCEL": "-0.426211 < dist_52w_high <= -0.299178 AND w30_slope4 > 0.0502433",
    "EXTENDED_REIGNITION": "dist_52w_high > -0.299178 AND w30_distance > 0.403923",
}

DIRECTION_FEATURES = list(base.FEATURES)
MODEL_FEATURES = {
    "FULL": DIRECTION_FEATURES,
    "NO_LIFECYCLE": [f for f in DIRECTION_FEATURES if f not in {"dist_52w_high", "w30_slope4", "w30_distance"}],
    "NO_FLOW": [f for f in DIRECTION_FEATURES if not (f.startswith("flow_") or f.startswith("theme_hhi"))],
    "NO_RS": [f for f in DIRECTION_FEATURES if not (f.startswith("rs") or f.startswith("term"))],
}


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


def clean_series(frame: pd.DataFrame, feature: str) -> pd.Series:
    return pd.to_numeric(frame[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).clip(-1_000_000.0, 1_000_000.0)


def lifecycle_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    d52 = pd.to_numeric(frame["dist_52w_high"], errors="coerce")
    slope = pd.to_numeric(frame["w30_slope4"], errors="coerce")
    wdist = pd.to_numeric(frame["w30_distance"], errors="coerce")
    return {
        "BROAD_LIFECYCLE": (d52 <= -0.299178) | (wdist > 0.403923),
        "DEEP_ACCEL": (d52 <= -0.426211) & (slope > 0.0417902),
        "MID_ACCEL": (d52 > -0.426211) & (d52 <= -0.299178) & (slope > 0.0502433),
        "EXTENDED_REIGNITION": (d52 > -0.299178) & (wdist > 0.403923),
    }


def add_date_ord(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["entry_date"] = pd.to_datetime(out["entry_date"])
    all_dates = np.sort(out["entry_date"].unique())
    pos = {pd.Timestamp(d): i for i, d in enumerate(all_dates)}
    out["date_ord"] = out["entry_date"].map(pos).astype(int)
    return out


def state_entry_events(frame: pd.DataFrame, selected: pd.Series, want_selected: bool) -> pd.DataFrame:
    x = frame.copy()
    x["_state"] = selected.reindex(frame.index, fill_value=False).astype(bool).to_numpy()
    x = x.sort_values(["symbol", "theme", "entry_date"]).copy()
    prev_state = x.groupby(["symbol", "theme"], observed=True)["_state"].shift(1)
    prev_ord = x.groupby(["symbol", "theme"], observed=True)["date_ord"].shift(1)
    new_run = prev_state.isna() | (prev_state != x["_state"]) | ((x["date_ord"] - prev_ord) > 1)
    candidates = x[new_run & (x["_state"] == want_selected)].copy()
    if candidates.empty:
        return candidates
    keep_idx: list[int] = []
    for _, g in candidates.groupby(["symbol", "theme"], observed=True, sort=False):
        last = -10**9
        for idx, row in g.sort_values("date_ord").iterrows():
            cur = int(row["date_ord"])
            if cur - last > COOLDOWN:
                keep_idx.append(idx)
                last = cur
    return candidates.loc[keep_idx].sort_values("entry_date")


def compare_events(sel: pd.DataFrame, ctl: pd.DataFrame, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {"selected_n": len(sel), "control_n": len(ctl)}
    a = (pd.to_numeric(sel["stock_minus_peers_20"], errors="coerce") >= 0.10).dropna()
    b = (pd.to_numeric(ctl["stock_minus_peers_20"], errors="coerce") >= 0.10).dropna()
    out["winner_rate"] = float(a.mean()) if len(a) else None
    out["control_winner_rate"] = float(b.mean()) if len(b) else None
    out["winner_lift_pp"] = 100.0 * (float(a.mean()) - float(b.mean())) if len(a) and len(b) else None
    if len(a) and len(b):
        _, p = fisher_exact([[int(a.sum()), len(a)-int(a.sum())], [int(b.sum()), len(b)-int(b.sum())]], alternative="greater")
        out["fisher_greater_p"] = float(p)
    else:
        out["fisher_greater_p"] = None
    both = pd.concat([sel.assign(_pick=True), ctl.assign(_pick=False)], ignore_index=True)
    both["_up"] = (pd.to_numeric(both["stock_minus_peers_20"], errors="coerce") >= 0.10).astype(float)
    m = both["_pick"].astype(bool)
    for i, cluster in enumerate(("entry_date", "theme", "symbol")):
        out[f"winner_{cluster}_ci95"] = base.cluster_diff_ci(both, m, "_up", cluster, seed + i * 1000)
    for h in (5, 10, 20):
        col = f"stock_minus_peers_{h}"
        xs = pd.to_numeric(sel[col], errors="coerce").dropna(); xc = pd.to_numeric(ctl[col], errors="coerce").dropna()
        out[f"peer{h}"] = {
            "selected_mean": float(xs.mean()) if len(xs) else None,
            "control_mean": float(xc.mean()) if len(xc) else None,
            "diff": float(xs.mean()-xc.mean()) if len(xs) and len(xc) else None,
        }
    for col in ("mfe20", "mae20"):
        xs = pd.to_numeric(sel[col], errors="coerce").dropna(); xc = pd.to_numeric(ctl[col], errors="coerce").dropna()
        out[col] = {
            "selected_mean": float(xs.mean()) if len(xs) else None,
            "control_mean": float(xc.mean()) if len(xc) else None,
            "diff": float(xs.mean()-xc.mean()) if len(xs) and len(xc) else None,
        }
    return out


def split_frame(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = pd.to_datetime(frame["entry_date"])
    return {
        "DISCOVERY_2016_2021": frame[(d >= base.ANALYSIS_START) & (d <= base.DISCOVERY_END)].copy(),
        "VALIDATION_2022_2024": frame[(d >= base.VALIDATION_START) & (d <= base.VALIDATION_END)].copy(),
        "OPENED_2025_2026H1": frame[(d >= base.HOLDOUT_START) & (d <= ORIGINAL_END)].copy(),
        "FRESH_2026_06_22_TO_07_28": frame[(d >= FRESH_START) & (d <= FRESH_END)].copy(),
    }


def fit_direction_tree(discovery_big: pd.DataFrame, features: list[str], seed: int):
    med: dict[str, float] = {}
    Xd: dict[str, pd.Series] = {}
    for f in features:
        s = clean_series(discovery_big, f)
        med[f] = float(s.median()) if s.notna().any() else 0.0
        Xd[f] = s.fillna(med[f])
    X = pd.DataFrame(Xd)
    y = discovery_big["direction_up"].astype(int)
    model = DecisionTreeClassifier(max_depth=MAX_DEPTH, min_samples_leaf=MIN_LEAF, min_samples_split=MIN_LEAF*2, random_state=seed)
    model.fit(X, y)
    return model, med, base.extract_leaf_rules(model, features)


def apply_tree(model, frame: pd.DataFrame, features: list[str], med: dict[str, float]) -> np.ndarray:
    X = pd.DataFrame({f: clean_series(frame, f).fillna(med[f]) for f in features})
    return model.apply(X)


def direction_cluster_ci(frame: pd.DataFrame, mask: pd.Series, seed: int) -> dict[str, Any]:
    use = frame.copy()
    use["_up"] = use["direction_up"].astype(float)
    return {c: base.cluster_diff_ci(use, mask, "_up", c, seed + i*1000) for i, c in enumerate(("entry_date", "theme", "symbol"))}


def direction_eval_big(frame_big: pd.DataFrame, selected: pd.Series, seed: int) -> dict[str, Any]:
    selected = selected.reindex(frame_big.index, fill_value=False).astype(bool)
    a = frame_big.loc[selected, "direction_up"].astype(bool); b = frame_big.loc[~selected, "direction_up"].astype(bool)
    out = {
        "selected_n": int(selected.sum()), "other_n": int((~selected).sum()),
        "up_rate": float(a.mean()) if len(a) else None,
        "other_up_rate": float(b.mean()) if len(b) else None,
        "up_lift_pp": 100*(float(a.mean())-float(b.mean())) if len(a) and len(b) else None,
        "cluster_ci95": direction_cluster_ci(frame_big, selected, seed),
    }
    if len(a) and len(b):
        _, p = fisher_exact([[int(a.sum()), len(a)-int(a.sum())], [int(b.sum()), len(b)-int(b.sum())]], alternative="greater")
        out["fisher_greater_p"] = float(p)
    else:
        out["fisher_greater_p"] = None
    return out


def eval_selected_all(frame: pd.DataFrame, selected: pd.Series) -> dict[str, Any]:
    selected = selected.reindex(frame.index, fill_value=False).astype(bool)
    def side(mask: pd.Series) -> dict[str, Any]:
        x = frame.loc[mask]
        peer20 = pd.to_numeric(x["stock_minus_peers_20"], errors="coerce")
        mfe = pd.to_numeric(x["mfe20"], errors="coerce"); mae = pd.to_numeric(x["mae20"], errors="coerce")
        return {
            "n": len(x),
            "up10_rate": float((peer20 >= 0.10).mean()) if len(x) else None,
            "down10_rate": float((peer20 <= -0.10).mean()) if len(x) else None,
            "peer20_mean": float(peer20.mean()) if len(x) else None,
            "mfe20_mean": float(mfe.mean()) if len(x) else None,
            "mae20_mean": float(mae.mean()) if len(x) else None,
            "clean_up_rate": float(((peer20 >= 0.10) & (mfe >= 0.15) & (mae > -0.10)).mean()) if len(x) else None,
        }
    return {"selected": side(selected), "other": side(~selected)}


def run_direction_model(name: str, frames: dict[str, pd.DataFrame], features: list[str], seed: int) -> dict[str, Any]:
    big_frames: dict[str, pd.DataFrame] = {}
    for k, fr in frames.items():
        p = pd.to_numeric(fr["stock_minus_peers_20"], errors="coerce")
        b = fr[(p >= 0.10) | (p <= -0.10)].copy()
        b["direction_up"] = (pd.to_numeric(b["stock_minus_peers_20"], errors="coerce") >= 0.10).astype(int)
        big_frames[k] = b
    model, med, rules = fit_direction_tree(big_frames["DISCOVERY_2016_2021"], features, seed)
    leafs_big = {k: apply_tree(model, v, features, med) for k, v in big_frames.items()}
    leafs_all = {k: apply_tree(model, v, features, med) for k, v in frames.items()}
    base_rates = {k: float(v["direction_up"].mean()) if len(v) else None for k, v in big_frames.items()}
    leaf_table: list[dict[str, Any]] = []
    for leaf in sorted(rules):
        rec: dict[str, Any] = {"leaf": int(leaf), "rule": rules[leaf]}
        for sk, fr in big_frames.items():
            mask = leafs_big[sk] == leaf
            rate = float(fr.loc[mask, "direction_up"].mean()) if mask.sum() else None
            rec[sk] = {"n": int(mask.sum()), "up_rate": rate, "lift_pp": 100*(rate-base_rates[sk]) if rate is not None and base_rates[sk] is not None else None}
        leaf_table.append(rec)
    validated: list[int] = []
    for rec in leaf_table:
        d = rec["DISCOVERY_2016_2021"]; v = rec["VALIDATION_2022_2024"]
        if d["n"] >= MIN_LEAF and v["n"] >= 100 and d["lift_pp"] is not None and v["lift_pp"] is not None and d["lift_pp"] >= 5.0 and v["lift_pp"] >= 3.0:
            validated.append(int(rec["leaf"]))
    evals: dict[str, Any] = {}
    all_evals: dict[str, Any] = {}
    for i, sk in enumerate(frames):
        mb = pd.Series(np.isin(leafs_big[sk], validated), index=big_frames[sk].index)
        ma = pd.Series(np.isin(leafs_all[sk], validated), index=frames[sk].index)
        evals[sk] = direction_eval_big(big_frames[sk], mb, seed + 10000 + i*100)
        all_evals[sk] = eval_selected_all(frames[sk], ma)
    return {
        "features": features,
        "tree_depth": int(model.get_depth()),
        "leaves": int(model.get_n_leaves()),
        "validated_leaves": validated,
        "rules_selected": [{"leaf": x, "rule": rules[x]} for x in validated],
        "leaf_table": leaf_table,
        "big_mover_evaluation": evals,
        "all_population_evaluation": all_evals,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()
    root = Path(args.root); outdir = root / args.output; outdir.mkdir(parents=True, exist_ok=True)

    # Extend only the research analysis window to create a genuinely fresh final period.
    base.ANALYSIS_END = ANALYSIS_END
    frame, diag = base.build_candidates(root, args.max_tickers, args.batch_size, args.min_members)
    frame = add_date_ord(frame)
    frames = split_frame(frame)

    lifecycle: dict[str, Any] = {}
    for ri, (rname, desc) in enumerate(LIFECYCLE_RULES.items()):
        lifecycle[rname] = {"definition": desc, "splits": {}}
        for si, (sk, fr) in enumerate(frames.items()):
            mask = lifecycle_masks(fr)[rname]
            sel = state_entry_events(fr, mask, True)
            ctl = state_entry_events(fr, mask, False)
            lifecycle[rname]["splits"][sk] = compare_events(sel, ctl, 20000 + ri*1000 + si*100)

    direction: dict[str, Any] = {}
    for i, (name, features) in enumerate(MODEL_FEATURES.items()):
        print(f"DIRECTION {name}", flush=True)
        direction[name] = run_direction_model(name, frames, features, 30000 + i*100)

    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_LIFECYCLE_DIRECTION",
        "design": {
            "population": "all stock-days inside frozen Subtheme Momentum; no Hidden Ignition or RS21 gate",
            "lifecycle": {"frozen_rules": LIFECYCLE_RULES, "event_rule": "first day of state run only; 20 trading-day cooldown per symbol-theme", "clusters": ["date", "theme", "symbol"]},
            "direction": {
                "primary_question": "among |20d stock-minus-theme-peers| >=10% big movers, which current features distinguish UP (+10%) from DOWN (-10%)?",
                "discovery": "2016-2021", "validation": "2022-2024", "opened_reference": "2025-2026H1", "fresh_final": "2026-06-22..2026-07-28",
                "tree": {"max_depth": MAX_DEPTH, "min_leaf": MIN_LEAF, "validation_rule": "Discovery UP-rate lift >=5pp AND Validation >=3pp AND validation n>=100"},
                "model_families": list(MODEL_FEATURES),
            },
        },
        "coverage": diag,
        "split_coverage": {k: {"n": len(v), "dates": int(v.entry_date.nunique()), "themes": int(v.theme.nunique()), "symbols": int(v.symbol.nunique())} for k, v in frames.items()},
        "lifecycle_event_validation": lifecycle,
        "direction_models": direction,
    }
    (outdir / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LIFECYCLE_DIRECTION_RESULT_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LIFECYCLE_DIRECTION_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
