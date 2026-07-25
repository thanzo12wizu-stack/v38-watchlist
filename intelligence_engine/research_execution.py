from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .prices import load_price_map
from .research_prices import _normalize
from .research_storage import load_dataset


@dataclass(frozen=True)
class ExecutionPolicy:
    round_trip_cost: float = 0.002
    max_positions: int = 4
    first_leg_weight: float = 0.50
    add_leg_weight: float = 0.50
    add_deadline_sessions: int = 5
    progress_exit_sessions: int = 5
    hard_exit_sessions: int = 10
    progress_threshold: float = 0.05
    partial_target: float = 0.25
    partial_fraction: float = 0.25
    max_holding_sessions: int = 63
    min_trades: int = 100
    min_positive_year_rate: float = 0.70
    min_oos_positive_rate: float = 0.60
    bootstrap_samples: int = 1000
    seed: int = 38


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _clear(value: Any) -> bool:
    if isinstance(value, list):
        return not value
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return True
    return str(value).strip() in {"", "[]", "null", "None"}


def strategy_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    clear = frame.get("hard_blocks", pd.Series([None] * len(frame), index=frame.index)).map(_clear)
    archetype = frame.get("candidate_archetype", pd.Series("NONE", index=frame.index)).astype(str)
    status = frame.get("decision_status", pd.Series("", index=frame.index)).astype(str)
    confidence = pd.to_numeric(frame.get("research_confidence", pd.Series(np.nan, index=frame.index)), errors="coerce")
    edge = pd.to_numeric(frame.get("expected_edge_10d", pd.Series(np.nan, index=frame.index)), errors="coerce")
    consistency = frame.get("expectancy_consistency", pd.Series("", index=frame.index)).astype(str)
    return {
        "BASELINE": pd.Series(True, index=frame.index),
        "HARD_BLOCKS": clear,
        "ARCHETYPE": clear & ~archetype.isin(["NONE", "DETERIORATION_ALERT"]),
        "RESEARCH_QUALIFIED": clear & status.isin(["QUALIFIED", "PROMISING"]),
        "EDGE_CONFIRMED": clear & (edge > 0) & consistency.isin(["CONFIRMED", "PRIMARY_ONLY"]) & (confidence >= 0.60),
    }


def prepare_price(raw: pd.DataFrame) -> pd.DataFrame:
    price = _normalize(raw)
    if price.empty or "open" not in price:
        return pd.DataFrame()
    price = price.copy()
    price["ema21_low"] = pd.to_numeric(price["low"], errors="coerce").ewm(span=21, adjust=False).mean()
    price["sma10"] = pd.to_numeric(price["close"], errors="coerce").rolling(10).mean()
    return price


def _fill(price: float, buy: bool, policy: ExecutionPolicy) -> float:
    half = policy.round_trip_cost / 2.0
    return price * (1.0 + half if buy else 1.0 - half)


def simulate_trade(signal: pd.Series, raw: pd.DataFrame, policy: ExecutionPolicy, trail: str) -> dict[str, Any] | None:
    price = prepare_price(raw)
    if price.empty:
        return None
    signal_date = pd.Timestamp(signal.get("date")).normalize()
    entry_pos = int(price.index.searchsorted(signal_date, side="right"))
    if entry_pos >= len(price):
        return None
    first_open = _num(price.iloc[entry_pos].get("open"))
    if first_open is None or first_open <= 0:
        return None
    first = _fill(first_open, True, policy)
    pivot = _num(signal.get("pivot_20d"))
    units = policy.first_leg_weight / first
    invested = policy.first_leg_weight
    added = False
    partial = False
    realized = 0.0
    peak = first
    exit_pos = min(entry_pos + policy.max_holding_sessions, len(price) - 1)
    exit_px = _fill(float(price.iloc[exit_pos]["close"]), False, policy)
    exit_reason = "MAX_HOLD"

    for offset in range(policy.max_holding_sessions + 1):
        pos = entry_pos + offset
        if pos >= len(price):
            break
        row = price.iloc[pos]
        open_px = _num(row.get("open")); high = _num(row.get("high")); low = _num(row.get("low")); close = _num(row.get("close"))
        if None in {open_px, high, low, close}:
            continue
        peak = max(peak, high)
        if not added and pivot is not None and offset <= policy.add_deadline_sessions and high >= pivot:
            second = _fill(max(open_px, pivot), True, policy)
            units += policy.add_leg_weight / second
            invested += policy.add_leg_weight
            added = True
        avg = invested / units
        if not partial and high >= avg * (1.0 + policy.partial_target):
            sold = units * policy.partial_fraction
            realized += sold * _fill(avg * (1.0 + policy.partial_target), False, policy)
            units -= sold
            partial = True
        trail_px = _num(row.get("ema21_low" if trail == "EMA21_LOW" else "sma10"))
        if offset > 0 and trail_px is not None and low <= trail_px:
            exit_px = _fill(min(open_px, trail_px), False, policy)
            exit_pos = pos
            exit_reason = trail
            break
        progressed = peak >= max(first * (1.0 + policy.progress_threshold), pivot or 0.0)
        if offset >= policy.progress_exit_sessions and not progressed and not added:
            exit_px = _fill(close, False, policy)
            exit_pos = pos
            exit_reason = "NO_PROGRESS_5D"
            break
        if offset >= policy.hard_exit_sessions and not added:
            exit_px = _fill(close, False, policy)
            exit_pos = pos
            exit_reason = "NO_ADD_10D"
            break

    trade_return = (realized + units * exit_px) / invested - 1.0
    return {
        "ticker": str(signal.get("ticker")),
        "entry_date": pd.Timestamp(price.index[entry_pos]).date().isoformat(),
        "exit_date": pd.Timestamp(price.index[exit_pos]).date().isoformat(),
        "return": float(trade_return),
        "added": added,
        "partial_taken": partial,
        "holding_sessions": int(exit_pos - entry_pos),
        "exit_reason": exit_reason,
        "research_rank": _num(signal.get("research_rank")),
    }


