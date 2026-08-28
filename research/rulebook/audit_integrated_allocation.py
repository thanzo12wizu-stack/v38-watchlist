from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi30_mc_nqsar as mn
import audit_rsi30_vix_sequence as va
import audit_rsi_reset_portfolio as panic_portfolio
import audit_rsi_reset_robust as market_base
import validate_early_rotation as universe_base
import validate_post_ignition_leaders as price_base


COST = 5.0 / 10000.0
ANALYSIS_START = pd.Timestamp("2016-01-04")
ANALYSIS_END = pd.Timestamp("2026-03-20")
DISCOVERY_END = pd.Timestamp("2021-12-31")
CONFIRM_START = pd.Timestamp("2022-01-03")
ANCHOR_MONDAY = pd.Timestamp("2026-07-13")
N_PORT = 12


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        z = float(value)
        return z if math.isfinite(z) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def metrics(returns: pd.Series) -> dict:
    r = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if len(r) < 2:
        return {"n": int(len(r))}
    equity = (1.0 + r).cumprod()
    years = max((equity.index[-1] - equity.index[0]).days / 365.2425, 1 / 252)
    drawdown = equity / equity.cummax() - 1.0
    vol = float(r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 else np.nan
    cagr = float(equity.iloc[-1] ** (1 / years) - 1.0)
    return {
        "n": int(len(r)),
        "start": str(equity.index[0].date()),
        "end_date": str(equity.index[-1].date()),
        "end": float(equity.iloc[-1]),
        "cagr": cagr,
        "mdd": float(drawdown.min()),
        "vol": vol,
        "sharpe0": float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else None,
        "calmar": float(cagr / abs(drawdown.min())) if drawdown.min() < 0 else None,
        "worst_5d": rolling_min(r, 5),
        "worst_10d": rolling_min(r, 10),
        "worst_20d": rolling_min(r, 20),
    }


def rolling_min(returns: pd.Series, sessions: int) -> float | None:
    z = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).rolling(sessions).apply(np.prod, raw=True) - 1.0
    return None if z.dropna().empty else float(z.min())


