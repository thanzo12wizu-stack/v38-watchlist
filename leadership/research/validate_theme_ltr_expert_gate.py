from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import validate_theme_ltr as base
import validate_theme_ltr_stability as stability
import validate_post_ignition_leaders as post

SEEDS = stability.SEEDS
LABELS = stability.LABELS
DEV_YEARS = (2019, 2020, 2021)
HORIZONS = (20, 40, 63)
THEME_FEATURES = (
    "theme_rs_pct", "theme_rank_delta20", "theme_breadth", "parent_rs_pct",
    "theme_member_count", "theme_disp20", "theme_disp63",
)
MARKET_SYMBOLS = ("SPY", "QQQ", "IWM", "HYG", "TLT", "^VIX")


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


def market_features(root: Path, dates: pd.DatetimeIndex, start: str, end: str, batch_size: int) -> pd.DataFrame:
    ohlcv, diag = post.rtv2.download_ohlcvo(
        list(MARKET_SYMBOLS),
        str((pd.Timestamp(start) - pd.Timedelta(days=400)).date()),
        str((pd.Timestamp(end) + pd.Timedelta(days=10)).date()),
        batch_size,
    )
    close = ohlcv["close"].copy()
    out = pd.DataFrame(index=close.index)
    for s in ("SPY", "QQQ", "IWM", "HYG", "TLT"):
        if s not in close.columns:
            continue
        x = pd.to_numeric(close[s], errors="coerce")
        r = x.pct_change(fill_method=None)
        for n in (5, 20, 63, 126):
            out[f"{s.lower()}_ret{n}"] = x / x.shift(n) - 1.0
        out[f"{s.lower()}_vol20"] = r.rolling(20, min_periods=14).std()
        out[f"{s.lower()}_vol63"] = r.rolling(63, min_periods=40).std()
        out[f"{s.lower()}_dist50"] = x / x.rolling(50, min_periods=35).mean() - 1.0
        out[f"{s.lower()}_dist200"] = x / x.rolling(200, min_periods=140).mean() - 1.0
    for s in ("QQQ", "IWM", "HYG", "TLT"):
        p = s.lower()
        if f"{p}_ret20" in out and "spy_ret20" in out:
            out[f"{p}_vs_spy20"] = out[f"{p}_ret20"] - out["spy_ret20"]
            out[f"{p}_vs_spy63"] = out[f"{p}_ret63"] - out["spy_ret63"]
    if "hyg_ret20" in out and "tlt_ret20" in out:
        out["hyg_vs_tlt20"] = out["hyg_ret20"] - out["tlt_ret20"]
        out["hyg_vs_tlt63"] = out["hyg_ret63"] - out["tlt_ret63"]
    if "^VIX" in close.columns:
        v = pd.to_numeric(close["^VIX"], errors="coerce")
        out["vix_level"] = v
        out["vix_chg5"] = v / v.shift(5) - 1.0
        out["vix_chg20"] = v / v.shift(20) - 1.0
        mu = v.rolling(63, min_periods=40).mean()
        sd = v.rolling(63, min_periods=40).std()
        out["vix_z63"] = (v - mu) / sd.replace(0, np.nan)
    out = out.replace([np.inf, -np.inf], np.nan)
    out.index = pd.to_datetime(out.index).tz_localize(None)
    target = pd.DatetimeIndex(pd.to_datetime(dates).tz_localize(None))
    out = out.reindex(target).ffill(limit=3)
    out.index.name = "date"
    out = out.reset_index()
    return out, diag


