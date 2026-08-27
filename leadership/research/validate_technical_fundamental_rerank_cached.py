from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import validate_technical_fundamental_rerank as base

BOOT_REPS = 3000
BOOT_SEED = 20260827


def _safe_float(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _paired(events: pd.DataFrame, method: str, baseline: str, horizon: int) -> pd.DataFrame:
    metric = f"ret_cost_{horizon}"
    a = events.loc[events.method == method, ["date", "theme", "symbol", metric]].rename(
        columns={"symbol": "symbol_a", metric: "a"}
    )
    b = events.loc[events.method == baseline, ["date", "theme", "symbol", metric]].rename(
        columns={"symbol": "symbol_b", metric: "b"}
    )
    m = a.merge(b, on=["date", "theme"]).dropna().copy()
    m["date"] = pd.to_datetime(m["date"])
    m["diff"] = m["a"] - m["b"]
    m["changed"] = m["symbol_a"] != m["symbol_b"]
    return m


def _bootstrap_means(values: np.ndarray, reps: int = BOOT_REPS, seed: int = BOOT_SEED) -> list[float | None]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    out = np.empty(reps, dtype=float)
    for i in range(reps):
        out[i] = rng.choice(x, size=len(x), replace=True).mean()
    q = np.quantile(out, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def _date_equal_stats(m: pd.DataFrame) -> tuple[float | None, list[float | None]]:
    if m.empty:
        return None, [None, None]
    g = m.groupby("date", observed=True)["diff"].mean()
    return float(g.mean()), _bootstrap_means(g.to_numpy(), seed=BOOT_SEED + 1)


def _theme_equal_stats(m: pd.DataFrame) -> tuple[float | None, list[float | None]]:
    if m.empty:
        return None, [None, None]
    g = m.groupby("theme", observed=True)["diff"].mean()
    return float(g.mean()), _bootstrap_means(g.to_numpy(), seed=BOOT_SEED + 2)


def _block20_date_equal_ci(m: pd.DataFrame, pos_map: pd.DataFrame) -> list[float | None]:
    if m.empty:
        return [None, None]
    d = m.groupby("date", observed=True)["diff"].mean().reset_index()
    p = pos_map[["date", "event_pos"]].drop_duplicates("date").copy()
    p["date"] = pd.to_datetime(p["date"])
    d = d.merge(p, on="date", how="left").dropna(subset=["event_pos"])
    if d.empty:
        return [None, None]
    d["block20"] = (pd.to_numeric(d["event_pos"], errors="coerce") // 20).astype("Int64")
    block_values = [g["diff"].to_numpy(dtype=float) for _, g in d.groupby("block20", observed=True) if len(g)]
    if not block_values:
        return [None, None]
    rng = np.random.default_rng(BOOT_SEED + 3)
    out = np.empty(BOOT_REPS, dtype=float)
    n = len(block_values)
    for i in range(BOOT_REPS):
        idx = rng.integers(0, n, size=n)
        sample = np.concatenate([block_values[j] for j in idx])
        out[i] = float(np.mean(sample))
    q = np.quantile(out, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def _paired_robust(
    events: pd.DataFrame,
    method: str,
    baseline: str,
    horizon: int,
    pos_map: pd.DataFrame,
) -> dict:
    m = _paired(events, method, baseline, horizon)
    if m.empty:
        return {"n": 0}
    date_mean, date_ci = _date_equal_stats(m)
    theme_mean, theme_ci = _theme_equal_stats(m)
    changed = m[m["changed"]]
    return {
        "n": int(len(m)),
        "event_mean": float(m["diff"].mean()),
        "median": float(m["diff"].median()),
        "positive_rate": float((m["diff"] > 0).mean()),
        "event_bootstrap_ci": _bootstrap_means(m["diff"].to_numpy(), seed=BOOT_SEED),
        "date_equal_mean": date_mean,
        "date_equal_bootstrap_ci": date_ci,
        "theme_equal_mean": theme_mean,
        "theme_equal_bootstrap_ci": theme_ci,
        "block20_date_equal_bootstrap_ci": _block20_date_equal_ci(m, pos_map),
        "changed_rate": float(m["changed"].mean()),
        "changed_n": int(len(changed)),
        "changed_mean": float(changed["diff"].mean()) if len(changed) else None,
        "changed_positive_rate": float((changed["diff"] > 0).mean()) if len(changed) else None,
    }


def _year_summary(events: pd.DataFrame, method: str, baseline: str) -> list[dict]:
    out = []
    for h in base.HORIZONS:
        m = _paired(events, method, baseline, h)
        if m.empty:
            continue
        m["year"] = m["date"].dt.year
        for y, g in m.groupby("year", observed=True):
            out.append({
                "horizon": int(h),
                "year": int(y),
                "n": int(len(g)),
                "event_mean": float(g["diff"].mean()),
                "positive_rate": float((g["diff"] > 0).mean()),
            })
    return out


def _subset_stats(
    events: pd.DataFrame,
    method: str,
    baseline: str,
    keys: pd.DataFrame,
    pos_map: pd.DataFrame,
) -> dict:
    out = {"events": int(len(keys))}
    for h in base.HORIZONS:
        m = _paired(events, method, baseline, h).merge(keys[["date", "theme"]], on=["date", "theme"], how="inner")
        if m.empty:
            out[str(h)] = {"n": 0}
            continue
        date_mean, date_ci = _date_equal_stats(m)
        out[str(h)] = {
            "n": int(len(m)),
            "event_mean": float(m["diff"].mean()),
            "date_equal_mean": date_mean,
            "date_equal_bootstrap_ci": date_ci,
            "block20_date_equal_bootstrap_ci": _block20_date_equal_ci(m, pos_map),
            "changed_rate": float(m["changed"].mean()),
        }
    return out


def _coverage_summary(test: pd.DataFrame) -> dict:
    x = test.copy()
    x["year"] = pd.to_datetime(x["date"]).dt.year
    result = {
        "rows": int(len(x)),
        "events": int(x[["date", "theme"]].drop_duplicates().shape[0]),
        "symbols": int(x["symbol"].nunique()),
        "has_sec_rate": float(pd.to_numeric(x["sec_has_data"], errors="coerce").fillna(0).mean()),
        "by_year": {},
    }
    for y, g in x.groupby("year", observed=True):
        result["by_year"][str(int(y))] = {
            "rows": int(len(g)),
            "has_sec_rate": float(pd.to_numeric(g["sec_has_data"], errors="coerce").fillna(0).mean()),
            "rev_yoy_rate": float(pd.to_numeric(g["rev_yoy"], errors="coerce").notna().mean()),
            "eps_yoy_rate": float(pd.to_numeric(g["eps_yoy"], errors="coerce").notna().mean()),
        }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--sec-features", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    rows = pd.read_csv(args.input, compression="gzip", parse_dates=["date"])
    sec = pd.read_csv(args.sec_features, compression="gzip", parse_dates=["date"])
    rows = rows.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    sec = sec.drop_duplicates(["date", "symbol"], keep="last")
    enriched = rows.merge(sec, on=["date", "symbol"], how="left")
    for c in base.FUND_FEATURES:
        if c not in enriched:
            enriched[c] = np.nan
    enriched["sec_has_data"] = enriched["sec_has_data"].fillna(0.0)
    pos_map = rows[["date", "event_pos"]].drop_duplicates("date")

    all_events = []
    summaries = {}
    for pool_name, union_flag in [("RS63_TOP3", False), ("RS63_RS189_UNION", True)]:
        pool = base.candidate_pool(enriched, union_rs189=union_flag).copy()
        pool["label40_local"] = base.rank_label(pool, "fwd_ret40")
        pool["label_mfe_local"] = base.rank_label(pool, "fwd_mfe63")
        train = pool[pool.date <= base.TRAIN_END].copy()
        test = pool[pool.date >= base.HOLDOUT_START].copy()

        tech_features = [c for c in base.TECH_FEATURES if c in pool.columns]
        hybrid_features = tech_features + [c for c in base.FUND_FEATURES if c in pool.columns]

        for objective, label in [("RET40", "label40_local"), ("MFE63", "label_mfe_local")]:
            test[f"tech_{objective}"] = base.fit_predict_ensemble(train, test, tech_features, label, f"tech_{objective}")
            test[f"hybrid_{objective}"] = base.fit_predict_ensemble(train, test, hybrid_features, label, f"hybrid_{objective}")

        for kind in ("tech", "hybrid"):
            ranks = []
            for objective in ("RET40", "MFE63"):
                c = f"{kind}_{objective}"
                rc = f"{c}_rank"
                test[rc] = test.groupby(["date", "theme"], observed=True)[c].rank(pct=True, method="average")
                ranks.append(rc)
            test[f"{kind}_ensemble"] = test[ranks].mean(axis=1)

        selected = {
            "RS63_TOP1": base.choose_top1(test, "ret63"),
            "RS189_TOP1": base.choose_top1(test, "ret189"),
            "TECH_ML_TOP1": base.choose_top1(test, "tech_ensemble"),
            "HYBRID_ML_TOP1": base.choose_top1(test, "hybrid_ensemble"),
        }
        ev = pd.concat(
            [base.evaluate(v, enriched, f"{pool_name}_{k}") for k, v in selected.items()],
            ignore_index=True,
        )
        all_events.append(ev)

        hybrid = f"{pool_name}_HYBRID_ML_TOP1"
        tech = f"{pool_name}_TECH_ML_TOP1"
        rs63 = f"{pool_name}_RS63_TOP1"
        rs189 = f"{pool_name}_RS189_TOP1"

        event_cov = test.groupby(["date", "theme"], observed=True).agg(
            sec_n=("sec_has_data", "sum"),
            sec_rate=("sec_has_data", "mean"),
            recent30_n=("sec_recent_30", "sum"),
            recent60_n=("sec_recent_60", "sum"),
        ).reset_index()
        subsets = {
            "sec_2plus": event_cov[event_cov.sec_n >= 2][["date", "theme"]],
            "sec_all_candidates": event_cov[event_cov.sec_rate >= 0.999999][["date", "theme"]],
            "recent30_any": event_cov[event_cov.recent30_n >= 1][["date", "theme"]],
            "recent60_any": event_cov[event_cov.recent60_n >= 1][["date", "theme"]],
        }

        comparisons = {}
        for baseline_name, baseline_method in [("TECH_ML", tech), ("RS63", rs63), ("RS189", rs189)]:
            comparisons[baseline_name] = {
                str(h): _paired_robust(ev, hybrid, baseline_method, h, pos_map)
                for h in base.HORIZONS
            }

        summaries[pool_name] = {
            "train_rows": int(len(train)),
            "holdout_rows": int(len(test)),
            "holdout_events": int(test[["date", "theme"]].drop_duplicates().shape[0]),
            "coverage": _coverage_summary(test),
            "hybrid_comparisons": comparisons,
            "hybrid_vs_tech_by_year": _year_summary(ev, hybrid, tech),
            "predeclared_subsets_hybrid_vs_tech": {
                name: _subset_stats(ev, hybrid, tech, keys, pos_map)
                for name, keys in subsets.items()
            },
        }
        test.to_csv(out / f"holdout_candidates_{pool_name.lower()}.csv.gz", index=False, compression="gzip")

    events = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    events.to_csv(out / "robust_event_results.csv.gz", index=False, compression="gzip")

    summary = {
        "status": "RESEARCH_TECHNICAL_FIRST_SEC_RERANK_CACHED_ROBUST",
        "primary_pool": "RS63_TOP3",
        "train_end": str(base.TRAIN_END.date()),
        "holdout_start": str(base.HOLDOUT_START.date()),
        "cost_bps_side": float(base.COST_BPS_SIDE),
        "seeds": list(base.SEEDS),
        "bootstrap_reps": BOOT_REPS,
        "models": summaries,
        "interpretation_guardrails": [
            "Primary question is HYBRID_ML_TOP1 minus TECH_ML_TOP1 inside the preselected RS63 top-3 technical candidate pool.",
            "No feature, model parameter, horizon, or subset threshold was tuned using 2022+ holdout results in this recovery run.",
            "SEC features are reused exactly from the prior filed<=signal-date PIT artifact; no SEC refetch occurs here.",
            "Date-equal and 20-trading-session-block bootstrap are emphasized because multiple Theme events can occur on the same date.",
            "Current universe/current taxonomy survivorship bias remains and limits absolute-return interpretation.",
        ],
    }
    (out / "robust_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