def locate_file(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {name} under {root}, found {len(matches)}: {matches[:10]}")
    return matches[0]


def load_full_market(root: Path) -> dict:
    snap = universe_base.load_json(root / "sector_snapshot.json")
    members_all, taxonomy = universe_base.extract_theme_members(snap)
    industry_map = universe_base.read_industry_map(root / "industry_map.json")
    universe = universe_base.read_universe_symbols(root / "universe.csv")
    selected = universe_base.stratified_symbols(members_all, set(industry_map) & universe, 6000)
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    ohlcv, diagnostic = price_base.rtv2.download_ohlcvo(
        requested,
        str((ANALYSIS_START - pd.Timedelta(days=1000)).date()),
        str((ANALYSIS_END + pd.Timedelta(days=14)).date()),
        75,
    )
    close_all, open_all, high_all, low_all, volume_all = (
        ohlcv[key] for key in ("close", "open", "high", "low", "volume")
    )
    columns = [symbol for symbol in selected if symbol in close_all.columns]
    members = {theme: [symbol for symbol in symbols if symbol in columns] for theme, symbols in members_all.items()}
    return {
        "close": close_all[columns].sort_index(),
        "open": open_all[columns].sort_index(),
        "high": high_all[columns].sort_index(),
        "low": low_all[columns].sort_index(),
        "volume": volume_all[columns].sort_index(),
        "spy_close": close_all["SPY"].sort_index(),
        "members": members,
        "taxonomy": taxonomy,
        "industry_map": industry_map,
        "diagnostic": diagnostic,
        "selected": selected,
    }


def flexible_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    normalized = {str(c).strip().lower(): c for c in frame.columns}
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def structural_exclusions(root: Path, symbols: list[str], industry_map: dict) -> pd.Series:
    raw = pd.read_csv(root / "universe.csv")
    sym_col = flexible_column(raw, ("symbol", "ticker", "シンボル"))
    mcap_col = flexible_column(raw, ("marketcap", "market_cap", "mcap", "時価総額"))
    revenue_col = flexible_column(raw, ("revenuettm", "revenue_ttm", "売上高ttm"))
    meta = raw.set_index(raw[sym_col].astype(str).str.upper()) if sym_col else pd.DataFrame()
    out = pd.Series(False, index=symbols, dtype=bool)
    for symbol in symbols:
        sec_ind = industry_map.get(symbol, ("", ""))
        industry = str(sec_ind[1] if isinstance(sec_ind, (tuple, list)) and len(sec_ind) > 1 else "")
        if industry not in ("Biotechnology", "Pharmaceuticals: Other"):
            continue
        if symbol not in meta.index:
            continue
        row = meta.loc[symbol]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        mcap = pd.to_numeric(row.get(mcap_col), errors="coerce") if mcap_col else np.nan
        revenue = pd.to_numeric(row.get(revenue_col), errors="coerce") if revenue_col else np.nan
        # Production behavior: missing revenue passes; only small, pre-revenue clinical names are excluded.
        out.at[symbol] = bool(pd.notna(mcap) and pd.notna(revenue) and mcap < 1e10 and revenue < 5e7)
    return out


def rebalance_sessions(calendar: pd.DatetimeIndex) -> set[pd.Timestamp]:
    start = calendar.min().normalize() - pd.Timedelta(days=21)
    end = calendar.max().normalize() + pd.Timedelta(days=21)
    mondays = pd.date_range(start, end, freq="W-MON")
    targets = [d for d in mondays if (d - ANCHOR_MONDAY).days % 14 == 0]
    sessions: set[pd.Timestamp] = set()
    for target in targets:
        candidates = calendar[(calendar >= target) & (calendar <= target + pd.Timedelta(days=4))]
        if len(candidates):
            sessions.add(pd.Timestamp(candidates[0]))
    return sessions


def core_signal_frames(market: dict, root: Path) -> dict:
    close, volume = market["close"], market["volume"]
    ret63 = close.pct_change(63, fill_method=None)
    ret189 = close.pct_change(189, fill_method=None)
    rs63 = ret63.rank(axis=1, pct=True, method="average") * 100.0
    rs189 = ret189.rank(axis=1, pct=True, method="average") * 100.0
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    dollar_volume = (close * volume).rolling(20).mean()
    excluded = structural_exclusions(root, list(close.columns), market["industry_map"])
    return {
        "rs63": rs63,
        "rs189": rs189,
        "sma50": sma50,
        "sma200": sma200,
        "dollar_volume": dollar_volume,
        "excluded": excluded,
    }


def core_candidates(date: pd.Timestamp, market: dict, signal: dict) -> tuple[list[str], pd.Series]:
    close = market["close"].loc[date]
    rs63, rs189 = signal["rs63"].loc[date], signal["rs189"].loc[date]
    sma50, sma200 = signal["sma50"].loc[date], signal["sma200"].loc[date]
    dvol = signal["dollar_volume"].loc[date]
    base = (
        (sma50 > sma200)
        & (dvol >= 10_000_000.0)
        & (close >= 5.0)
        & (rs189 >= 85.0)
        & (~signal["excluded"])
    ).fillna(False)
    rank = pd.Series(np.nan, index=close.index, dtype=float)
    rank.loc[base] = rs189.loc[base].rank(ascending=False, method="min")
    leader = base & (rs63 >= 85.0) & (close > sma200)
    picks = rs189.loc[leader].sort_values(ascending=False, kind="mergesort").head(N_PORT).index.tolist()
    return picks, rank


def mark_nav(cash: float, lots: dict, prices: pd.Series) -> tuple[float, float]:
    gross = 0.0
    for symbol, lot in lots.items():
        px = prices.get(symbol, np.nan)
        if pd.notna(px):
            gross += lot["shares"] * float(px)
    return cash + gross, gross


def sell_symbol(cash: float, lots: dict, symbol: str, price: float) -> tuple[float, float]:
    lot = lots.pop(symbol)
    gross = lot["shares"] * price
    return cash + gross * (1.0 - COST), gross


def simulate_core12(market: dict, signal: dict, nq: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    close, open_ = market["close"], market["open"]
    calendar = close.index[(close.index >= ANALYSIS_START) & (close.index <= ANALYSIS_END)]
    rebalances = rebalance_sessions(calendar)
    nq_color = nq["nq_color"].reindex(close.index).ffill()
    lots: dict[str, dict] = {}
    cash = 1.0
    initialized = False
    prior_gate = None
    turnover = 0.0
    records: list[dict] = []

    for i, date in enumerate(calendar):
        previous = close.index[close.index.get_loc(date) - 1]
        gate = str(nq_color.get(previous, "Red"))
        open_prices = open_.loc[date]

        for symbol in list(lots):
            px = open_prices.get(symbol, np.nan)
            if lots[symbol].get("stop_next") and pd.notna(px) and px > 0:
                cash, sold = sell_symbol(cash, lots, symbol, float(px))
                turnover += sold

        if gate == "Red":
            for symbol in list(lots):
                px = open_prices.get(symbol, np.nan)
                if pd.notna(px) and px > 0:
                    cash, sold = sell_symbol(cash, lots, symbol, float(px))
                    turnover += sold
        else:
            recovery = prior_gate == "Red" and gate in ("Blue", "Green")
            do_rebalance = gate in ("Blue", "Green") and (date in rebalances or recovery or not initialized)
            if do_rebalance:
                picks, continuation_rank = core_candidates(previous, market, signal)
                survivors = [s for s in lots if pd.notna(continuation_rank.get(s)) and continuation_rank.get(s) <= 24]
                selected = survivors[:N_PORT]
                selected.extend([s for s in picks if s not in selected][: N_PORT - len(selected)])

                nav_open, _ = mark_nav(cash, lots, open_prices)
                target_value = nav_open / N_PORT
                for symbol in list(lots):
                    if symbol not in selected:
                        px = open_prices.get(symbol, np.nan)
                        if pd.notna(px) and px > 0:
                            cash, sold = sell_symbol(cash, lots, symbol, float(px))
                            turnover += sold

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
                            lots[symbol] = {
                                "shares": buy / px,
                                "entry_px": px,
                                "peak": px,
                                "stop_next": False,
                            }
                        else:
                            lots[symbol]["shares"] += buy / px
                    elif delta < -1e-12 and symbol in lots:
                        sell = min(-delta, current_value)
                        gross_shares = sell / px
                        lots[symbol]["shares"] -= gross_shares
                        cash += sell * (1.0 - COST)
                        turnover += sell
                initialized = True

        close_prices = close.loc[date]
        nav_close, gross_close = mark_nav(cash, lots, close_prices)
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
                "gate_signal": gate,
                "rebalance_execution": date in rebalances,
            }
        )
        prior_gate = gate

    daily = pd.DataFrame(records).set_index("date")
    result = {
        **metrics(daily.nav.pct_change(fill_method=None).fillna(0.0)),
        "turnover_nav": float(turnover / daily.nav.mean()),
        "avg_exposure": float(daily.exposure.mean()),
        "max_exposure": float(daily.exposure.max()),
        "max_positions": int(daily.positions.max()),
        "rebalance_sessions": int(daily.rebalance_execution.sum()),
    }
    return result, daily