def nested_reference_iterations(train: pd.DataFrame, features: list[str], label: str, outer_year: int) -> int:
    val_year = outer_year - 1
    val = train[train.date.dt.year == val_year].copy()
    if val.empty:
        return 80
    first_val_pos = int(val.event_pos.min())
    sub = train[(train.date < val.date.min()) & ((train.event_pos + 63) < first_val_pos)].copy()
    if sub[["date", "theme"]].drop_duplicates().shape[0] < 100:
        return 80
    a, ag = base.grouped(sub)
    b, bg = base.grouped(val)
    probe = lgb.LGBMRanker(**stability.stable_params(38, 500, sampling=True))
    probe.fit(
        a[features], a[label].astype(int), group=ag,
        eval_set=[(b[features], b[label].astype(int))], eval_group=[bg], eval_at=[1, 3],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    return int(probe.best_iteration_ or 120)


def stable_ai_scores(train: pd.DataFrame, test: pd.DataFrame, features: list[str], iterations: dict[str, int]) -> pd.DataFrame:
    accum = np.zeros(len(test), dtype=float)
    for seed in SEEDS:
        rank_cols = []
        for i, (name, label) in enumerate(LABELS.items()):
            model = stability.fit_full(train, features, label, seed + i, iterations[name], sampling=True)
            pred = model.predict(test[features])
            tmp = pd.DataFrame({"date": test.date.values, "theme": test.theme.values, "pred": pred}, index=test.index)
            rank = tmp.groupby(["date", "theme"], observed=True)["pred"].rank(pct=True, method="average")
            rank_cols.append(rank.reindex(test.index).to_numpy())
        accum += np.nanmean(np.column_stack(rank_cols), axis=1) / len(SEEDS)
    out = test[["date", "theme", "symbol", "event_pos"]].copy()
    out["ai_score"] = accum
    return out


def build_oof_ai(rows: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, dict]:
    parts = []
    diag = {}
    for year in DEV_YEARS:
        test = rows[rows.date.dt.year == year].copy()
        if test.empty:
            continue
        first_pos = int(test.event_pos.min())
        train = rows[(rows.date < pd.Timestamp(f"{year}-01-01")) & ((rows.event_pos + 63) < first_pos)].copy()
        iterations = {name: nested_reference_iterations(train, features, label, year) for name, label in LABELS.items()}
        print("OOF_YEAR", year, "train_events", train[["date", "theme"]].drop_duplicates().shape[0],
              "test_events", test[["date", "theme"]].drop_duplicates().shape[0], "iters", iterations, flush=True)
        p = stable_ai_scores(train, test, features, iterations)
        parts.append(p)
        diag[str(year)] = {
            "train_events": int(train[["date", "theme"]].drop_duplicates().shape[0]),
            "test_events": int(test[["date", "theme"]].drop_duplicates().shape[0]),
            "iterations": iterations,
        }
    return pd.concat(parts, ignore_index=True), diag


def top_rows(df: pd.DataFrame, score: str) -> pd.DataFrame:
    idx = df.groupby(["date", "theme"], observed=True)[score].idxmax()
    return df.loc[idx].sort_values(["date", "theme"]).reset_index(drop=True)


def expert_event_data(rows: pd.DataFrame, ai_scores: pd.DataFrame) -> pd.DataFrame:
    z = ai_scores.merge(rows, on=["date", "theme", "symbol", "event_pos"], how="left", validate="one_to_one")
    ai = top_rows(z, "ai_score")
    rs = top_rows(z, "ret63")
    keys = ["date", "theme"]
    keep_context = list(THEME_FEATURES)
    a = ai[keys + ["event_pos", "symbol"] + keep_context + [f"fwd_ret{h}" for h in HORIZONS]].copy()
    a = a.rename(columns={"symbol": "ai_symbol", **{f"fwd_ret{h}": f"ai_ret{h}" for h in HORIZONS}})
    b = rs[keys + ["symbol"] + [f"fwd_ret{h}" for h in HORIZONS]].copy()
    b = b.rename(columns={"symbol": "rs_symbol", **{f"fwd_ret{h}": f"rs_ret{h}" for h in HORIZONS}})
    out = a.merge(b, on=keys, validate="one_to_one")
    out["same_symbol"] = (out.ai_symbol == out.rs_symbol).astype(float)
    out["ai_composite"] = out[[f"ai_ret{h}" for h in HORIZONS]].mean(axis=1)
    out["rs_composite"] = out[[f"rs_ret{h}" for h in HORIZONS]].mean(axis=1)
    out["advantage"] = out.ai_composite - out.rs_composite
    return out


def add_gate_features(events: pd.DataFrame, market: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    z = events.merge(market, on="date", how="left", validate="many_to_one")
    z["theme_disp_ratio"] = z.theme_disp20 / (z.theme_disp63.abs() + 1e-6)
    z["parent_theme_gap"] = z.parent_rs_pct - z.theme_rs_pct
    z["breadth_rank_interaction"] = z.theme_breadth * z.theme_rank_delta20 / 100.0
    market_cols = [c for c in market.columns if c != "date"]
    features = list(THEME_FEATURES) + ["theme_disp_ratio", "parent_theme_gap", "breadth_rank_interaction"] + market_cols
    return z, features


def fit_gate(train: pd.DataFrame, features: list[str], kind: str):
    X = train[features]
    y = train["advantage"]
    if kind == "RIDGE":
        model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))
    elif kind == "LGB_HUBER":
        model = lgb.LGBMRegressor(
            objective="huber", alpha=0.8, n_estimators=80, learning_rate=0.03,
            num_leaves=7, max_depth=3, min_child_samples=50,
            subsample=1.0, colsample_bytree=1.0, reg_alpha=0.2, reg_lambda=2.0,
            random_state=123, n_jobs=1, deterministic=True, force_col_wise=True, verbosity=-1,
        )
    else:
        raise ValueError(kind)
    model.fit(X, y)
    return model


