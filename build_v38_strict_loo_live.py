#!/usr/bin/env python3
"""Build forward-only strict Leave-One-Out Peer Theme live state.

This is intentionally a live/PIT accumulator, not a historical taxonomy backfill.
For each completed market session it uses that session's ``sector_snapshot.json:s2t``
membership, computes candidate-excluded Theme RS63 and Breadth21 exactly as the
audited research, and persists the peer RS percentile needed 20 trading sessions
later.  Rank acceleration is emitted only when the snapshot for the exact market
session 20 sessions earlier exists.  Missing history therefore stays DATA REQUIRED
instead of using today's taxonomy as a historical approximation.

Research definition source:
- Run 33240190205 / Artifact 9711172105
- audit_ordinary_stock_theme_leave_one_out.py at run head d8770ef...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

MIN_THEME_MEMBERS = 3
RS_WINDOW = 63
RS_MIN_PERIODS = int(math.ceil(RS_WINDOW * 0.8))
HISTORY_KEEP_SESSIONS = 45
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _is_ticker(value: Any) -> bool:
    return isinstance(value, str) and bool(TICKER_RE.fullmatch(value.strip().upper()))


def _leaf_strings(value: Any, depth: int = 0) -> list[str]:
    """Same bounded membership-value traversal used by the research extractor."""
    if depth > 3:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_leaf_strings(item, depth + 1))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for key in ("theme", "themes", "subtheme", "subthemes", "name", "label"):
            if key in value:
                out.extend(_leaf_strings(value[key], depth + 1))
        if out:
            return out
        for item in value.values():
            out.extend(_leaf_strings(item, depth + 1))
        return out
    return []


def extract_s2t(snapshot: Any) -> dict[str, list[str]]:
    """Use only the canonical ``s2t`` route; never substitute display Theme labels."""
    node = snapshot.get("s2t") if isinstance(snapshot, dict) else None
    if not isinstance(node, dict):
        return {}
    out: dict[str, list[str]] = {}
    for raw_symbol, value in node.items():
        symbol = str(raw_symbol).strip().upper()
        if not _is_ticker(symbol):
            continue
        seen: set[str] = set()
        themes: list[str] = []
        for theme in _leaf_strings(value):
            if theme and not _is_ticker(theme) and theme not in seen:
                seen.add(theme)
                themes.append(theme)
        if themes:
            out[symbol] = themes
    return out


def invert_memberships(s2t: dict[str, list[str]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol, themes in s2t.items():
        for theme in themes:
            groups[theme].append(symbol)
    return {
        theme: sorted(set(members))
        for theme, members in groups.items()
        if len(set(members)) >= MIN_THEME_MEMBERS
    }


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def download_adjusted_close(symbols: list[str], start: str, end: str,
                            batch_size: int = 200) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Research-compatible adjusted-close downloader, batched for the full taxonomy."""
    requested = list(dict.fromkeys(symbols))
    frames: list[pd.DataFrame] = []
    failed_batches = 0
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        names = [yahoo_symbol(symbol) for symbol in batch]
        reverse = {yahoo_symbol(symbol): symbol for symbol in batch}
        try:
            raw = yf.download(
                names, start=start, end=end, auto_adjust=False, actions=False,
                progress=False, group_by="ticker", threads=True, timeout=30,
            )
        except Exception as exc:  # live route must degrade to DATA REQUIRED, not approximation
            print(f"LOO_DOWNLOAD_BATCH_FAILED pos={pos} error={type(exc).__name__}", flush=True)
            failed_batches += 1
            continue
        if raw is None or raw.empty:
            failed_batches += 1
            continue
        cols: dict[str, pd.Series] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for name in names:
                if name not in level0:
                    continue
                part = raw[name]
                field = "Adj Close" if "Adj Close" in part.columns else (
                    "Close" if "Close" in part.columns else None
                )
                if field:
                    cols[reverse[name]] = pd.to_numeric(part[field], errors="coerce")
        elif len(batch) == 1:
            field = "Adj Close" if "Adj Close" in raw.columns else (
                "Close" if "Close" in raw.columns else None
            )
            if field:
                cols[batch[0]] = pd.to_numeric(raw[field], errors="coerce")
        if cols:
            frames.append(pd.DataFrame(cols))
        print(
            f"LOO_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)} "
            f"columns={sum(frame.shape[1] for frame in frames)}",
            flush=True,
        )
    if not frames:
        raise RuntimeError("Yahoo download returned no usable adjusted-close data")
    close = pd.concat(frames, axis=1)
    close = close.loc[:, ~close.columns.duplicated()].sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.replace([np.inf, -np.inf], np.nan)
    return close, {
        "requested": len(requested),
        "downloaded": int(close.shape[1]),
        "rows": int(close.shape[0]),
        "failed_batches": failed_batches,
    }