def vix_daily() -> pd.DataFrame:
    raw = va.load_vix("1990-01-02", "2026-03-23")
    enriched = va.add_expanding_sigma(raw)
    phases, events = va.build_sequence(enriched)
    check = va.validate_recent(events)
    if not check["all_match"]:
        raise RuntimeError("VIX Sequence production-date validation failed")
    return phases


def panic_series(
    trades: pd.DataFrame,
    market: dict,
    vix: pd.DataFrame,
    block_event_rollover: bool,
) -> tuple[dict, pd.DataFrame]:
    selected = trades[
        trades.kind.eq("RISE")
        & trades.threshold.eq(30)
        & trades.RS63_TOP3.astype(bool)
        & trades.signal_top3.astype(bool)
    ].copy()
    selected = selected.sort_values(["day0_date", "theme", "symbol", "signal_date"]).drop_duplicates(
        ["day0_date", "theme", "symbol"], keep="first"
    )
    if block_event_rollover:
        phase = vix["phase"].reindex(pd.to_datetime(selected.signal_date)).to_numpy()
        selected = selected[~pd.Series(phase, index=selected.index).isin(["EVENT", "ROLLOVER"])].copy()
    selected["rank_priority"] = selected.rank63 - 1.0
    calendar = market["close"].index[
        (market["close"].index >= ANALYSIS_START) & (market["close"].index <= ANALYSIS_END)
    ]
    active = pd.DataFrame(False, index=market["close"].index, columns=[])
    # The selected rule already requires signal-date Theme top-three. Theme cap remains two.
    themes = sorted(selected.theme.astype(str).unique())
    active = active.reindex(columns=themes, fill_value=True)
    result, daily = panic_portfolio.simulate(
        calendar,
        market["open"],
        market["close"],
        active,
        market["close"].ewm(span=21, adjust=False).mean(),
        selected,
        0.029,
        4,
        20,
        "full",
        False,
    )
    daily = daily.set_index("date")
    result["input_signals"] = int(len(selected))
    result["vix_event_rollover_block"] = bool(block_event_rollover)
    return result, daily


