from __future__ import annotations

import math
import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit

_orig_download = audit.loo.download_adjusted_close


def _download_with_coverage(*args, **kwargs):
    close, quality = _orig_download(*args, **kwargs)
    quality = dict(quality or {})
    requested = int(quality.get("requested") or 0)
    downloaded = int(quality.get("downloaded") or 0)
    quality["coverage"] = downloaded / max(1, requested)
    return close, quality


def _replacement_percentile(values: np.ndarray, reference: np.ndarray, pair_theme_idx: np.ndarray) -> np.ndarray:
    d_n, p_n = values.shape
    out = np.full((d_n, p_n), np.nan, dtype=np.float32)
    for i in range(d_n):
        vals = values[i].astype(float, copy=False)
        mask = np.isfinite(vals)
        if not mask.any():
            continue
        ref = reference[i].astype(float, copy=False)
        ref_finite = ref[np.isfinite(ref)]
        if not len(ref_finite):
            continue
        sorted_ref = np.sort(ref_finite)
        pos = np.flatnonzero(mask)
        vv = vals[pos]
        ti = pair_theme_idx[pos]
        orig = ref[ti]
        counts = np.searchsorted(sorted_ref, vv, side="right").astype(float)
        orig_finite = np.isfinite(orig)
        counts -= (orig_finite & (orig <= vv)).astype(float)
        counts += 1.0
        denom = float(len(sorted_ref)) + (~orig_finite).astype(float)
        out[i, pos] = (counts / denom * 100.0).astype(np.float32)
    return out


def _theme_scores_fast(theme_close: pd.DataFrame, s2t: dict[str, list[str]], end_asof: pd.Timestamp, target_symbols: list[str]):
    close = theme_close.loc[theme_close.index <= end_asof].copy()
    stock_cols = list(close.columns)
    stock_pos = {s: i for i, s in enumerate(stock_cols)}
    stock_ret = audit.loo.arithmetic_returns(close)
    groups0 = audit.loo.invert_memberships(s2t)
    groups = {t: [s for s in members if s in stock_pos] for t, members in groups0.items()}
    groups = {t: members for t, members in groups.items() if len(members) >= audit.loo.MIN_THEME_MEMBERS}

    normal_daily = {}
    for n, (theme, members) in enumerate(groups.items(), 1):
        part = stock_ret[members]
        count = part.notna().sum(axis=1)
        normal_daily[theme] = part.mean(axis=1, skipna=True).where(count >= audit.loo.MIN_THEME_MEMBERS)
        if n % 50 == 0 or n == len(groups):
            print(f"FAST_NORMAL_THEME {n}/{len(groups)}", flush=True)
    normal_ret = pd.DataFrame(normal_daily)
    normal63 = audit.loo.period_return(normal_ret, audit.loo.RS_WINDOW)
    themes = list(normal63.columns)
    theme_pos = {t: i for i, t in enumerate(themes)}
    normal_pct = normal63.rank(axis=1, pct=True, method="average") * 100.0
    normal_delta20 = normal_pct - normal_pct.shift(20)

    pairs = []
    pair_theme_idx = []
    pair_stock_idx = []
    slices = {}
    for theme in themes:
        members = groups.get(theme, [])
        start = len(pairs)
        for s in members:
            pairs.append((theme, s))
            pair_theme_idx.append(theme_pos[theme])
            pair_stock_idx.append(stock_pos[s])
        slices[theme] = (start, len(pairs), members)

    d_n, p_n = len(close.index), len(pairs)
    peer63 = np.full((d_n, p_n), np.nan, dtype=np.float32)
    peer_breadth = np.full((d_n, p_n), np.nan, dtype=np.float32)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid_b = close.notna() & ema21.notna()
    above_b = (close > ema21).where(valid_b)
    minp = audit.loo.RS_MIN_PERIODS

    for n, theme in enumerate(themes, 1):
        start, end, members = slices[theme]
        if not members:
            continue
        vals = stock_ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        den = counts[:, None] - valid.astype(np.int16)
        num = sums[:, None] - np.where(valid, vals, 0.0)
        peer_daily = np.divide(num, den, out=np.full_like(num, np.nan), where=den >= 2)
        peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
        peer63[:, start:end] = np.expm1(
            pd.DataFrame(peer_log, index=close.index).rolling(audit.loo.RS_WINDOW, min_periods=minp).sum().to_numpy(float)
        ).astype(np.float32)
        vb = valid_b[members].to_numpy(bool)
        ab = np.nan_to_num(above_b[members].astype(float).to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)
        total_valid = vb.sum(axis=1)
        total_above = ab.sum(axis=1)
        peer_valid = total_valid[:, None] - vb.astype(np.int16)
        peer_above = total_above[:, None] - ab
        peer_breadth[:, start:end] = np.divide(
            peer_above * 100.0, peer_valid,
            out=np.full_like(peer_above, np.nan, dtype=float), where=peer_valid >= 2,
        ).astype(np.float32)
        if n % 25 == 0 or n == len(themes):
            print(f"FAST_LOO_THEME {n}/{len(themes)} pairs={end}", flush=True)

    pti = np.asarray(pair_theme_idx, dtype=np.int32)
    psi = np.asarray(pair_stock_idx, dtype=np.int32)
    peer_pct = _replacement_percentile(peer63, normal63.to_numpy(float), pti)
    peer_delta20 = np.full_like(peer_pct, np.nan, dtype=np.float32)
    peer_delta20[20:] = peer_pct[20:] - peer_pct[:-20]
    accel_pct = _replacement_percentile(peer_delta20, normal_delta20.to_numpy(float), pti)
    score = np.full_like(peer_pct, np.nan, dtype=np.float32)
    ok = np.isfinite(peer_pct) & np.isfinite(accel_pct) & np.isfinite(peer_breadth)
    score[ok] = ((peer_pct[ok] + accel_pct[ok] + peer_breadth[ok]) / 3.0).astype(np.float32)

    best = np.full((d_n, len(stock_cols)), np.nan, dtype=np.float32)
    for j in range(p_n):
        best[:, psi[j]] = np.fmax(best[:, psi[j]], score[:, j])

    target = [s for s in target_symbols if s in stock_pos]
    target_positions = np.asarray([stock_pos[s] for s in target], dtype=np.int32)
    dates = []
    for i, d in enumerate(close.index):
        if d < audit.PIT_EFFECTIVE or d > end_asof or i < 20:
            continue
        base_date = close.index[i - 20]
        if base_date < audit.PIT_EFFECTIVE:
            continue
        dates.append((i, pd.Timestamp(d)))
    out = {}
    for i, d in dates:
        vals = best[i, target_positions]
        day = {}
        for s, v in zip(target, vals):
            day[s] = float(v) if np.isfinite(v) else 50.0
        out[d] = day
    return out, {
        "pit_market_sessions": int(((close.index >= audit.PIT_EFFECTIVE) & (close.index <= end_asof)).sum()),
        "scored_sessions": len(out),
        "first_scored": str(min(out).date()) if out else None,
        "last_scored": str(max(out).date()) if out else None,
        "vectorized": True,
        "themes": len(themes),
        "theme_stock_pairs": p_n,
        "taxonomy_policy": "single verified PIT taxonomy effective 2026-06-22; no pre-effective signal emitted",
    }


audit.loo.download_adjusted_close = _download_with_coverage
audit.theme_scores_by_date = _theme_scores_fast

if __name__ == "__main__":
    audit.main()
