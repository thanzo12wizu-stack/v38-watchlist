from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


SECTOR_COOLDOWN = 20
ENTRY_WINDOW = 7
LEAD_LOOKBACK = 10
MIN_SECTOR_MEMBERS = 5


@dataclass(frozen=True)
class DiffusionThresholds:
    relative_high_5d: float = 32.0
    relative_high_delta_5d: float = 7.0
    above21_share: float = 55.0
    above21_delta_5d: float = 3.0
    leader_density: float = 12.0
    leader_density_delta_5d: float = 2.0
    max_extended_share: float = 35.0


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _series_share(mask: pd.DataFrame, valid: pd.DataFrame) -> pd.Series:
    masked = mask.astype(float).where(valid)
    return masked.mean(axis=1) * 100.0


def _cooldown_events(condition: pd.Series, cooldown: int) -> list[pd.Timestamp]:
    events: list[pd.Timestamp] = []
    last_pos: int | None = None
    values = condition.fillna(False).astype(bool)
    for pos, (date, active) in enumerate(values.items()):
        if not active:
            continue
        if pos > 0 and bool(values.iloc[pos - 1]):
            continue
        if last_pos is not None and pos - last_pos < cooldown:
            continue
        events.append(pd.Timestamp(date))
        last_pos = pos
    return events


def _last_position(index: pd.Index, date: pd.Timestamp) -> int | None:
    try:
        loc = index.get_loc(date)
    except KeyError:
        return None
    if isinstance(loc, slice):
        return int(loc.start)
    if isinstance(loc, (list, tuple)):
        return int(loc[0]) if loc else None
    try:
        return int(loc)
    except (TypeError, ValueError):
        return None


def _rolling_avwap(frame: pd.DataFrame, start_date: pd.Timestamp) -> pd.Series:
    local = frame.loc[frame.index >= start_date].copy()
    if local.empty or "Volume" not in local.columns:
        return pd.Series(dtype=float)
    volume = pd.to_numeric(local["Volume"], errors="coerce").fillna(0.0)
    if {"High", "Low", "Close"}.issubset(local.columns):
        price = (
            pd.to_numeric(local["High"], errors="coerce")
            + pd.to_numeric(local["Low"], errors="coerce")
            + pd.to_numeric(local["Close"], errors="coerce")
        ) / 3.0
    else:
        price = pd.to_numeric(local["Close"], errors="coerce")
    denom = volume.cumsum()
    numer = (price * volume).cumsum()
    out = numer / denom.replace(0.0, float("nan"))
    return out.dropna()


def _first_reclaim_now(price: pd.Series, level: pd.Series, start_pos: int, tolerance: float = 0.005) -> bool:
    if len(price) < 2 or len(level) < 2:
        return False
    aligned = pd.concat([price.rename("p"), level.rename("l")], axis=1).dropna()
    if len(aligned) < 2:
        return False
    reclaim = (aligned["p"] > aligned["l"]) & (aligned["p"].shift(1) <= aligned["l"].shift(1) * (1.0 + tolerance))
    post = reclaim.iloc[max(1, start_pos):]
    true_dates = list(post.index[post.fillna(False)])
    return bool(true_dates) and true_dates[0] == aligned.index[-1]


