from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_confirmed_leadership as cl
import validate_post_ignition_leaders as post
import validate_theme_ltr as base

SEEDS = (11, 23, 37, 53, 71, 101, 149, 211)
LABELS = {
    "ret20": "label_ret20",
    "ret40": "label_ret40",
    "ret63": "label_ret63",
    "mfe63": "label_mfe63",
}


def safe(v):
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if np.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def fingerprint(df: pd.DataFrame, decimals: int | None = None) -> str:
    z = df.sort_values(["date", "theme", "symbol"]).reset_index(drop=True).copy()
    z["date"] = pd.to_datetime(z["date"]).dt.strftime("%Y-%m-%d")
    if decimals is not None:
        for c in z.select_dtypes(include=[np.number]).columns:
            z[c] = z[c].round(decimals)
    payload = z.to_csv(index=False, na_rep="NA", lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_params(seed: int, n_estimators: int, sampling: bool = True) -> dict:
    p = base.params(seed, n_estimators)
    p.update(
        n_jobs=1,
        deterministic=True,
        force_col_wise=True,
        verbosity=-1,
    )
    if not sampling:
        p.update(subsample=1.0, subsample_freq=0, colsample_bytree=1.0)
    return p


def reference_iterations(train: pd.DataFrame, features: list[str], label: str, calendar: pd.DatetimeIndex) -> int:
    fv = int(np.where(calendar >= pd.Timestamp("2020-01-01"))[0][0])
    sub = train[(train.date < pd.Timestamp("2020-01-01")) & ((train.event_pos + 63) < fv)].copy()
    val = train[train.date >= pd.Timestamp("2020-01-01")].copy()
    a, ag = base.grouped(sub)
    b, bg = base.grouped(val)
    probe = lgb.LGBMRanker(**stable_params(38, 700, sampling=True))
    probe.fit(
        a[features], a[label].astype(int), group=ag,
        eval_set=[(b[features], b[label].astype(int))],
        eval_group=[bg], eval_at=[1, 3],
        callbacks=[lgb.early_stopping(60, verbose=False)],
    )
    return int(probe.best_iteration_ or 350)


def fit_full(train: pd.DataFrame, features: list[str], label: str, seed: int, n_estimators: int, sampling: bool = True):
    full, fg = base.grouped(train)
    model = lgb.LGBMRanker(**stable_params(seed, n_estimators, sampling=sampling))
    model.fit(full[features], full[label].astype(int), group=fg)
    return model


def add_prediction_columns(test: pd.DataFrame, models: dict[str, lgb.LGBMRanker], features: list[str], prefix: str) -> pd.DataFrame:
    z = test[["date", "theme", "symbol"]].copy()
    rank_cols = []
    for name, model in models.items():
        pred = model.predict(test[features])
        col = f"{prefix}_{name}"
        z[col] = pred
        rcol = f"rank_{col}"
        z[rcol] = z.groupby(["date", "theme"], observed=True)[col].rank(pct=True, method="average")
        rank_cols.append(rcol)
    z[f"{prefix}_ensemble"] = z[rank_cols].mean(axis=1)
    return z[["date", "theme", "symbol", f"{prefix}_ensemble"]]


def top_symbols(df: pd.DataFrame, score: str, n: int) -> dict[tuple[pd.Timestamp, str], tuple[str, ...]]:
    out = {}
    for (d, t), g in df.groupby(["date", "theme"], observed=True, sort=True):
        x = g.dropna(subset=[score]).sort_values([score, "symbol"], ascending=[False, True]).head(n)
        out[(pd.Timestamp(d), str(t))] = tuple(x.symbol.astype(str))
    return out


def mean_pairwise_top1(choice_maps: dict[int, dict]) -> float:
    vals = []
    seeds = sorted(choice_maps)
    for a, b in combinations(seeds, 2):
        common = sorted(set(choice_maps[a]) & set(choice_maps[b]))
        if common:
            vals.append(np.mean([choice_maps[a][k][0] == choice_maps[b][k][0] for k in common]))
    return float(np.mean(vals)) if vals else np.nan


def mean_pairwise_jaccard(choice_maps: dict[int, dict]) -> float:
    vals = []
    seeds = sorted(choice_maps)
    for a, b in combinations(seeds, 2):
        common = sorted(set(choice_maps[a]) & set(choice_maps[b]))
        for k in common:
            x, y = set(choice_maps[a][k]), set(choice_maps[b][k])
            if x or y:
                vals.append(len(x & y) / len(x | y))
    return float(np.mean(vals)) if vals else np.nan


def evaluate_choices(rows: pd.DataFrame, choices: dict, method: str) -> pd.DataFrame:
    records = []
    grouped = {(pd.Timestamp(d), str(t)): g for (d, t), g in rows.groupby(["date", "theme"], observed=True, sort=True)}
    for key, selected in choices.items():
        g = grouped.get(key)
        if g is None or len(g) < base.MIN_POOL or not selected:
            continue
        chosen = g[g.symbol.astype(str).isin(selected)]
        if chosen.empty:
            continue
        rec = {"date": key[0], "theme": key[1], "method": method, "selected_count": len(chosen)}
        for h in base.HORIZONS:
            pool = pd.to_numeric(g[f"fwd_ret{h}"], errors="coerce").dropna()
            pick = pd.to_numeric(chosen[f"fwd_ret{h}"], errors="coerce").dropna()
            if len(pool) < base.MIN_POOL or pick.empty:
                rec[f"ret_cost_{h}"] = np.nan
                rec[f"vs_theme_{h}"] = np.nan
                rec[f"winner_capture_{h}"] = np.nan
                continue
            raw = float(pick.mean())
            rec[f"ret_cost_{h}"] = raw - 2 * base.COST_BPS_SIDE / 10000.0
            rec[f"vs_theme_{h}"] = raw - float(pool.mean())
            winner = str(g.loc[pd.to_numeric(g[f"fwd_ret{h}"], errors="coerce").idxmax(), "symbol"])
            rec[f"winner_capture_{h}"] = float(winner in set(chosen.symbol.astype(str)))
        records.append(rec)
    return pd.DataFrame(records)


def score_choices(rows: pd.DataFrame, score: str, n: int) -> dict:
    return top_symbols(rows, score, n)


def summary_series(s: pd.Series) -> dict:
    x = pd.to_numeric(s, errors="coerce").dropna()
    if x.empty:
        return {"n": 0}
    return {
        "n": int(len(x)),
        "mean": float(x.mean()),
        "median": float(x.median()),
        "p10": float(x.quantile(0.10)),
        "p90": float(x.quantile(0.90)),
        "positive_rate": float((x > 0).mean()),
    }


def paired_diff(ev: pd.DataFrame, method: str, baseline: str, metric: str) -> dict:
    a = ev[ev.method == method][["date", "theme", metric]].rename(columns={metric: "a"})
    b = ev[ev.method == baseline][["date", "theme", metric]].rename(columns={metric: "b"})
    m = a.merge(b, on=["date", "theme"])
    return summary_series(m.a - m.b)


def build_dataset(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int, min_members: int):
    snap = er.load_json(root / "sector_snapshot.json")
    all_members, taxonomy = er.extract_theme_members(snap)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    selected = er.stratified_symbols(all_members, set(industry_map) & universe, max_tickers)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    ohlcv, download_diag = post.rtv2.download_ohlcvo(
        requested,
        str((pd.Timestamp(analysis_start) - pd.Timedelta(days=900)).date()),
        str((pd.Timestamp(analysis_end) + pd.Timedelta(days=140)).date()),
        batch_size,
    )
    ca, oa, ha, la, va = (ohlcv[k] for k in ("close", "open", "high", "low", "volume"))
    cols = [s for s in selected if s in ca.columns]
    close, open_, high, vol = ca[cols], oa[cols], ha[cols], va[cols]
    stock_ret = close.pct_change(fill_method=None)
    spy_ret = ca.SPY.pct_change(fill_method=None)

    members = {t: [s for s in m if s in cols] for t, m in all_members.items()}
    counts = {t: len(m) for t, m in members.items()}
    theme_ret = er.grouped_equal_weight(stock_ret, members, min_members)
    spy63 = er.period_return(spy_ret, 63)
    theme63 = er.period_return(theme_ret, 63)
    theme_pct = theme63.sub(spy63, axis=0).rank(axis=1, pct=True) * 100
    breadth = er.breadth_above_ema21(close, members, min_members).reindex(columns=theme_ret.columns)

    industry_groups = defaultdict(list)
    for s in cols:
        if s in industry_map and industry_map[s][1]:
            industry_groups[industry_map[s][1]].append(s)
    industry_ret = er.grouped_equal_weight(stock_ret, dict(industry_groups), min_members)
    weights = er.build_parent_weights(all_members, industry_map)
    industry_pct = er.period_return(industry_ret, 63).sub(spy63, axis=0).rank(axis=1, pct=True) * 100
    parent = er.weighted_matrix(industry_pct, weights, list(theme_ret.columns)).reindex(columns=theme_ret.columns)

    events = er.extract_events(
        cl.momentum_mask(theme_pct, parent, breadth), theme_pct, parent, breadth, counts,
        pd.Timestamp(analysis_start), pd.Timestamp(analysis_end),
    ).sort_values(["date", "theme"]).reset_index(drop=True)

    feats = base.make_features(ohlcv, cols)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    sma50 = close.rolling(50, min_periods=35).mean()
    dv20 = (close * vol).rolling(20, min_periods=15).mean()
    rows = base.build_rows(events, close, open_, high, stock_ret, ca.SPY, theme_ret, parent, members, feats, dv20, ema21, sma50)
    train, test, purge_diag = base.purge(rows, close.index)
    return rows, train, test, close.index, download_diag, taxonomy, purge_diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--replicate", default="A")
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-30")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    ap.add_argument("--min-members", type=int, default=3)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    rows, train, test, calendar, download_diag, taxonomy, purge_diag = build_dataset(
        root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size, args.min_members
    )
    rows = rows.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    train = train.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    test = test.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    rows.to_csv(out / "frozen_event_stock_rows.csv.gz", index=False, compression="gzip")

    features = base.feature_cols(rows)
    best = {name: reference_iterations(train, features, label, calendar) for name, label in LABELS.items()}
    print("REFERENCE_ITERATIONS", best, flush=True)

    seed_predictions = []
    top1_maps = {}
    top3_maps = {}
    seed_method_rows = []
    for seed in SEEDS:
        print("SEED", seed, flush=True)
        models = {name: fit_full(train, features, label, seed + i, best[name], sampling=True)
                  for i, (name, label) in enumerate(LABELS.items())}
        p = add_prediction_columns(test, models, features, f"s{seed}")
        seed_predictions.append(p)
        score = f"s{seed}_ensemble"
        top1_maps[seed] = top_symbols(p, score, 1)
        top3_maps[seed] = top_symbols(p, score, 3)
        e1 = evaluate_choices(test, top1_maps[seed], f"AI_SEED_{seed}_TOP1")
        e3 = evaluate_choices(test, top3_maps[seed], f"AI_SEED_{seed}_TOP3")
        seed_method_rows.extend([e1, e3])

    merged = seed_predictions[0]
    for p in seed_predictions[1:]:
        merged = merged.merge(p, on=["date", "theme", "symbol"], how="inner")
    ensemble_cols = [f"s{s}_ensemble" for s in SEEDS]
    merged["seed_ensemble"] = merged[ensemble_cols].mean(axis=1)
    merged.to_csv(out / "seed_predictions.csv.gz", index=False, compression="gzip")

    # Deterministic no-sampling reference: if this changes across A/B, tiny input perturbations alone are enough to destabilize trees.
    det_models = {name: fit_full(train, features, label, 1000 + i, best[name], sampling=False)
                  for i, (name, label) in enumerate(LABELS.items())}
    det = add_prediction_columns(test, det_models, features, "det")
    det_choice1 = top_symbols(det, "det_ensemble", 1)
    det_choice3 = top_symbols(det, "det_ensemble", 3)

    seed_ens_choice1 = top_symbols(merged, "seed_ensemble", 1)
    seed_ens_choice3 = top_symbols(merged, "seed_ensemble", 3)
    rs63_1 = score_choices(test, "ret63", 1)
    rs63_3 = score_choices(test, "ret63", 3)
    rs189_1 = score_choices(test, "ret189", 1)
    rs189_3 = score_choices(test, "ret189", 3)

    evals = [
        evaluate_choices(test, seed_ens_choice1, "AI_SEED_ENSEMBLE_TOP1"),
        evaluate_choices(test, seed_ens_choice3, "AI_SEED_ENSEMBLE_TOP3"),
        evaluate_choices(test, det_choice1, "AI_DETERMINISTIC_TOP1"),
        evaluate_choices(test, det_choice3, "AI_DETERMINISTIC_TOP3"),
        evaluate_choices(test, rs63_1, "RS63_TOP1"),
        evaluate_choices(test, rs63_3, "RS63_TOP3"),
        evaluate_choices(test, rs189_1, "RS189_TOP1"),
        evaluate_choices(test, rs189_3, "RS189_TOP3"),
    ] + seed_method_rows
    ev = pd.concat(evals, ignore_index=True)
    ev.to_csv(out / "stability_method_rows.csv.gz", index=False, compression="gzip")

    result = {
        "status": "FROZEN_DATA_LTR_STABILITY",
        "replicate": args.replicate,
        "seeds": list(SEEDS),
        "best_iterations": best,
        "download": download_diag,
        "taxonomy": taxonomy,
        "purge": purge_diag,
        "coverage": {
            "all_rows": int(len(rows)),
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "train_events": int(train[["date", "theme"]].drop_duplicates().shape[0]),
            "test_events": int(test[["date", "theme"]].drop_duplicates().shape[0]),
        },
        "fingerprints": {
            "raw_all": fingerprint(rows),
            "rounded6_all": fingerprint(rows, 6),
            "rounded5_all": fingerprint(rows, 5),
            "raw_train": fingerprint(train),
            "rounded6_train": fingerprint(train, 6),
            "rounded5_train": fingerprint(train, 5),
            "raw_test": fingerprint(test),
            "rounded6_test": fingerprint(test, 6),
            "rounded5_test": fingerprint(test, 5),
        },
        "within_replicate_stability": {
            "mean_pairwise_top1_same": mean_pairwise_top1(top1_maps),
            "mean_pairwise_top3_jaccard": mean_pairwise_jaccard(top3_maps),
        },
        "methods": {},
        "paired": {},
    }

    key_methods = [
        "AI_SEED_ENSEMBLE_TOP1", "AI_SEED_ENSEMBLE_TOP3",
        "AI_DETERMINISTIC_TOP1", "AI_DETERMINISTIC_TOP3",
        "RS63_TOP1", "RS63_TOP3", "RS189_TOP1", "RS189_TOP3",
    ]
    for method in key_methods:
        part = ev[ev.method == method]
        result["methods"][method] = {
            str(h): {
                "ret_cost": summary_series(part[f"ret_cost_{h}"]),
                "vs_theme": summary_series(part[f"vs_theme_{h}"]),
                "winner_capture": summary_series(part[f"winner_capture_{h}"]),
            } for h in base.HORIZONS
        }

    for method in ["AI_SEED_ENSEMBLE_TOP1", "AI_SEED_ENSEMBLE_TOP3", "AI_DETERMINISTIC_TOP1", "AI_DETERMINISTIC_TOP3"]:
        result["paired"][method] = {}
        for baseline in ["RS63_TOP1", "RS63_TOP3", "RS189_TOP1", "RS189_TOP3"]:
            result["paired"][method][baseline] = {
                str(h): paired_diff(ev, method, baseline, f"ret_cost_{h}") for h in base.HORIZONS
            }

    # Seed-by-seed economic dispersion is itself a stability diagnostic.
    result["seed_performance"] = {}
    for seed in SEEDS:
        result["seed_performance"][str(seed)] = {}
        for n in (1, 3):
            method = f"AI_SEED_{seed}_TOP{n}"
            part = ev[ev.method == method]
            result["seed_performance"][str(seed)][f"top{n}"] = {
                str(h): summary_series(part[f"ret_cost_{h}"]) for h in base.HORIZONS
            }

    (out / "stability_summary.json").write_text(
        json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("===LTR_STABILITY_RESULT===")
    print(json.dumps(safe(result), ensure_ascii=False, separators=(",", ":")))
    print("===END===", flush=True)


if __name__ == "__main__":
    main()