def tqqq_components(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    x["date"] = pd.to_datetime(x.date).dt.normalize()
    x = x.set_index("date").sort_index()
    current = x["target_CURRENT30"].shift(2).fillna(0.0)
    exact = x["target_M30_TOUCH30_F80_D10"].shift(2).fillna(0.0)
    aggressive = x["target_FINAL80_100"].shift(2).fillna(0.0)
    out = pd.DataFrame(
        {
            "tqqq_ret": x.tqqq_ret_usd.fillna(0.0),
            "tq_current": current,
            "tq_exact80": exact,
            "tq_aggressive": aggressive,
        }
    )
    out["exact_rebound"] = out.tq_exact80 > out.tq_current + 1e-12
    return out


def tqqq_contribution(tqqq_ret: pd.Series, effective_target: pd.Series) -> pd.Series:
    turnover = effective_target.diff().abs().fillna(0.0)
    return effective_target * tqqq_ret - turnover * COST


def strategy_return(
    data: pd.DataFrame,
    tqqq_target: pd.Series,
    core_cap: pd.Series,
    include_panic: bool,
) -> tuple[pd.Series, pd.DataFrame]:
    panic_exposure = data.panic_exposure if include_panic else pd.Series(0.0, index=data.index)
    panic_return = data.panic_return if include_panic else pd.Series(0.0, index=data.index)
    target = pd.to_numeric(tqqq_target, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    cap = pd.to_numeric(core_cap, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    core_weight = np.minimum(cap, np.maximum(0.0, 1.0 - target - panic_exposure))
    # Internal Core12 buys/sells already pay costs. This only charges resizing of an existing sleeve.
    core_turnover = (
        core_weight.diff().abs().fillna(0.0)
        * data.core_exposure.shift(1).fillna(0.0)
        * COST
    )
    tqqq_return = tqqq_contribution(data.tqqq_ret, target)
    total = core_weight * data.core_return - core_turnover + panic_return + tqqq_return
    detail = pd.DataFrame(
        {
            "return": total,
            "core_weight": core_weight,
            "tqqq_weight": target,
            "panic_exposure": panic_exposure,
            "total_exposure": core_weight * data.core_exposure + target + panic_exposure,
        },
        index=data.index,
    )
    return total, detail


def build_strategies(data: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.DataFrame]]:
    tactical = data.exact_rebound.astype(bool)
    base_cap = pd.Series(0.70, index=data.index)
    stock_cap = pd.Series(np.where(tactical, 0.80, 0.70), index=data.index)
    balanced_target = pd.Series(np.where(tactical, np.maximum(data.tq_current, 0.50), data.tq_current), index=data.index)
    stock_heavy_target = pd.Series(
        np.where(tactical, np.minimum(data.tq_current, 0.20), data.tq_current),
        index=data.index,
    )
    specs = {
        "BASE_CORE70_CURRENT30": (data.tq_current, base_cap, True),
        "EXACT_REBOUND_TQQQ80": (data.tq_exact80, base_cap, True),
        "EXACT_REBOUND_BALANCED50": (balanced_target, base_cap, True),
        "EXACT_REBOUND_STOCK80": (stock_heavy_target, stock_cap, True),
        "EXACT_REBOUND_TQQQ80_NO_PANIC_STOCK": (data.tq_exact80, base_cap, False),
        "AGGRESSIVE_TQQQ_NORMAL": (data.tq_aggressive, base_cap, True),
    }
    returns: dict[str, pd.Series] = {}
    details: dict[str, pd.DataFrame] = {}
    for name, (target, cap, include_panic) in specs.items():
        returns[name], details[name] = strategy_return(data, target, cap, include_panic)
    return returns, details


def summarize_strategies(returns: dict[str, pd.Series], details: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    periods = (
        ("ALL", ANALYSIS_START, ANALYSIS_END),
        ("DISCOVERY", ANALYSIS_START, DISCOVERY_END),
        ("CONFIRM", CONFIRM_START, ANALYSIS_END),
    )
    for name, series in returns.items():
        for period, start, end in periods:
            r = series.loc[start:end]
            detail = details[name].loc[start:end]
            rows.append(
                {
                    "strategy": name,
                    "period": period,
                    **metrics(r),
                    "avg_core_weight": float(detail.core_weight.mean()),
                    "avg_tqqq_weight": float(detail.tqqq_weight.mean()),
                    "avg_panic_exposure": float(detail.panic_exposure.mean()),
                    "max_total_exposure": float(detail.total_exposure.max()),
                    "cap_breach_days": int((detail.total_exposure > 1.0000001).sum()),
                }
            )
    return pd.DataFrame(rows)


def regime_statistics(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    regime = pd.Series("OTHER", index=data.index, dtype=object)
    regime.loc[data.exact_rebound] = "EXACT_REBOUND"
    healthy = (~data.exact_rebound) & data.nq_color.isin(["Blue", "Green"]) & (data.mc >= 35)
    soft = (~data.exact_rebound) & data.nq_color.isin(["Blue", "Green"]) & (data.mc >= 20) & (data.mc < 35)
    risk = (~data.exact_rebound) & (data.nq_color.isin(["Yellow", "Red"]) | (data.mc < 20))
    regime.loc[healthy] = "HEALTHY_UPTREND"
    regime.loc[soft] = "SOFT_UPTREND"
    regime.loc[risk] = "RISK_OFF"
    data["regime"] = regime

    rows = []
    for period, start, end in (
        ("ALL", ANALYSIS_START, ANALYSIS_END),
        ("DISCOVERY", ANALYSIS_START, DISCOVERY_END),
        ("CONFIRM", CONFIRM_START, ANALYSIS_END),
    ):
        block = data.loc[start:end]
        for label, group in block.groupby("regime", observed=True):
            for component, column in (
                ("CORE12_FULLY_FUNDED", "core_return"),
                ("TQQQ_FULLY_FUNDED", "tqqq_ret"),
                ("PANIC_STOCK_INCREMENT", "panic_return"),
            ):
                r = group[column]
                rows.append(
                    {
                        "period": period,
                        "regime": label,
                        "component": component,
                        "days": int(len(r)),
                        "mean_daily": float(r.mean()),
                        "median_daily": float(r.median()),
                        "win_daily": float((r > 0).mean()),
                        "cumulative": float((1 + r).prod() - 1),
                        "annualized_mean": float(r.mean() * 252),
                        "annualized_vol": float(r.std(ddof=1) * np.sqrt(252)),
                    }
                )

    event_rows = []
    tactical = data.exact_rebound.astype(bool)
    event_id = (tactical & ~tactical.shift(1, fill_value=False)).cumsum().where(tactical)
    for event, group in data[tactical].groupby(event_id[tactical]):
        event_rows.append(
            {
                "event": int(event),
                "start": str(group.index.min().date()),
                "end": str(group.index.max().date()),
                "days": int(len(group)),
                "core12_return": float((1 + group.core_return).prod() - 1),
                "tqqq_return": float((1 + group.tqqq_ret).prod() - 1),
                "panic_stock_increment": float((1 + group.panic_return).prod() - 1),
                "vix_phases": ",".join(sorted(set(group.vix_phase.dropna().astype(str)))),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(event_rows)


def paired_bootstrap(returns: dict[str, pd.Series], seed: int = 280828) -> pd.DataFrame:
    names = list(returns)
    frame = pd.concat([returns[name].rename(name) for name in names], axis=1).fillna(0.0)
    n = len(frame)
    horizon = min(2520, n)
    block = 60
    simulations = 1000
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(horizon / block))
    offsets = np.arange(block)
    starts = rng.integers(0, n - block + 1, size=(simulations, blocks))
    paths = (starts[:, :, None] + offsets).reshape(simulations, -1)[:, :horizon]
    rows = []
    base = "BASE_CORE70_CURRENT30"
    values = frame.to_numpy(float)
    for sim, ix in enumerate(paths):
        sample = values[ix]
        sample_metrics = {}
        for j, name in enumerate(names):
            eq = np.cumprod(1 + sample[:, j])
            dd = eq / np.maximum.accumulate(eq) - 1
            sample_metrics[name] = {
                "cagr": float(eq[-1] ** (252 / horizon) - 1),
                "mdd": float(dd.min()),
                "end": float(eq[-1]),
            }
        for name in names:
            rows.append(
                {
                    "sim": sim,
                    "strategy": name,
                    **sample_metrics[name],
                    "cagr_minus_base": sample_metrics[name]["cagr"] - sample_metrics[base]["cagr"],
                    "mdd_minus_base": sample_metrics[name]["mdd"] - sample_metrics[base]["mdd"],
                    "end_minus_base": sample_metrics[name]["end"] - sample_metrics[base]["end"],
                }
            )
    raw = pd.DataFrame(rows)
    summary = raw.groupby("strategy", observed=True).agg(
        cagr_median=("cagr", "median"),
        cagr_p05=("cagr", lambda x: x.quantile(0.05)),
        mdd_median=("mdd", "median"),
        mdd_p05=("mdd", lambda x: x.quantile(0.05)),
        cagr_delta_median=("cagr_minus_base", "median"),
        cagr_delta_p05=("cagr_minus_base", lambda x: x.quantile(0.05)),
        probability_cagr_beats_base=("cagr_minus_base", lambda x: float((x > 0).mean())),
        probability_mdd_beats_base=("mdd_minus_base", lambda x: float((x > 0).mean())),
    ).reset_index()
    return summary


def evidence_ledger(inputs: Path) -> dict:
    strength = inputs / "rsi-strong-stock-threshold-interaction-audit"
    marketwide = inputs / "market-wide-rs189-rsi-reset-audit"
    stock_port = inputs / "rsi-reset-portfolio-construction-audit"
    mc_nq = inputs / "rsi30-mc-nqsar-audit"
    vix = inputs / "rsi30-vix-sequence-audit"
    tq = inputs / "tqqq-stage56-mandate-fx-tax"
    ledger = {
        "stock_threshold": {
            "signal_strength_summary": str(locate_file(strength, "signal_strength_summary.csv").relative_to(inputs)),
            "portfolio_rule_comparison": str(locate_file(strength, "portfolio_rule_comparison.csv").relative_to(inputs)),
            "threshold_pairwise": str(locate_file(strength, "threshold_pairwise.csv").relative_to(inputs)),
        },
        "theme_free_rs189": {
            "summary": str(locate_file(marketwide, "market_rs189_summary.csv").relative_to(inputs)),
            "portfolio": str(locate_file(marketwide, "market_rs189_portfolio.csv").relative_to(inputs)),
            "combined": str(locate_file(marketwide, "combined_theme_market_portfolio.csv").relative_to(inputs)),
        },
        "stock_panic_portfolio": {
            "scenarios": str(locate_file(stock_port, "portfolio_scenarios.csv").relative_to(inputs)),
            "summary": str(locate_file(stock_port, "summary.json").relative_to(inputs)),
        },
        "mc_nqsar": {"summary": str(locate_file(mc_nq, "summary.json").relative_to(inputs))},
        "vix": {
            "summary": str(locate_file(vix, "summary.json").relative_to(inputs)),
            "sequence_validation": str(locate_file(vix, "sequence_validation.json").relative_to(inputs)),
        },
        "tqqq": {
            "scan": str(locate_file(tq, "tqqq_stage56_mandate_scan.csv").relative_to(inputs)),
            "subperiods": str(locate_file(tq, "tqqq_stage56_subperiods.csv").relative_to(inputs)),
            "mc": str(locate_file(tq, "tqqq_stage56_mc_summary.csv").relative_to(inputs)),
            "summary": str(locate_file(tq, "tqqq_stage56_summary.json").relative_to(inputs)),
        },
    }
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    inputs = Path(args.inputs)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    market = load_full_market(root)
    signal = core_signal_frames(market, root)
    nq = mn.build_nqsar("2010-01-01", "2026-03-23")
    mc = mn.build_mc("2026-03-20")
    vix = vix_daily()

    core_result, core_daily = simulate_core12(market, signal, nq)
    strength_trades = pd.read_csv(
        locate_file(inputs / "rsi-strong-stock-threshold-interaction-audit", "threshold_trade_rows.csv.gz"),
        compression="gzip",
        parse_dates=["day0_date", "signal_date", "entry_date"],
    )
    panic_all_result, panic_all = panic_series(strength_trades, market, vix, False)
    panic_safe_result, panic_safe = panic_series(strength_trades, market, vix, True)

    tq_raw = pd.read_csv(
        locate_file(inputs / "tqqq-stage56-mandate-fx-tax", "tqqq_stage56_daily.csv.gz"),
        compression="gzip",
    )
    tq = tqqq_components(tq_raw)

    data = pd.DataFrame(index=core_daily.index)
    data["core_return"] = core_daily.nav.pct_change(fill_method=None).fillna(0.0)
    data["core_exposure"] = core_daily.exposure.fillna(0.0)
    data["panic_return"] = panic_safe.nav.pct_change(fill_method=None).fillna(0.0)
    data["panic_exposure"] = panic_safe.exposure.fillna(0.0)
    data["panic_unblocked_return"] = panic_all.nav.pct_change(fill_method=None).fillna(0.0)
    data = data.join(tq, how="inner")
    data["nq_color"] = nq.nq_color.reindex(data.index).ffill()
    data["mc"] = mc.mc.reindex(data.index).ffill()
    data["vix_phase"] = vix.phase.reindex(data.index).ffill()
    data = data.dropna(subset=["tqqq_ret", "tq_current", "nq_color", "mc"])

    returns, details = build_strategies(data)
    strategy_summary = summarize_strategies(returns, details)
    regime_summary, rebound_events = regime_statistics(data)
    bootstrap = paired_bootstrap(returns)

    daily = data.copy()
    for name, series in returns.items():
        daily[f"ret_{name}"] = series
        daily[f"core_weight_{name}"] = details[name].core_weight
        daily[f"tqqq_weight_{name}"] = details[name].tqqq_weight
        daily[f"total_exposure_{name}"] = details[name].total_exposure
    daily.reset_index(names="date").to_csv(output / "integrated_daily.csv.gz", index=False, compression="gzip")
    strategy_summary.to_csv(output / "strategy_summary.csv", index=False)
    regime_summary.to_csv(output / "regime_component_summary.csv", index=False)
    rebound_events.to_csv(output / "exact_rebound_events.csv", index=False)
    bootstrap.to_csv(output / "paired_bootstrap_summary.csv", index=False)
    core_daily.reset_index().to_csv(output / "core12_daily.csv.gz", index=False, compression="gzip")
    panic_safe.reset_index().to_csv(output / "panic_stock_safe_daily.csv.gz", index=False, compression="gzip")

    max_exposure = float(max(detail.total_exposure.max() for detail in details.values()))
    summary = {
        "status": "INTEGRATED_RULEBOOK_ALLOCATION_AUDIT",
        "coverage": {
            "start": str(data.index.min().date()),
            "end": str(data.index.max().date()),
            "sessions": int(len(data)),
            "download": market["diagnostic"],
        },
        "core12": core_result,
        "panic_stock_unblocked": panic_all_result,
        "panic_stock_vix_safe": panic_safe_result,
        "capital_cap": {"maximum_total_exposure": max_exposure, "breach": bool(max_exposure > 1.0000001)},
        "definitions": {
            "core12": "production-matched biweekly Core 12: global RS189 top, RS189>=85, RS63>=85, 50SMA>200SMA, close>200SMA, dollar volume>=10M, price>=5, maximum 12, continuation top24, NQSAR gate, next-open execution, initial -25% / peak -30% stop",
            "panic_stock": "Theme Momentum Day0 RS63 top3; RSI14 <=30 then first up day within 20 sessions; still theme RS63 top3 at signal; next open; 2.9% x max4; max2/theme; 20 sessions; VIX EVENT/ROLLOVER blocked in the integrated rule",
            "tqqq": "Stage56 raw targets shifted two sessions to match open-to-open return convention; exact rebound is M30_TOUCH30_F80_D10 above CURRENT30",
            "capital_priority": "TQQQ target plus measured panic-stock exposure are reserved first; Core12 receives the residual up to its strategy cap; total exposure capped at 100%",
            "regimes": "EXACT_REBOUND has priority; otherwise NQSAR Blue/Green plus MC57>=35=healthy, MC57 20-35=soft, Yellow/Red or MC57<20=risk-off",
        },
        "limitations": [
            "Current-universe/current-taxonomy survivorship bias remains in both stock sleeves.",
            "No pristine untouched out-of-sample period remains after iterative research.",
            "Core12 is reconstructed from the documented production rules; it is not the missing original V38 stock-engine ledger.",
            "The allocation comparison is pre-tax USD. Stage56 separately supplies TQQQ JPY and Japanese-tax sensitivity.",
            "Core12 is close-marked while TQQQ is open-to-open; all actions use prior-close signals and next-open execution, but daily mark timing remains approximate.",
            "Moving-block bootstrap resamples observed strategy returns and is not a forecast distribution.",
        ],
        "evidence": evidence_ledger(inputs),
    }
    (output / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)
    print(strategy_summary.to_string(index=False), flush=True)
    print(rebound_events.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
