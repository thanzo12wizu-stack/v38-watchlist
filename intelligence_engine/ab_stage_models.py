from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .ab_stage_data import ExperimentConfig, TRAIN_WINDOWS, num, series_num
from .research_prices import _normalize

SPEC_NAMES = {
    1: "RS189のみ", 2: "RS63＋126＋189", 3: "セクターRS＋個別RS",
    4: "個別ステージ＋RS", 5: "市場＋セクター＋個別ステージ＋RS",
    6: "Aランキングモデル", 7: "B先着確率モデル", 8: "A＋B",
    9: "A＋B＋ステージ", 10: "A＋B＋ステージ＋エントリー品質",
}
RS = ["pct_rs_raw_63", "pct_rs_raw_126", "pct_rs_raw_189"]
A_FEATURES = [
    *RS, "rs63_rank_change_21d", "rs126_rank_change_21d", "rs189_rank_change_21d",
    "rs126_top20_persistence_63d", "sector_rs63_mean", "sector_rs126_mean",
    "sector_rs189_mean", "sector_rs_rank", "industry_rs_rank", "adr_pct",
    "distance_52w_high_pct", "fundamental_quality", "fundamental_change",
    "leadership_quality", "research_confidence",
]
B_FEATURES = [
    *RS, "adr_pct", "volume_ratio_20d", "distance_52w_high_pct",
    "distance_pivot_pct", "stop_risk_pct", "reward_risk_raw", "extension_atr",
    "supply_risk_raw", "hard_block_numeric", "stop_fallback",
]


def safe_mean(values: Iterable[Any]) -> float | None:
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(values)) if values else None


def rank_pct(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(pct=True, method="average")


def numeric_matrix(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame({column: series_num(frame, column) for column in columns}, index=frame.index)


def safe_spearman(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(pair) < 5 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    value = spearmanr(pair["x"], pair["y"]).statistic
    return float(value) if value is not None and math.isfinite(float(value)) else None


def regressor(seed: int) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("model", HistGradientBoostingRegressor(
            max_iter=100, learning_rate=.05, max_leaf_nodes=31, min_samples_leaf=40,
            l2_regularization=1.0, random_state=seed,
        )),
    ])


def classifier(seed: int) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("model", HistGradientBoostingClassifier(
            max_iter=100, learning_rate=.05, max_leaf_nodes=31, min_samples_leaf=40,
            l2_regularization=1.0, random_state=seed,
        )),
    ])


def fit_predict_regression(train: pd.DataFrame, test: pd.DataFrame, seed: int):
    y = pd.to_numeric(train["target_rank_10"], errors="coerce")
    valid = y.notna()
    if valid.sum() < 100:
        raise RuntimeError("insufficient A-model training rows")
    model = regressor(seed)
    x_train, x_test = numeric_matrix(train, A_FEATURES), numeric_matrix(test, A_FEATURES)
    model.fit(x_train.loc[valid], y.loc[valid])
    return model.predict(x_train), model.predict(x_test)


def fit_predict_classifier(train: pd.DataFrame, test: pd.DataFrame, seed: int):
    y = pd.to_numeric(train["hit_3r_before_1r_15"], errors="coerce")
    valid = y.notna()
    if valid.sum() < 100 or y.loc[valid].nunique() < 2:
        raise RuntimeError("insufficient B-model training rows")
    model = classifier(seed)
    x_train, x_test = numeric_matrix(train, B_FEATURES), numeric_matrix(test, B_FEATURES)
    model.fit(x_train.loc[valid], y.loc[valid].astype(int))
    return model.predict_proba(x_train)[:, 1], model.predict_proba(x_test)[:, 1]


def expanding_oof(train: pd.DataFrame, task: str, seed: int) -> pd.Series:
    years = sorted(pd.to_datetime(train["date"]).dt.year.unique())
    result = pd.Series(np.nan, index=train.index, dtype=float)
    for index in range(1, len(years)):
        fit = train[pd.to_datetime(train["date"]).dt.year.isin(years[:index])]
        validation = train[pd.to_datetime(train["date"]).dt.year == years[index]]
        if fit.empty or validation.empty:
            continue
        try:
            _, prediction = (fit_predict_regression(fit, validation, seed + index)
                             if task == "A" else fit_predict_classifier(fit, validation, seed + index))
        except RuntimeError:
            if task == "A":
                prediction = series_num(validation, "pct_rs_raw_189").fillna(50).to_numpy() / 100
            else:
                prediction = np.repeat(series_num(fit, "hit_3r_before_1r_15").mean(), len(validation))
        result.loc[validation.index] = prediction
    return result