def _entry_signal(
    frame: pd.DataFrame,
    event_date: pd.Timestamp,
    ema21: pd.Series,
    event_age: int,
) -> dict[str, Any]:
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < 25 or event_date not in close.index:
        return {"status": "NO_DATA", "reason": "Entry判定データ不足"}
    current = _finite(close.iloc[-1])
    previous = _finite(close.iloc[-2]) if len(close) >= 2 else None
    if current is None:
        return {"status": "NO_DATA", "reason": "終値データ不足"}

    ema = ema21.reindex(close.index)
    ema_now = _finite(ema.iloc[-1])
    ema_gap = 100.0 * (current / ema_now - 1.0) if ema_now and ema_now > 0 else None

    price_prior_high = close.shift(1).rolling(20, min_periods=15).max()
    pivot = _finite(price_prior_high.iloc[-1])
    breakout_gap = 100.0 * (current / pivot - 1.0) if pivot and pivot > 0 else None

    rvol = None
    if "Volume" in frame.columns and len(frame) >= 21:
        volume = pd.to_numeric(frame["Volume"], errors="coerce").reindex(close.index)
        prior_avg = _finite(volume.iloc[-21:-1].mean())
        latest = _finite(volume.iloc[-1])
        if prior_avg and prior_avg > 0 and latest is not None:
            rvol = latest / prior_avg

    avwap = _rolling_avwap(frame, event_date).reindex(close.index)
    avwap_now = _finite(avwap.iloc[-1]) if len(avwap) else None
    event_pos = _last_position(close.index, event_date)
    avwap_reclaim = False
    ema_reclaim = False
    if event_pos is not None and event_age >= 1:
        if avwap_now and abs(current / avwap_now - 1.0) <= 0.03:
            avwap_reclaim = _first_reclaim_now(close, avwap, event_pos + 1)
        if ema_now and abs(current / ema_now - 1.0) <= 0.03:
            ema_reclaim = _first_reclaim_now(close, ema, event_pos + 1)

    recent = close.tail(3)
    tight_range = False
    if len(recent) == 3 and float(recent.min()) > 0:
        tight_range = float(recent.max() / recent.min() - 1.0) <= 0.04
    breakout_now = bool(pivot and previous is not None and previous <= pivot and current > pivot)
    tight_breakout = breakout_now and tight_range and (rvol is None or rvol >= 1.2) and (ema_gap is None or ema_gap <= 8.0)

    if (ema_gap is not None and ema_gap > 12.0) or (breakout_gap is not None and breakout_gap > 8.0):
        return {
            "status": "EXTENDED",
            "reason": "21EMAまたは20日Pivotから乖離大。追わない",
            "ema21_gap_pct": round(ema_gap, 2) if ema_gap is not None else None,
            "pivot_gap_pct": round(breakout_gap, 2) if breakout_gap is not None else None,
            "event_avwap": round(avwap_now, 4) if avwap_now is not None else None,
            "rvol": round(rvol, 2) if rvol is not None else None,
        }
    if avwap_reclaim or ema_reclaim:
        level = "Sector Ignition AVWAP" if avwap_reclaim else "21EMA"
        return {
            "status": "PULLBACK_RECLAIM",
            "reason": f"{level}への初回押しから終値Reclaim",
            "ema21_gap_pct": round(ema_gap, 2) if ema_gap is not None else None,
            "pivot_gap_pct": round(breakout_gap, 2) if breakout_gap is not None else None,
            "event_avwap": round(avwap_now, 4) if avwap_now is not None else None,
            "rvol": round(rvol, 2) if rvol is not None else None,
        }
    if tight_breakout:
        return {
            "status": "TIGHT_BREAKOUT",
            "reason": "3日Tight + 20日高値更新。21EMA乖離と出来高を確認",
            "ema21_gap_pct": round(ema_gap, 2) if ema_gap is not None else None,
            "pivot_gap_pct": round(breakout_gap, 2) if breakout_gap is not None else None,
            "event_avwap": round(avwap_now, 4) if avwap_now is not None else None,
            "rvol": round(rvol, 2) if rvol is not None else None,
        }
    return {
        "status": "WATCH",
        "reason": "Sector発火後の最初のAVWAP/21EMA押し、またはTight Breakout待ち",
        "ema21_gap_pct": round(ema_gap, 2) if ema_gap is not None else None,
        "pivot_gap_pct": round(breakout_gap, 2) if breakout_gap is not None else None,
        "event_avwap": round(avwap_now, 4) if avwap_now is not None else None,
        "rvol": round(rvol, 2) if rvol is not None else None,
    }


