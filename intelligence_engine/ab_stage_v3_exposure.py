from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .ab_stage_data import ExperimentConfig, TRAIN_WINDOWS, num, series_num
from .ab_stage_v2_models import (
    daily_rank,
    expanding_oof_a,
    expanding_oof_b2,
    fit_a,
    fit_b2,
    safe_mean,
    safe_spearman,
    stage_weight_multiplier,
    top_decile,
)
from .research_prices import _normalize

POLICY_VERSION = "3.0.0"
SPEC_NAMES = {
    14: "A＋B2・基準ロット",
    18: "A＋B2・ステージ別ロット",
    20: "A＋B2・学習期エクスポージャー正規化ロット",
}


@dataclass
class Position:
    ticker: str
    shares: float
    exit_date: pd.Timestamp
    exit_price: float
    allocated: float
    net_return: float


def build_ab2_scores(
    train: pd.DataFrame,
    test: pd.DataFrame,
    seed: int,
) -> tuple[pd.Series, pd.Series, float]:
    train = train.copy()
    test = test.copy()
    train["target_rank_10"] = train.groupby("date")["excess_10"].rank(pct=True)
    test["target_rank_10"] = test.groupby("date")["excess_10"].rank(pct=True)
    a_oof = expanding_oof_a(train, seed)
    b2_oof = expanding_oof_b2(train, seed + 100)
    _, a_test_values = fit_a(train, test, seed + 200)
    _, b2_test = fit_b2(train, test, seed + 300)
    a_test = pd.Series(a_test_values, index=test.index)
    train_score = daily_rank(train, a_oof) * 0.70 + daily_rank(
        train, b2_oof["score"]
    ) * 0.30
    test_score = daily_rank(test, a_test) * 0.70 + daily_rank(
        test, b2_test["score"]
    ) * 0.30
    selected_train = train[top_decile(train, train_score)]
    multipliers = selected_train.apply(stage_weight_multiplier, axis=1)
    mean_multiplier = float(multipliers.mean()) if len(multipliers) else 1.0
    if not math.isfinite(mean_multiplier) or mean_multiplier <= 0:
        mean_multiplier = 1.0
    scale = float(np.clip(1.0 / mean_multiplier, 1.0, 3.0))
    return train_score, test_score, scale


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