def baseline_scores(frame: pd.DataFrame) -> dict[int, pd.Series]:
    rs189 = series_num(frame, "pct_rs_raw_189") / 100
    rs = (series_num(frame, "pct_rs_raw_63") * .2 + series_num(frame, "pct_rs_raw_126") * .3 + series_num(frame, "pct_rs_raw_189") * .5) / 100
    group_rs = (series_num(frame, "sector_rs_rank") * .65 + series_num(frame, "industry_rs_rank") * .35) / 100
    individual = (series_num(frame, "individual_stage_numeric") + 4) / 7
    sector_stage = series_num(frame, "sector_stage_score") / 100
    market = (series_num(frame, "market_stage_numeric") + 4) / 7
    return {
        1: rs189, 2: rs, 3: rs * .7 + group_rs * .3,
        4: rs * .7 + individual * .3,
        5: rs * .45 + individual * .2 + group_rs * .15 + sector_stage * .1 + market * .1,
    }


def stage_score(frame: pd.DataFrame) -> pd.Series:
    individual = (series_num(frame, "individual_stage_numeric") + 4) / 7
    sector = series_num(frame, "sector_stage_score") / 100
    market = (series_num(frame, "market_stage_numeric") + 4) / 7
    return individual * .45 + sector * .30 + market * .25


def entry_score(frame: pd.DataFrame) -> pd.Series:
    parts = [
        series_num(frame, "entry_quality") / 100, series_num(frame, "risk_fit") / 100,
        series_num(frame, "base_composite") / 100, rank_pct(series_num(frame, "reward_risk_raw")),
        1 - rank_pct(series_num(frame, "extension_atr").abs()),
        1 - rank_pct(series_num(frame, "supply_risk_raw")),
    ]
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True)


def calibrate(train_score: pd.Series, train_target: pd.Series, test_score: pd.Series) -> np.ndarray:
    x, y = pd.to_numeric(train_score, errors="coerce"), pd.to_numeric(train_target, errors="coerce")
    valid = x.notna() & y.notna()
    if valid.sum() < 100 or y.loc[valid].nunique() < 2:
        return np.repeat(float(y.loc[valid].mean()) if valid.any() else .5, len(test_score))
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", LogisticRegression(max_iter=500, C=.5))])
    model.fit(x.loc[valid].to_numpy().reshape(-1, 1), y.loc[valid].astype(int))
    return model.predict_proba(pd.to_numeric(test_score, errors="coerce").to_numpy().reshape(-1, 1))[:, 1]