def predict_gate(model, df: pd.DataFrame, features: list[str]) -> np.ndarray:
    return np.asarray(model.predict(df[features]), dtype=float)


def apply_gate(df: pd.DataFrame, pred: np.ndarray, method: str) -> pd.DataFrame:
    z = df.copy()
    z["pred_advantage"] = pred
    z["use_ai"] = z.pred_advantage > 0.0
    z["method"] = method
    for h in HORIZONS:
        z[f"ret_{h}"] = np.where(z.use_ai, z[f"ai_ret{h}"], z[f"rs_ret{h}"])
        z[f"diff_rs_{h}"] = z[f"ret_{h}"] - z[f"rs_ret{h}"]
    z["ret_composite"] = z[[f"ret_{h}" for h in HORIZONS]].mean(axis=1)
    z["diff_rs_composite"] = z.ret_composite - z.rs_composite
    return z


def internal_gate_selection(dev: pd.DataFrame, features: list[str]) -> tuple[str, dict, pd.DataFrame]:
    candidates = ("RIDGE", "LGB_HUBER")
    all_rows = []
    report = {}
    for kind in candidates:
        folds = []
        for year in (2020, 2021):
            test = dev[dev.date.dt.year == year].copy()
            if test.empty:
                continue
            first_pos = int(test.event_pos.min())
            train = dev[(dev.date < pd.Timestamp(f"{year}-01-01")) & ((dev.event_pos + 63) < first_pos)].copy()
            if len(train) < 200:
                continue
            model = fit_gate(train, features, kind)
            pred = predict_gate(model, test, features)
            fold = apply_gate(test, pred, f"{kind}_OOF")
            folds.append(fold)
        if folds:
            zz = pd.concat(folds, ignore_index=True)
            adv = float(zz.diff_rs_composite.mean())
            report[kind] = {
                "n": int(len(zz)),
                "ai_share": float(zz.use_ai.mean()),
                "mean_advantage_composite": adv,
                "by_year": {
                    str(y): {
                        "n": int(len(g)),
                        "ai_share": float(g.use_ai.mean()),
                        "mean_advantage_composite": float(g.diff_rs_composite.mean()),
                    } for y, g in zz.groupby(zz.date.dt.year)
                },
            }
            all_rows.append(zz)
        else:
            report[kind] = {"n": 0, "mean_advantage_composite": None}
    valid = [(k, v["mean_advantage_composite"]) for k, v in report.items()
             if v.get("mean_advantage_composite") is not None]
    best_kind, best_adv = max(valid, key=lambda x: x[1]) if valid else ("RS_ONLY", 0.0)
    if best_adv <= 0.0:
        best_kind = "RS_ONLY"
    return best_kind, report, pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()


def summary(s: pd.Series) -> dict:
    x = pd.to_numeric(s, errors="coerce").dropna()
    if x.empty:
        return {"n": 0}
    return {
        "n": int(len(x)), "mean": float(x.mean()), "median": float(x.median()),
        "p10": float(x.quantile(0.10)), "p90": float(x.quantile(0.90)),
        "positive_rate": float((x > 0).mean()),
    }


