from __future__ import annotations

import math
from dataclasses import dataclass
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

POLICY_VERSION = "2.0.0"
SPEC_NAMES = {
    11: "Aランキング・3R/1R出口",
    12: "Aランキング・10日固定出口",
    13: "B2経路期待値・3R/1R出口",
    14: "A＋B2・3R/1R出口",
    15: "A＋B2・10日固定出口",
    16: "Aステージ交互作用・10日固定出口",
    17: "Aステージ交互作用＋B2・3R/1R出口",
    18: "A＋B2・ステージ別ロット",
    19: "Aステージ交互作用＋B2・ステージ別ロット",
}
PORTFOLIO_MODE = {
    11: "PATH",
    12: "FIXED10",
    13: "PATH",
    14: "PATH",
    15: "FIXED10",
    16: "FIXED10",
    17: "PATH",
    18: "PATH",
    19: "PATH",
}
STAGE_SIZING_SPECS = {18, 19}

RS = ["pct_rs_raw_63", "pct_rs_raw_126", "pct_rs_raw_189"]
A_FEATURES = [
    *RS,
    "rs63_rank_change_21d",
    "rs126_rank_change_21d",
    "rs189_rank_change_21d",
    "rs126_top20_persistence_63d",
    "sector_rs63_mean",
    "sector_rs126_mean",
    "sector_rs189_mean",
    "sector_rs_rank",
    "industry_rs_rank",
    "adr_pct",
    "distance_52w_high_pct",
    "fundamental_quality",
    "fundamental_change",
    "leadership_quality",
    "research_confidence",
]
B_FEATURES = [
    *RS,
    "adr_pct",
    "volume_ratio_20d",
    "distance_52w_high_pct",
    "distance_pivot_pct",
    "stop_risk_pct",
    "reward_risk_raw",
    "extension_atr",
    "supply_risk_raw",
    "hard_block_numeric",
    "stop_fallback",
]
STAGE_FEATURES = [
    "individual_stage_numeric",
    "individual_stage_days",
    "individual_stage_change",
    "individual_stage_upgrade",
    "individual_stage_downgrade",
    "sector_stage_score",
    "sector_stage_change_21d",
    "market_stage_numeric",
    "market_stage_days",
    "market_stage_change",
    "market_stage_upgrade",
    "market_stage_downgrade",
    "market_stage2_share",
    "market_bear_share",
]


def safe_mean(values: Iterable[Any]) -> float | None:
    output = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return float(np.mean(output)) if output else None


def safe_spearman(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.DataFrame(
        {
            "x": pd.to_numeric(x, errors="coerce"),
            "y": pd.to_numeric(y, errors="coerce"),
        }
    ).dropna()
    if len(pair) < 5 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    value = spearmanr(pair["x"], pair["y"]).statistic
    return float(value) if value is not None and math.isfinite(float(value)) else None


def numeric_matrix(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    stage_interactions: bool = False,
) -> pd.DataFrame:
    output = pd.DataFrame(
        {column: series_num(frame, column) for column in columns},
        index=frame.index,
    )
    if not stage_interactions:
        return output
    rs = (
        series_num(frame, "pct_rs_raw_63") * 0.2
        + series_num(frame, "pct_rs_raw_126") * 0.3
        + series_num(frame, "pct_rs_raw_189") * 0.5
    ) / 100.0
    individual = series_num(frame, "individual_stage_numeric")
    sector = series_num(frame, "sector_stage_score") / 100.0
    market = series_num(frame, "market_stage_numeric")
    output["stage_x_rs_individual"] = rs * individual
    output["stage_x_rs_sector"] = rs * sector
    output["stage_x_rs_market"] = rs * market
    output["stage_x_extension"] = individual * series_num(frame, "extension_atr")
    output["stage_days_log"] = np.log1p(
        series_num(frame, "individual_stage_days").clip(lower=0)
    )
    return output


def regressor(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            (
                "model",
                HistGradientBoostingRegressor(
                    max_iter=100,
                    learning_rate=0.05,
                    max_leaf_nodes=31,
                    min_samples_leaf=40,
                    l2_regularization=1.0,
                    random_state=seed,
                ),
            ),
        ]
    )