def build_predictions(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> dict[int, pd.DataFrame]:
    train, test = train.copy(), test.copy()
    train["target_rank_10"] = train.groupby("date")["excess_10"].rank(pct=True)
    test["target_rank_10"] = test.groupby("date")["excess_10"].rank(pct=True)
    predictions = {}
    train_base, test_base = baseline_scores(train), baseline_scores(test)
    for spec in range(1, 6):
        predictions[spec] = pd.DataFrame({
            "score": test_base[spec],
            "probability": calibrate(train_base[spec], train["hit_3r_before_1r_15"], test_base[spec]),
        }, index=test.index)
    a_oof, b_oof = expanding_oof(train, "A", seed), expanding_oof(train, "B", seed + 100)
    _, a_test = fit_predict_regression(train, test, seed + 200)
    _, b_test = fit_predict_classifier(train, test, seed + 300)
    a_test, b_test = pd.Series(a_test, index=test.index), pd.Series(b_test, index=test.index)
    predictions[6] = pd.DataFrame({"score": a_test, "probability": calibrate(a_oof, train["hit_3r_before_1r_15"], a_test)}, index=test.index)
    predictions[7] = pd.DataFrame({"score": b_test, "probability": b_test.clip(0, 1)}, index=test.index)
    train_date, test_date = pd.to_datetime(train["date"]).dt.normalize(), pd.to_datetime(test["date"]).dt.normalize()
    train8 = a_oof.groupby(train_date).rank(pct=True) * .6 + b_oof.groupby(train_date).rank(pct=True) * .4
    test8 = a_test.groupby(test_date).rank(pct=True) * .6 + b_test.groupby(test_date).rank(pct=True) * .4
    train9, test9 = train8 * .8 + stage_score(train) * .2, test8 * .8 + stage_score(test) * .2
    train10, test10 = train9 * .85 + entry_score(train) * .15, test9 * .85 + entry_score(test) * .15
    for spec, train_score, test_score in ((8, train8, test8), (9, train9, test9), (10, train10, test10)):
        predictions[spec] = pd.DataFrame({
            "score": test_score,
            "probability": calibrate(train_score, train["hit_3r_before_1r_15"], test_score),
        }, index=test.index)
    return predictions


def top_decile(frame: pd.DataFrame, score: pd.Series) -> pd.Series:
    return score.groupby(pd.to_datetime(frame["date"]).dt.normalize()).rank(pct=True) >= .90


def simulate_portfolio(frame: pd.DataFrame, score: pd.Series, config: ExperimentConfig) -> dict[str, Any]:
    work = frame.copy(); work["score"] = pd.to_numeric(score, errors="coerce")
    work["date"] = pd.to_datetime(work["date"]).dt.normalize()
    work["trade_exit_date"] = pd.to_datetime(work["trade_exit_date"]).dt.normalize()
    work = work[top_decile(work, work["score"])].dropna(subset=["trade_exit_date", "trade_return_gross", "score"])
    work = work.sort_values(["date", "score", "ticker"], ascending=[True, False, True])
    active, daily_pnl, trades = [], {}, []
    for date, candidates in work.groupby("date", sort=True):
        remaining = []
        for position in active:
            if position["exit"] <= date:
                daily_pnl[position["exit"]] = daily_pnl.get(position["exit"], 0) + position["pnl"]
            else:
                remaining.append(position)
        active = remaining
        held, slots = {position["ticker"] for position in active}, max(0, config.max_positions - len(active))
        for _, row in candidates.iterrows():
            ticker = str(row["ticker"])
            if ticker in held or slots <= 0:
                continue
            risk = num(row.get("risk_fraction"))
            weight = min(config.max_position_weight, config.risk_per_trade / risk) if np.isfinite(risk) and risk > 0 else config.max_position_weight
            net = num(row.get("trade_return_gross"), 0) - config.roundtrip_cost
            position = {"ticker": ticker, "exit": row["trade_exit_date"], "pnl": weight * net}
            active.append(position); held.add(ticker); trades.append(position); slots -= 1
    for position in active:
        daily_pnl[position["exit"]] = daily_pnl.get(position["exit"], 0) + position["pnl"]
    equity = peak = 1.0; max_dd = 0.0
    for date in sorted(daily_pnl):
        equity *= max(0, 1 + daily_pnl[date]); peak = max(peak, equity); max_dd = min(max_dd, equity / peak - 1)
    gains = sum(max(0, trade["pnl"]) for trade in trades)
    losses = abs(sum(min(0, trade["pnl"]) for trade in trades))
    pf = gains / losses if losses else (float("inf") if gains else np.nan)
    return {"trade_count": len(trades), "portfolio_return": equity - 1, "profit_factor": pf, "max_drawdown": max_dd}


def evaluate(frame: pd.DataFrame, prediction: pd.DataFrame, config: ExperimentConfig) -> dict[str, Any]:
    score = pd.to_numeric(prediction["score"], errors="coerce")
    probability = pd.to_numeric(prediction["probability"], errors="coerce").clip(0, 1)
    ic = [safe_spearman(group["_score"], group["excess_10"]) for _, group in frame.assign(_score=score).groupby("date")]
    ic = [value for value in ic if value is not None]
    selected = frame[top_decile(frame, score)]
    pair = pd.DataFrame({"p": probability, "y": series_num(frame, "hit_3r_before_1r_15")}).dropna()
    return {
        "daily_spearman_ic": safe_mean(ic), "ic_days": len(ic),
        "top10_excess_return": safe_mean(series_num(selected, "excess_10").dropna()),
        "top10_hit_3r_rate": safe_mean(series_num(selected, "hit_3r_before_1r_15").dropna()),
        "top10_early_failure_rate": safe_mean(series_num(selected, "early_failure_5").dropna()),
        "brier_score": float(np.mean((pair["p"] - pair["y"]) ** 2)) if not pair.empty else np.nan,
        "candidate_rows": len(frame), "top10_rows": len(selected),
        **simulate_portfolio(frame, score, config),
    }


def qqq_return(prices: Mapping[str, pd.DataFrame], year: int) -> float | None:
    qqq = _normalize(prices["QQQ"]); selected = qqq[qqq.index.year == year]
    if selected.empty:
        return None
    first, last = num(selected.iloc[0].get("open")), num(selected.iloc[-1].get("close"))
    return last / first - 1 if np.isfinite(first) and first > 0 and np.isfinite(last) else None


def run_walk_forward(dataset: pd.DataFrame, prices: Mapping[str, pd.DataFrame], config: ExperimentConfig):
    data = dataset.copy(); data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["label_end_date"] = pd.to_datetime(data["label_end_date"]).dt.normalize()
    rows, folds = [], []
    for fold_index, (train_start, train_end, test_year) in enumerate(TRAIN_WINDOWS, start=1):
        test_start = pd.Timestamp(test_year, 1, 1)
        train = data[data["date"].dt.year.between(train_start, train_end) & (data["label_end_date"] < test_start)]
        test = data[data["date"].dt.year == test_year]
        if train.empty or test.empty:
            folds.append({"test_year": test_year, "status": "SKIPPED_EMPTY", "train_rows": len(train), "test_rows": len(test)})
            continue
        predictions, benchmark = build_predictions(train, test, config.seed + fold_index * 1000), qqq_return(prices, test_year)
        for spec, prediction in predictions.items():
            metrics = evaluate(test, prediction, config)
            rows.append({
                "spec": spec, "spec_name": SPEC_NAMES[spec], "train_start": train_start,
                "train_end": train_end, "test_year": test_year, "train_rows": len(train),
                "test_rows": len(test), "qqq_return": benchmark,
                "beats_qqq": bool(benchmark is not None and metrics["portfolio_return"] > benchmark), **metrics,
            })
        folds.append({"test_year": test_year, "status": "PASS", "train_rows": len(train), "test_rows": len(test)})
    return pd.DataFrame(rows), {"folds": folds}


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec, group in results.groupby("spec", sort=True):
        returns, qqq = pd.to_numeric(group["portfolio_return"], errors="coerce"), pd.to_numeric(group["qqq_return"], errors="coerce")
        pf_values = [min(value, 20) for value in pd.to_numeric(group["profit_factor"], errors="coerce") if np.isfinite(value)]
        rows.append({
            "spec": int(spec), "spec_name": SPEC_NAMES[int(spec)], "folds": len(group),
            "mean_daily_spearman_ic": safe_mean(group["daily_spearman_ic"]),
            "median_daily_spearman_ic": pd.to_numeric(group["daily_spearman_ic"], errors="coerce").median(),
            "mean_top10_excess_return": safe_mean(group["top10_excess_return"]),
            "mean_hit_3r_rate": safe_mean(group["top10_hit_3r_rate"]),
            "mean_early_failure_rate": safe_mean(group["top10_early_failure_rate"]),
            "mean_brier_score": safe_mean(group["brier_score"]), "mean_profit_factor": safe_mean(pf_values),
            "worst_max_drawdown": pd.to_numeric(group["max_drawdown"], errors="coerce").min(),
            "mean_portfolio_return": safe_mean(returns), "median_portfolio_return": returns.median(),
            "worst_portfolio_return": returns.min(), "positive_years": int((returns > 0).sum()),
            "qqq_excess_years": int((returns > qqq).sum()), "yearly_return_std": returns.std(ddof=0),
            "total_trades": int(pd.to_numeric(group["trade_count"], errors="coerce").sum()),
        })
    return pd.DataFrame(rows).sort_values("spec").reset_index(drop=True)


def incremental_verdicts(summary: pd.DataFrame) -> list[dict[str, Any]]:
    lookup = {int(row["spec"]): row for _, row in summary.iterrows()}
    pairs = ((4, 3, "個別ステージ"), (5, 4, "市場・セクターステージ"), (9, 8, "A+Bへのステージ追加"), (10, 9, "エントリー品質追加"))
    checks = (
        ("mean_top10_excess_return", .001, 1, "上位10%超過収益"),
        ("mean_hit_3r_rate", .01, 1, "+3R先着率"),
        ("mean_early_failure_rate", .01, -1, "Early Failure率"),
        ("mean_brier_score", .005, -1, "Brier Score"),
        ("mean_profit_factor", .10, 1, "PF"), ("worst_max_drawdown", .01, 1, "最大DD"),
    )
    output = []
    for new_spec, old_spec, label in pairs:
        if new_spec not in lookup or old_spec not in lookup:
            continue
        reasons = []
        for column, threshold, direction, name in checks:
            new, old = num(lookup[new_spec].get(column)), num(lookup[old_spec].get(column))
            if np.isfinite(new) and np.isfinite(old) and (new - old) * direction >= threshold:
                reasons.append(name)
        output.append({
            "increment": label, "from_spec": old_spec, "to_spec": new_spec,
            "verdict": "ADOPT" if reasons else "REJECT", "material_improvements": reasons,
            "trade_count_change": int(lookup[new_spec].get("total_trades") or 0) - int(lookup[old_spec].get("total_trades") or 0),
            "note": "取引数減少だけでは採用しない固定ルール",
        })
    return output
