from __future__ import annotations

import numpy as np
import pandas as pd

import validate_dynamic_pioneer_followthrough as dpf


def build_followthrough_rows_fast(
    hidden: pd.DataFrame,
    theme_members: dict[str, list[str]],
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    stock_ret: pd.DataFrame,
    spy_ret: pd.Series,
    delay: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exact-equivalent implementation with cached prior highs and peer returns."""
    prior_high20 = high.shift(1).rolling(20, min_periods=15).max()
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_fwd = {h: dpf.er.forward_return(stock_ret, h) for h in dpf.HORIZONS}
    spy_fwd = {h: dpf.er.forward_return(spy_ret, h) for h in dpf.HORIZONS}
    peer_cache: dict[tuple[tuple[str, ...], int, int], dict[str, float]] = {}

    def peer_returns(members: list[str], pos: int, horizon: int) -> dict[str, float]:
        key = (tuple(members), int(pos), int(horizon))
        if key not in peer_cache:
            peer_cache[key] = dpf.ie.rs.event_peer_returns(stock_ret, members, pos, horizon)
        return peer_cache[key]

    diag_records: list[dict] = []
    confirmed_records: list[dict] = []
    for row in hidden.itertuples(index=False):
        d0 = pd.Timestamp(row.entry_date)
        p0 = date_pos.get(d0, -1)
        sym = str(row.symbol)
        theme = str(row.theme)
        if p0 < 0 or p0 + delay >= len(close) or sym not in close.columns:
            continue
        members = [s for s in theme_members.get(theme, []) if s in close.columns]
        if len(members) < 3:
            continue

        p = p0 + delay
        d = close.index[p]
        c0 = close.at[d0, sym]
        c = close.at[d, sym]
        ph0 = prior_high20.at[d0, sym]
        ph = prior_high20.at[d, sym]
        if pd.isna(c0) or pd.isna(c) or pd.isna(ph0) or pd.isna(ph) or c0 <= 0 or ph0 <= 0 or ph <= 0:
            continue

        stock_since = float(c / c0 - 1.0)
        peer_since = peer_returns(members, p0, delay).get(sym, np.nan)
        peer_excess_since = stock_since - peer_since if pd.notna(peer_since) else np.nan
        dist0 = float(c0 / ph0 - 1.0)
        dist_now = float(c / ph - 1.0)

        fast_breakout = False
        for q in range(p0 + 1, p + 1):
            dq = close.index[q]
            cq = close.at[dq, sym]
            phq = prior_high20.at[dq, sym]
            if pd.notna(cq) and pd.notna(phq) and float(cq) > float(phq):
                fast_breakout = True
                break

        price_up = stock_since > 0.0
        peer_up = pd.notna(peer_excess_since) and float(peer_excess_since) > 0.0
        high_gap_shrinking = dist_now > dist0
        prebreakout_confirm = bool(price_up and peer_up and high_gap_shrinking and not fast_breakout)
        any_confirm = bool(price_up and peer_up and high_gap_shrinking)
        diag_records.append({
            "ignition_date": d0,
            "check_date": d,
            "theme": theme,
            "symbol": sym,
            "delay": delay,
            "stock_since_ignite": stock_since,
            "peer_excess_since_ignite": float(peer_excess_since) if pd.notna(peer_excess_since) else np.nan,
            "dist_high20_ignite": dist0,
            "dist_high20_check": dist_now,
            "price_up": price_up,
            "peer_up": peer_up,
            "high_gap_shrinking": high_gap_shrinking,
            "fast_breakout_by_check": fast_breakout,
            "any_followthrough": any_confirm,
            "prebreakout_followthrough": prebreakout_confirm,
        })
        if not prebreakout_confirm:
            continue

        entry_price = float(c)
        rec = {
            "entry_date": d,
            "ignition_date": d0,
            "theme": theme,
            "symbol": sym,
            "delay": delay,
            "stock_since_ignite": stock_since,
            "peer_excess_since_ignite": float(peer_excess_since),
            "dist_high20_ignite": dist0,
            "dist_high20_check": dist_now,
        }
        for h in dpf.HORIZONS:
            sr = stock_fwd[h].at[d, sym] if d in stock_fwd[h].index else np.nan
            sp = spy_fwd[h].at[d] if d in spy_fwd[h].index else np.nan
            pr = peer_returns(members, p, h).get(sym, np.nan)
            future_dates = close.index[p + 1:min(p + h + 1, len(close))]
            highs = high.loc[future_dates, sym].dropna()
            lows = low.loc[future_dates, sym].dropna()
            rec[f"stock_minus_peers_{h}"] = sr - pr if pd.notna(sr) and pd.notna(pr) else np.nan
            rec[f"stock_minus_spy_{h}"] = sr - sp if pd.notna(sr) and pd.notna(sp) else np.nan
            rec[f"mfe_{h}"] = float(highs.max() / entry_price - 1.0) if len(highs) else np.nan
            rec[f"mae_{h}"] = float(lows.min() / entry_price - 1.0) if len(lows) else np.nan
            rec[f"ignition_peer_{h}"] = getattr(row, f"stock_minus_peers_{h}")
        confirmed_records.append(rec)

    return pd.DataFrame(diag_records), pd.DataFrame(confirmed_records)


if __name__ == "__main__":
    dpf.build_followthrough_rows = build_followthrough_rows_fast
    dpf.main()