def simulate(
    frame: pd.DataFrame,
    score: pd.Series,
    prices: Mapping[str, pd.DataFrame],
    config: ExperimentConfig,
    *,
    stage_mode: str,
    learned_scale: float,
) -> dict[str, Any]:
    work = frame.copy()
    work["score"] = pd.to_numeric(score, errors="coerce")
    work["entry_date"] = pd.to_datetime(work["entry_date"]).dt.normalize()
    work["_exit_date"] = pd.to_datetime(work["trade_exit_date"]).dt.normalize()
    work["_gross_return"] = series_num(work, "trade_return_gross")
    work = work[top_decile(work, work["score"])].dropna(
        subset=["entry_date", "_exit_date", "_gross_return", "entry_price", "score"]
    )
    work = work.sort_values(["entry_date", "score", "ticker"], ascending=[True, False, True])
    if work.empty:
        return {
            "trade_count": 0,
            "portfolio_return": 0.0,
            "profit_factor": np.nan,
            "max_drawdown": 0.0,
            "average_gross_exposure": 0.0,
            "median_gross_exposure": 0.0,
            "max_gross_exposure": 0.0,
            "qqq_return": np.nan,
        }
    candidates = {date: group for date, group in work.groupby("entry_date", sort=True)}
    first_date = pd.Timestamp(work["entry_date"].min())
    last_date = pd.Timestamp(work["_exit_date"].max())
    qqq = _normalize(prices.get("QQQ"))
    sessions = qqq.index[(qqq.index >= first_date) & (qqq.index <= last_date)]
    if not len(sessions):
        raise RuntimeError("no QQQ sessions for V3 portfolio")

    cash = 1.0
    active: list[Position] = []
    cache: dict[str, pd.DataFrame] = {}
    prior_close: dict[str, float] = {}
    trade_pnls: list[float] = []
    equity_values: list[float] = []
    exposure_values: list[float] = []

    for raw_date in sessions:
        date = pd.Timestamp(raw_date).normalize()
        held = {position.ticker for position in active}
        slots = max(0, config.max_positions - len(active))
        equity_open = cash
        for position in active:
            reference = prior_close.get(
                position.ticker,
                position.exit_price / max(1 + position.net_return, 0.01),
            )
            equity_open += position.shares * _price_value(
                cache, prices, position.ticker, date, "open", reference
            )

        todays = candidates.get(date)
        if todays is not None and slots > 0:
            for _, row in todays.iterrows():
                ticker = str(row["ticker"]).upper()
                if ticker in held or slots <= 0:
                    continue
                risk = num(row.get("risk_fraction"))
                base_weight = (
                    min(config.max_position_weight, config.risk_per_trade / risk)
                    if np.isfinite(risk) and risk > 0
                    else config.max_position_weight
                )
                multiplier = 1.0
                if stage_mode in {"RAW", "NORMALIZED"}:
                    multiplier = stage_weight_multiplier(row)
                if stage_mode == "NORMALIZED":
                    multiplier *= learned_scale
                weight = min(config.max_position_weight, base_weight * multiplier)
                if weight <= 0:
                    continue
                entry_price = num(row.get("entry_price"))
                gross = num(row.get("_gross_return"))
                if not np.isfinite(entry_price) or entry_price <= 0 or not np.isfinite(gross):
                    continue
                allocated = min(cash, equity_open * weight)
                if allocated <= 0:
                    continue
                net_return = gross - config.roundtrip_cost
                active.append(
                    Position(
                        ticker=ticker,
                        shares=allocated / entry_price,
                        exit_date=pd.Timestamp(row["_exit_date"]).normalize(),
                        exit_price=entry_price * (1 + net_return),
                        allocated=allocated,
                        net_return=net_return,
                    )
                )
                cash -= allocated
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

        invested = 0.0
        for position in active:
            reference = prior_close.get(
                position.ticker,
                position.exit_price / max(1 + position.net_return, 0.01),
            )
            close_value = _price_value(
                cache, prices, position.ticker, date, "close", reference
            )
            prior_close[position.ticker] = close_value
            invested += position.shares * close_value
        equity = cash + invested
        equity_values.append(equity)
        exposure_values.append(invested / equity if equity > 0 else 0.0)

    if active:
        final_date = pd.Timestamp(sessions[-1]).normalize()
        for position in active:
            value = _price_value(
                cache, prices, position.ticker, final_date, "close", position.exit_price
            )
            cash += position.shares * value
            trade_pnls.append(position.shares * value - position.allocated)
        equity_values.append(cash)
        exposure_values.append(0.0)

    equity = pd.Series(equity_values, dtype=float)
    max_drawdown = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0
    gains = sum(max(0.0, value) for value in trade_pnls)
    losses = abs(sum(min(0.0, value) for value in trade_pnls))
    pf = gains / losses if losses else (float("inf") if gains else np.nan)
    qqq_start = num(qqq.loc[sessions[0], "open"])
    qqq_end = num(qqq.loc[sessions[-1], "close"])
    qqq_return = qqq_end / qqq_start - 1 if np.isfinite(qqq_start) and qqq_start > 0 and np.isfinite(qqq_end) else np.nan
    exposure = pd.Series(exposure_values, dtype=float)
    average_exposure = float(exposure.mean()) if len(exposure) else 0.0
    portfolio_return = float(equity.iloc[-1] - 1) if len(equity) else 0.0
    return {
        "trade_count": len(trade_pnls),
        "portfolio_return": portfolio_return,
        "profit_factor": pf,
        "max_drawdown": max_drawdown,
        "average_gross_exposure": average_exposure,
        "median_gross_exposure": float(exposure.median()) if len(exposure) else 0.0,
        "max_gross_exposure": float(exposure.max()) if len(exposure) else 0.0,
        "return_per_average_exposure": portfolio_return / average_exposure if average_exposure > 0 else np.nan,
        "drawdown_per_average_exposure": max_drawdown / average_exposure if average_exposure > 0 else np.nan,
        "qqq_return": qqq_return,
        "learned_stage_scale": learned_scale,
    }