def compute_diffusion_snapshot(
    frames: dict[str, pd.DataFrame],
    benchmark_frame: pd.DataFrame,
    universe: Iterable[Any],
    *,
    cooldown: int = SECTOR_COOLDOWN,
    entry_window: int = ENTRY_WINDOW,
    lead_lookback: int = LEAD_LOOKBACK,
    thresholds: DiffusionThresholds | None = None,
) -> dict[str, Any]:
    """Compute eventized sector diffusion and pre-ignition early leaders.

    Sector state is a threshold crossing with cooldown. Stock selection is then
    conditioned on a pre-ignition stock/sector relative breakout. Stock Capture
    is intentionally excluded.
    """
    thresholds = thresholds or DiffusionThresholds()
    benchmark_close = pd.to_numeric(benchmark_frame["Close"], errors="coerce").dropna()
    if len(benchmark_close) < 80:
        return {"status": "NO_DATA", "reason": "benchmark history insufficient", "sectors": {}, "stocks": {}}

    dates = benchmark_close.index
    symbol_sector: dict[str, str] = {}
    for row in universe:
        symbol = str(getattr(row, "symbol", "") or "").strip().upper()
        sector = str(getattr(row, "sector", "") or "").strip()
        if symbol and sector:
            symbol_sector[symbol] = sector

    close_map: dict[str, pd.Series] = {}
    for symbol, frame in frames.items():
        if symbol not in symbol_sector or frame is None or frame.empty or "Close" not in frame.columns:
            continue
        series = pd.to_numeric(frame["Close"], errors="coerce").reindex(dates)
        if series.notna().sum() >= 80:
            close_map[symbol] = series
    if not close_map:
        return {"status": "NO_DATA", "reason": "stock history insufficient", "sectors": {}, "stocks": {}}

    close = pd.DataFrame(close_map, index=dates).ffill(limit=2)
    valid = close.notna()
    benchmark = benchmark_close.reindex(dates).ffill()
    rel_bench = close.div(benchmark, axis=0)
    rel_high20 = rel_bench.rolling(20, min_periods=15).max()
    rel_near_high = ((rel_bench >= rel_high20 * 0.99) & (rel_bench > rel_bench.shift(5))).where(valid)
    rel_breakout = (rel_bench > rel_bench.shift(1).rolling(20, min_periods=15).max()).where(valid)

    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    above21 = (close >= ema21).where(valid)
    ema_gap = ((close / ema21) - 1.0) * 100.0
    extended = (ema_gap > 12.0).where(valid)

    ret21 = close / close.shift(21) - 1.0
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0
    bench21 = benchmark / benchmark.shift(21) - 1.0
    bench63 = benchmark / benchmark.shift(63) - 1.0
    bench189 = benchmark / benchmark.shift(189) - 1.0
    excess21 = ret21.sub(bench21, axis=0)
    excess63 = ret63.sub(bench63, axis=0)
    excess189 = ret189.sub(bench189, axis=0)
    rs63 = excess63.rank(axis=1, pct=True, method="average") * 100.0
    rs189 = excess189.rank(axis=1, pct=True, method="average") * 100.0
    leader = ((rs63 >= 80.0) & (rs189 >= 80.0) & (close >= ema21)).where(valid)

    sector_symbols: dict[str, list[str]] = {}
    for symbol in close.columns:
        sector = symbol_sector.get(symbol, "")
        if sector:
            sector_symbols.setdefault(sector, []).append(symbol)

    sectors_out: dict[str, dict[str, Any]] = {}
    stocks_out: dict[str, dict[str, Any]] = {}
    event_total = 0
    active_sector_count = 0

    for sector, symbols in sorted(sector_symbols.items()):
        if len(symbols) < MIN_SECTOR_MEMBERS:
            continue
        sector_valid = valid[symbols]
        member_count = int((sector_valid.iloc[-1]).sum())
        if member_count < MIN_SECTOR_MEMBERS:
            continue

        rel_high_share = _series_share(rel_near_high[symbols].fillna(False), sector_valid)
        rel_breakout_share = _series_share(rel_breakout[symbols].fillna(False), sector_valid)
        above21_share = _series_share(above21[symbols].fillna(False), sector_valid)
        leader_density = _series_share(leader[symbols].fillna(False), sector_valid)
        extended_share = _series_share(extended[symbols].fillna(False), sector_valid)
        sector_excess21 = excess21[symbols].median(axis=1, skipna=True) * 100.0

        rh5 = rel_high_share.rolling(5, min_periods=3).mean()
        rh_delta5 = rh5 - rh5.shift(5)
        above_delta5 = above21_share - above21_share.shift(5)
        leader_delta5 = leader_density - leader_density.shift(5)
        excess_delta5 = sector_excess21 - sector_excess21.shift(5)

        raw = (
            (rh5 >= thresholds.relative_high_5d)
            & (rh_delta5 >= thresholds.relative_high_delta_5d)
            & (above21_share >= thresholds.above21_share)
            & (above_delta5 >= thresholds.above21_delta_5d)
            & (leader_density >= thresholds.leader_density)
            & (leader_delta5 >= thresholds.leader_density_delta_5d)
            & (sector_excess21 > 0.0)
            & (excess_delta5 > 0.0)
            & (extended_share <= thresholds.max_extended_share)
        )
        events = _cooldown_events(raw, cooldown)
        event_total += len(events)
        latest_event = events[-1] if events else None
        event_age = None
        if latest_event is not None:
            event_pos = _last_position(dates, latest_event)
            if event_pos is not None:
                event_age = len(dates) - 1 - event_pos

        current_excess = _finite(sector_excess21.iloc[-1])
        current_above = _finite(above21_share.iloc[-1])
        if event_age is not None and event_age <= 2:
            state = "IGNITION"
        elif event_age is not None and event_age <= entry_window and (current_excess or 0.0) > 0 and (current_above or 0.0) >= 50:
            state = "ACTIVE"
        elif event_age is not None and event_age <= cooldown and (current_above or 0.0) >= 45:
            state = "MATURE"
        elif event_age is not None and event_age <= cooldown + 10:
            state = "DECAY"
        else:
            state = "NONE"
        if state in {"IGNITION", "ACTIVE"}:
            active_sector_count += 1

        score_components = [
            _clip((_finite(rh5.iloc[-1]) or 0.0) * 1.5),
            _clip(50.0 + (_finite(rh_delta5.iloc[-1]) or 0.0) * 3.0),
            _clip(_finite(above21_share.iloc[-1]) or 0.0),
            _clip((_finite(leader_density.iloc[-1]) or 0.0) * 2.0),
            _clip(50.0 + (_finite(excess_delta5.iloc[-1]) or 0.0) * 8.0),
        ]
        event_score = sum(score_components) / len(score_components)

        sector_row = {
            "state": state,
            "event_date": str(latest_event.date()) if latest_event is not None else None,
            "event_age": event_age,
            "event_score": round(event_score, 1),
            "members": member_count,
            "relative_high_share": round(_finite(rel_high_share.iloc[-1]) or 0.0, 1),
            "relative_high_5d": round(_finite(rh5.iloc[-1]) or 0.0, 1),
            "relative_high_delta_5d": round(_finite(rh_delta5.iloc[-1]) or 0.0, 1),
            "relative_breakout_share": round(_finite(rel_breakout_share.iloc[-1]) or 0.0, 1),
            "above21_share": round(_finite(above21_share.iloc[-1]) or 0.0, 1),
            "above21_delta_5d": round(_finite(above_delta5.iloc[-1]) or 0.0, 1),
            "leader_density": round(_finite(leader_density.iloc[-1]) or 0.0, 1),
            "leader_density_delta_5d": round(_finite(leader_delta5.iloc[-1]) or 0.0, 1),
            "sector_excess21_pct": round(current_excess or 0.0, 2),
            "sector_excess21_delta_5d": round(_finite(excess_delta5.iloc[-1]) or 0.0, 2),
            "extended_share": round(_finite(extended_share.iloc[-1]) or 0.0, 1),
            "event_count": len(events),
            "recent_events": [str(x.date()) for x in events[-6:]],
        }
        sectors_out[sector] = sector_row

        if latest_event is None or event_age is None or event_age > cooldown:
            continue
        event_pos = _last_position(dates, latest_event)
        if event_pos is None or event_pos < 25:
            continue

        sector_daily_ret = close[symbols].pct_change(fill_method=None).median(axis=1, skipna=True).fillna(0.0)
        sector_index = (1.0 + sector_daily_ret).cumprod()

        for symbol in symbols:
            frame = frames.get(symbol)
            if frame is None or frame.empty or symbol not in close.columns:
                continue
            stock_close = close[symbol]
            stock_sector_rel = stock_close / sector_index
            prior_high = stock_sector_rel.shift(1).rolling(20, min_periods=15).max()
            ss_breakout = stock_sector_rel > prior_high
            start = max(20, event_pos - lead_lookback)
            lead_slice = ss_breakout.iloc[start:event_pos]
            lead_dates = list(lead_slice.index[lead_slice.fillna(False)])
            if not lead_dates:
                continue
            breakout_date = pd.Timestamp(lead_dates[0])
            breakout_pos = _last_position(dates, breakout_date)
            if breakout_pos is None:
                continue
            lead_days = event_pos - breakout_pos

            rs63_event = _finite(rs63[symbol].iloc[event_pos]) if symbol in rs63 else None
            rs189_event = _finite(rs189[symbol].iloc[event_pos]) if symbol in rs189 else None
            event_price = _finite(stock_close.iloc[event_pos])
            event_ema = _finite(ema21[symbol].iloc[event_pos])
            current_price = _finite(stock_close.iloc[-1])
            current_ema = _finite(ema21[symbol].iloc[-1])
            current_rel = _finite(stock_sector_rel.iloc[-1])
            current_rel_high = _finite(stock_sector_rel.rolling(20, min_periods=15).max().iloc[-1])
            maintained = bool(current_rel and current_rel_high and current_rel >= current_rel_high * 0.98)
            trend_ok = bool(event_price and event_ema and event_price >= event_ema and current_price and current_ema and current_price >= current_ema)
            early = bool(
                1 <= lead_days <= lead_lookback
                and (rs63_event or 0.0) >= 80.0
                and (rs189_event or 0.0) >= 80.0
                and maintained
                and trend_ok
            )
            if not early:
                continue

            current_rs63 = _finite(rs63[symbol].iloc[-1])
            current_rs189 = _finite(rs189[symbol].iloc[-1])
            rel_change = None
            event_rel = _finite(stock_sector_rel.iloc[event_pos])
            if event_rel and current_rel:
                rel_change = 100.0 * (current_rel / event_rel - 1.0)
            lead_score = _clip(
                45.0
                + min(lead_days, lead_lookback) * 2.0
                + max(0.0, (rs63_event or 80.0) - 80.0) * 0.7
                + max(0.0, (rs189_event or 80.0) - 80.0) * 0.4
                + max(0.0, rel_change or 0.0) * 1.5
            )
            entry = _entry_signal(frame, latest_event, ema21[symbol].dropna(), event_age)
            if event_age > entry_window and entry.get("status") not in {"EXTENDED", "NO_DATA"}:
                entry = dict(entry)
                entry["status"] = "WINDOW_CLOSED"
                entry["reason"] = f"Sector発火から{event_age}営業日。新規Entry Window終了"

            stocks_out[symbol] = {
                "sector": sector,
                "early_leader": True,
                "lead_days": lead_days,
                "lead_breakout_date": str(breakout_date.date()),
                "lead_score": round(lead_score, 1),
                "rs63_at_event": round(rs63_event, 1) if rs63_event is not None else None,
                "rs189_at_event": round(rs189_event, 1) if rs189_event is not None else None,
                "rs63_now": round(current_rs63, 1) if current_rs63 is not None else None,
                "rs189_now": round(current_rs189, 1) if current_rs189 is not None else None,
                "sector_relative_change_since_event_pct": round(rel_change, 2) if rel_change is not None else None,
                "maintained_relative_high": maintained,
                "entry": entry,
            }

    return {
        "status": "OK",
        "method": "Sector relative-high diffusion -> 20-session cooldown event -> pre-event stock/sector relative breakout -> first pullback/tight breakout",
        "uses_stock_capture": False,
        "cooldown_sessions": cooldown,
        "entry_window_sessions": entry_window,
        "lead_lookback_sessions": lead_lookback,
        "thresholds": {
            "relative_high_5d": thresholds.relative_high_5d,
            "relative_high_delta_5d": thresholds.relative_high_delta_5d,
            "above21_share": thresholds.above21_share,
            "above21_delta_5d": thresholds.above21_delta_5d,
            "leader_density": thresholds.leader_density,
            "leader_density_delta_5d": thresholds.leader_density_delta_5d,
            "max_extended_share": thresholds.max_extended_share,
        },
        "eventization": "new threshold crossing only; sector 20-session cooldown",
        "coverage": {
            "sectors": len(sectors_out),
            "events_in_history_window": event_total,
            "active_sectors": active_sector_count,
            "early_leaders": len(stocks_out),
        },
        "sectors": sectors_out,
        "stocks": stocks_out,
    }
