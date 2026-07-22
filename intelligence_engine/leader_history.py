from __future__ import annotations

from typing import Any

import pandas as pd

LEADER_HISTORY_POLICY_VERSION = "1.0.0"
WINDOWS = (63, 126, 189)


def _close(frame: pd.DataFrame | None) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    mapping = {str(column).lower().replace(" ", "_"): column for column in frame.columns}
    column = next((mapping[name] for name in ("close", "adj_close", "adjclose") if name in mapping), None)
    if column is None:
        return pd.Series(dtype="float64")
    result = pd.to_numeric(frame[column], errors="coerce").dropna()
    if not isinstance(result.index, pd.DatetimeIndex):
        return pd.Series(dtype="float64")
    if result.index.tz is not None:
        result.index = result.index.tz_convert(None)
    return result.sort_index().loc[~result.index.duplicated(keep="last")]


def _rs_at(
    stock: pd.Series,
    benchmark: pd.Series,
    window: int,
    offset: int,
) -> float | None:
    common = stock.index.intersection(benchmark.index)
    if len(common) <= window + offset:
        return None
    end_pos = len(common) - 1 - offset
    start_pos = end_pos - window
    if start_pos < 0:
        return None
    end = common[end_pos]
    start = common[start_pos]
    s0 = stock.get(start)
    s1 = stock.get(end)
    q0 = benchmark.get(start)
    q1 = benchmark.get(end)
    if any(pd.isna(value) for value in (s0, s1, q0, q1)) or not s0 or not q0:
        return None
    return float(s1 / s0 - q1 / q0)


def build_price_leader_transitions(
    prices: dict[str, pd.DataFrame],
    *,
    lookback_sessions: int = 5,
    top_n: int = 10,
) -> dict[str, Any]:
    benchmark = _close(prices.get("QQQ"))
    if benchmark.empty:
        return {
            "status": "NO_BENCHMARK",
            "policy_version": LEADER_HISTORY_POLICY_VERSION,
            "changes": {},
            "rank_changes": [],
            "leader_board": {},
        }

    changes: dict[str, Any] = {}
    flat: list[dict[str, Any]] = []
    leader_board: dict[str, list[dict[str, Any]]] = {}
    for window in WINDOWS:
        now_scores: dict[str, float] = {}
        prior_scores: dict[str, float] = {}
        for ticker, frame in prices.items():
            if ticker == "QQQ":
                continue
            close = _close(frame)
            if close.empty:
                continue
            now = _rs_at(close, benchmark, window, 0)
            prior = _rs_at(close, benchmark, window, lookback_sessions)
            if now is not None:
                now_scores[str(ticker)] = now
            if prior is not None:
                prior_scores[str(ticker)] = prior
        ordered_now = sorted(now_scores, key=lambda ticker: (-now_scores[ticker], ticker))
        ordered_prior = sorted(prior_scores, key=lambda ticker: (-prior_scores[ticker], ticker))
        now_rank = {ticker: rank for rank, ticker in enumerate(ordered_now, 1)}
        prior_rank = {ticker: rank for rank, ticker in enumerate(ordered_prior, 1)}
        rows = []
        for ticker in ordered_now:
            current_rank = now_rank[ticker]
            previous_rank = prior_rank.get(ticker)
            rank_change = (previous_rank if previous_rank is not None else len(prior_rank) + 1) - current_rank
            row = {
                "ticker": ticker,
                "window": window,
                "previous_rank": previous_rank,
                "current_rank": current_rank,
                "rank_change": rank_change,
                "rs_raw": now_scores[ticker],
                "rs_change": now_scores[ticker] - prior_scores.get(ticker, now_scores[ticker]),
            }
            rows.append(row)
            flat.append(row)
        rows.sort(key=lambda item: (-item["rank_change"], item["ticker"]))
        key = f"rs{window}"
        changes[key] = {
            "new_top10": sorted(
                ticker for ticker, rank in now_rank.items()
                if rank <= top_n and prior_rank.get(ticker, 999999) > top_n
            ),
            "dropped_top10": sorted(
                ticker for ticker, rank in prior_rank.items()
                if rank <= top_n and now_rank.get(ticker, 999999) > top_n
            ),
            "rank_changes": rows[:30],
        }
        leader_board[key] = [
            {
                "ticker": ticker,
                "rank": now_rank[ticker],
                "rs_raw": now_scores[ticker],
                "rank_change": next(
                    (row["rank_change"] for row in rows if row["ticker"] == ticker),
                    0,
                ),
            }
            for ticker in ordered_now[:top_n]
        ]

    flat.sort(key=lambda item: (-item["rank_change"], item["window"], item["ticker"]))
    return {
        "status": "PRICE_HISTORY",
        "policy_version": LEADER_HISTORY_POLICY_VERSION,
        "lookback_sessions": lookback_sessions,
        "changes": changes,
        "rank_changes": flat[:90],
        "leader_board": leader_board,
    }
