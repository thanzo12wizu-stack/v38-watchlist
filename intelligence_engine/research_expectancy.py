from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .research_contracts import (
    RESEARCH_COMPARISON_WINDOWS,
    RESEARCH_PRIMARY_WINDOW_YEARS,
)


def _bootstrap_ci(values: pd.Series, *, samples: int = 300, seed: int = 38) -> list[float] | None:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) < 10:
        return None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for index in range(samples):
        means[index] = rng.choice(clean, len(clean), replace=True).mean()
    return [float(np.quantile(means, .025)), float(np.quantile(means, .975))]


def _profit_factor(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean[clean > 0].sum())
    losses = float(-clean[clean < 0].sum())
    if losses <= 0:
        return None if gains <= 0 else 99.0
    return gains / losses


def _qualification(
    count: int,
    mean: float | None,
    ci: list[float] | None,
    min_samples: int,
    *,
    year_count: int,
    positive_year_rate: float | None,
    loyo_positive_rate: float | None,
    max_ticker_share: float | None,
    max_year_share: float | None,
) -> str:
    stable_years = year_count < 3 or (positive_year_rate is not None and positive_year_rate >= .60)
    stable_loyo = year_count < 3 or (loyo_positive_rate is not None and loyo_positive_rate >= .60)
    diversified = (max_ticker_share is None or max_ticker_share <= .25) and (
        max_year_share is None or max_year_share <= .50
    )
    if (
        count >= max(50, min_samples)
        and mean is not None
        and mean > 0
        and ci is not None
        and ci[0] > 0
        and stable_years
        and stable_loyo
        and diversified
    ):
        return "QUALIFIED"
    if count >= max(25, int(min_samples * .75)) and mean is not None and mean > 0:
        return "PROMISING"
    return "EXPLORATORY"


