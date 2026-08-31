#!/usr/bin/env python3
"""Build forward-only strict Leave-One-Out Peer Theme live state.

This is a live/PIT accumulator with a bounded bootstrap from the first verified
Git-saved taxonomy. It never applies a taxonomy before its saved effective date.
On the first run it computes the current and exact t-20 session snapshots in one
pass, so rank acceleration can be READY immediately when both taxonomy coverage
and market data are available. Missing PIT coverage stays DATA REQUIRED.

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
import subprocess
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
PIT_BOOTSTRAP_COMMIT = "79073ffd9742102c2b6e9f72d349801a10e126db"
PIT_BOOTSTRAP_EFFECTIVE_ASOF = "2026-06-22"
PIT_BOOTSTRAP_PATH = "sector_snapshot.json"
PIT_BOOTSTRAP_BLOB_SHA = "18ce2ed94b72cc2f7c6e0c2954f2d975b566a7ad"
PIT_BOOTSTRAP_TAXONOMY_SHA256 = "dfa417586b4de5436cbfc64f2df5098ca9fd8081f235efe4b4f276b870b83e39"
PIT_BOOTSTRAP_SOURCE = f"git:{PIT_BOOTSTRAP_COMMIT}:{PIT_BOOTSTRAP_PATH}"


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


def taxonomy_sha256(s2t: dict[str, list[str]]) -> str:
    payload = json.dumps(s2t, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_verified_git_taxonomy(commit: str = PIT_BOOTSTRAP_COMMIT,
                               path: str = PIT_BOOTSTRAP_PATH) -> dict[str, list[str]]:
    """Load exactly the audited first saved taxonomy, never an approximate substitute."""
    blob = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if commit == PIT_BOOTSTRAP_COMMIT and path == PIT_BOOTSTRAP_PATH:
        if blob != PIT_BOOTSTRAP_BLOB_SHA:
            raise RuntimeError(f"PIT_BOOTSTRAP_BLOB_MISMATCH {blob}")
    raw = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        check=True, capture_output=True, text=True,
    ).stdout
    s2t = extract_s2t(json.loads(raw))
    if not s2t:
        raise RuntimeError("PIT_BOOTSTRAP_S2T_REQUIRED")
    if commit == PIT_BOOTSTRAP_COMMIT and path == PIT_BOOTSTRAP_PATH:
        digest = taxonomy_sha256(s2t)
        if digest != PIT_BOOTSTRAP_TAXONOMY_SHA256:
            raise RuntimeError(f"PIT_BOOTSTRAP_TAXONOMY_MISMATCH {digest}")
    return s2t


def register_taxonomy_snapshot(history: dict[str, Any], effective_asof: str,
                               s2t: dict[str, list[str]], source: str) -> dict[str, Any]:
    """Persist only changed PIT memberships and retain the earliest known effective date."""
    out = dict(history)
    rows = [dict(row) for row in out.get("taxonomy_snapshots", [])
            if isinstance(row, dict) and row.get("effective_asof") and isinstance(row.get("s2t"), dict)]
    digest = taxonomy_sha256(s2t)
    matching = next((row for row in rows if row.get("taxonomy_sha256") == digest), None)
    if matching is not None:
        if effective_asof < str(matching["effective_asof"]):
            matching["effective_asof"] = effective_asof
            matching["source"] = source
        matching["last_seen_asof"] = max(str(matching.get("last_seen_asof") or effective_asof), effective_asof)
    else:
        rows.append({
            "effective_asof": effective_asof,
            "last_seen_asof": effective_asof,
            "taxonomy_sha256": digest,
            "source": source,
            "s2t": s2t,
        })
    rows.sort(key=lambda row: str(row["effective_asof"]))
    out["taxonomy_snapshots"] = rows
    return out


def has_verified_bootstrap(history: dict[str, Any]) -> bool:
    return any(
        isinstance(row, dict)
        and row.get("source") == PIT_BOOTSTRAP_SOURCE
        and row.get("effective_asof") == PIT_BOOTSTRAP_EFFECTIVE_ASOF
        and row.get("taxonomy_sha256") == PIT_BOOTSTRAP_TAXONOMY_SHA256
        and isinstance(row.get("s2t"), dict)
        and bool(row["s2t"])
        for row in history.get("taxonomy_snapshots", [])
    )


def taxonomy_for_asof(history: dict[str, Any], asof: str) -> tuple[dict[str, list[str]], dict[str, Any]]:
    eligible = [row for row in history.get("taxonomy_snapshots", [])
                if isinstance(row, dict) and str(row.get("effective_asof") or "") <= asof
                and isinstance(row.get("s2t"), dict)]
    if not eligible:
        raise RuntimeError(f"PIT_TAXONOMY_REQUIRED asof={asof}")
    row = max(eligible, key=lambda item: str(item["effective_asof"]))
    return row["s2t"], row


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

    return {
        "asof": str(asof.date()),
        "taxonomy_sha256": taxonomy_sha256(s2t),
        "normal_theme_rs63_pct": normal_pct,
        "peer_theme_rs63_pct": dict(pair_rs),
        "peer_breadth21_pct": dict(pair_breadth),
        "theme_count": len(theme_members),
        "pair_count": sum(len(values) for values in pair_rs.values()),
    }


def _upsert_history(history: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    out = dict(history)
    sessions = [row for row in history.get("sessions", []) if isinstance(row, dict) and row.get("asof")]
    sessions = [row for row in sessions if row.get("asof") != session["asof"]]
    sessions.append(session)
    sessions.sort(key=lambda row: str(row["asof"]))
    sessions = sessions[-HISTORY_KEEP_SESSIONS:]
    out.update({"schema": "v38-strict-loo-history-1", "sessions": sessions})
    return out


def backfill_required_snapshots(history: dict[str, Any], close: pd.DataFrame,
                                asof: pd.Timestamp) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Compute current and exact t-20 snapshots from their PIT taxonomies.

    Intermediate sessions are represented by verified PIT coverage metadata;
    only the two endpoints required by the audited acceleration formula are
    expensive to compute and persist.
    """
    close = close.loc[close.index <= asof]
    market_sessions = list(close.index.unique())
    if asof not in market_sessions:
        raise RuntimeError(f"PRICE_ASOF_REQUIRED latest={close.index.max() if len(close) else None}")
    current_pos = market_sessions.index(asof)
    if current_pos < 20:
        raise RuntimeError("TWENTY_SESSION_PRICE_HISTORY_REQUIRED")
    base_asof = market_sessions[current_pos - 20]
    required = (base_asof, asof)
    by_date = {str(row.get("asof")): row for row in history.get("sessions", [])
               if isinstance(row, dict) and row.get("asof")}
    out = history
    generated: dict[str, dict[str, Any]] = {}
    for target in required:
        target_text = str(target.date())
        taxonomy, taxonomy_row = taxonomy_for_asof(out, target_text)
        existing = by_date.get(target_text)
        if existing is not None and existing.get("taxonomy_sha256") == taxonomy_row.get("taxonomy_sha256"):
            session = existing
        else:
            session = compute_session_snapshot(close, taxonomy, target)
            session["taxonomy_effective_asof"] = taxonomy_row["effective_asof"]
            session["taxonomy_source"] = taxonomy_row.get("source")
            out = _upsert_history(out, session)
            by_date[target_text] = session
        generated[target_text] = session

    earliest_effective = min(str(row["effective_asof"]) for row in out.get("taxonomy_snapshots", []))
    covered = [session for session in market_sessions
               if earliest_effective <= str(session.date()) <= str(asof.date())]
    out["covered_market_sessions"] = len(covered)
    out["coverage_start_asof"] = str(covered[0].date()) if covered else None
    out["coverage_end_asof"] = str(asof.date())
    out["computed_snapshot_count"] = len(out.get("sessions", []))
    out["bootstrap_policy"] = "VERIFIED_GIT_SNAPSHOT_EFFECTIVE_DATE_ONLY"
    return out, generated[str(asof.date())], str(base_asof.date())


