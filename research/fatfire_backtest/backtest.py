from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

START_CAPITAL = 9_000_000.0
ANNUAL_CONTRIBUTION = 1_000_000.0
TAX_RATE = 0.20315
START = "2011-01-03"
END = "2026-01-01"  # exclusive: full 2011-2025 calendar years

CORE = ["QQQ", "SPY", "TQQQ", "^VIX"]
BREADTH_ETFS = [
    "DIA", "IWM", "MDY", "RSP",
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC",
    "IYR", "IYT", "XHB", "XRT", "KRE", "KBE", "SMH", "IBB", "XBI", "ITA",
    "IGV", "IHI", "IHF", "IYZ", "XME", "XOP", "GDX",
]
ROTATION_ETFS = [
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC",
    "IYR", "IYT", "XHB", "XRT", "KRE", "KBE", "SMH", "IBB", "XBI", "ITA",
    "IGV", "IHI", "IHF", "IYZ", "XME", "XOP", "GDX",
]
ALL_TICKERS = list(dict.fromkeys(CORE + BREADTH_ETFS + ROTATION_ETFS))

# Exact thresholds/weights from V38 market policy v1.0.0 (historical production commit).
COMPONENT_WEIGHTS = {
    "index_trend": 0.30,
    "short_breadth": 0.15,
    "medium_breadth": 0.20,
    "long_breadth": 0.10,
    "relative_strength_breadth": 0.15,
    "sector_participation": 0.10,
}

REGIME_EXPOSURE = {"BLUE": 1.0, "GREEN": 0.75, "YELLOW": 0.35, "RED": 0.0}


@dataclass
class TaxResult:
    equity: pd.Series
    yearly: pd.DataFrame
    total_tax: float
    total_contributions: float


