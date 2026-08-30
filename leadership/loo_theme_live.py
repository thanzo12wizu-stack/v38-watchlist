from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Mapping

import numpy as np
import pandas as pd

MIN_THEME_MEMBERS = 3
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")


def _ticker(value: Any) -> bool:
    return isinstance(value, str) and bool(TICKER_RE.fullmatch(value.strip().upper()))


def _leaf_strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_leaf_strings(item, depth + 1))
        return out
    if isinstance(value, Mapping):
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


def extract_theme_members(snapshot: Mapping[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Use the exact research source contract: sector_snapshot.json['s2t'].

    Returns (theme->members, stock->themes). We intentionally do not fall back
    to the single display theme because the research used multi-membership s2t.
    """
    raw = snapshot.get("s2t") if isinstance(snapshot, Mapping) else None
    if not isinstance(raw, Mapping):
        raise ValueError("sector_snapshot.json s2t multi-theme mapping is required")
    stock_themes: dict[str, list[str]] = {}
    theme_members: dict[str, list[str]] = defaultdict(list)
    for raw_sym, value in raw.items():
        sym = str(raw_sym).strip().upper()
        if not _ticker(sym):
            continue
        themes: list[str] = []
        seen: set[str] = set()
        for theme in _leaf_strings(value):
            if theme and not _ticker(theme) and theme not in seen:
                seen.add(theme)
                themes.append(theme)
        if not themes:
            continue
        stock_themes[sym] = themes
        for theme in themes:
            theme_members[theme].append(sym)
    return {k: sorted(set(v)) for k, v in theme_members.items()}, stock_themes


def _arithmetic_returns(close: pd.DataFrame) -> pd.DataFrame:
    ret = close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return ret.where(ret > -0.999999)


def _period_return(ret: pd.DataFrame, window: int, min_ratio: float = 0.8) -> pd.DataFrame:
    min_periods = int(math.ceil(window * min_ratio))
    safe = ret.where(ret > -0.999999)
    return np.expm1(np.log1p(safe).rolling(window, min_periods=min_periods).sum())


def _replacement_percentile(value: float, reference: np.ndarray, theme_index: int) -> float | None:
    if not np.isfinite(value):
        return None
    ref = np.asarray(reference, float)
    finite = ref[np.isfinite(ref)]
    if not len(finite):
        return None
    sorted_ref = np.sort(finite)
    count = float(np.searchsorted(sorted_ref, value, side="right"))
    original = ref[theme_index]
    if np.isfinite(original) and original <= value:
        count -= 1.0
    count += 1.0
    denom = float(len(sorted_ref)) + (0.0 if np.isfinite(original) else 1.0)
    return count / denom * 100.0 if denom > 0 else None


def _close_matrix(frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for sym, frame in frames.items():
        if frame is None or frame.empty or "Close" not in frame.columns:
            continue
        s = pd.to_numeric(frame["Close"], errors="coerce").copy()
        idx = pd.to_datetime(s.index)
        try:
            idx = idx.tz_localize(None)
        except TypeError:
            idx = idx.tz_convert(None)
        s.index = idx.normalize()
        series[str(sym).upper()] = s[~s.index.duplicated(keep="last")]
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index().replace([np.inf, -np.inf], np.nan)


def build_loo_theme_live(
    frames: Mapping[str, pd.DataFrame],
    sector_snapshot: Mapping[str, Any],
    *,
    source_universe_total: int | None = None,
    full_download_requested: bool = True,
) -> dict[str, Any]:
    """Replicate the research Full3 leave-one-out score for the latest session.

    Formula follows audit_ordinary_stock_theme_leave_one_out.py. Taxonomy is
    current, not historical PIT; this output must never be presented as PIT.
    """
    close = _close_matrix(frames)
    if close.empty or len(close) < 84:
        return {"schema": "v38-loo-theme-live-1", "status": "DATA_REQUIRED", "reason": "insufficient price history"}

    theme_members_all, stock_themes = extract_theme_members(sector_snapshot)
    stock_set = set(close.columns)
    theme_members = {
        theme: [s for s in members if s in stock_set]
        for theme, members in theme_members_all.items()
    }
    theme_members = {t: m for t, m in theme_members.items() if len(m) >= MIN_THEME_MEMBERS}
    if not theme_members:
        return {"schema": "v38-loo-theme-live-1", "status": "DATA_REQUIRED", "reason": "no valid themes"}

    ret = _arithmetic_returns(close)
    theme_daily: dict[str, pd.Series] = {}
    for theme, members in theme_members.items():
        part = ret[members]
        count = part.notna().sum(axis=1)
        theme_daily[theme] = part.mean(axis=1, skipna=True).where(count >= MIN_THEME_MEMBERS)
    normal_ret = pd.DataFrame(theme_daily, index=close.index)
    normal63 = _period_return(normal_ret, 63)
    normal_pct = normal63.rank(axis=1, pct=True, method="average") * 100.0
    normal_delta20 = normal_pct - normal_pct.shift(20)

    themes = list(normal63.columns)
    theme_index = {theme: i for i, theme in enumerate(themes)}
    latest_i = len(close.index) - 1
    prior_i = latest_i - 20
    latest_date = close.index[latest_i]
    if prior_i < 0:
        return {"schema": "v38-loo-theme-live-1", "status": "DATA_REQUIRED", "reason": "20-session acceleration unavailable"}

    ref63_now = normal63.iloc[latest_i].to_numpy(float)
    ref63_prior = normal63.iloc[prior_i].to_numpy(float)
    ref_delta_now = normal_delta20.iloc[latest_i].to_numpy(float)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)
    min_periods = int(math.ceil(63 * 0.8))

    by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for theme in themes:
        members = theme_members[theme]
        ti = theme_index[theme]
        vals = ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        vb = valid_b[members].to_numpy(bool)
        ab_raw = above_b[members].astype(float).to_numpy()
        ab = np.nan_to_num(ab_raw, nan=0.0, posinf=0.0, neginf=0.0)
        total_valid = vb.sum(axis=1)
        total_above = ab.sum(axis=1)

        for j, sym in enumerate(members):
            den = counts - valid[:, j].astype(np.int16)
            num = sums - np.where(valid[:, j], vals[:, j], 0.0)
            peer_daily = np.divide(num, den, out=np.full(len(close), np.nan), where=den >= 2)
            peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
            peer63 = pd.Series(peer_log, index=close.index).rolling(63, min_periods=min_periods).sum()
            peer63 = np.expm1(peer63.to_numpy(float))

            p_now = _replacement_percentile(peer63[latest_i], ref63_now, ti)
            p_prior = _replacement_percentile(peer63[prior_i], ref63_prior, ti)
            peer_delta = (p_now - p_prior) if p_now is not None and p_prior is not None else None
            accel_pct = _replacement_percentile(float(peer_delta) if peer_delta is not None else np.nan, ref_delta_now, ti)

            peer_valid = total_valid[latest_i] - int(vb[latest_i, j])
            peer_above = total_above[latest_i] - float(ab[latest_i, j])
            breadth = (peer_above * 100.0 / peer_valid) if peer_valid >= 2 else None
            score = None
            if p_now is not None and accel_pct is not None and breadth is not None and all(np.isfinite(x) for x in (p_now, accel_pct, breadth)):
                score = (p_now + accel_pct + breadth) / 3.0
            by_stock[sym].append({
                "theme": theme,
                "theme_rs63_pct": round(float(p_now), 4) if p_now is not None else None,
                "theme_acceleration_pct": round(float(accel_pct), 4) if accel_pct is not None else None,
                "theme_breadth21": round(float(breadth), 4) if breadth is not None else None,
                "peer_theme_score": round(float(score), 4) if score is not None else None,
                "peer_members": int(peer_valid) if peer_valid is not None else None,
            })

    stocks: dict[str, dict[str, Any]] = {}
    for sym, memberships in by_stock.items():
        valid_scores = [m for m in memberships if m.get("peer_theme_score") is not None]
        selected = max(valid_scores, key=lambda m: (float(m["peer_theme_score"]), str(m["theme"]))) if valid_scores else None
        stocks[sym] = {
            "memberships": len(stock_themes.get(sym, [])),
            "valid_memberships": len(valid_scores),
            "selected": selected,
        }

    mapped_available = sum(1 for sym in stock_themes if sym in stock_set)
    mapped_total = len(stock_themes)
    formula_exact = full_download_requested
    status = "LIVE_CURRENT_TAXONOMY" if formula_exact else "PARTIAL_SMOKE_ONLY"
    return {
        "schema": "v38-loo-theme-live-1",
        "status": status,
        "asof": str(pd.Timestamp(latest_date).date()),
        "taxonomy": "CURRENT_S2T_NOT_PIT",
        "formula": "(candidate-excluded Theme63 percentile + candidate-excluded 20d rank acceleration percentile + candidate-excluded Breadth21) / 3; max valid membership",
        "min_theme_members": MIN_THEME_MEMBERS,
        "coverage": {
            "source_universe_total": source_universe_total,
            "price_stocks": int(close.shape[1]),
            "mapped_total": mapped_total,
            "mapped_available": mapped_available,
            "themes": len(themes),
            "scored_stocks": sum(1 for row in stocks.values() if row.get("selected")),
        },
        "stocks": stocks,
        "caveat": "Current taxonomy only. Historical PIT taxonomy remains unresolved; do not interpret backtest absolute CAGR as PIT-validated expected return.",
    }
