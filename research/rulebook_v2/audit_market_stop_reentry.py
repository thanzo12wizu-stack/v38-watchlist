from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from research.rulebook import audit_integrated_allocation as base


COST = base.COST
ANALYSIS_START = base.ANALYSIS_START
ANALYSIS_END = base.ANALYSIS_END
DISCOVERY_END = base.DISCOVERY_END
CONFIRM_START = base.CONFIRM_START
N_PORT = base.N_PORT


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        z = float(value)
        return z if math.isfinite(z) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def download_qqq(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("QQQ", start=start, end=end, auto_adjust=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("QQQ download returned empty frame")
    if isinstance(raw.columns, pd.MultiIndex):
        if "QQQ" in raw.columns.get_level_values(-1):
            raw = raw.xs("QQQ", axis=1, level=-1)
        else:
            raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index)
    try:
        raw.index = raw.index.tz_localize(None)
    except TypeError:
        raw.index = raw.index.tz_convert(None)
    raw.index = raw.index.normalize()
    out = raw[["Close", "Volume"]].astype(float).dropna().sort_index()
    return out


def ftd_like(qqq: pd.DataFrame, threshold: float) -> pd.DataFrame:
    close = qqq.Close.to_numpy(float)
    volume = qqq.Volume.to_numpy(float)
    ret = pd.Series(close, index=qqq.index).pct_change(fill_method=None).to_numpy(float)
    day = np.zeros(len(qqq), dtype=int)
    signal = np.zeros(len(qqq), dtype=bool)
    rally_low = np.nan
    active = False
    rally_day = 0
    for i in range(len(qqq)):
        c = close[i]
        if not np.isfinite(c):
            continue
        if not np.isfinite(rally_low) or c < rally_low:
            rally_low = c
            active = False
            rally_day = 0
        if i == 0:
            day[i] = rally_day
            continue
        if not active:
            if c > close[i - 1]:
                active = True
                rally_day = 1
        else:
            rally_day += 1
        day[i] = rally_day
        if (
            active
            and rally_day >= 4
            and np.isfinite(ret[i])
            and ret[i] >= threshold
            and np.isfinite(volume[i - 1])
            and volume[i] > volume[i - 1]
        ):
            signal[i] = True
    return pd.DataFrame(
        {
            f"ftd{int(round(threshold * 10000))}_signal": signal,
            f"ftd{int(round(threshold * 10000))}_rally_day": day,
            "qqq_ret": ret,
        },
        index=qqq.index,
    )


def permission_series(nq: pd.DataFrame, qqq_state: pd.DataFrame, calendar: pd.DatetimeIndex, mode: str) -> pd.DataFrame:
    nq_color = nq["nq_color"].reindex(calendar).ffill().fillna("Red")
    f15 = qqq_state["ftd150_signal"].reindex(calendar).fillna(False).astype(bool)
    f20 = qqq_state["ftd200_signal"].reindex(calendar).fillna(False).astype(bool)

    permission = pd.Series(False, index=calendar, dtype=bool)
    episode = pd.Series(0, index=calendar, dtype=int)
    ftd_seen15 = False
    ftd_seen20 = False
    ep = 0
    was_red = False
    recovery_flag = pd.Series(False, index=calendar, dtype=bool)
    prior_permission = False

    for d in calendar:
        color = str(nq_color.at[d])
        red = color == "Red"
        if red and not was_red:
            ep += 1
            ftd_seen15 = False
            ftd_seen20 = False
        if f15.at[d] and ep > 0:
            ftd_seen15 = True
        if f20.at[d] and ep > 0:
            ftd_seen20 = True

        if mode == "NQ":
            allowed = color in ("Blue", "Green")
        elif mode == "FTD15":
            # After a Red episode, require a follow-through-like day and at least exit Red.
            # Before any Red episode, retain the baseline Blue/Green permission.
            allowed = (color in ("Blue", "Green")) if ep == 0 else (ftd_seen15 and color != "Red")
        elif mode == "FTD20":
            allowed = (color in ("Blue", "Green")) if ep == 0 else (ftd_seen20 and color != "Red")
        elif mode == "NQ_AND_FTD15":
            allowed = (color in ("Blue", "Green")) if ep == 0 else (ftd_seen15 and color in ("Blue", "Green"))
        else:
            raise ValueError(mode)

        permission.at[d] = bool(allowed)
        episode.at[d] = ep
        recovery_flag.at[d] = bool(allowed and not prior_permission)
        prior_permission = bool(allowed)
        was_red = red

    return pd.DataFrame(
        {
            "permission": permission,
            "episode": episode,
            "recovery": recovery_flag,
            "nq_color": nq_color,
            "ftd15": f15,
            "ftd20": f20,
        }
    )


def simulate_core(market: dict, signal: dict, permission: pd.DataFrame, force_exit_red: bool) -> tuple[dict, pd.DataFrame]:
    close, open_ = market["close"], market["open"]
    calendar = close.index[(close.index >= ANALYSIS_START) & (close.index <= ANALYSIS_END)]
    rebalances = base.rebalance_sessions(calendar)
    perm = permission.reindex(calendar).copy()

    lots: dict[str, dict] = {}
    cash = 1.0
    initialized = False
    turnover = 0.0
    forced_exit_count = 0
    entry_days = 0
    records: list[dict] = []

    for date in calendar:
        previous = close.index[close.index.get_loc(date) - 1]
        p_allowed = bool(perm.permission.get(previous, False))
        p_color = str(perm.nq_color.get(previous, "Red"))
        p_recovery = bool(perm.recovery.get(previous, False))
        open_prices = open_.loc[date]

        # Individual stock exits remain active in every regime.
        for symbol in list(lots):
            px = open_prices.get(symbol, np.nan)
            if lots[symbol].get("stop_next") and pd.notna(px) and px > 0:
                cash, sold = base.sell_symbol(cash, lots, symbol, float(px))
                turnover += sold

        if force_exit_red and p_color == "Red":
            for symbol in list(lots):
                px = open_prices.get(symbol, np.nan)
                if pd.notna(px) and px > 0:
                    cash, sold = base.sell_symbol(cash, lots, symbol, float(px))
                    turnover += sold
                    forced_exit_count += 1
        else:
            do_rebalance = p_allowed and (date in rebalances or p_recovery or not initialized)
            if do_rebalance:
                picks, continuation_rank = base.core_candidates(previous, market, signal)
                survivors = [s for s in lots if pd.notna(continuation_rank.get(s)) and continuation_rank.get(s) <= 24]
                selected = survivors[:N_PORT]
                selected.extend([s for s in picks if s not in selected][: N_PORT - len(selected)])

                nav_open, _ = base.mark_nav(cash, lots, open_prices)
                target_value = nav_open / N_PORT
                for symbol in list(lots):
                    if symbol not in selected:
                        px = open_prices.get(symbol, np.nan)
                        if pd.notna(px) and px > 0:
                            cash, sold = base.sell_symbol(cash, lots, symbol, float(px))
                            turnover += sold

                before = set(lots)
                for symbol in selected:
                    px = open_prices.get(symbol, np.nan)
                    if pd.isna(px) or px <= 0:
                        continue
                    px = float(px)
                    current_value = lots.get(symbol, {}).get("shares", 0.0) * px
                    delta = target_value - current_value
                    if delta > 1e-12:
                        buy = min(delta, max(0.0, cash) / (1.0 + COST))
                        if buy <= 0:
                            continue
                        cash -= buy * (1.0 + COST)
                        turnover += buy
                        if symbol not in lots:
                            lots[symbol] = {"shares": buy / px, "entry_px": px, "peak": px, "stop_next": False}
                        else:
                            lots[symbol]["shares"] += buy / px
                    elif delta < -1e-12 and symbol in lots:
                        sell = min(-delta, current_value)
                        gross_shares = sell / px
                        lots[symbol]["shares"] -= gross_shares
                        cash += sell * (1.0 - COST)
                        turnover += sell
                if set(lots) - before:
                    entry_days += 1
                initialized = True

        close_prices = close.loc[date]
        nav_close, gross_close = base.mark_nav(cash, lots, close_prices)
        for symbol, lot in lots.items():
            px = close_prices.get(symbol, np.nan)
            if pd.isna(px):
                continue
            px = float(px)
            lot["peak"] = max(float(lot["peak"]), px)
            stop = max(float(lot["entry_px"]) * 0.75, float(lot["peak"]) * 0.70)
            lot["stop_next"] = px <= stop
        records.append(
            {
                "date": date,
                "nav": nav_close,
                "exposure": gross_close / nav_close if nav_close > 0 else np.nan,
                "positions": len(lots),
                "permission_signal": p_allowed,
                "gate_signal": p_color,
                "recovery_signal": p_recovery,
            }
        )

    daily = pd.DataFrame(records).set_index("date")
    ret = daily.nav.pct_change(fill_method=None).fillna(0.0)
    result = {
        **base.metrics(ret),
        "turnover_nav": float(turnover / daily.nav.mean()),
        "avg_exposure": float(daily.exposure.mean()),
        "max_exposure": float(daily.exposure.max()),
        "max_positions": int(daily.positions.max()),
        "forced_exit_count": int(forced_exit_count),
        "entry_days": int(entry_days),
        "permission_rate": float(daily.permission_signal.mean()),
    }
    return result, daily


def period_metrics(daily: pd.DataFrame) -> dict:
    out = {}
    periods = {
        "ALL": (ANALYSIS_START, ANALYSIS_END),
        "DISCOVERY": (ANALYSIS_START, DISCOVERY_END),
        "CONFIRM": (CONFIRM_START, ANALYSIS_END),
        "2018Q4": (pd.Timestamp("2018-10-01"), pd.Timestamp("2018-12-31")),
        "COVID2020": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-06-30")),
        "BEAR2022": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-12-30")),
    }
    for name, (a, b) in periods.items():
        q = daily.loc[(daily.index >= a) & (daily.index <= b)]
        out[name] = base.metrics(q.nav.pct_change(fill_method=None).fillna(0.0)) if len(q) else {"n": 0}
    return out


def episode_table(permission_sets: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    basep = permission_sets["NQ"].reindex(calendar)
    rows = []
    red = basep.nq_color.eq("Red")
    starts = calendar[red & ~red.shift(1, fill_value=False)]
    for i, start in enumerate(starts, start=1):
        next_starts = starts[starts > start]
        stop = next_starts[0] - pd.Timedelta(days=1) if len(next_starts) else calendar[-1]
        row = {"episode": i, "red_start": start}
        for mode, p in permission_sets.items():
            q = p.loc[(p.index >= start) & (p.index <= stop)]
            recovered = q.index[q.recovery]
            d = recovered[0] if len(recovered) else pd.NaT
            row[f"{mode}_restart"] = d
            row[f"{mode}_sessions_to_restart"] = (
                int(calendar.get_loc(d) - calendar.get_loc(start)) if pd.notna(d) and d in calendar else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print("LOAD_MARKET", flush=True)
    market = base.load_full_market(root)
    signal = base.core_signal_frames(market, root)
    calendar = market["close"].index[(market["close"].index >= ANALYSIS_START) & (market["close"].index <= ANALYSIS_END)]

    print("BUILD_NQSAR", flush=True)
    nq = base.mn.build_nqsar("2010-01-01", str((ANALYSIS_END + pd.Timedelta(days=7)).date()))
    qqq = download_qqq(str((ANALYSIS_START - pd.Timedelta(days=365)).date()), str((ANALYSIS_END + pd.Timedelta(days=7)).date()))
    q15 = ftd_like(qqq, 0.015)
    q20 = ftd_like(qqq, 0.020)
    qstate = q15.join(q20.drop(columns=["qqq_ret"]), how="outer")
    qstate.to_csv(out / "qqq_ftd_like.csv")

    modes = ["NQ", "FTD15", "FTD20", "NQ_AND_FTD15"]
    permission_sets = {m: permission_series(nq, qstate, calendar, m) for m in modes}
    ep = episode_table(permission_sets, calendar)
    ep.to_csv(out / "red_episode_restarts.csv", index=False)

    specs = [
        ("CURRENT_FULL_EXIT_NQ", "NQ", True),
        ("STOP_ONLY_NQ", "NQ", False),
        ("FULL_EXIT_FTD15", "FTD15", True),
        ("STOP_ONLY_FTD15", "FTD15", False),
        ("STOP_ONLY_FTD20", "FTD20", False),
        ("STOP_ONLY_NQ_AND_FTD15", "NQ_AND_FTD15", False),
    ]
    summary = {
        "status": "MARKET_STOP_REENTRY_AUDIT",
        "definitions": {
            "market_damage": "NQSAR Red episode",
            "baseline_restart": "previous-session NQSAR Blue/Green permits next-open normal-stock rebalance",
            "stop_only": "Red blocks new normal-stock rebalances but existing positions remain subject to the model's individual exits",
            "full_exit": "Red liquidates existing normal-stock positions at next open",
            "ftd_like_15": "after a rally-attempt low, day 4+ QQQ gain >=1.5% with volume above prior session; after a Red episode, restart requires this event and NQSAR no longer Red",
            "ftd_like_20": "same with QQQ gain >=2.0%",
            "both": "FTD-like 1.5% has occurred after Red and NQSAR is Blue/Green",
        },
        "limitations": [
            "Normal-stock sleeve is the existing comparison reconstruction, not an exact historical production ledger.",
            "Current-universe/current-industry survivorship bias remains.",
            "FTD-like rules are frozen public-style mechanical approximations, not a claim to reproduce a proprietary IBD signal exactly.",
            "Analysis end follows the integrated comparison model and is 2026-03-20.",
        ],
        "variants": {},
        "episodes": {
            "n": int(len(ep)),
            "median_restart_sessions": {
                m: float(pd.to_numeric(ep[f"{m}_sessions_to_restart"], errors="coerce").median()) if len(ep) else None
                for m in modes
            },
        },
    }

    comparison_rows = []
    for name, mode, force_exit in specs:
        print("SIM", name, flush=True)
        result, daily = simulate_core(market, signal, permission_sets[mode], force_exit)
        pm = period_metrics(daily)
        summary["variants"][name] = {"overall": result, "periods": pm}
        daily.to_csv(out / f"{name.lower()}_daily.csv.gz", compression="gzip")
        for period, met in pm.items():
            comparison_rows.append({"strategy": name, "period": period, **met})

    pd.DataFrame(comparison_rows).to_csv(out / "comparison.csv", index=False)
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
