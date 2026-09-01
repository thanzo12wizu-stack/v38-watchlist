#!/usr/bin/env python3
"""Run the audited sleeve builder with guarded live price acquisition.

Normal Stock keeps the existing narrow Yahoo Chart fallback. RSI Reset keeps the
same strategy/universe, but its large OHLC route is fail-closed: validated cache
is reused, missing batches are retried, real-data coverage is checked, and an
incomplete rebuild is never allowed to replace a previously READY live state.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import build_v38_sleeve_live as live
from build_v38_tqqq_live import download_yahoo_chart

_BASE_DOWNLOAD = live.download_adjusted_ohlc

RESET_LARGE_REQUEST_THRESHOLD = 50
RESET_CACHE_ENV = "V38_RESET_CACHE_DIR"
RESET_CACHE_DEFAULT = ".cache/v38-reset-prices"
RESET_CACHE_OPEN = "reset-open.pkl.gz"
RESET_CACHE_CLOSE = "reset-close.pkl.gz"
RESET_REQUIRED_HISTORY_SESSIONS = 84
RESET_MIN_HISTORY_COVERAGE = 0.85
RESET_MIN_TARGET_COVERAGE = 0.85
RESET_MIN_RECENT_MEDIAN_COVERAGE = 0.85
RESET_BATCH_SIZE = 100
RESET_BATCH_RETRIES = 3
RESET_RETRY_SLEEP_SECONDS = 1.5
RESET_INTER_BATCH_SLEEP_SECONDS = 0.15
RESET_RECENT_REFRESH_DAYS = 12


class ResetPriceCoverageError(RuntimeError):
    """Raised when Reset OHLC cannot be proven complete enough for live use."""


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    return out.sort_index().replace([np.inf, -np.inf], np.nan)


def _merge_non_null(base: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if base.empty:
        return _normalize(fresh) if not fresh.empty else fresh.copy()
    if fresh.empty:
        return _normalize(base)
    left = _normalize(base)
    right = _normalize(fresh)
    index = left.index.union(right.index)
    columns = left.columns.union(right.columns)
    out = left.reindex(index=index, columns=columns)
    out.update(right.reindex(index=index, columns=columns))
    return _normalize(out)


def _cache_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get(RESET_CACHE_ENV, RESET_CACHE_DEFAULT))
    return root / RESET_CACHE_OPEN, root / RESET_CACHE_CLOSE


def _read_cached_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        value = pd.read_pickle(path, compression="gzip")
    except Exception as exc:
        print(f"SLEEVE_RESET_CACHE_READ_FAILED {path} {type(exc).__name__}", flush=True)
        return pd.DataFrame()
    return _normalize(value) if isinstance(value, pd.DataFrame) and not value.empty else pd.DataFrame()


def _write_cached_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_pickle(tmp, compression="gzip")
    os.replace(tmp, path)


def _bounded(frame: pd.DataFrame, requested: list[str], start: str, end: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=requested)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = _normalize(frame)
    out = out.loc[(out.index >= start_ts) & (out.index < end_ts)]
    return out.reindex(columns=requested)


def _valid_ohlc(op: pd.DataFrame, cl: pd.DataFrame, requested: list[str], start: str, end: str) -> pd.DataFrame:
    opw = _bounded(op, requested, start, end)
    clw = _bounded(cl, requested, start, end)
    index = opw.index.union(clw.index)
    opw = opw.reindex(index=index, columns=requested).apply(pd.to_numeric, errors="coerce")
    clw = clw.reindex(index=index, columns=requested).apply(pd.to_numeric, errors="coerce")
    opw = opw.replace([np.inf, -np.inf], np.nan)
    clw = clw.replace([np.inf, -np.inf], np.nan)
    return opw.notna() & clw.notna() & (opw > 0) & (clw > 0)


def reset_price_coverage(
    op: pd.DataFrame, cl: pd.DataFrame, requested: list[str], start: str, end: str
) -> dict[str, Any]:
    requested = list(dict.fromkeys(requested))
    valid = _valid_ohlc(op, cl, requested, start, end)
    target = pd.Timestamp(end).normalize() - pd.Timedelta(days=1)
    requested_count = len(requested)
    if requested_count == 0:
        return {
            "coverage_ok": False,
            "reason": "NO_RESET_SYMBOLS",
            "requested": 0,
            "target_date": str(target.date()),
        }

    history_counts = valid.sum(axis=0) if not valid.empty else pd.Series(0, index=requested, dtype=float)
    history_ready = int((history_counts >= RESET_REQUIRED_HISTORY_SESSIONS).sum())
    any_valid = int((history_counts > 0).sum())

    if target in valid.index:
        target_valid = int(valid.loc[target].sum())
    else:
        target_valid = 0

    recent = valid.tail(min(20, len(valid.index)))
    recent_median = float(recent.mean(axis=1).median()) if not recent.empty else 0.0

    history_ratio = history_ready / requested_count
    target_ratio = target_valid / requested_count
    coverage_ok = (
        len(valid.index) >= RESET_REQUIRED_HISTORY_SESSIONS
        and history_ratio >= RESET_MIN_HISTORY_COVERAGE
        and target_ratio >= RESET_MIN_TARGET_COVERAGE
        and recent_median >= RESET_MIN_RECENT_MEDIAN_COVERAGE
    )
    reason = (
        "READY"
        if coverage_ok
        else (
            "INSUFFICIENT_SESSION_ROWS"
            if len(valid.index) < RESET_REQUIRED_HISTORY_SESSIONS
            else "HISTORY_COVERAGE_LOW"
            if history_ratio < RESET_MIN_HISTORY_COVERAGE
            else "TARGET_DATE_COVERAGE_LOW"
            if target_ratio < RESET_MIN_TARGET_COVERAGE
            else "RECENT_COVERAGE_LOW"
        )
    )
    return {
        "coverage_ok": coverage_ok,
        "reason": reason,
        "requested": requested_count,
        "downloaded": any_valid,
        "history_required_sessions": RESET_REQUIRED_HISTORY_SESSIONS,
        "history_ready_symbols": history_ready,
        "history_coverage_ratio": history_ratio,
        "target_date": str(target.date()),
        "target_valid_symbols": target_valid,
        "target_coverage_ratio": target_ratio,
        "recent_median_coverage_ratio": recent_median,
        "window_rows": int(len(valid.index)),
    }


def _symbol_target_valid(op: pd.DataFrame, cl: pd.DataFrame, symbol: str, target: pd.Timestamp) -> bool:
    try:
        a = float(op.at[target, symbol])
        b = float(cl.at[target, symbol])
        return math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0
    except Exception:
        return False


def _symbol_history_ready(op: pd.DataFrame, cl: pd.DataFrame, symbol: str, start: str, end: str) -> bool:
    valid = _valid_ohlc(op, cl, [symbol], start, end)
    return not valid.empty and int(valid[symbol].sum()) >= RESET_REQUIRED_HISTORY_SESSIONS


def _reset_batch_download(
    batch: list[str],
    op: pd.DataFrame,
    cl: pd.DataFrame,
    start: str,
    end: str,
    batch_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    target = pd.Timestamp(end).normalize() - pd.Timedelta(days=1)
    merged_op, merged_cl = op, cl
    failures = 0
    retry_rounds = 0

    for attempt in range(RESET_BATCH_RETRIES):
        pending = [
            s for s in batch
            if (
                not _symbol_target_valid(merged_op, merged_cl, s, target)
                or not _symbol_history_ready(merged_op, merged_cl, s, start, end)
            )
        ]
        if not pending:
            break

        # On a warm cache, existing symbols only need a short overlap to add the
        # new completed session. Symbols without enough cached history get the
        # full Reset lookback so their eligibility is not silently degraded.
        need_full = [
            s for s in pending if not _symbol_history_ready(merged_op, merged_cl, s, start, end)
        ]
        full_set = set(need_full)
        short = [s for s in pending if s not in full_set]
        groups: list[tuple[list[str], str]] = []
        if need_full:
            groups.append((need_full, start))
        if short:
            recent_start = max(
                pd.Timestamp(start),
                target - pd.Timedelta(days=RESET_RECENT_REFRESH_DAYS),
            )
            groups.append((short, str(recent_start.date())))

        retry_rounds = max(retry_rounds, attempt)
        for names, fetch_start in groups:
            try:
                fresh_op, fresh_cl, _ = _BASE_DOWNLOAD(
                    names, fetch_start, end, min(batch_size, max(1, len(names)))
                )
            except Exception as exc:
                failures += 1
                print(
                    f"SLEEVE_RESET_BATCH_FAILED attempt={attempt + 1} "
                    f"symbols={len(names)} {type(exc).__name__}",
                    flush=True,
                )
                continue
            merged_op = _merge_non_null(merged_op, fresh_op)
            merged_cl = _merge_non_null(merged_cl, fresh_cl)

        batch_target_ratio = (
            sum(_symbol_target_valid(merged_op, merged_cl, s, target) for s in batch)
            / max(1, len(batch))
        )
        batch_history_ratio = (
            sum(_symbol_history_ready(merged_op, merged_cl, s, start, end) for s in batch)
            / max(1, len(batch))
        )
        if (
            batch_target_ratio >= RESET_MIN_TARGET_COVERAGE
            and batch_history_ratio >= RESET_MIN_HISTORY_COVERAGE
        ):
            break
        if attempt + 1 < RESET_BATCH_RETRIES:
            time.sleep(RESET_RETRY_SLEEP_SECONDS * (attempt + 1))

    return merged_op, merged_cl, failures, retry_rounds


def _download_reset_cached(
    requested: list[str], start: str, end: str, batch_size: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    open_path, close_path = _cache_paths()
    cached_op = _read_cached_frame(open_path)
    cached_cl = _read_cached_frame(close_path)
    cached_op = _bounded(cached_op, requested, start, end)
    cached_cl = _bounded(cached_cl, requested, start, end)

    cached_quality = reset_price_coverage(cached_op, cached_cl, requested, start, end)
    if cached_quality["coverage_ok"]:
        quality = {
            **cached_quality,
            "source": "VALIDATED_CACHE",
            "cache_hit": True,
            "failed_batches": 0,
            "retry_rounds": 0,
        }
        print(
            "SLEEVE_RESET_CACHE_HIT "
            f"target={quality['target_date']} "
            f"target_coverage={quality['target_coverage_ratio']:.3f}",
            flush=True,
        )
        return cached_op, cached_cl, quality

    merged_op, merged_cl = cached_op, cached_cl
    failed_batches = 0
    retry_rounds = 0
    effective_batch_size = min(max(1, batch_size), RESET_BATCH_SIZE)

    for pos in range(0, len(requested), effective_batch_size):
        batch = requested[pos:pos + effective_batch_size]
        merged_op, merged_cl, failures, retries = _reset_batch_download(
            batch, merged_op, merged_cl, start, end, effective_batch_size
        )
        failed_batches += failures
        retry_rounds = max(retry_rounds, retries)
        print(
            f"SLEEVE_RESET_DOWNLOAD {min(pos + effective_batch_size, len(requested))}/{len(requested)}",
            flush=True,
        )
        if RESET_INTER_BATCH_SLEEP_SECONDS > 0:
            time.sleep(RESET_INTER_BATCH_SLEEP_SECONDS)

    merged_op = _bounded(merged_op, requested, start, end)
    merged_cl = _bounded(merged_cl, requested, start, end)
    quality = reset_price_coverage(merged_op, merged_cl, requested, start, end)
    quality.update(
        {
            "source": "CACHE_PLUS_BATCH_RETRY",
            "cache_hit": False,
            "failed_batches": failed_batches,
            "retry_rounds": retry_rounds,
        }
    )

    if not quality["coverage_ok"]:
        raise ResetPriceCoverageError(
            "RESET_PRICE_COVERAGE_INSUFFICIENT "
            f"reason={quality['reason']} "
            f"history={quality.get('history_coverage_ratio', 0):.3f} "
            f"target={quality.get('target_coverage_ratio', 0):.3f} "
            f"recent={quality.get('recent_median_coverage_ratio', 0):.3f}"
        )

    # Cache is updated only after the full Reset window passes the guard.
    _write_cached_frame(open_path, merged_op)
    _write_cached_frame(close_path, merged_cl)
    print(
        "SLEEVE_RESET_COVERAGE_READY "
        f"history={quality['history_coverage_ratio']:.3f} "
        f"target={quality['target_coverage_ratio']:.3f} "
        f"recent={quality['recent_median_coverage_ratio']:.3f}",
        flush=True,
    )
    return merged_op, merged_cl, quality


def download_adjusted_ohlc_resilient(
    symbols: list[str], start: str, end: str, batch_size: int = 150
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))

    if len(requested) > RESET_LARGE_REQUEST_THRESHOLD:
        return _download_reset_cached(requested, start, end, batch_size)

    # Normal Stock path: preserve the existing narrow per-symbol fallback.
    try:
        op, cl, quality = _BASE_DOWNLOAD(requested, start, end, batch_size)
    except RuntimeError as exc:
        if "SLEEVE_PRICE_DOWNLOAD_EMPTY" not in str(exc):
            raise
        op = pd.DataFrame()
        cl = pd.DataFrame()
        quality = {"requested": len(requested), "downloaded": 0, "failed_batches": 1}

    op = _normalize(op) if not op.empty else op
    cl = _normalize(cl) if not cl.empty else cl
    missing = [
        symbol for symbol in requested
        if symbol not in cl.columns or cl[symbol].dropna().empty
    ]
    fallback_used: list[str] = []
    fallback_failed: dict[str, str] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    for symbol in missing:
        try:
            frame = _normalize(download_yahoo_chart(symbol, start=start))
            frame = frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]
            if frame.empty:
                raise RuntimeError("empty fallback range")
            if "Open" not in frame.columns or "Close" not in frame.columns:
                raise RuntimeError("fallback missing OHLC")
            op[symbol] = pd.to_numeric(frame["Open"], errors="coerce")
            cl[symbol] = pd.to_numeric(frame["Close"], errors="coerce")
            if cl[symbol].dropna().empty:
                raise RuntimeError("fallback close empty")
            fallback_used.append(symbol)
            print(f"SLEEVE_NORMAL_FALLBACK {symbol} YAHOO_CHART", flush=True)
        except Exception as exc:
            fallback_failed[symbol] = f"{type(exc).__name__}: {exc}"
            print(
                f"SLEEVE_NORMAL_FALLBACK_FAILED {symbol} "
                f"{fallback_failed[symbol]}",
                flush=True,
            )

    if op.empty or cl.empty:
        raise RuntimeError("SLEEVE_NORMAL_PRICE_DOWNLOAD_EMPTY_AFTER_FALLBACK")

    quality = dict(quality or {})
    quality["fallback_used"] = fallback_used
    quality["fallback_failed"] = fallback_failed
    quality["downloaded"] = int(cl.shape[1])
    return _normalize(op), _normalize(cl), quality


def _reset_display_candidate(row: dict[str, Any]) -> bool:
    """Keep only strong, still-actionable Reset names in the published monitor."""
    status = str(row.get("status") or "")
    if status in {"ACTIVE_POSITION", "SIGNAL_TODAY_NEXT_OPEN"}:
        return True
    if status == "SIGNAL_OCCURRED" or row.get("current_theme_rs63_top3") is not True:
        return False
    try:
        days_left = int(row.get("signal_window_days_left"))
        distance = float(row.get("distance_to_30"))
    except (TypeError, ValueError):
        return False
    return days_left > 0 and math.isfinite(distance) and distance <= 10.0


def _filter_reset_monitor(path: Path) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    reset = state.get("rsi_reset")
    if not isinstance(reset, dict) or not isinstance(reset.get("monitor"), list):
        return

    visible = [row for row in reset["monitor"] if isinstance(row, dict) and _reset_display_candidate(row)]
    reset["monitor"] = visible
    reset["monitor_summary"] = {
        "active_positions": sum(str(row.get("status") or "") == "ACTIVE_POSITION" for row in visible),
        "signal_today": sum(str(row.get("status") or "") == "SIGNAL_TODAY_NEXT_OPEN" for row in visible),
        "touched_wait_rise": sum(str(row.get("status") or "") == "RSI30_TOUCHED_WAIT_RISE" for row in visible),
        "within_5pt": sum(
            math.isfinite(float(row.get("distance_to_30"))) and float(row.get("distance_to_30")) <= 5.0
            for row in visible
            if row.get("distance_to_30") is not None
        ),
        "within_10pt": sum(
            math.isfinite(float(row.get("distance_to_30"))) and float(row.get("distance_to_30")) <= 10.0
            for row in visible
            if row.get("distance_to_30") is not None
        ),
        "watch_count": len(visible),
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SLEEVE_RESET_DISPLAY_FILTER {len(visible)} strong actionable names", flush=True)


def _argument_path(flag: str, default: str) -> Path:
    try:
        idx = sys.argv.index(flag)
        return Path(sys.argv[idx + 1])
    except (ValueError, IndexError):
        return Path(default)


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _attempted_asof(failed_payload: dict[str, Any]) -> str | None:
    value = str(failed_payload.get("asof") or "").strip()
    if value:
        return value
    companion = _load_payload(_argument_path("--companion", "v38-live-state.json"))
    value = str(companion.get("asof") or "").strip()
    return value or None


def _refresh_metadata(*, status: str, attempted_asof: str | None,
                      last_successful_asof: str | None, preserved: bool,
                      error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "attempted_at_utc": _utc_now_iso(),
        "attempted_asof": attempted_asof,
        "last_successful_asof": last_successful_asof,
        "preserved_previous_ready": preserved,
        "error": error,
    }


def _ready_sleeve_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "READY"
        and isinstance(payload.get("rsi_reset"), dict)
        and payload["rsi_reset"].get("status") == "READY"
    )


def _validate_guarded_output(path: Path) -> dict[str, Any]:
    payload = _load_payload(path)
    if not _ready_sleeve_payload(payload):
        raise ResetPriceCoverageError("RESET_REBUILD_NOT_READY")
    quality = payload["rsi_reset"].get("download_quality")
    if not isinstance(quality, dict) or quality.get("coverage_ok") is not True:
        raise ResetPriceCoverageError(
            f"RESET_REBUILD_COVERAGE_NOT_PROVEN quality={quality}"
        )
    return payload


def _restore_bytes(backups: dict[Path, bytes]) -> None:
    for path, value in backups.items():
        path.write_bytes(value)


def run_guarded_refresh(runner: Callable[[], None] | None = None, *,
                        continue_with_previous_ready: bool = False) -> dict[str, Any]:
    out = _argument_path("--out", "v38-sleeve-state.json")
    tqqq_state = _argument_path("--tqqq-state", "tqqq-panic-state.json")
    previous = _load_payload(out)
    previous_ready = _ready_sleeve_payload(previous)
    backups = {
        path: path.read_bytes()
        for path in (out, tqqq_state)
        if path.is_file()
    }

    try:
        live.download_adjusted_ohlc = download_adjusted_ohlc_resilient
        (runner or live.main)()
        _filter_reset_monitor(out)
        payload = _validate_guarded_output(out)
        payload["refresh"] = _refresh_metadata(
            status="FRESH",
            attempted_asof=str(payload.get("asof") or "") or None,
            last_successful_asof=str(payload.get("asof") or "") or None,
            preserved=False,
            error=None,
        )
        _write_payload(out, payload)
        return payload
    except BaseException as exc:
        failed_payload = _load_payload(out)
        attempted_asof = _attempted_asof(failed_payload)
        if previous_ready:
            _restore_bytes(backups)
            failed_reason = str(failed_payload.get("reason") or "").strip()
            error_text = failed_reason or f"{type(exc).__name__}: {exc}"
            if continue_with_previous_ready:
                preserved = _load_payload(out)
                last_successful_asof = str(preserved.get("asof") or "") or None
                preserved["refresh"] = _refresh_metadata(
                    status="STALE / LAST_READY_PRESERVED",
                    attempted_asof=attempted_asof,
                    last_successful_asof=last_successful_asof,
                    preserved=True,
                    error=error_text,
                )
                _write_payload(out, preserved)

                same_session = bool(
                    attempted_asof and last_successful_asof
                    and str(attempted_asof) == str(last_successful_asof)
                )
                normal_pct = (preserved.get("normal_stock") or {}).get("desired_pct")
                reset_pct = (preserved.get("rsi_reset") or {}).get("desired_pct")
                merge_asof = str(attempted_asof or last_successful_asof or "")
                live._merge_desired_into_tqqq(
                    tqqq_state, merge_asof,
                    normal_pct if same_session else None,
                    reset_pct if same_session else None,
                    "READY" if same_session else "DATA REQUIRED",
                    error_text,
                )
                tqqq_payload = _load_payload(tqqq_state)
                tqqq_payload["sleeve_live_status"] = (
                    "READY" if same_session else "STALE / LAST_READY_PRESERVED"
                )
                tqqq_payload["sleeve_live_reason"] = (
                    "STALE / LAST_READY_PRESERVED: " + error_text
                )
                _write_payload(tqqq_state, tqqq_payload)
                print(
                    "SLEEVE_REFRESH_FAILED_LAST_READY_PRESERVED "
                    f"attempted_asof={attempted_asof} "
                    f"last_successful_asof={last_successful_asof} "
                    f"same_session={same_session} {error_text}",
                    flush=True,
                )
                return preserved

            print(
                "SLEEVE_REFRESH_REJECTED_KEEP_PREVIOUS_READY "
                f"{error_text}",
                flush=True,
            )
        raise


def _stable_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 12) if math.isfinite(number) else None


def reset_reproducibility_payload(state: dict[str, Any]) -> dict[str, Any]:
    reset = state.get("rsi_reset") if isinstance(state, dict) else None
    if not isinstance(reset, dict):
        raise ValueError("rsi_reset missing")
    positions = []
    for row in reset.get("positions", []):
        if not isinstance(row, dict):
            continue
        positions.append(
            {
                "symbol": row.get("symbol"),
                "theme": row.get("theme"),
                "entry_date": row.get("entry_date"),
                "exit_i": row.get("exit_i"),
                "shares": _stable_float(row.get("shares")),
                "close": _stable_float(row.get("close")),
                "mark": _stable_float(row.get("mark")),
            }
        )
    positions.sort(key=lambda x: (str(x["symbol"]), str(x["entry_date"]), str(x["theme"])))

    live_signals = []
    for row in reset.get("monitor", []):
        if not isinstance(row, dict) or not row.get("signal_date"):
            continue
        live_signals.append(
            {
                "symbol": row.get("symbol"),
                "theme": row.get("theme"),
                "signal_date": row.get("signal_date"),
                "status": row.get("status"),
            }
        )
    live_signals.sort(key=lambda x: (str(x["signal_date"]), str(x["symbol"]), str(x["theme"])))

    return {
        "asof": reset.get("asof"),
        "strategy": reset.get("strategy"),
        "desired_pct": _stable_float(reset.get("desired_pct")),
        "position_count": reset.get("position_count"),
        "positions": positions,
        "signal_count_in_rebuild_window": reset.get("signal_count_in_rebuild_window"),
        "accepted_in_rebuild_window": reset.get("accepted_in_rebuild_window"),
        "visible_signals": live_signals,
    }


def main(*, continue_with_previous_ready: bool = False) -> None:
    run_guarded_refresh(continue_with_previous_ready=continue_with_previous_ready)


if __name__ == "__main__":
    main()