def arithmetic_returns(close: pd.DataFrame) -> pd.DataFrame:
    ret = close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return ret.where(ret > -0.999999)


def period_return(ret: pd.DataFrame | pd.Series, window: int = RS_WINDOW):
    safe = ret.where(ret > -0.999999)
    return np.expm1(np.log1p(safe).rolling(window, min_periods=RS_MIN_PERIODS).sum())


def replacement_percentile(value: float, reference: dict[str, float], theme: str) -> float | None:
    """Scalar form of research ``_replacement_percentile`` for one pair/date."""
    if not _finite(value):
        return None
    ref = {name: float(v) for name, v in reference.items() if _finite(v)}
    if not ref:
        return None
    sorted_ref = np.sort(np.asarray(list(ref.values()), dtype=float))
    vv = float(value)
    count = float(np.searchsorted(sorted_ref, vv, side="right"))
    original = ref.get(theme)
    if original is not None and original <= vv:
        count -= 1.0
    count += 1.0
    denom = float(len(sorted_ref) + (0 if original is not None else 1))
    return count / denom * 100.0 if denom > 0 else None


def _normal_theme_snapshot(stock_ret: pd.DataFrame, theme_members: dict[str, list[str]]) -> tuple[dict[str, float], dict[str, float]]:
    theme_daily: dict[str, pd.Series] = {}
    for theme, members in theme_members.items():
        cols = [symbol for symbol in members if symbol in stock_ret.columns]
        if len(cols) < MIN_THEME_MEMBERS:
            continue
        part = stock_ret[cols]
        count = part.notna().sum(axis=1)
        theme_daily[theme] = part.mean(axis=1, skipna=True).where(count >= MIN_THEME_MEMBERS)
    if not theme_daily:
        return {}, {}
    theme_ret = pd.DataFrame(theme_daily)
    theme63 = period_return(theme_ret)
    last = theme63.iloc[-1]
    valid = last.dropna()
    pct = valid.rank(pct=True, method="average") * 100.0
    return (
        {str(theme): float(value) for theme, value in valid.items() if _finite(value)},
        {str(theme): float(value) for theme, value in pct.items() if _finite(value)},
    )