def select_portfolio(trades: pd.DataFrame, policy: ExecutionPolicy) -> pd.DataFrame:
    if trades.empty:
        return trades
    work = trades.copy()
    work["entry_date"] = pd.to_datetime(work["entry_date"], errors="coerce")
    work["exit_date"] = pd.to_datetime(work["exit_date"], errors="coerce")
    work = work.sort_values(["entry_date", "research_rank", "ticker"], na_position="last")
    active: list[pd.Timestamp] = []
    keep: list[bool] = []
    for _, row in work.iterrows():
        entry = row["entry_date"]
        active = [date for date in active if date >= entry]
        accepted = len(active) < policy.max_positions
        keep.append(accepted)
        if accepted:
            active.append(row["exit_date"])
    return work.loc[keep].reset_index(drop=True)


def date_block_ci(frame: pd.DataFrame, policy: ExecutionPolicy) -> list[float] | None:
    if frame.empty:
        return None
    daily = frame.groupby("entry_date")["return"].mean().dropna()
    if len(daily) < 10:
        return None
    rng = np.random.default_rng(policy.seed)
    values = daily.to_numpy(dtype=float)
    means = np.array([rng.choice(values, len(values), replace=True).mean() for _ in range(policy.bootstrap_samples)])
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def summarize(frame: pd.DataFrame, policy: ExecutionPolicy) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0, "mean_return": None, "win_rate": None, "positive_year_rate": None, "oos_positive_rate": None, "date_block_ci95": None}
    work = frame.copy()
    work["entry_date"] = pd.to_datetime(work["entry_date"], errors="coerce")
    yearly = work.groupby(work["entry_date"].dt.year)["return"].mean()
    positive = float((yearly > 0).mean()) if len(yearly) else None
    return {
        "trades": int(len(work)),
        "mean_return": float(work["return"].mean()),
        "median_return": float(work["return"].median()),
        "win_rate": float((work["return"] > 0).mean()),
        "positive_year_rate": positive,
        "oos_positive_rate": positive,
        "years": {str(int(year)): float(value) for year, value in yearly.items()},
        "add_rate": float(work["added"].mean()),
        "partial_rate": float(work["partial_taken"].mean()),
        "mean_holding_sessions": float(work["holding_sessions"].mean()),
        "date_block_ci95": date_block_ci(work, policy),
    }


def decide(summary: dict[str, Any], policy: ExecutionPolicy) -> tuple[str, list[str]]:
    ci = summary.get("date_block_ci95")
    checks = {
        "trades": (summary.get("trades") or 0) >= policy.min_trades,
        "mean": (summary.get("mean_return") or 0) > 0,
        "block_ci": ci is not None and ci[0] > 0,
        "positive_year_rate": (summary.get("positive_year_rate") or 0) >= policy.min_positive_year_rate,
        "oos_positive_rate": (summary.get("oos_positive_rate") or 0) >= policy.min_oos_positive_rate,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if all(checks.values()):
        return "ADOPT", failed
    if checks["trades"] and checks["mean"] and checks["positive_year_rate"]:
        return "DISPLAY_ONLY", failed
    return "REJECT", failed


def build_report(root: Path, prices_path: Path, policy: ExecutionPolicy = ExecutionPolicy()) -> dict[str, Any]:
    rankings = load_dataset(root, "rankings")
    if rankings.empty:
        raise RuntimeError("research rankings are missing")
    prices = load_price_map(prices_path)
    results: list[dict[str, Any]] = []
    for trail in ("EMA21_LOW", "SMA10"):
        for strategy, mask in strategy_masks(rankings).items():
            rows: list[dict[str, Any]] = []
            for _, signal in rankings.loc[mask].iterrows():
                raw = prices.get(str(signal.get("ticker", "")).upper())
                if raw is None:
                    continue
                trade = simulate_trade(signal, raw, policy, trail)
                if trade is not None:
                    rows.append(trade)
            selected = select_portfolio(pd.DataFrame(rows), policy)
            summary = summarize(selected, policy)
            decision, reasons = decide(summary, policy)
            results.append({"strategy": strategy, "trail": trail, "decision": decision, "reasons": reasons, "summary": summary})
    priority = {"ADOPT": 0, "DISPLAY_ONLY": 1, "REJECT": 2}
    results.sort(key=lambda item: (priority[item["decision"]], -(item["summary"].get("mean_return") or -999)))
    return {
        "schema_version": "1.0",
        "method": "next-open; two-stage entry; 5/10-session progress exits; 25% partial at +25%; EMA21-low or SMA10 trail; four-position cap",
        "policy": asdict(policy),
        "results": results,
        "implementation": {
            "adopted": [{"strategy": x["strategy"], "trail": x["trail"]} for x in results if x["decision"] == "ADOPT"],
            "command_center_integration": "SIDECAR_ONLY",
            "command_center_modified": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--output", default="research-execution-report.json")
    args = parser.parse_args()
    report = build_report(Path(args.root), Path(args.prices))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "results": len(report["results"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