def bootstrap_ci(df: pd.DataFrame, metric: str, cluster: str, seed: int = 123, n_boot: int = 2000) -> dict:
    z = df[["date", "theme", "event_pos", metric]].dropna().copy()
    if z.empty:
        return {"n": 0}
    if cluster == "DATE":
        unit = z.groupby("date", observed=True)[metric].mean()
    elif cluster == "BLOCK20":
        z["block"] = (z.event_pos.astype(int) // 20).astype(int)
        unit = z.groupby("block", observed=True)[metric].mean()
    elif cluster == "THEME":
        unit = z.groupby("theme", observed=True)[metric].mean()
    else:
        unit = z[metric]
    arr = unit.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = rng.choice(arr, size=len(arr), replace=True).mean()
    return {
        "n_units": int(len(arr)),
        "point": float(z[metric].mean()),
        "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
    }


def result_block(z: pd.DataFrame) -> dict:
    out = {
        "n": int(len(z)),
        "ai_share": float(z.use_ai.mean()),
        "by_year": {},
        "metrics": {},
    }
    for h in HORIZONS:
        out["metrics"][str(h)] = {
            "gate_return": summary(z[f"ret_{h}"]),
            "vs_rs63": summary(z[f"diff_rs_{h}"]),
            "date_cluster": bootstrap_ci(z, f"diff_rs_{h}", "DATE", 100 + h),
            "block20_cluster": bootstrap_ci(z, f"diff_rs_{h}", "BLOCK20", 200 + h),
            "theme_cluster": bootstrap_ci(z, f"diff_rs_{h}", "THEME", 300 + h),
        }
    out["metrics"]["composite"] = {
        "gate_return": summary(z.ret_composite),
        "vs_rs63": summary(z.diff_rs_composite),
        "date_cluster": bootstrap_ci(z, "diff_rs_composite", "DATE", 401),
        "block20_cluster": bootstrap_ci(z, "diff_rs_composite", "BLOCK20", 402),
        "theme_cluster": bootstrap_ci(z, "diff_rs_composite", "THEME", 403),
    }
    for y, g in z.groupby(z.date.dt.year):
        out["by_year"][str(y)] = {
            "n": int(len(g)), "ai_share": float(g.use_ai.mean()),
            **{f"diff_rs_{h}": float(g[f"diff_rs_{h}"].mean()) for h in HORIZONS},
            "diff_rs_composite": float(g.diff_rs_composite.mean()),
        }
    return out


def gate_importance(model, features: list[str], kind: str) -> list[dict]:
    if kind == "LGB_HUBER":
        imp = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
        return [{"feature": str(k), "value": float(v)} for k, v in imp.head(25).items()]
    if kind == "RIDGE":
        ridge = model.named_steps["ridge"]
        imp = pd.Series(np.abs(ridge.coef_), index=features).sort_values(ascending=False)
        return [{"feature": str(k), "value": float(v)} for k, v in imp.head(25).items()]
    return []


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
    outdir = root / args.output
    outdir.mkdir(parents=True, exist_ok=True)

    rows, train, test, calendar, download_diag, taxonomy, purge_diag = stability.build_dataset(
        root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size, args.min_members
    )
    rows = rows.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    rows["date"] = pd.to_datetime(rows["date"])
    train = train.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    test = test.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    train["date"] = pd.to_datetime(train["date"])
    test["date"] = pd.to_datetime(test["date"])
    rows.to_csv(outdir / "frozen_event_stock_rows.csv.gz", index=False, compression="gzip")

    features = base.feature_cols(rows)
    oof_scores, oof_diag = build_oof_ai(rows, features)
    dev = expert_event_data(rows, oof_scores)

    market, market_diag = market_features(root, pd.DatetimeIndex(sorted(rows.date.unique())),
                                          args.analysis_start, args.analysis_end, args.batch_size)
    dev, gate_features = add_gate_features(dev, market)

    first_test_pos = int(test.event_pos.min())
    gate_dev = dev[(dev.event_pos + 63) < first_test_pos].copy()
    print("GATE_DEV", len(gate_dev), "through", gate_dev.date.max(), flush=True)

    selected_gate, internal_report, internal_rows = internal_gate_selection(gate_dev, gate_features)
    if not internal_rows.empty:
        internal_rows.to_csv(outdir / "gate_internal_oof.csv.gz", index=False, compression="gzip")
    print("SELECTED_GATE", selected_gate, internal_report, flush=True)

    final_iters = {name: stability.reference_iterations(train, features, label, calendar)
                   for name, label in LABELS.items()}
    final_ai = stable_ai_scores(train, test, features, final_iters)
    holdout = expert_event_data(rows, final_ai)
    holdout, _ = add_gate_features(holdout, market)

    if selected_gate == "RS_ONLY":
        pred = np.full(len(holdout), -1.0)
        gate_model = None
    else:
        gate_model = fit_gate(gate_dev, gate_features, selected_gate)
        pred = predict_gate(gate_model, holdout, gate_features)
    gated = apply_gate(holdout, pred, "AI_RS_GATE")

    rs189 = top_rows(test, "ret189")[["date", "theme", "symbol"] + [f"fwd_ret{h}" for h in HORIZONS]].copy()
    rs189 = rs189.rename(columns={"symbol": "rs189_symbol", **{f"fwd_ret{h}": f"rs189_ret{h}" for h in HORIZONS}})
    gated = gated.merge(rs189, on=["date", "theme"], how="left", validate="one_to_one")
    for h in HORIZONS:
        gated[f"diff_rs189_{h}"] = gated[f"ret_{h}"] - gated[f"rs189_ret{h}"]
    gated["rs189_composite"] = gated[[f"rs189_ret{h}" for h in HORIZONS]].mean(axis=1)
    gated["diff_rs189_composite"] = gated.ret_composite - gated.rs189_composite
    gated.to_csv(outdir / "gate_holdout_events.csv.gz", index=False, compression="gzip")

    rs189_summary = {
        str(h): {
            "point": summary(gated[f"diff_rs189_{h}"]),
            "date_cluster": bootstrap_ci(gated, f"diff_rs189_{h}", "DATE", 500 + h),
            "block20_cluster": bootstrap_ci(gated, f"diff_rs189_{h}", "BLOCK20", 600 + h),
            "theme_cluster": bootstrap_ci(gated, f"diff_rs189_{h}", "THEME", 700 + h),
        } for h in HORIZONS
    }
    rs189_summary["composite"] = {
        "point": summary(gated.diff_rs189_composite),
        "date_cluster": bootstrap_ci(gated, "diff_rs189_composite", "DATE", 801),
        "block20_cluster": bootstrap_ci(gated, "diff_rs189_composite", "BLOCK20", 802),
        "theme_cluster": bootstrap_ci(gated, "diff_rs189_composite", "THEME", 803),
    }

    result = {
        "status": "THEME_LTR_MIXTURE_OF_EXPERTS_GATE",
        "replicate": args.replicate,
        "warning": (
            "2022+ was inspected in preceding LTR research, so this is not a pristine untouched holdout. "
            "This gate specification was locked before this run; treat 2022+ as secondary confirmation, "
            "not a new discovery sample."
        ),
        "design": {
            "stock_experts": ["RS63_TOP1", "8-seed multi-target LambdaMART TOP1"],
            "gate_inputs": gate_features,
            "gate_target": "mean(AI-RS63 realized return across 20/40/63d)",
            "gate_candidates": ["RIDGE", "LGB_HUBER"],
            "selection_rule": "Walk-forward 2020/2021 within pre-2022 data; best combined composite advantage, else RS_ONLY if <=0.",
            "decision_rule": "Use AI only when predicted AI-RS63 composite advantage > 0.",
            "purge": "63 trading sessions for stock labels and final gate training.",
        },
        "download": download_diag,
        "market_download": market_diag,
        "taxonomy": taxonomy,
        "purge": purge_diag,
        "coverage": {
            "rows": int(len(rows)),
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "gate_dev_events": int(len(gate_dev)),
            "holdout_events": int(len(gated)),
        },
        "oof_ai": oof_diag,
        "final_iterations": final_iters,
        "internal_gate": internal_report,
        "selected_gate": selected_gate,
        "gate_importance": gate_importance(gate_model, gate_features, selected_gate) if gate_model is not None else [],
        "vs_rs63": result_block(gated),
        "vs_rs189": rs189_summary,
    }
    with open(outdir / "gate_summary.json", "w", encoding="utf-8") as f:
        json.dump(safe(result), f, ensure_ascii=False, indent=2)
    print(json.dumps(safe({
        "selected_gate": selected_gate,
        "coverage": result["coverage"],
        "internal_gate": internal_report,
        "vs_rs63_composite": result["vs_rs63"]["metrics"]["composite"],
        "vs_rs189_composite": result["vs_rs189"]["composite"],
    }), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