def _summary(
    group: pd.DataFrame,
    horizon: int,
    *,
    min_samples: int,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    excess = pd.to_numeric(group.get(f"excess_{horizon}"), errors="coerce").dropna()
    count = int(len(excess))
    if not count:
        return {
            "samples": 0,
            "qualification": "EXPLORATORY",
            "win_rate": None,
            "mean_excess_return": None,
            "median_excess_return": None,
            "downside_tail_p10": None,
            "downside_tail_p5": None,
            "profit_factor": None,
            "bootstrap_mean_ci95": None,
            "mean_mfe": None,
            "mean_mae": None,
            "stop_rate": None,
            "target25_rate": None,
            "target25_before_stop_rate": None,
            "positive_year_rate": None,
            "loyo_positive_rate": None,
            "year_count": 0,
            "max_ticker_share": None,
            "max_year_share": None,
        }
    subset = group.loc[excess.index]
    mean = float(excess.mean())
    ci = _bootstrap_ci(excess, samples=bootstrap_samples, seed=seed + horizon + count)
    tickers = subset["ticker"].astype(str) if "ticker" in subset else pd.Series(dtype=str)
    years = pd.to_datetime(subset["date"], errors="coerce").dt.year
    yearly = pd.DataFrame({"year": years, "value": excess}).dropna().groupby("year")["value"].mean()
    positive_year_rate = float((yearly > 0).mean()) if len(yearly) else None
    loyo_means = []
    for omitted in yearly.index:
        values = excess[years != omitted]
        if len(values):
            loyo_means.append(float(values.mean()))
    loyo_positive_rate = float(np.mean(np.asarray(loyo_means) > 0)) if loyo_means else None
    max_ticker_share = float(tickers.value_counts(normalize=True).max()) if not tickers.empty else None
    max_year_share = float(years.value_counts(normalize=True).max()) if years.notna().any() else None
    result = {
        "samples": count,
        "win_rate": float((excess > 0).mean()),
        "mean_excess_return": mean,
        "median_excess_return": float(excess.median()),
        "downside_tail_p10": float(excess.quantile(.10)),
        "downside_tail_p5": float(excess.quantile(.05)),
        "profit_factor": _profit_factor(excess),
        "bootstrap_mean_ci95": ci,
        "max_ticker_share": max_ticker_share,
        "max_year_share": max_year_share,
        "positive_year_rate": positive_year_rate,
        "loyo_positive_rate": loyo_positive_rate,
        "year_count": int(len(yearly)),
    }
    result["qualification"] = _qualification(
        count,
        mean,
        ci,
        min_samples,
        year_count=len(yearly),
        positive_year_rate=positive_year_rate,
        loyo_positive_rate=loyo_positive_rate,
        max_ticker_share=max_ticker_share,
        max_year_share=max_year_share,
    )
    for source, target in ((f"mfe_{horizon}", "mean_mfe"), (f"mae_{horizon}", "mean_mae")):
        result[target] = (
            float(pd.to_numeric(subset.get(source), errors="coerce").mean())
            if source in subset
            else None
        )
    for source, target in (
        (f"stop_hit_{horizon}", "stop_rate"),
        (f"target25_hit_{horizon}", "target25_rate"),
        (f"target25_before_stop_{horizon}", "target25_before_stop_rate"),
    ):
        result[target] = (
            float(pd.Series(subset.get(source), dtype="boolean").mean())
            if source in subset
            else None
        )
    return result


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _add_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["rs63_bucket"] = pd.cut(
        _numeric_column(out, "pct_rs_raw_63"),
        [-np.inf, 50, 70, 85, np.inf],
        labels=["LT50", "50TO70", "70TO85", "GE85"],
    )
    out["eps_growth_bucket"] = pd.cut(
        _numeric_column(out, "eps_yoy"),
        [-np.inf, 0, .15, .30, np.inf],
        labels=["NEG", "0TO15", "15TO30", "GE30"],
    )
    out["stop_bucket"] = pd.cut(
        _numeric_column(out, "stop_risk_pct"),
        [-np.inf, 4, 7, 10, np.inf],
        labels=["LE4", "4TO7", "7TO10", "GT10"],
    )
    out["rr_bucket"] = pd.cut(
        _numeric_column(out, "reward_risk_raw"),
        [-np.inf, 1.5, 2.5, 4, np.inf],
        labels=["LT1.5", "1.5TO2.5", "2.5TO4", "GE4"],
    )
    return out


def _group_specs() -> list[tuple[str, list[str]]]:
    return [
        ("archetype", ["candidate_archetype"]),
        ("archetype_setup", ["candidate_archetype", "setup"]),
        ("archetype_regime", ["candidate_archetype", "market_regime"]),
        ("rs_setup", ["rs_archetype", "setup"]),
        ("financial_setup", ["financial_phase", "setup"]),
        ("rs_bucket_setup", ["rs63_bucket", "setup"]),
        ("eps_bucket_setup", ["eps_growth_bucket", "setup"]),
        ("risk_bucket", ["stop_bucket", "rr_bucket"]),
    ]


def _groups(
    data: pd.DataFrame,
    horizons: tuple[int, ...],
    *,
    min_samples: int,
    bootstrap_samples: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_type, columns in _group_specs():
        if any(column not in data for column in columns):
            continue
        for values, group in data.groupby(columns, dropna=False, observed=True):
            if not isinstance(values, tuple):
                values = (values,)
            dimensions = {
                column: (None if pd.isna(value) else str(value))
                for column, value in zip(columns, values)
            }
            for horizon in horizons:
                rows.append(
                    {
                        "group_type": group_type,
                        **dimensions,
                        "horizon": horizon,
                        **_summary(
                            group,
                            horizon,
                            min_samples=min_samples,
                            bootstrap_samples=bootstrap_samples,
                            seed=seed,
                        ),
                    }
                )
    rows.sort(
        key=lambda row: (
            row["group_type"],
            row["horizon"],
            -(row.get("mean_excess_return") or -999),
            -row.get("samples", 0),
        )
    )
    return rows


def _walk_forward(data: pd.DataFrame, horizons: tuple[int, ...], min_samples: int) -> list[dict[str, Any]]:
    results = []
    dates = pd.to_datetime(data["date"], errors="coerce")
    years = sorted(int(value) for value in dates.dt.year.dropna().unique())
    for horizon in horizons:
        outcome_dates = (
            pd.to_datetime(data[f"outcome_date_{horizon}"], errors="coerce")
            if f"outcome_date_{horizon}" in data
            else pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")
        )
        for test_year in years:
            cutoff = pd.Timestamp(test_year, 1, 1)
            next_year = pd.Timestamp(test_year + 1, 1, 1)
            train = data[outcome_dates < cutoff]
            test = data[(dates >= cutoff) & (dates < next_year)]
            if train.empty or test.empty:
                continue
            candidates = []
            for archetype, group in train.groupby("candidate_archetype", dropna=False):
                values = pd.to_numeric(group.get(f"excess_{horizon}"), errors="coerce").dropna()
                if len(values) >= min_samples:
                    candidates.append((str(archetype), float(values.mean()), int(len(values))))
            if not candidates:
                continue
            candidates.sort(key=lambda value: (-value[1], -value[2], value[0]))
            selected, train_mean, train_samples = candidates[0]
            observed = pd.to_numeric(
                test[test["candidate_archetype"].astype(str) == selected].get(f"excess_{horizon}"),
                errors="coerce",
            ).dropna()
            results.append(
                {
                    "horizon": horizon,
                    "test_year": test_year,
                    "selected_archetype": selected,
                    "train_samples": train_samples,
                    "train_mean_excess": train_mean,
                    "test_samples": int(len(observed)),
                    "test_mean_excess": float(observed.mean()) if len(observed) else None,
                    "test_win_rate": float((observed > 0).mean()) if len(observed) else None,
                    "training_cutoff": cutoff.date().isoformat(),
                }
            )
    return results


def _leave_one_year_out(data: pd.DataFrame, horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    results = []
    years = pd.to_datetime(data["date"], errors="coerce").dt.year
    for horizon in horizons:
        for omitted_year in sorted(int(value) for value in years.dropna().unique()):
            subset = data[years != omitted_year]
            values = pd.to_numeric(subset.get(f"excess_{horizon}"), errors="coerce").dropna()
            results.append(
                {
                    "horizon": horizon,
                    "omitted_year": omitted_year,
                    "samples": int(len(values)),
                    "mean_excess_return": float(values.mean()) if len(values) else None,
                    "win_rate": float((values > 0).mean()) if len(values) else None,
                }
            )
    return results


def _window_subset(data: pd.DataFrame, window_years: int) -> pd.DataFrame:
    dates = pd.to_datetime(data["date"], errors="coerce")
    latest = dates.max()
    if pd.isna(latest):
        return data.iloc[0:0].copy()
    cutoff = pd.Timestamp(latest).normalize() - pd.DateOffset(years=int(window_years))
    return data[dates >= cutoff].copy()


def _window_payload(
    data: pd.DataFrame,
    window_years: int,
    horizons: tuple[int, ...],
    *,
    min_samples: int,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    dates = pd.to_datetime(data.get("date"), errors="coerce")
    return {
        "window_years": int(window_years),
        "sample_count": int(len(data)),
        "ticker_count": int(data["ticker"].nunique()) if "ticker" in data else 0,
        "years": sorted(int(value) for value in dates.dt.year.dropna().unique()),
        "groups": _groups(
            data,
            horizons,
            min_samples=min_samples,
            bootstrap_samples=bootstrap_samples,
            seed=seed + int(window_years) * 100,
        ),
    }


def build_research_expectancy(
    outcomes: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (5, 10, 21, 63),
    min_samples: int = 40,
    bootstrap_samples: int = 300,
    seed: int = 38,
    analysis_windows: Iterable[int] = RESEARCH_COMPARISON_WINDOWS,
    primary_window_years: int = RESEARCH_PRIMARY_WINDOW_YEARS,
) -> dict[str, Any]:
    if outcomes is None or outcomes.empty:
        return {
            "status": "NO_SAMPLES",
            "groups": [],
            "windows": [],
            "walk_forward": [],
            "leave_one_year_out": [],
            "excluding_2020": [],
        }
    data = _add_buckets(outcomes)
    windows = []
    for value in sorted({max(1, int(item)) for item in analysis_windows}, reverse=True):
        windows.append(
            _window_payload(
                _window_subset(data, value),
                value,
                horizons,
                min_samples=min_samples,
                bootstrap_samples=bootstrap_samples,
                seed=seed,
            )
        )
    primary = next(
        (item for item in windows if item["window_years"] == int(primary_window_years)),
        windows[0] if windows else {"groups": [], "sample_count": 0, "ticker_count": 0, "years": []},
    )
    years = pd.to_datetime(data["date"], errors="coerce").dt.year
    filtered = data[years != 2020]
    excluding_2020 = [
        {
            "horizon": horizon,
            **_summary(
                filtered,
                horizon,
                min_samples=min_samples,
                bootstrap_samples=bootstrap_samples,
                seed=seed + 2020,
            ),
        }
        for horizon in horizons
    ]
    return {
        "status": "OK",
        "primary_window_years": int(primary_window_years),
        "comparison_windows_years": [item["window_years"] for item in windows],
        "sample_count": primary.get("sample_count", 0),
        "ticker_count": primary.get("ticker_count", 0),
        "years": primary.get("years", []),
        "retained_sample_count": int(len(data)),
        "retained_years": sorted(int(value) for value in years.dropna().unique()),
        "groups": primary.get("groups", []),
        "windows": windows,
        "walk_forward": _walk_forward(data, horizons, min_samples),
        "leave_one_year_out": _leave_one_year_out(data, horizons),
        "excluding_2020": excluding_2020,
    }