def compute_session_snapshot(close: pd.DataFrame, s2t: dict[str, list[str]], asof: pd.Timestamp) -> dict[str, Any]:
    """Compute current candidate-excluded RS63 percentile and Breadth21 for every pair."""
    close = close.loc[close.index <= asof].copy()
    if close.empty or asof not in close.index:
        raise RuntimeError(f"adjusted-close data does not contain requested asof {asof.date()}")
    theme_members = invert_memberships(s2t)
    stock_ret = arithmetic_returns(close)
    normal63, normal_pct = _normal_theme_snapshot(stock_ret, theme_members)
    if not normal63 or not normal_pct:
        raise RuntimeError("no valid normal Theme RS63 cross-section")

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)

    pair_rs: dict[str, dict[str, float]] = defaultdict(dict)
    pair_breadth: dict[str, dict[str, float]] = defaultdict(dict)
    for number, (theme, members0) in enumerate(theme_members.items(), start=1):
        members = [symbol for symbol in members0 if symbol in close.columns]
        if len(members) < MIN_THEME_MEMBERS or theme not in normal63:
            continue
        vals = stock_ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        denominator = counts[:, None] - valid.astype(np.int16)
        numerator = sums[:, None] - np.where(valid, vals, 0.0)
        peer_daily = np.divide(
            numerator, denominator,
            out=np.full_like(numerator, np.nan, dtype=float),
            where=denominator >= 2,
        )
        peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
        peer63 = np.expm1(
            pd.DataFrame(peer_log, index=close.index)
            .rolling(RS_WINDOW, min_periods=RS_MIN_PERIODS).sum()
            .iloc[-1].to_numpy(float)
        )

        vb = valid_b[members].iloc[-1].to_numpy(bool)
        ab = above_b[members].iloc[-1].astype(float).fillna(0.0).to_numpy(float)
        total_valid = int(vb.sum())
        total_above = float(ab.sum())
        for j, symbol in enumerate(members):
            peer_pct = replacement_percentile(peer63[j], normal63, theme)
            peer_valid = total_valid - int(vb[j])
            peer_above = total_above - float(ab[j])
            breadth = peer_above * 100.0 / peer_valid if peer_valid >= 2 else None
            if peer_pct is not None and _finite(peer_pct):
                pair_rs[symbol][theme] = float(peer_pct)
            if breadth is not None and _finite(breadth):
                pair_breadth[symbol][theme] = float(breadth)
        if number % 25 == 0 or number == len(theme_members):
            print(f"LOO_THEME {number}/{len(theme_members)} pairs={sum(len(x) for x in pair_rs.values())}", flush=True)

    taxonomy_payload = json.dumps(s2t, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "asof": str(asof.date()),
        "taxonomy_sha256": hashlib.sha256(taxonomy_payload.encode("utf-8")).hexdigest(),
        "normal_theme_rs63_pct": normal_pct,
        "peer_theme_rs63_pct": dict(pair_rs),
        "peer_breadth21_pct": dict(pair_breadth),
        "theme_count": len(theme_members),
        "pair_count": sum(len(values) for values in pair_rs.values()),
    }