def _download(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Need warmup for 200d/252d features. Download in one request, then tolerate later ETF inceptions.
    raw = yf.download(
        ALL_TICKERS,
        start="2009-01-01",
        end=end,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no market data")

    def field(name: str) -> pd.DataFrame:
        out: dict[str, pd.Series] = {}
        for ticker in ALL_TICKERS:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    s = raw[(ticker, name)]
                else:
                    s = raw[name]
                out[ticker] = pd.to_numeric(s, errors="coerce")
            except Exception:
                out[ticker] = pd.Series(index=raw.index, dtype=float)
        frame = pd.DataFrame(out).sort_index()
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        return frame

    close = field("Close")
    open_ = field("Open")
    volume = field("Volume")
    high = field("High")
    # A few yfinance batches can return a ticker entirely empty. Core tickers are mandatory.
    missing_core = [t for t in CORE if t not in close or close[t].dropna().empty]
    if missing_core:
        raise RuntimeError(f"missing core market data: {missing_core}")
    return close, open_, volume, high


def _masked_ratio(condition: pd.DataFrame, valid: pd.DataFrame) -> pd.Series:
    return condition.astype(float).where(valid).mean(axis=1)


def build_v38_proxy(close: pd.DataFrame, open_: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct the V38 v1.0.0 market score point-in-time.

    Index-trend logic and score weights/thresholds match the historical V38 policy.
    Cross-sectional stock breadth is proxied with a fixed ETF panel to avoid using today's stock universe
    back in 2011. ETFs only enter calculations after their own required history exists.
    """
    q = close["QQQ"]
    spy = close["SPY"]
    q_sma20 = q.rolling(20, min_periods=20).mean()
    q_sma50 = q.rolling(50, min_periods=50).mean()
    q_sma200 = q.rolling(200, min_periods=200).mean()
    index_trend = pd.concat(
        [
            q > q_sma20,
            q > q_sma50,
            q > q_sma200,
            q_sma20 > q_sma20.shift(5),
            q_sma50 > q_sma50.shift(20),
        ],
        axis=1,
    ).astype(float).mean(axis=1)

    panel = close[BREADTH_ETFS]
    sma10 = panel.rolling(10, min_periods=10).mean()
    sma50 = panel.rolling(50, min_periods=50).mean()
    sma200 = panel.rolling(200, min_periods=200).mean()

    short_breadth = _masked_ratio(panel > sma10, panel.notna() & sma10.notna())
    medium_breadth = _masked_ratio(panel > sma50, panel.notna() & sma50.notna())
    long_breadth = _masked_ratio(panel > sma200, panel.notna() & sma200.notna())

    panel_r63 = panel.pct_change(63, fill_method=None)
    panel_r126 = panel.pct_change(126, fill_method=None)
    spy_r63 = spy.pct_change(63, fill_method=None)
    spy_r126 = spy.pct_change(126, fill_method=None)
    rs63 = panel_r63.sub(spy_r63, axis=0)
    rs126 = panel_r126.sub(spy_r126, axis=0)
    pos63 = _masked_ratio(rs63 > 0, rs63.notna())
    pos126 = _masked_ratio(rs126 > 0, rs126.notna())
    rs_breadth = pos63 * 0.6 + pos126 * 0.4

    rotation = close[ROTATION_ETFS]
    rot63 = rotation.pct_change(63, fill_method=None)
    rel63 = rot63.sub(spy_r63, axis=0)
    top1 = rel63.idxmax(axis=1)
    # Point-in-time top 3 sectors; sector participation proxy = fraction of those ETFs with positive 63d return.
    top3_names: list[list[str]] = []
    sector_participation = []
    for dt in rel63.index:
        row = rel63.loc[dt].dropna().sort_values(ascending=False)
        names = row.index[:3].tolist()
        top3_names.append(names)
        if not names:
            sector_participation.append(np.nan)
        else:
            vals = rot63.loc[dt, names].dropna()
            sector_participation.append(float((vals > 0).mean()) if len(vals) else np.nan)
    sector_participation = pd.Series(sector_participation, index=rel63.index, dtype=float)

    components = pd.DataFrame(
        {
            "index_trend": index_trend,
            "short_breadth": short_breadth,
            "medium_breadth": medium_breadth,
            "long_breadth": long_breadth,
            "relative_strength_breadth": rs_breadth,
            "sector_participation": sector_participation,
        }
    )
    weighted_num = pd.Series(0.0, index=components.index)
    weighted_den = pd.Series(0.0, index=components.index)
    for name, weight in COMPONENT_WEIGHTS.items():
        valid = components[name].notna()
        weighted_num = weighted_num.add(components[name].fillna(0) * weight)
        weighted_den = weighted_den.add(valid.astype(float) * weight)
    score = weighted_num / weighted_den.replace(0, np.nan)

    regime = pd.Series("RED", index=score.index, dtype="object")
    regime.loc[score >= 0.38] = "YELLOW"
    regime.loc[score >= 0.55] = "GREEN"
    regime.loc[score >= 0.72] = "BLUE"
    regime.loc[score.isna()] = "UNKNOWN"

    # Same warning concepts as V38 v1.0.0; useful diagnostics, not directly optimized in this test.
    warning_count = pd.Series(0, index=score.index, dtype=int)
    warning_count += (medium_breadth < 0.40).fillna(False).astype(int)
    warning_count += (short_breadth < medium_breadth - 0.15).fillna(False).astype(int)
    warning_count += ((q > q_sma50) & (medium_breadth < 0.45)).fillna(False).astype(int)

    vix = close["^VIX"]
    vix_p95 = vix.rolling(252, min_periods=126).quantile(0.95)
    vix_event = (vix >= 30) & (vix >= vix_p95)

    qret = q.pct_change(fill_method=None)
    qlow20 = q.rolling(20, min_periods=20).min()
    local_low = q <= qlow20 * 1.002
    qvol = volume["QQQ"]
    qopen = open_["QQQ"]
    ftd = pd.Series(False, index=q.index)
    last_low_pos: int | None = None
    armed = False
    red_streak = 0
    for i, dt in enumerate(q.index):
        r = regime.loc[dt]
        red_streak = red_streak + 1 if r == "RED" else 0
        if bool(vix_event.loc[dt]) or red_streak >= 3:
            armed = True
        if bool(local_low.loc[dt]):
            last_low_pos = i
        if armed and last_low_pos is not None:
            age = i - last_low_pos
            if 4 <= age <= 12:
                cond = (
                    pd.notna(qret.iloc[i]) and float(qret.iloc[i]) >= 0.015
                    and pd.notna(qvol.iloc[i]) and pd.notna(qvol.iloc[i - 1]) and qvol.iloc[i] > qvol.iloc[i - 1]
                    and pd.notna(qopen.iloc[i]) and q.iloc[i] > qopen.iloc[i]
                )
                if cond:
                    ftd.iloc[i] = True
                    armed = False
            elif age > 12:
                last_low_pos = None

    # Experimental staged re-entry. It is reported separately from the core V38 regime backtest.
    stage = pd.Series(3, index=q.index, dtype=int)
    current_stage = 3
    red_streak = 0
    shock_armed = False
    days_since_reset = 999
    for i, dt in enumerate(q.index):
        r = regime.loc[dt]
        red_streak = red_streak + 1 if r == "RED" else 0
        if bool(vix_event.loc[dt]) or red_streak >= 3:
            current_stage = 0
            shock_armed = True
            days_since_reset = 0
        else:
            days_since_reset += 1
        if shock_armed and bool(ftd.loc[dt]):
            current_stage = max(current_stage, 1)
        if current_stage >= 1 and r == "GREEN":
            current_stage = max(current_stage, 2)
        if current_stage >= 1 and r == "BLUE":
            current_stage = 3
            shock_armed = False
        # Fallback: a sustained recovered regime can re-open risk even if the strict FTD proxy was missed.
        if shock_armed and days_since_reset >= 20 and r in {"GREEN", "BLUE"}:
            current_stage = 2 if r == "GREEN" else 3
            if r == "BLUE":
                shock_armed = False
        if r == "RED":
            current_stage = 0
        stage.loc[dt] = current_stage

    out = components.copy()
    out["score"] = score
    out["regime"] = regime
    out["recommended_exposure"] = regime.map(REGIME_EXPOSURE).fillna(0.0)
    out["warning_count_proxy"] = warning_count
    out["top1_sector"] = top1
    out["top3_sectors"] = ["|".join(x) for x in top3_names]
    out["vix"] = vix
    out["vix_event"] = vix_event.fillna(False)
    out["ftd_proxy"] = ftd
    out["reentry_stage"] = stage
    return out


def _next_open_returns(open_: pd.DataFrame) -> pd.DataFrame:
    # Signal is computed after close t. Earliest tradable entry is open t+1; hold until open t+2.
    return open_.shift(-2).div(open_.shift(-1)).sub(1.0)


def _weights_for_strategy(name: str, state: pd.DataFrame) -> pd.DataFrame:
    cols = [t for t in ["QQQ", "TQQQ"] + ROTATION_ETFS if t in ALL_TICKERS]
    w = pd.DataFrame(0.0, index=state.index, columns=cols)

    if name == "QQQ_buy_hold":
        w["QQQ"] = 1.0
        return w
    if name == "TQQQ_buy_hold":
        w["TQQQ"] = 1.0
        return w
    if name == "V38_regime_QQQ":
        w["QQQ"] = state["recommended_exposure"]
        return w
    if name == "V38_regime_TQQQ":
        m = {"BLUE": 0.65, "GREEN": 0.35, "YELLOW": 0.0, "RED": 0.0}
        w["TQQQ"] = state["regime"].map(m).fillna(0.0)
        w["QQQ"] = state["regime"].map({"BLUE": 0.25, "GREEN": 0.30, "YELLOW": 0.15, "RED": 0.0}).fillna(0.0)
        return w
    if name not in {"V38_beta_rotation", "V38_beta_rotation_FTD"}:
        raise ValueError(name)

    for dt, row in state.iterrows():
        r = row["regime"]
        if r == "BLUE":
            tqqq, qqq, rot_budget = 0.50, 0.15, 0.25
        elif r == "GREEN":
            tqqq, qqq, rot_budget = 0.25, 0.20, 0.30
        elif r == "YELLOW":
            tqqq, qqq, rot_budget = 0.00, 0.10, 0.10
        else:
            tqqq, qqq, rot_budget = 0.00, 0.00, 0.00

        scale = 1.0
        if name.endswith("_FTD"):
            scale = {0: 0.0, 1: 0.35, 2: 0.70, 3: 1.0}.get(int(row["reentry_stage"]), 1.0)
        w.at[dt, "TQQQ"] = tqqq * scale
        w.at[dt, "QQQ"] = qqq * scale

        names = [x for x in str(row["top3_sectors"]).split("|") if x and x in w.columns]
        chosen = names[:2] if r in {"BLUE", "GREEN"} else names[:1]
        if chosen:
            each = rot_budget * scale / len(chosen)
            for ticker in chosen:
                w.at[dt, ticker] += each
    return w


def strategy_returns(weights: pd.DataFrame, next_open_ret: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    common = [c for c in weights.columns if c in next_open_ret.columns]
    # Missing return after an ETF inception is treated as uninvested cash; target generation only ranks valid ETFs.
    r = (weights[common] * next_open_ret[common].fillna(0.0)).sum(axis=1)
    turnover = weights[common].diff().abs().sum(axis=1) / 2.0
    return r, turnover


def simulate_tax(
    returns: pd.Series,
    start_capital: float = START_CAPITAL,
    annual_contribution: float = ANNUAL_CONTRIBUTION,
    tax_rate: float = TAX_RATE,
    loss_carryforward_years: int = 3,
) -> TaxResult:
    """Conservative annual-realization tax model.

    All positive calendar-year strategy P&L is treated as realized at year-end. Losses may offset gains for
    up to loss_carryforward_years. The annual contribution is added after tax on each calendar year's final
    trading signal date, which is deliberately conservative versus monthly/early-year saving.
    """
    ret = returns.dropna().copy()
    equity = float(start_capital)
    year_start_equity = equity
    total_tax = 0.0
    total_contrib = 0.0
    loss_vintages: list[tuple[int, float]] = []
    curve: dict[pd.Timestamp, float] = {}
    rows: list[dict] = []

    dates = list(ret.index)
    for i, dt in enumerate(dates):
        equity *= 1.0 + float(ret.loc[dt])
        curve[dt] = equity
        is_year_end = i == len(dates) - 1 or dates[i + 1].year != dt.year
        if not is_year_end:
            continue

        year = int(dt.year)
        pnl = equity - year_start_equity
        # Drop expired losses. A loss from Y can offset Y+1..Y+N.
        loss_vintages = [(y, loss) for y, loss in loss_vintages if year - y <= loss_carryforward_years]
        taxable = max(0.0, pnl)
        used_loss = 0.0
        if taxable > 0:
            updated: list[tuple[int, float]] = []
            for y, loss in loss_vintages:
                use = min(loss, taxable)
                taxable -= use
                used_loss += use
                remainder = loss - use
                if remainder > 1e-9:
                    updated.append((y, remainder))
            loss_vintages = updated
        elif pnl < 0:
            loss_vintages.append((year, -pnl))

        tax = taxable * tax_rate
        equity -= tax
        total_tax += tax
        pre_contrib = equity
        equity += annual_contribution
        total_contrib += annual_contribution
        curve[dt] = equity

        net_year_return = pre_contrib / year_start_equity - 1.0 if year_start_equity > 0 else np.nan
        rows.append(
            {
                "year": year,
                "start_equity": year_start_equity,
                "pnl_before_tax": pnl,
                "loss_offset_used": used_loss,
                "taxable_gain": taxable,
                "tax_paid": tax,
                "net_return_after_tax_before_contribution": net_year_return,
                "contribution": annual_contribution,
                "end_equity_after_tax_and_contribution": equity,
            }
        )
        year_start_equity = equity

    return TaxResult(
        equity=pd.Series(curve, name="equity_after_tax"),
        yearly=pd.DataFrame(rows),
        total_tax=total_tax,
        total_contributions=total_contrib,
    )


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def _goal_date(equity: pd.Series, goal: float) -> str | None:
    hit = equity[equity >= goal]
    return None if hit.empty else hit.index[0].date().isoformat()


def summarize(name: str, tax: TaxResult, turnover: pd.Series) -> dict:
    yr = tax.yearly
    yearly_returns = yr["net_return_after_tax_before_contribution"].dropna()
    twr = float(np.prod(1.0 + yearly_returns) ** (1.0 / len(yearly_returns)) - 1.0) if len(yearly_returns) else np.nan
    worst_year_row = yr.loc[yr["net_return_after_tax_before_contribution"].idxmin()] if len(yr) else None
    return {
        "strategy": name,
        "final_after_tax_jpy": float(tax.equity.iloc[-1]),
        "net_twr_cagr": twr,
        "max_drawdown_after_tax_curve": _max_drawdown(tax.equity),
        "worst_year": None if worst_year_row is None else int(worst_year_row["year"]),
        "worst_year_return": None if worst_year_row is None else float(worst_year_row["net_return_after_tax_before_contribution"]),
        "total_tax_jpy": float(tax.total_tax),
        "total_contributions_jpy": float(tax.total_contributions),
        "annualized_turnover_proxy": float(turnover.groupby(turnover.index.year).sum().mean()),
        "reach_200m": _goal_date(tax.equity, 200_000_000),
        "reach_300m": _goal_date(tax.equity, 300_000_000),
        "reach_540m": _goal_date(tax.equity, 540_000_000),
    }


def run(out_dir: Path, start: str = START, end: str = END) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    close, open_, volume, _ = _download(start, end)
    state = build_v38_proxy(close, open_, volume)
    eval_idx = state.loc[(state.index >= pd.Timestamp(start)) & (state.index < pd.Timestamp(end))].index
    state = state.loc[eval_idx].copy()
    next_ret = _next_open_returns(open_).reindex(eval_idx)

    strategies = [
        "QQQ_buy_hold",
        "TQQQ_buy_hold",
        "V38_regime_QQQ",
        "V38_regime_TQQQ",
        "V38_beta_rotation",
        "V38_beta_rotation_FTD",
    ]
    summaries: list[dict] = []
    equity_frame = pd.DataFrame(index=eval_idx)
    yearly_frames: list[pd.DataFrame] = []
    weights_meta: list[dict] = []
    for name in strategies:
        weights = _weights_for_strategy(name, state)
        ret, turnover = strategy_returns(weights, next_ret)
        tax = simulate_tax(ret)
        summaries.append(summarize(name, tax, turnover))
        equity_frame[name] = tax.equity.reindex(eval_idx).ffill()
        y = tax.yearly.copy()
        y.insert(0, "strategy", name)
        yearly_frames.append(y)
        weights_meta.append({
            "strategy": name,
            "mean_invested_fraction": float(weights.sum(axis=1).mean()),
            "max_invested_fraction": float(weights.sum(axis=1).max()),
        })

    regime_counts = state["regime"].value_counts().to_dict()
    result = {
        "period": {"start": start, "end_exclusive": end, "years": 15},
        "capital": {"start_jpy": START_CAPITAL, "annual_contribution_jpy": ANNUAL_CONTRIBUTION},
        "tax": {"rate": TAX_RATE, "loss_carryforward_years": 3, "model": "annual realization; contribution after year-end tax"},
        "market_policy": {
            "source": "V38 market policy v1.0.0 thresholds and component weights",
            "stock_breadth_reconstruction": "fixed ETF cross-section proxy; dynamic by available history; not full point-in-time stock universe",
            "signal_execution": "close t signal -> open t+1 entry -> open t+2 mark; no close look-ahead",
        },
        "regime_counts": {str(k): int(v) for k, v in regime_counts.items()},
        "vix_event_count": int(state["vix_event"].sum()),
        "ftd_proxy_count": int(state["ftd_proxy"].sum()),
        "weights_meta": weights_meta,
        "strategies": summaries,
    }

    state.to_csv(out_dir / "regimes.csv", index_label="date")
    equity_frame.to_csv(out_dir / "equity.csv", index_label="date")
    pd.concat(yearly_frames, ignore_index=True).to_csv(out_dir / "yearly.csv", index=False)
    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="research/fatfire_backtest/output")
    p.add_argument("--start", default=START)
    p.add_argument("--end", default=END)
    args = p.parse_args()
    run(Path(args.out), args.start, args.end)


if __name__ == "__main__":
    main()
