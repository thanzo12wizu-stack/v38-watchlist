#!/usr/bin/env python3
"""Build compact sharded Options history for the Options Intelligence chart.

Purpose:
  * keep broad daily Options observations independent from Dashboard/V38 logic;
  * expose Spot + Call Wall + Put Wall + Gamma Flip history for nearly all liquid names;
  * avoid one huge browser payload by sharding on the first ticker character;
  * never invent missing observations or relabel stale/low-quality data as current.

Inputs:
  options_scan_history.csv   broad daily 7-21DTE history
  options_history.csv        detailed history (preferred when both exist)

Outputs:
  options_chart_history/index.json
  options_chart_history/<A-Z|0-9|_>.json
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DETAIL_HISTORY = Path(os.environ.get("V38_OPT_HISTORY", "options_history.csv"))
SCAN_HISTORY = Path(os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv"))
OUT_DIR = Path(os.environ.get("V38_OPT_CHART_HISTORY_DIR", "options_chart_history"))
MAX_OBSERVATIONS = max(60, int(os.environ.get("V38_OPT_CHART_HISTORY_MAX", "260")))


def _finite(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _boolish(v: Any) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y"}


def _quality_rank(v: Any) -> int:
    return {"HIGH": 4, "OK": 4, "MEDIUM": 3, "LOW": 1}.get(
        str(v or "").strip().upper(), 2
    )


def _shard(ticker: str) -> str:
    c = (ticker or "_").upper()[:1]
    return c if c.isalnum() else "_"


def _round(v: Any) -> float | None:
    x = _finite(v)
    return round(x, 6) if x is not None else None


def _valid_market_date(v: Any) -> str:
    day = str(v or "")[:10]
    if len(day) != 10:
        return ""
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return ""
    return day if dt.weekday() < 5 else ""


def _load_rows() -> dict[str, list[dict[str, Any]]]:
    """Choose one honest observation per ticker/session.

    Spot is retained whenever the row is current enough to be a valid historical
    observation. Wall values are independently nulled for LOW confidence or legacy
    wrong-side walls. DETAIL wins ties over SCAN.
    """
    chosen: dict[tuple[str, str], tuple[tuple[Any, ...], dict[str, Any]]] = {}
    order = 0
    for source, path in (("SCAN", SCAN_HISTORY), ("DETAIL", DETAIL_HISTORY)):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                order += 1
                ticker = str(row.get("ticker") or "").strip().upper()
                date = _valid_market_date(row.get("price_session_date") or row.get("date"))
                if not ticker or not date:
                    continue
                if _boolish(row.get("stale")):
                    continue
                session_flag = str(row.get("session_consistent") or "").strip()
                if session_flag and not _boolish(session_flag):
                    continue

                spot = _finite(row.get("spot"))
                if spot is None or spot <= 0:
                    continue

                confidence = str(row.get("confidence") or "").strip().upper() or "UNKNOWN"
                call = _finite(row.get("call_wall"))
                put = _finite(row.get("put_wall"))
                flip = _finite(row.get("gamma_flip"))
                exp_low = _finite(row.get("expected_low"))
                exp_high = _finite(row.get("expected_high"))

                # Low-confidence Wall geometry is not promoted to the chart, but the
                # daily Spot observation remains useful and honest.
                if confidence == "LOW":
                    call = put = flip = exp_low = exp_high = None

                # Preserve the current directional-wall definition when showing
                # history. Old wrong-side concentrations are not relabelled as walls.
                if call is not None and call <= spot:
                    call = None
                if put is not None and put >= spot:
                    put = None
                if exp_low is not None and exp_high is not None and exp_high <= exp_low:
                    exp_low = exp_high = None

                item = {
                    "time": date,
                    "spot": round(spot, 6),
                    "call_wall": round(call, 6) if call is not None else None,
                    "put_wall": round(put, 6) if put is not None else None,
                    "gamma_flip": round(flip, 6) if flip is not None else None,
                    "expected_low": round(exp_low, 6) if exp_low is not None else None,
                    "expected_high": round(exp_high, 6) if exp_high is not None else None,
                    "expiry": str(row.get("expiry") or ""),
                    "dte": _round(row.get("dte")),
                    "confidence": confidence,
                    "source": source,
                }
                observed = str(row.get("observed_at") or "")
                score = (
                    _quality_rank(confidence),
                    1 if source == "DETAIL" else 0,
                    observed,
                    order,
                )
                key = (ticker, date)
                prev = chosen.get(key)
                if prev is None or score >= prev[0]:
                    chosen[key] = (score, item)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (ticker, _date), (_score, item) in chosen.items():
        grouped[ticker].append(item)
    for ticker in grouped:
        grouped[ticker].sort(key=lambda x: x["time"])
        grouped[ticker] = grouped[ticker][-MAX_OBSERVATIONS:]
    return dict(grouped)


def build() -> dict[str, Any]:
    grouped = _load_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    shards: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    latest_session = ""
    wall_tickers = 0
    observations = 0
    wall_observations = 0
    for ticker, rows in grouped.items():
        shards[_shard(ticker)][ticker] = rows
        observations += len(rows)
        if rows:
            latest_session = max(latest_session, rows[-1]["time"])
        wc = sum(
            1
            for r in rows
            if r.get("call_wall") is not None
            or r.get("put_wall") is not None
            or r.get("gamma_flip") is not None
        )
        wall_observations += wc
        if wc:
            wall_tickers += 1

    for shard, tickers in shards.items():
        payload = {
            "schema_version": "1.0",
            "generated_at": now,
            "latest_session": latest_session,
            "shard": shard,
            "source": "options_only_daily_spot_and_positioning_history",
            "tickers": {t: tickers[t] for t in sorted(tickers)},
        }
        (OUT_DIR / f"{shard}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    index = {
        "schema_version": "1.0",
        "generated_at": now,
        "latest_session": latest_session,
        "source": "options_history_sharded_for_chart",
        "max_observations_per_ticker": MAX_OBSERVATIONS,
        "ticker_count": len(grouped),
        "wall_ticker_count": wall_tickers,
        "observation_count": observations,
        "wall_observation_count": wall_observations,
        "shards": {k: len(v) for k, v in sorted(shards.items())},
        "upstream_read_only": [str(DETAIL_HISTORY), str(SCAN_HISTORY)],
    }
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(index, ensure_ascii=False))
    return index


if __name__ == "__main__":
    build()