def _upsert_history(history: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    sessions = [row for row in history.get("sessions", []) if isinstance(row, dict) and row.get("asof")]
    sessions = [row for row in sessions if row.get("asof") != session["asof"]]
    sessions.append(session)
    sessions.sort(key=lambda row: str(row["asof"]))
    sessions = sessions[-HISTORY_KEEP_SESSIONS:]
    return {"schema": "v38-strict-loo-history-1", "sessions": sessions}


def build_live(history: dict[str, Any], s2t: dict[str, list[str]], current: dict[str, Any],
               expected_base_asof: str | None) -> dict[str, Any]:
    sessions = [row for row in history.get("sessions", []) if isinstance(row, dict)]
    by_date = {str(row.get("asof")): row for row in sessions if row.get("asof")}
    old = by_date.get(expected_base_asof) if expected_base_asof else None
    current_normal = current.get("normal_theme_rs63_pct", {})
    current_peer = current.get("peer_theme_rs63_pct", {})
    current_breadth = current.get("peer_breadth21_pct", {})

    normal_delta: dict[str, float] = {}
    if old:
        old_normal = old.get("normal_theme_rs63_pct", {})
        for theme, value in current_normal.items():
            if _finite(value) and _finite(old_normal.get(theme)):
                normal_delta[theme] = float(value) - float(old_normal[theme])

    candidates: dict[str, Any] = {}
    for symbol, memberships in s2t.items():
        themes: dict[str, Any] = {}
        old_peer_map = (old.get("peer_theme_rs63_pct", {}).get(symbol, {})
                        if isinstance(old, dict) else {})
        for theme in memberships:
            peer_now = current_peer.get(symbol, {}).get(theme)
            breadth_now = current_breadth.get(symbol, {}).get(theme)
            peer_old = old_peer_map.get(theme) if isinstance(old_peer_map, dict) else None
            if not (_finite(peer_now) and _finite(breadth_now) and _finite(peer_old)):
                continue
            peer_delta = float(peer_now) - float(peer_old)
            acceleration_pct = replacement_percentile(peer_delta, normal_delta, theme)
            if acceleration_pct is None or not _finite(acceleration_pct):
                continue
            themes[theme] = {
                "theme_rs63_pct": float(peer_now),
                "acceleration20_pct": float(acceleration_pct),
                "breadth21_pct": float(breadth_now),
                "candidate_excluded_from_return": True,
                "candidate_excluded_from_acceleration": True,
                "candidate_excluded_from_breadth21": True,
                "acceleration_base_asof": expected_base_asof,
            }
        history_ready = old is not None
        candidates[symbol] = {
            "status": "READY" if history_ready else "DATA REQUIRED",
            "history_sessions": len(sessions),
            "expected_acceleration_base_asof": expected_base_asof,
            "themes": themes,
            "no_valid_theme": bool(history_ready and not themes),
        }

    return {
        "schema": "v38-strict-loo-live-1",
        "asof": current.get("asof"),
        "status": "READY" if old is not None else "DATA REQUIRED",
        "history_sessions": len(sessions),
        "expected_acceleration_base_asof": expected_base_asof,
        "history_has_exact_20_session_base": old is not None,
        "membership_source": "sector_snapshot.json:s2t",
        "pit_policy": "FORWARD_ONLY_SAVED_SNAPSHOTS; NO_CURRENT_TAXONOMY_BACKFILL",
        "candidate_exclusion": ["Theme Return", "Theme Rank Acceleration", "Theme Breadth21"],
        "coverage": {
            "theme_count": current.get("theme_count"),
            "theme_stock_pairs": current.get("pair_count"),
            "taxonomy_sha256": current.get("taxonomy_sha256"),
        },
        "candidates": candidates,
    }


def _data_required_live(asof: str | None, reason: str) -> dict[str, Any]:
    return {
        "schema": "v38-strict-loo-live-1",
        "asof": asof,
        "status": "DATA REQUIRED",
        "reason": reason,
        "history_has_exact_20_session_base": False,
        "membership_source": "sector_snapshot.json:s2t",
        "pit_policy": "FORWARD_ONLY_SAVED_SNAPSHOTS; NO_CURRENT_TAXONOMY_BACKFILL",
        "candidates": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="state.json")
    parser.add_argument("--sector-snapshot", default="sector_snapshot.json")
    parser.add_argument("--history", default="v38-strict-loo-history.json")
    parser.add_argument("--out", default="v38-strict-loo-live.json")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    state = _load_json(Path(args.state), {})
    asof_text = str(state.get("date") or "")
    out_path = Path(args.out)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", asof_text):
        out_path.write_text(json.dumps(_data_required_live(None, "STATE_DATE_REQUIRED"), indent=2) + "\n")
        return
    asof = pd.Timestamp(asof_text)
    snapshot = _load_json(Path(args.sector_snapshot), {})
    s2t = extract_s2t(snapshot)
    if not s2t:
        out_path.write_text(json.dumps(_data_required_live(asof_text, "S2T_MEMBERSHIP_REQUIRED"), indent=2) + "\n")
        return

    symbols = sorted({symbol for symbol in s2t})
    start = str((asof - pd.Timedelta(days=170)).date())
    end = str((asof + pd.Timedelta(days=1)).date())
    try:
        close, quality = download_adjusted_close(symbols, start, end, args.batch_size)
        close = close.loc[close.index <= asof]
        if asof not in close.index:
            raise RuntimeError(f"PRICE_ASOF_REQUIRED latest={close.index.max() if len(close) else None}")
        market_sessions = list(close.index.unique())
        current_pos = market_sessions.index(asof)
        expected_base = market_sessions[current_pos - 20] if current_pos >= 20 else None
        current = compute_session_snapshot(close, s2t, asof)
        current["download_quality"] = quality
        history_path = Path(args.history)
        history = _load_json(history_path, {"schema": "v38-strict-loo-history-1", "sessions": []})
        history = _upsert_history(history, current)
        history_path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        live = build_live(history, s2t, current, str(expected_base.date()) if expected_base is not None else None)
    except Exception as exc:
        live = _data_required_live(asof_text, f"{type(exc).__name__}: {exc}")
        print(f"LOO_LIVE_DATA_REQUIRED {type(exc).__name__}: {exc}", flush=True)
    out_path.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {out_path}: status={live.get('status')} asof={live.get('asof')} "
        f"history={live.get('history_sessions')}", flush=True,
    )


if __name__ == "__main__":
    main()
