from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import discover_base_quality as bq


TRANSITION_FEATURES = [
    "base_vol10_vs_prior30",
    "base_tr5_vs_prior20",
    "base_atr10_vs50",
    "base_higher_low_atr",
    "base_support_ema21_10",
    "base_support_sma50_10",
    "base_down_vol10_vs_prior20",
    "base_tight_tr_frac10",
    "base_rvol_vs_dry5",
    "close_location",
    "flow_share_ratio_3v20",
    "flow_share_ratio_5v20",
    "flow_share_ratio_10v20",
    "flow_accel_3v10",
    "flow_accel_3v5",
    "rs21_pct",
    "rs21_delta5",
    "rs21_delta10",
    "rs21_delta20",
    "rs21_accel_5v10",
    "rs21_accel_5v20",
    "term21_63",
]

MODEL_FEATURES = {
    "TRANSITION_CORE": [
        "base_vol10_vs_prior30", "base_tr5_vs_prior20", "base_higher_low_atr",
        "base_support_ema21_10", "base_rvol_vs_dry5", "close_location",
        "flow_share_ratio_3v20", "flow_accel_3v10",
        "rs21_pct", "rs21_delta5", "rs21_accel_5v20",
    ],
    "FLOW_TRANSITION": [
        "base_vol10_vs_prior30", "base_tr5_vs_prior20", "base_rvol_vs_dry5",
        "base_higher_low_atr", "flow_share_ratio_3v20", "flow_share_ratio_5v20",
        "flow_share_ratio_10v20", "flow_accel_3v10", "flow_accel_3v5",
    ],
    "RS_FLOW_TRANSITION": [
        "base_vol10_vs_prior30", "base_tr5_vs_prior20", "base_rvol_vs_dry5",
        "base_higher_low_atr", "flow_share_ratio_3v20", "flow_accel_3v10",
        "rs21_pct", "rs21_delta5", "rs21_delta10", "rs21_delta20",
        "rs21_accel_5v10", "rs21_accel_5v20", "term21_63",
    ],
    "TRANSITION_PLUS_CONTEXT": TRANSITION_FEATURES + [
        "industry_rs", "theme_rs63", "theme_rs_delta20", "breadth", "momentum_age",
        "ema21_atr", "sma50_atr", "dist_prior_high20", "dist_prior_high63",
    ],
}


def safe_log_ratio(a: pd.Series, b: pd.Series | float = 1.0) -> pd.Series:
    aa = pd.to_numeric(a, errors="coerce")
    bb = pd.to_numeric(b, errors="coerce") if isinstance(b, pd.Series) else float(b)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(aa / bb)
    return pd.Series(out, index=a.index).replace([np.inf, -np.inf], np.nan)