def classifier(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            (
                "model",
                HistGradientBoostingClassifier(
                    max_iter=100,
                    learning_rate=0.05,
                    max_leaf_nodes=31,
                    min_samples_leaf=40,
                    l2_regularization=1.0,
                    random_state=seed,
                ),
            ),
        ]
    )


def fit_a(
    train: pd.DataFrame,
    test: pd.DataFrame,
    seed: int,
    *,
    stage_interactions: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    y = pd.to_numeric(train["target_rank_10"], errors="coerce")
    valid = y.notna()
    if valid.sum() < 100:
        raise RuntimeError("insufficient A training rows")
    columns = A_FEATURES + (STAGE_FEATURES if stage_interactions else [])
    x_train = numeric_matrix(train, columns, stage_interactions=stage_interactions)
    x_test = numeric_matrix(test, columns, stage_interactions=stage_interactions)
    model = regressor(seed)
    model.fit(x_train.loc[valid], y.loc[valid])
    return model.predict(x_train), model.predict(x_test)


def competing_target(frame: pd.DataFrame) -> pd.Series:
    upper = series_num(frame, "hit_3r_before_1r_15").fillna(0).astype(int)
    lower = series_num(frame, "stop_before_3r_15").fillna(0).astype(int)
    result = pd.Series(1, index=frame.index, dtype=int)
    result.loc[lower.eq(1)] = 0
    result.loc[upper.eq(1)] = 2
    return result


def fit_b2(
    train: pd.DataFrame,
    test: pd.DataFrame,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    x_train = numeric_matrix(train, B_FEATURES)
    x_test = numeric_matrix(test, B_FEATURES)
    y_path = competing_target(train)
    if len(y_path) < 100 or y_path.nunique() < 3:
        raise RuntimeError("insufficient B2 competing-risk rows")
    path_model = classifier(seed)
    path_model.fit(x_train, y_path)
    train_path = path_model.predict_proba(x_train)
    test_path = path_model.predict_proba(x_test)
    class_index = {
        int(value): index
        for index, value in enumerate(path_model.named_steps["model"].classes_)
    }

    y_early = series_num(train, "early_failure_5")
    valid_early = y_early.notna()
    if valid_early.sum() < 100 or y_early.loc[valid_early].nunique() < 2:
        raise RuntimeError("insufficient B2 early-failure rows")
    early_model = classifier(seed + 1)
    early_model.fit(x_train.loc[valid_early], y_early.loc[valid_early].astype(int))
    train_early = early_model.predict_proba(x_train)[:, 1]
    test_early = early_model.predict_proba(x_test)[:, 1]

    neither = series_num(train, "neither_3r_nor_1r_15").eq(1)
    risk = series_num(train, "risk_fraction").replace(0, np.nan)
    payoff_r = (
        series_num(train, "trade_return_gross") / risk
    ).where(neither).replace([np.inf, -np.inf], np.nan)
    none_payoff_r = (
        float(payoff_r.clip(-1, 3).median()) if payoff_r.notna().any() else 0.0
    )
    if not math.isfinite(none_payoff_r):
        none_payoff_r = 0.0

    def make(
        path_prob: np.ndarray,
        early_prob: np.ndarray,
        index: pd.Index,
    ) -> pd.DataFrame:
        p_lower = path_prob[:, class_index[0]]
        p_none = path_prob[:, class_index[1]]
        p_upper = path_prob[:, class_index[2]]
        score = 3.0 * p_upper - p_lower + none_payoff_r * p_none - 0.5 * early_prob
        return pd.DataFrame(
            {
                "score": score,
                "p_upper": p_upper,
                "p_lower": p_lower,
                "p_none": p_none,
                "p_early": early_prob,
                "none_payoff_r": none_payoff_r,
            },
            index=index,
        )

    return make(train_path, train_early, train.index), make(
        test_path, test_early, test.index
    )


def expanding_oof_a(
    train: pd.DataFrame,
    seed: int,
    *,
    stage_interactions: bool = False,
) -> pd.Series:
    years = sorted(pd.to_datetime(train["date"]).dt.year.unique())
    output = pd.Series(np.nan, index=train.index, dtype=float)
    for position in range(1, len(years)):
        fit = train[pd.to_datetime(train["date"]).dt.year.isin(years[:position])]
        validation = train[pd.to_datetime(train["date"]).dt.year.eq(years[position])]
        if fit.empty or validation.empty:
            continue
        try:
            _, prediction = fit_a(
                fit,
                validation,
                seed + position,
                stage_interactions=stage_interactions,
            )
        except RuntimeError:
            prediction = (
                series_num(validation, "pct_rs_raw_189").fillna(50).to_numpy()
                / 100.0
            )
        output.loc[validation.index] = prediction
    return output


def expanding_oof_b2(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    years = sorted(pd.to_datetime(train["date"]).dt.year.unique())
    columns = [
        "score",
        "p_upper",
        "p_lower",
        "p_none",
        "p_early",
        "none_payoff_r",
    ]
    output = pd.DataFrame(np.nan, index=train.index, columns=columns)
    for position in range(1, len(years)):
        fit = train[pd.to_datetime(train["date"]).dt.year.isin(years[:position])]
        validation = train[pd.to_datetime(train["date"]).dt.year.eq(years[position])]
        if fit.empty or validation.empty:
            continue
        try:
            _, prediction = fit_b2(fit, validation, seed + position * 10)
        except RuntimeError:
            upper = float(series_num(fit, "hit_3r_before_1r_15").mean())
            early = float(series_num(fit, "early_failure_5").mean())
            lower = float(series_num(fit, "stop_before_3r_15").mean())
            none = max(0.0, 1.0 - upper - lower)
            prediction = pd.DataFrame(
                {
                    "score": np.repeat(3 * upper - lower - 0.5 * early, len(validation)),
                    "p_upper": upper,
                    "p_lower": lower,
                    "p_none": none,
                    "p_early": early,
                    "none_payoff_r": 0.0,
                },
                index=validation.index,
            )
        output.loc[validation.index, columns] = prediction[columns]
    return output


def calibrate(
    train_score: pd.Series,
    train_target: pd.Series,
    test_score: pd.Series,
) -> np.ndarray:
    x = pd.to_numeric(train_score, errors="coerce")
    y = pd.to_numeric(train_target, errors="coerce")
    valid = x.notna() & y.notna()
    if valid.sum() < 100 or y.loc[valid].nunique() < 2:
        base = float(y.loc[valid].mean()) if valid.any() else 0.5
        return np.repeat(base, len(test_score))
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("model", LogisticRegression(max_iter=500, C=0.5)),
        ]
    )
    model.fit(x.loc[valid].to_numpy().reshape(-1, 1), y.loc[valid].astype(int))
    values = pd.to_numeric(test_score, errors="coerce").to_numpy().reshape(-1, 1)
    return model.predict_proba(values)[:, 1]


def daily_rank(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(frame["date"]).dt.normalize()
    return pd.to_numeric(values, errors="coerce").groupby(dates).rank(pct=True)


def build_predictions(
    train: pd.DataFrame,
    test: pd.DataFrame,
    seed: int,
) -> dict[int, pd.DataFrame]:
    train = train.copy()
    test = test.copy()
    train["target_rank_10"] = train.groupby("date")["excess_10"].rank(pct=True)
    test["target_rank_10"] = test.groupby("date")["excess_10"].rank(pct=True)

    a_oof = expanding_oof_a(train, seed)
    a_stage_oof = expanding_oof_a(train, seed + 100, stage_interactions=True)
    _, a_test_values = fit_a(train, test, seed + 200)
    _, a_stage_test_values = fit_a(
        train, test, seed + 300, stage_interactions=True
    )
    a_test = pd.Series(a_test_values, index=test.index)
    a_stage_test = pd.Series(a_stage_test_values, index=test.index)

    b2_oof = expanding_oof_b2(train, seed + 400)
    _, b2_test = fit_b2(train, test, seed + 500)

    train_ab2 = daily_rank(train, a_oof) * 0.70 + daily_rank(
        train, b2_oof["score"]
    ) * 0.30
    test_ab2 = daily_rank(test, a_test) * 0.70 + daily_rank(
        test, b2_test["score"]
    ) * 0.30
    train_stage_ab2 = daily_rank(train, a_stage_oof) * 0.70 + daily_rank(
        train, b2_oof["score"]
    ) * 0.30
    test_stage_ab2 = daily_rank(test, a_stage_test) * 0.70 + daily_rank(
        test, b2_test["score"]
    ) * 0.30

    target = train["hit_3r_before_1r_15"]
    base_probability = float(pd.to_numeric(target, errors="coerce").mean())
    predictions: dict[int, pd.DataFrame] = {}

    def pack(
        score: pd.Series,
        probability: np.ndarray | pd.Series,
        **extra: Any,
    ) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "score": pd.to_numeric(score, errors="coerce"),
                "probability": np.asarray(probability, dtype=float),
                "baseline_probability": base_probability,
            },
            index=test.index,
        )
        for key, value in extra.items():
            out[key] = value
        return out

    a_probability = calibrate(a_oof, target, a_test)
    a_stage_probability = calibrate(a_stage_oof, target, a_stage_test)
    ab2_probability = calibrate(train_ab2, target, test_ab2)
    stage_ab2_probability = calibrate(train_stage_ab2, target, test_stage_ab2)

    predictions[11] = pack(a_test, a_probability)
    predictions[12] = pack(a_test, a_probability)
    predictions[13] = pack(
        b2_test["score"],
        b2_test["p_upper"],
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    predictions[14] = pack(
        test_ab2,
        ab2_probability,
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    predictions[15] = pack(
        test_ab2,
        ab2_probability,
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    predictions[16] = pack(a_stage_test, a_stage_probability)
    predictions[17] = pack(
        test_stage_ab2,
        stage_ab2_probability,
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    predictions[18] = pack(
        test_ab2,
        ab2_probability,
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    predictions[19] = pack(
        test_stage_ab2,
        stage_ab2_probability,
        p_early=b2_test["p_early"],
        p_none=b2_test["p_none"],
    )
    return predictions


def top_decile(frame: pd.DataFrame, score: pd.Series) -> pd.Series:
    dates = pd.to_datetime(frame["date"]).dt.normalize()
    return pd.to_numeric(score, errors="coerce").groupby(dates).rank(pct=True) >= 0.90


def stage_weight_multiplier(row: pd.Series) -> float:
    individual_map = {
        "2A": 1.00,
        "2B": 1.00,
        "1A": 0.75,
        "1B": 0.75,
        "2C": 0.50,
        "3A": 0.50,
        "3B": 0.25,
        "4A": 0.0,
        "4B": 0.0,
        "4C": 0.0,
        "NA": 0.50,
    }
    market_map = {
        "2A": 1.00,
        "2B": 1.00,
        "1A": 0.80,
        "1B": 0.80,
        "2C": 0.75,
        "3A": 0.60,
        "3B": 0.40,
        "4A": 0.25,
        "4B": 0.25,
        "4C": 0.25,
        "NA": 0.50,
    }
    individual = individual_map.get(
        str(row.get("individual_stage") or "NA"), 0.50
    )
    market = market_map.get(str(row.get("market_stage") or "NA"), 0.50)
    sector = 0.50 + 0.50 * np.clip(
        num(row.get("sector_stage_score"), 50.0) / 100.0, 0, 1
    )
    return float(np.clip(individual * market * sector, 0, 1))


@dataclass
class Position:
    ticker: str
    shares: float
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    exit_price: float
    allocated: float
    net_return: float


def _price_value(
    cache: dict[str, pd.DataFrame],
    prices: Mapping[str, pd.DataFrame],
    ticker: str,
    date: pd.Timestamp,
    column: str,
    fallback: float,
) -> float:
    if ticker not in cache:
        raw = prices.get(ticker)
        cache[ticker] = _normalize(raw) if raw is not None else pd.DataFrame()
    frame = cache[ticker]
    if frame.empty or column not in frame or date not in frame.index:
        return fallback
    return num(frame.at[date, column], fallback)


def simulate_portfolio_mtm(
    frame: pd.DataFrame,
    score: pd.Series,
    prices: Mapping[str, pd.DataFrame],
    config: ExperimentConfig,
    *,
    mode: str,
    stage_sizing: bool,
) -> dict[str, Any]:
    work = frame.copy()
    work["score"] = pd.to_numeric(score, errors="coerce")
    work["date"] = pd.to_datetime(work["date"]).dt.normalize()
    work["entry_date"] = pd.to_datetime(work["entry_date"]).dt.normalize()
    if mode == "FIXED10":
        work["_exit_date"] = pd.to_datetime(work["outcome_date_10"]).dt.normalize()
        work["_gross_return"] = series_num(work, "return_10")
    else:
        work["_exit_date"] = pd.to_datetime(work["trade_exit_date"]).dt.normalize()
        work["_gross_return"] = series_num(work, "trade_return_gross")
    work = work[top_decile(work, work["score"])].dropna(
        subset=[
            "entry_date",
            "_exit_date",
            "_gross_return",
            "entry_price",
            "score",
        ]
    )
    work = work.sort_values(
        ["entry_date", "score", "ticker"],
        ascending=[True, False, True],
    )
    if work.empty:
        return {
            "trade_count": 0,
            "portfolio_return": 0.0,
            "profit_factor": np.nan,
            "max_drawdown": 0.0,
            "qqq_aligned_return": np.nan,
            "portfolio_start": None,
            "portfolio_end": None,
        }

    candidate_map = {
        date: group for date, group in work.groupby("entry_date", sort=True)
    }
    first_date = pd.Timestamp(work["entry_date"].min())
    last_date = pd.Timestamp(work["_exit_date"].max())
    qqq = _normalize(prices.get("QQQ"))
    sessions = qqq.index[(qqq.index >= first_date) & (qqq.index <= last_date)]
    if len(sessions) == 0:
        raise RuntimeError("no QQQ sessions for portfolio simulation")

    cash = 1.0
    active: list[Position] = []
    cache: dict[str, pd.DataFrame] = {}
    trade_pnls: list[float] = []
    equity_series: list[tuple[pd.Timestamp, float]] = []
    prior_close: dict[str, float] = {}

    for date in sessions:
        date = pd.Timestamp(date).normalize()
        held = {position.ticker for position in active}
        slots = max(0, config.max_positions - len(active))
        equity_open = cash
        for position in active:
            reference = prior_close.get(
                position.ticker,
                position.exit_price / max(1 + position.net_return, 0.01),
            )
            open_value = _price_value(
                cache, prices, position.ticker, date, "open", reference
            )
            equity_open += position.shares * open_value

        candidates = candidate_map.get(date)
        if candidates is not None and slots > 0:
            for _, row in candidates.iterrows():
                ticker = str(row["ticker"]).upper()
                if ticker in held or slots <= 0:
                    continue
                risk = num(row.get("risk_fraction"))
                base_weight = (
                    min(config.max_position_weight, config.risk_per_trade / risk)
                    if np.isfinite(risk) and risk > 0
                    else config.max_position_weight
                )
                multiplier = stage_weight_multiplier(row) if stage_sizing else 1.0
                weight = base_weight * multiplier
                if weight <= 0:
                    continue
                entry_price = num(row.get("entry_price"))
                gross = num(row.get("_gross_return"))
                if (
                    not np.isfinite(entry_price)
                    or entry_price <= 0
                    or not np.isfinite(gross)
                ):
                    continue
                net_return = gross - config.roundtrip_cost
                desired = equity_open * weight
                allocated = min(cash, desired)
                if allocated <= 0:
                    continue
                shares = allocated / entry_price
                cash -= allocated
                position = Position(
                    ticker=ticker,
                    shares=shares,
                    entry_date=date,
                    exit_date=pd.Timestamp(row["_exit_date"]).normalize(),
                    exit_price=entry_price * (1 + net_return),
                    allocated=allocated,
                    net_return=net_return,
                )
                active.append(position)
                held.add(ticker)
                slots -= 1

        remaining: list[Position] = []
        for position in active:
            if position.exit_date <= date:
                proceeds = max(0.0, position.shares * position.exit_price)
                cash += proceeds
                trade_pnls.append(position.allocated * position.net_return)
            else:
                remaining.append(position)
        active = remaining

        equity_close = cash
        for position in active:
            reference = prior_close.get(
                position.ticker,
                position.exit_price / max(1 + position.net_return, 0.01),
            )
            close_value = _price_value(
                cache, prices, position.ticker, date, "close", reference
            )
            prior_close[position.ticker] = close_value
            equity_close += position.shares * close_value
        equity_series.append((date, equity_close))

    if active:
        final_date = pd.Timestamp(sessions[-1]).normalize()
        for position in active:
            close_value = _price_value(
                cache,
                prices,
                position.ticker,
                final_date,
                "close",
                position.exit_price,
            )
            cash += position.shares * close_value
            trade_pnls.append(position.shares * close_value - position.allocated)
        equity_series.append((final_date, cash))

    equity_values = pd.Series(
        {date: value for date, value in equity_series}
    ).sort_index()
    peaks = equity_values.cummax()
    max_drawdown = (
        float((equity_values / peaks - 1).min()) if not equity_values.empty else 0.0
    )
    gains = sum(max(0.0, value) for value in trade_pnls)
    losses = abs(sum(min(0.0, value) for value in trade_pnls))
    profit_factor = gains / losses if losses else (float("inf") if gains else np.nan)

    qqq_start = num(qqq.loc[sessions[0], "open"])
    qqq_end = num(qqq.loc[sessions[-1], "close"])
    qqq_aligned = (
        qqq_end / qqq_start - 1
        if np.isfinite(qqq_start)
        and qqq_start > 0
        and np.isfinite(qqq_end)
        else np.nan
    )
    return {
        "trade_count": len(trade_pnls),
        "portfolio_return": (
            float(equity_values.iloc[-1] - 1) if not equity_values.empty else 0.0
        ),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "qqq_aligned_return": qqq_aligned,
        "portfolio_start": pd.Timestamp(sessions[0]),
        "portfolio_end": pd.Timestamp(sessions[-1]),
    }


def evaluate(
    frame: pd.DataFrame,
    prediction: pd.DataFrame,
    prices: Mapping[str, pd.DataFrame],
    config: ExperimentConfig,
    *,
    spec: int,
) -> dict[str, Any]:
    score = pd.to_numeric(prediction["score"], errors="coerce")
    probability = pd.to_numeric(
        prediction["probability"], errors="coerce"
    ).clip(0, 1)
    assigned = frame.assign(_score=score)
    ic_values = [
        safe_spearman(group["_score"], group["excess_10"])
        for _, group in assigned.groupby("date")
    ]
    ic_values = [value for value in ic_values if value is not None]
    selected = frame[top_decile(frame, score)]
    target = series_num(frame, "hit_3r_before_1r_15")
    pair = pd.DataFrame({"p": probability, "y": target}).dropna()
    baseline = (
        num(prediction["baseline_probability"].iloc[0], target.mean())
        if len(prediction)
        else num(target.mean(), 0.5)
    )
    brier = (
        float(np.mean((pair["p"] - pair["y"]) ** 2))
        if not pair.empty
        else np.nan
    )
    baseline_brier = (
        float(np.mean((baseline - pair["y"]) ** 2))
        if not pair.empty
        else np.nan
    )
    brier_skill = (
        1 - brier / baseline_brier
        if np.isfinite(brier)
        and np.isfinite(baseline_brier)
        and baseline_brier > 0
        else np.nan
    )

    path_days = series_num(selected, "days_to_3r_or_stop").dropna()
    portfolio = simulate_portfolio_mtm(
        frame,
        score,
        prices,
        config,
        mode=PORTFOLIO_MODE[spec],
        stage_sizing=spec in STAGE_SIZING_SPECS,
    )
    return {
        "daily_spearman_ic": safe_mean(ic_values),
        "ic_days": len(ic_values),
        "top10_excess_return": safe_mean(
            series_num(selected, "excess_10").dropna()
        ),
        "top10_hit_3r_rate": safe_mean(
            series_num(selected, "hit_3r_before_1r_15").dropna()
        ),
        "top10_early_failure_rate": safe_mean(
            series_num(selected, "early_failure_5").dropna()
        ),
        "top10_neither_rate": safe_mean(
            series_num(selected, "neither_3r_nor_1r_15").dropna()
        ),
        "top10_resolution_days": safe_mean(path_days),
        "brier_score": brier,
        "brier_skill": brier_skill,
        "candidate_rows": len(frame),
        "top10_rows": len(selected),
        "portfolio_mode": PORTFOLIO_MODE[spec],
        "stage_sizing": spec in STAGE_SIZING_SPECS,
        **portfolio,
    }


def run_walk_forward(
    dataset: pd.DataFrame,
    prices: Mapping[str, pd.DataFrame],
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    data = dataset.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["label_end_date"] = pd.to_datetime(data["label_end_date"]).dt.normalize()
    rows: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for fold_index, (train_start, train_end, test_year) in enumerate(
        TRAIN_WINDOWS, start=1
    ):
        test_start = pd.Timestamp(test_year, 1, 1)
        train = data[
            data["date"].dt.year.between(train_start, train_end)
            & (data["label_end_date"] < test_start)
        ]
        test = data[data["date"].dt.year == test_year]
        if train.empty or test.empty:
            folds.append(
                {
                    "test_year": test_year,
                    "status": "SKIPPED_EMPTY",
                    "train_rows": len(train),
                    "test_rows": len(test),
                }
            )
            continue
        predictions = build_predictions(
            train, test, config.seed + fold_index * 1000
        )
        for spec, prediction in predictions.items():
            metrics = evaluate(test, prediction, prices, config, spec=spec)
            benchmark = num(metrics.get("qqq_aligned_return"))
            rows.append(
                {
                    "spec": spec,
                    "spec_name": SPEC_NAMES[spec],
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_year": test_year,
                    "train_rows": len(train),
                    "test_rows": len(test),
                    "qqq_return": benchmark,
                    "beats_qqq": bool(
                        np.isfinite(benchmark)
                        and metrics["portfolio_return"] > benchmark
                    ),
                    **metrics,
                }
            )
        folds.append(
            {
                "test_year": test_year,
                "status": "PASS",
                "train_rows": len(train),
                "test_rows": len(test),
            }
        )
    return pd.DataFrame(rows), {"folds": folds}


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec, group in results.groupby("spec", sort=True):
        returns = pd.to_numeric(group["portfolio_return"], errors="coerce")
        qqq = pd.to_numeric(group["qqq_return"], errors="coerce")
        pf_values = [
            min(value, 20)
            for value in pd.to_numeric(group["profit_factor"], errors="coerce")
            if np.isfinite(value)
        ]
        rows.append(
            {
                "spec": int(spec),
                "spec_name": SPEC_NAMES[int(spec)],
                "folds": len(group),
                "portfolio_mode": str(group["portfolio_mode"].iloc[0]),
                "stage_sizing": bool(group["stage_sizing"].iloc[0]),
                "mean_daily_spearman_ic": safe_mean(group["daily_spearman_ic"]),
                "median_daily_spearman_ic": pd.to_numeric(
                    group["daily_spearman_ic"], errors="coerce"
                ).median(),
                "mean_top10_excess_return": safe_mean(
                    group["top10_excess_return"]
                ),
                "mean_hit_3r_rate": safe_mean(group["top10_hit_3r_rate"]),
                "mean_early_failure_rate": safe_mean(
                    group["top10_early_failure_rate"]
                ),
                "mean_neither_rate": safe_mean(group["top10_neither_rate"]),
                "mean_resolution_days": safe_mean(
                    group["top10_resolution_days"]
                ),
                "mean_brier_score": safe_mean(group["brier_score"]),
                "mean_brier_skill": safe_mean(group["brier_skill"]),
                "mean_profit_factor": safe_mean(pf_values),
                "worst_max_drawdown": pd.to_numeric(
                    group["max_drawdown"], errors="coerce"
                ).min(),
                "mean_portfolio_return": safe_mean(returns),
                "median_portfolio_return": returns.median(),
                "worst_portfolio_return": returns.min(),
                "positive_years": int((returns > 0).sum()),
                "qqq_excess_years": int((returns > qqq).sum()),
                "yearly_return_std": returns.std(ddof=0),
                "total_trades": int(
                    pd.to_numeric(group["trade_count"], errors="coerce").sum()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("spec").reset_index(drop=True)


def incremental_verdicts(summary: pd.DataFrame) -> list[dict[str, Any]]:
    lookup = {int(row["spec"]): row for _, row in summary.iterrows()}
    pairs = (
        (12, 11, "Aの固定10日出口"),
        (14, 11, "AへのB2追加"),
        (15, 14, "A+B2の固定10日出口"),
        (16, 12, "Aへのステージ交互作用"),
        (17, 14, "A+B2へのステージ交互作用"),
        (18, 14, "A+B2のステージ別ロット"),
        (19, 17, "交互作用モデルのステージ別ロット"),
    )
    improvements = (
        ("mean_top10_excess_return", 0.001, 1, "上位10%超過収益"),
        ("mean_hit_3r_rate", 0.01, 1, "+3R先着率"),
        ("mean_early_failure_rate", 0.01, -1, "Early Failure率"),
        ("mean_brier_skill", 0.01, 1, "Brier Skill"),
        ("mean_profit_factor", 0.10, 1, "PF"),
        ("worst_max_drawdown", 0.02, 1, "完全MTM最大DD"),
        ("mean_portfolio_return", 0.03, 1, "平均運用収益"),
    )
    guardrails = (
        ("mean_top10_excess_return", -0.001, 1),
        ("mean_hit_3r_rate", -0.01, 1),
        ("mean_early_failure_rate", 0.01, -1),
        ("mean_profit_factor", -0.05, 1),
        ("worst_max_drawdown", -0.01, 1),
        ("mean_portfolio_return", -0.02, 1),
    )
    output = []
    for new_spec, old_spec, label in pairs:
        if new_spec not in lookup or old_spec not in lookup:
            continue
        new = lookup[new_spec]
        old = lookup[old_spec]
        reasons = []
        for column, threshold, direction, name in improvements:
            new_value = num(new.get(column))
            old_value = num(old.get(column))
            if (
                np.isfinite(new_value)
                and np.isfinite(old_value)
                and (new_value - old_value) * direction >= threshold
            ):
                reasons.append(name)
        violations = []
        for column, tolerance, direction in guardrails:
            new_value = num(new.get(column))
            old_value = num(old.get(column))
            if not np.isfinite(new_value) or not np.isfinite(old_value):
                continue
            change = (new_value - old_value) * direction
            if change < tolerance:
                violations.append(column)
        output.append(
            {
                "increment": label,
                "from_spec": old_spec,
                "to_spec": new_spec,
                "verdict": "ADOPT" if reasons and not violations else "REJECT",
                "material_improvements": reasons,
                "guardrail_violations": violations,
                "trade_count_change": int(new.get("total_trades") or 0)
                - int(old.get("total_trades") or 0),
                "note": "取引数減少だけでは採用しない。改善と非劣化を同時要求。",
            }
        )
    return output