def evaluate_rank(frame: pd.DataFrame, score: pd.Series) -> dict[str, Any]:
    assigned = frame.assign(_score=pd.to_numeric(score, errors="coerce"))
    ic = [safe_spearman(group["_score"], group["excess_10"]) for _, group in assigned.groupby("date")]
    selected = frame[top_decile(frame, score)]
    return {
        "daily_spearman_ic": safe_mean([value for value in ic if value is not None]),
        "top10_excess_return": safe_mean(series_num(selected, "excess_10").dropna()),
        "top10_hit_3r_rate": safe_mean(series_num(selected, "hit_3r_before_1r_15").dropna()),
        "top10_early_failure_rate": safe_mean(series_num(selected, "early_failure_5").dropna()),
    }


def run_walk_forward(
    dataset: pd.DataFrame,
    prices: Mapping[str, pd.DataFrame],
    config: ExperimentConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    data = dataset.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data["label_end_date"] = pd.to_datetime(data["label_end_date"]).dt.normalize()
    rows = []
    folds = []
    for fold_index, (train_start, train_end, test_year) in enumerate(TRAIN_WINDOWS, start=1):
        test_start = pd.Timestamp(test_year, 1, 1)
        train = data[
            data["date"].dt.year.between(train_start, train_end)
            & (data["label_end_date"] < test_start)
        ]
        test = data[data["date"].dt.year == test_year]
        if train.empty or test.empty:
            folds.append({"test_year": test_year, "status": "SKIPPED_EMPTY"})
            continue
        _, test_score, learned_scale = build_ab2_scores(
            train, test, config.seed + fold_index * 1000
        )
        rank_metrics = evaluate_rank(test, test_score)
        for spec, stage_mode in ((14, "NONE"), (18, "RAW"), (20, "NORMALIZED")):
            portfolio = simulate(
                test,
                test_score,
                prices,
                config,
                stage_mode=stage_mode,
                learned_scale=learned_scale,
            )
            rows.append(
                {
                    "spec": spec,
                    "spec_name": SPEC_NAMES[spec],
                    "test_year": test_year,
                    "train_start": train_start,
                    "train_end": train_end,
                    "train_rows": len(train),
                    "test_rows": len(test),
                    "stage_mode": stage_mode,
                    "beats_qqq": bool(
                        np.isfinite(num(portfolio.get("qqq_return")))
                        and portfolio["portfolio_return"] > portfolio["qqq_return"]
                    ),
                    **rank_metrics,
                    **portfolio,
                }
            )
        folds.append(
            {
                "test_year": test_year,
                "status": "PASS",
                "train_rows": len(train),
                "test_rows": len(test),
                "learned_stage_scale": learned_scale,
            }
        )
    return pd.DataFrame(rows), {"folds": folds}


def aggregate(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec, group in results.groupby("spec", sort=True):
        returns = pd.to_numeric(group["portfolio_return"], errors="coerce")
        qqq = pd.to_numeric(group["qqq_return"], errors="coerce")
        pfs = [min(value, 20) for value in pd.to_numeric(group["profit_factor"], errors="coerce") if np.isfinite(value)]
        rows.append(
            {
                "spec": int(spec),
                "spec_name": SPEC_NAMES[int(spec)],
                "folds": len(group),
                "stage_mode": str(group["stage_mode"].iloc[0]),
                "mean_daily_spearman_ic": safe_mean(group["daily_spearman_ic"]),
                "mean_top10_excess_return": safe_mean(group["top10_excess_return"]),
                "mean_hit_3r_rate": safe_mean(group["top10_hit_3r_rate"]),
                "mean_early_failure_rate": safe_mean(group["top10_early_failure_rate"]),
                "mean_profit_factor": safe_mean(pfs),
                "worst_max_drawdown": pd.to_numeric(group["max_drawdown"], errors="coerce").min(),
                "mean_portfolio_return": safe_mean(returns),
                "median_portfolio_return": returns.median(),
                "worst_portfolio_return": returns.min(),
                "positive_years": int((returns > 0).sum()),
                "qqq_excess_years": int((returns > qqq).sum()),
                "yearly_return_std": returns.std(ddof=0),
                "mean_average_gross_exposure": safe_mean(group["average_gross_exposure"]),
                "mean_max_gross_exposure": safe_mean(group["max_gross_exposure"]),
                "mean_return_per_exposure": safe_mean(group["return_per_average_exposure"]),
                "mean_drawdown_per_exposure": safe_mean(group["drawdown_per_average_exposure"]),
                "mean_learned_stage_scale": safe_mean(group["learned_stage_scale"]),
                "total_trades": int(pd.to_numeric(group["trade_count"], errors="coerce").sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("spec").reset_index(drop=True)