def add_transition_features(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    x["flow_accel_3v10"] = safe_log_ratio(x["flow_share_ratio_3v20"], x["flow_share_ratio_10v20"])
    x["flow_accel_3v5"] = safe_log_ratio(x["flow_share_ratio_3v20"], x["flow_share_ratio_5v20"])
    x["rs21_accel_5v10"] = pd.to_numeric(x["rs21_delta5"], errors="coerce") - 0.5 * pd.to_numeric(x["rs21_delta10"], errors="coerce")
    x["rs21_accel_5v20"] = pd.to_numeric(x["rs21_delta5"], errors="coerce") - 0.25 * pd.to_numeric(x["rs21_delta20"], errors="coerce")
    return x


def fixed_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    f = frame
    def num(c: str) -> pd.Series:
        return pd.to_numeric(f[c], errors="coerce")

    vol10 = num("base_vol10_vs_prior30")
    tr5 = num("base_tr5_vs_prior20")
    rexp = num("base_rvol_vs_dry5")
    cl = num("close_location")
    hl = num("base_higher_low_atr")
    flow3 = num("flow_share_ratio_3v20")
    facc = num("flow_accel_3v10")
    rs5 = num("rs21_delta5")
    rs20 = num("rs21_delta20")
    rsacc = num("rs21_accel_5v20")
    rs = num("rs21_pct")

    rules = {
        # Classical dry-up followed by the first meaningful volume return.
        "VOL_DRY_REEXPAND": (vol10 <= 0.80) & (rexp >= 1.25) & (cl >= 0.60),
        # Price/volume contraction first, then activity returns.
        "TIGHT_DRY_REEXPAND": (tr5 <= 0.80) & (vol10 <= 0.85) & (rexp >= 1.20),
        # Theme-relative capital share is accelerating, not merely high.
        "FLOW_ACCEL": (flow3 >= 1.25) & (facc >= math.log(1.15)),
        # Short RS turns up faster than its 20d path while not already fully mature.
        "RS_INFLECT": (rs >= 0.45) & (rs < 0.85) & (rs5 >= 0.10) & (rsacc >= 0.05),
        # Dry base followed by flow acceleration.
        "BASE_TO_FLOW": (vol10 <= 0.85) & (tr5 <= 0.90) & (flow3 >= 1.20) & (facc > 0),
        # Dry base + flow acceleration + RS inflection: predeclared full sequence proxy.
        "BASE_FLOW_RS": (vol10 <= 0.85) & (tr5 <= 0.90) & (flow3 >= 1.20) & (facc > 0) & (rs5 > 0) & (rsacc > 0),
        # Same but asks for an improving low rather than breakout proximity.
        "HIGHER_LOW_FLOW_RS": (hl > 0) & (flow3 >= 1.20) & (facc > 0) & (rs5 > 0) & (rs20 < 0.30),
    }
    return {k: v.fillna(False).astype(bool) for k, v in rules.items()}


def evaluate_mask(frame: pd.DataFrame, mask: pd.Series, seed: int) -> dict[str, Any]:
    m = mask.reindex(frame.index, fill_value=False).astype(bool)
    sel_ev = bq.eventize_mask(frame, m)
    ctrl_ev = bq.eventize_mask(frame, ~m)
    return {
        "raw_selected": bq.rate_summary(frame.loc[m]),
        "raw_other": bq.rate_summary(frame.loc[~m]),
        "event_compare": bq.event_compare(sel_ev, ctrl_ev, seed),
    }


def attach_eps_asof(root: Path, events: pd.DataFrame) -> pd.DataFrame:
    p = root / "earnings.json"
    if not p.exists() or events.empty:
        return pd.DataFrame()
    obj = json.loads(p.read_text(encoding="utf-8"))
    chunks = []
    for sym, g in events.groupby("symbol", observed=True):
        rec = obj.get(str(sym), {})
        eps = rec.get("eps", {}) if isinstance(rec, dict) else {}
        ys = eps.get("yoy_series", []) if isinstance(eps, dict) else []
        vals = []
        for z in ys:
            try:
                vals.append((pd.Timestamp(z["date"]), float(z["yoy"])))
            except Exception:
                pass
        vals = sorted(vals)
        if len(vals) < 2:
            continue
        dates = np.array([d.to_datetime64() for d, _ in vals])
        yoy = np.array([v for _, v in vals], float)
        gd = pd.to_datetime(g.entry_date).to_numpy(dtype="datetime64[ns]")
        ix = np.searchsorted(dates, gd, side="right") - 1
        ok = ix >= 1
        if not ok.any():
            continue
        h = g.loc[ok].copy()
        j = ix[ok]
        h["eps_report_date"] = [pd.Timestamp(dates[k]) for k in j]
        h["eps_latest_yoy"] = yoy[j]
        h["eps_prior_yoy"] = yoy[j - 1]
        h["eps_accel_1"] = (h.eps_latest_yoy > h.eps_prior_yoy) & (h.eps_latest_yoy > 0)
        acc2 = np.zeros(len(h), dtype=bool)
        has3 = j >= 2
        jj = j[has3]
        acc2[has3] = (yoy[jj] > yoy[jj - 1]) & (yoy[jj - 1] > yoy[jj - 2]) & (yoy[jj] > 0)
        h["eps_accel_2"] = acc2
        chunks.append(h)
    if not chunks:
        return pd.DataFrame()
    e = pd.concat(chunks, ignore_index=True)
    return e.sort_values(["symbol", "theme", "eps_report_date", "entry_date"]).groupby(
        ["symbol", "theme", "eps_report_date"], observed=True, as_index=False
    ).head(1)


def eps_rule_summary(root: Path, frame: pd.DataFrame, rule_masks: dict[str, pd.Series]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "RECENT_POINT_IN_TIME_PROXY_ONLY_NOT_HISTORICAL_MODEL", "rules": {}}
    for i, (name, mask) in enumerate(rule_masks.items()):
        ev = bq.eventize_mask(frame, mask)
        e = attach_eps_asof(root, ev)
        rec: dict[str, Any] = {"events_with_eps": int(len(e)), "symbols": int(e.symbol.nunique()) if len(e) else 0}
        if len(e):
            for eps_rule in ("eps_accel_1", "eps_accel_2"):
                m = e[eps_rule].astype(bool)
                a = e.loc[m]
                c = e.loc[~m]
                z: dict[str, Any] = {"selected": bq.rate_summary(a), "control": bq.rate_summary(c)}
                if len(a) and len(c):
                    for target in ("clean_up", "pioneer_winner10"):
                        aa = a[target].astype(int); cc = c[target].astype(int)
                        _, pv = fisher_exact(
                            [[int(aa.sum()), len(aa) - int(aa.sum())], [int(cc.sum()), len(cc) - int(cc.sum())]],
                            alternative="greater",
                        )
                        z[target] = {
                            "lift_pp": 100 * (float(aa.mean()) - float(cc.mean())),
                            "fisher_greater_p": float(pv),
                        }
                rec[eps_rule] = z
        out["rules"][name] = rec
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    outdir = root / args.output
    outdir.mkdir(parents=True, exist_ok=True)

    frame, diag = bq.build_candidates(root, args.max_tickers, args.batch_size, args.min_members)
    frame["entry_date"] = pd.to_datetime(frame.entry_date)
    frame = add_transition_features(frame)

    hold_sym = frame.symbol.astype(str).map(bq.is_symbol_holdout)
    train = frame[~hold_sym].copy()
    hold = frame[hold_sym].copy()
    train_frames = {
        "DISCOVERY_2016_2021": train[(train.entry_date >= bq.ANALYSIS_START) & (train.entry_date <= bq.DISCOVERY_END)],
        "VALIDATION_2022_2024": train[(train.entry_date >= bq.VALIDATION_START) & (train.entry_date <= bq.VALIDATION_END)],
        "OPENED_2025_PLUS": train[train.entry_date >= bq.OPENED_START],
    }

    result: dict[str, Any] = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY_BASE_TRANSITION",
        "design": {
            "population": "all stock-days in frozen Subtheme Momentum; same base population as Base Quality",
            "target": {
                "clean_up": "20d peer excess >=10%, MFE>=15%, MAE>-10%",
                "failure": "20d peer excess <=-10% OR MAE<=-15%",
            },
            "principle": "test changes in state: dry->reexpand, contraction->activity, RS inflection, capital-flow acceleration",
            "symbol_holdout": "sha1(symbol) mod 4 == 0; never used for fit/validation",
            "tree": {
                "max_depth": bq.MAX_DEPTH,
                "min_leaf": bq.MIN_LEAF,
                "validation_rule": "Discovery clean lift >=5pp AND Validation >=3pp AND validation n>=100",
            },
            "fixed_rules_are_predeclared": True,
            "eps": "recent as-of overlay only; never used in historical model",
        },
        "coverage": diag,
        "symbols": {"train": int(train.symbol.nunique()), "holdout": int(hold.symbol.nunique())},
        "models": {},
        "fixed_rules": {},
    }

    for i, (name, features) in enumerate(MODEL_FEATURES.items()):
        print(f"TRANSITION_MODEL {name}", flush=True)
        result["models"][name] = bq.run_model(name, features, train_frames, hold, 63000 + i * 100)

    frames = {
        **train_frames,
        "SYMBOL_HOLDOUT_ALL": hold,
        "SYMBOL_HOLDOUT_2022_PLUS": hold[hold.entry_date >= bq.VALIDATION_START],
    }
    for r_i, rname in enumerate(fixed_rule_masks(frame)):
        rec = {}
        for f_i, (fname, fr) in enumerate(frames.items()):
            masks = fixed_rule_masks(fr)
            rec[fname] = evaluate_mask(fr, masks[rname], 70000 + r_i * 1000 + f_i * 100)
        result["fixed_rules"][rname] = rec

    print("EPS TRANSITION OVERLAY", flush=True)
    result["eps_overlay"] = eps_rule_summary(root, frame, fixed_rule_masks(frame))

    (outdir / "summary.json").write_text(json.dumps(bq.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== BASE_TRANSITION_RESULT_JSON ===", flush=True)
    print(json.dumps(bq.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_BASE_TRANSITION_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()