def build_live(history: dict[str, Any], s2t: dict[str, list[str]], current: dict[str, Any],
               expected_base_asof: str | None) -> dict[str, Any]:
    sessions = [row for row in history.get("sessions", []) if isinstance(row, dict)]
    by_date = {str(row.get("asof")): row for row in sessions if row.get("asof")}
    old = by_date.get(expected_base_asof) if expected_base_asof else None
    current_normal = current.get("normal_theme_rs63_pct", {})
    current_peer = current.get("peer_theme_rs63_pct", {})
    current_breadth = current.get("peer_breadth21_pct", {})
    history_sessions = int(history.get("covered_market_sessions") or len(sessions))

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
            "history_sessions": history_sessions,
            "expected_acceleration_base_asof": expected_base_asof,
            "themes": themes,
            "no_valid_theme": bool(history_ready and not themes),
        }

    return {
        "schema": "v38-strict-loo-live-1",
        "asof": current.get("asof"),
        "status": "READY" if old is not None else "DATA REQUIRED",
        "history_sessions": history_sessions,
        "computed_snapshot_count": len(sessions),
        "history_start_asof": history.get("coverage_start_asof"),
        "history_end_asof": history.get("coverage_end_asof"),
        "expected_acceleration_base_asof": expected_base_asof,
        "history_has_exact_20_session_base": old is not None,
        "membership_source": "sector_snapshot.json:s2t",
        "pit_policy": "SAVED_PIT_TAXONOMY_FROM_EFFECTIVE_DATE; NO_PRE_SNAPSHOT_BACKFILL",
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
        "pit_policy": "SAVED_PIT_TAXONOMY_FROM_EFFECTIVE_DATE; NO_PRE_SNAPSHOT_BACKFILL",
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

    history_path = Path(args.history)
    history = _load_json(history_path, {"schema": "v38-strict-loo-history-1", "sessions": []})
    try:
        if not has_verified_bootstrap(history):
            bootstrap_s2t = load_verified_git_taxonomy()
            history = register_taxonomy_snapshot(
                history, PIT_BOOTSTRAP_EFFECTIVE_ASOF, bootstrap_s2t,
                PIT_BOOTSTRAP_SOURCE,
            )
        history = register_taxonomy_snapshot(history, asof_text, s2t, "daily:sector_snapshot.json")
    except Exception as exc:
        live = _data_required_live(asof_text, f"{type(exc).__name__}: {exc}")
        out_path.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"LOO_LIVE_DATA_REQUIRED {type(exc).__name__}: {exc}", flush=True)
        return

    symbols = sorted({symbol for row in history.get("taxonomy_snapshots", [])
                      for symbol in row.get("s2t", {})})
    start = str((asof - pd.Timedelta(days=170)).date())
    end = str((asof + pd.Timedelta(days=1)).date())
    try:
        close, quality = download_adjusted_close(symbols, start, end, args.batch_size)
        close = close.loc[close.index <= asof]
        if asof not in close.index:
            raise RuntimeError(f"PRICE_ASOF_REQUIRED latest={close.index.max() if len(close) else None}")
        history, current, expected_base_asof = backfill_required_snapshots(history, close, asof)
        current["download_quality"] = quality
        history = _upsert_history(history, current)
        history["computed_snapshot_count"] = len(history.get("sessions", []))
        history_path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        live = build_live(history, s2t, current, expected_base_asof)
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
