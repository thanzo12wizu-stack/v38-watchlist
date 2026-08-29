from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_rebalance_vs_trail as rt
import validate_early_rotation as er

SELECTIVE_SLOTS = 4
MIN_GROUP_MEMBERS = 3
VARIANTS = (
    "STOCK_RS189",
    "SECTOR20",
    "THEME15",
    "THEME30",
    "THEME45",
    "HIERARCHY_60_25_10_5",
    "ACTIVATION_PREF",
)


def build_group_context(root: Path, matrices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    close = matrices["close"]
    stock_cols = list(close.columns)
    stock_set = set(stock_cols)
    stock_ret = er.arithmetic_returns(close)

    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")

    theme_members = {
        t: [s for s in members if s in stock_set]
        for t, members in theme_members_all.items()
    }
    theme_members = {t: m for t, m in theme_members.items() if len(m) >= MIN_GROUP_MEMBERS}
    theme_ret = er.grouped_equal_weight(stock_ret, theme_members, MIN_GROUP_MEMBERS)
    theme63 = er.period_return(theme_ret, 63)
    theme_pct = theme63.rank(axis=1, pct=True, method="average") * 100.0
    theme_delta20 = theme_pct - theme_pct.shift(20)
    theme_delta_pct = theme_delta20.rank(axis=1, pct=True, method="average") * 100.0
    theme_breadth = er.breadth_above_ema21(close, theme_members, MIN_GROUP_MEMBERS).reindex(columns=theme_pct.columns)
    theme_score = (theme_pct + theme_delta_pct + theme_breadth) / 3.0
    theme_active = (theme_pct >= 80.0) & (theme_delta20 >= 15.0) & (theme_breadth >= 60.0)

    sector_groups: dict[str, list[str]] = defaultdict(list)
    industry_groups: dict[str, list[str]] = defaultdict(list)
    symbol_sector: dict[str, str] = {}
    symbol_industry: dict[str, str] = {}
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if not pair:
            continue
        sector, industry = pair
        if sector:
            sector_groups[sector].append(sym)
            symbol_sector[sym] = sector
        if industry:
            industry_groups[industry].append(sym)
            symbol_industry[sym] = industry
    sector_groups = {g: m for g, m in sector_groups.items() if len(m) >= MIN_GROUP_MEMBERS}
    industry_groups = {g: m for g, m in industry_groups.items() if len(m) >= MIN_GROUP_MEMBERS}
    sector_ret = er.grouped_equal_weight(stock_ret, sector_groups, MIN_GROUP_MEMBERS)
    industry_ret = er.grouped_equal_weight(stock_ret, industry_groups, MIN_GROUP_MEMBERS)
    sector_pct = er.period_return(sector_ret, 63).rank(axis=1, pct=True, method="average") * 100.0
    industry_pct = er.period_return(industry_ret, 63).rank(axis=1, pct=True, method="average") * 100.0

    stock_themes: dict[str, list[str]] = defaultdict(list)
    for theme, members in theme_members.items():
        for sym in members:
            stock_themes[sym].append(theme)

    return {
        "theme_score": theme_score,
        "theme_active": theme_active,
        "theme_pct": theme_pct,
        "theme_delta20": theme_delta20,
        "theme_breadth": theme_breadth,
        "sector_pct": sector_pct,
        "industry_pct": industry_pct,
        "stock_themes": dict(stock_themes),
        "symbol_sector": symbol_sector,
        "symbol_industry": symbol_industry,
        "taxonomy_candidates": taxonomy_candidates,
        "coverage": {
            "themes": int(len(theme_score.columns)),
            "sectors": int(len(sector_pct.columns)),
            "industries": int(len(industry_pct.columns)),
            "stocks_with_theme": int(sum(bool(stock_themes.get(s)) for s in stock_cols)),
            "stocks_total": int(len(stock_cols)),
        },
    }


def context_for_symbol(d: pd.Timestamp, sym: str, ctx: dict[str, Any]) -> dict[str, Any]:
    best_theme = None
    theme_score = np.nan
    theme_active = False
    themes = ctx["stock_themes"].get(sym, [])
    if themes and d in ctx["theme_score"].index:
        row = ctx["theme_score"].loc[d]
        vals = row.reindex(themes).dropna()
        if len(vals):
            best_theme = str(vals.idxmax())
            theme_score = float(vals.max())
            try:
                theme_active = bool(ctx["theme_active"].at[d, best_theme])
            except Exception:
                theme_active = False

    sector = ctx["symbol_sector"].get(sym)
    sector_score = np.nan
    if sector and d in ctx["sector_pct"].index and sector in ctx["sector_pct"].columns:
        x = ctx["sector_pct"].at[d, sector]
        if pd.notna(x):
            sector_score = float(x)

    industry = ctx["symbol_industry"].get(sym)
    industry_score = np.nan
    if industry and d in ctx["industry_pct"].index and industry in ctx["industry_pct"].columns:
        x = ctx["industry_pct"].at[d, industry]
        if pd.notna(x):
            industry_score = float(x)

    return {
        "best_theme": best_theme,
        "theme_score": theme_score,
        "theme_active": theme_active,
        "sector": sector,
        "sector_score": sector_score,
        "industry": industry,
        "industry_score": industry_score,
    }


def ranked_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], ctx: dict[str, Any], variant: str, n: int = base.N_PORT) -> list[tuple[str, dict[str, Any]]]:
    elig = matrices["new_eligible"].loc[d]
    stock_rs = matrices["rs189"].loc[d].where(elig).dropna()
    if stock_rs.empty:
        return []
    records: list[tuple[str, float, dict[str, Any]]] = []
    for sym, rs0 in stock_rs.items():
        c = context_for_symbol(d, str(sym), ctx)
        rs = float(rs0)
        ts = float(c["theme_score"]) if np.isfinite(c["theme_score"]) else 50.0
        ss = float(c["sector_score"]) if np.isfinite(c["sector_score"]) else 50.0
        ins = float(c["industry_score"]) if np.isfinite(c["industry_score"]) else 50.0
        if variant == "STOCK_RS189":
            score = rs
        elif variant == "SECTOR20":
            score = 0.80 * rs + 0.20 * ss
        elif variant == "THEME15":
            score = 0.85 * rs + 0.15 * ts
        elif variant == "THEME30":
            score = 0.70 * rs + 0.30 * ts
        elif variant == "THEME45":
            score = 0.55 * rs + 0.45 * ts
        elif variant == "HIERARCHY_60_25_10_5":
            score = 0.60 * rs + 0.25 * ts + 0.10 * ins + 0.05 * ss
        elif variant == "ACTIVATION_PREF":
            # Frozen prior activation definition. It is a preference, not a hard gate,
            # so exposure and fill mechanics remain comparable to baseline.
            score = rs + (1000.0 if c["theme_active"] else 0.0)
        else:
            raise ValueError(variant)
        c = dict(c)
        c["stock_rs189"] = rs
        c["rank_score"] = float(score)
        records.append((str(sym), float(score), c))
    records.sort(key=lambda x: (x[1], x[2]["stock_rs189"]), reverse=True)
    return [(sym, c) for sym, _, c in records[:n]]


def simulate(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], ctx: dict[str, Any], variant: str) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens, closes = matrices["open"], matrices["close"]
    breadth: pd.Series = meta["breadth"]
    nq: pd.DataFrame = meta["nq"]

    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    red_run = 0

    def px_at(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def exit_symbol(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += float(p["shares"]) * price
        trades.append({
            "variant": variant,
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "return": price / float(p["entry_price"]) - 1.0,
            "entry_bucket": p["entry_bucket"],
            "exit_reason": reason,
            "best_theme": p.get("best_theme"),
            "theme_score": p.get("theme_score"),
            "theme_active": p.get("theme_active"),
            "sector": p.get("sector"),
            "sector_score": p.get("sector_score"),
            "industry": p.get("industry"),
            "industry_score": p.get("industry_score"),
            "stock_rs189": p.get("stock_rs189"),
        })

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i - 1])
        if prev is not None:
            prev_color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            red_run = red_run + 1 if prev_color == "Red" else 0
            red_force = prev_color == "Red" and red_run >= 1

            if red_force:
                for sym in list(pos):
                    fb = px_at(closes, prev, sym, pos[sym]["entry_price"])
                    opx = px_at(opens, d, sym, fb)
                    if opx is not None:
                        exit_symbol(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px_at(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    stop = max(float(p["entry_price"]) * 0.75, float(p["peak"]) * 0.70)
                    if pc <= stop:
                        opx = px_at(opens, d, sym, pc)
                        if opx is not None:
                            exit_symbol(sym, d, opx, "WIDE_STOP")

            prev_b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(prev_b)
            is_bull = prev_color in ("Blue", "Green")
            capacity = base.N_PORT if is_bull and bucket == 2 else SELECTIVE_SLOTS if is_bull and bucket == 1 else 0

            # Final ordinary-stock mechanics under audit: no scheduled rank-prune;
            # rank candidates daily and fill vacancies next session when market mode permits.
            if (not red_force) and capacity > 0 and len(pos) < capacity:
                candidates = ranked_candidates(prev, matrices, ctx, variant, base.N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    fb = px_at(closes, prev, sym, p["entry_price"])
                    opx = px_at(opens, d, sym, fb)
                    if opx is not None:
                        nav_open += float(p["shares"]) * opx
                slot_cash = nav_open / base.N_PORT
                for sym, c in candidates:
                    if len(pos) >= capacity or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px_at(opens, d, sym, px_at(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    cash -= alloc
                    rec = {
                        "variant": variant,
                        "symbol": sym,
                        "signal_date": prev,
                        "entry_date": d,
                        "entry_bucket": bucket,
                        **c,
                    }
                    entries.append(rec)
                    pos[sym] = {
                        "shares": alloc / opx,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak": opx,
                        "entry_bucket": bucket,
                        **c,
                    }

        nav = cash
        for sym, p in pos.items():
            fb = px_at(opens, d, sym, p["entry_price"])
            cp = px_at(closes, d, sym, fb)
            if cp is None:
                cp = float(p["entry_price"])
            p["peak"] = max(float(p["peak"]), cp)
            nav += float(p["shares"]) * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(entries)
    return {
        "equity": eq,
        "metrics": base.slice_metrics(eq),
        "rolling_252": base.rolling_252_stats(eq),
        "trades": tdf,
        "entries": edf,
        "trade_stats": rt.trade_stats(tdf),
    }


def concentration(series: pd.Series) -> dict[str, Any]:
    s = series.dropna().astype(str)
    if s.empty:
        return {"n": 0, "unique": 0, "top_share": None, "hhi": None}
    p = s.value_counts(normalize=True)
    return {
        "n": int(len(s)),
        "unique": int(s.nunique()),
        "top_share": float(p.iloc[0]),
        "hhi": float((p * p).sum()),
        "top5": {str(k): int(v) for k, v in s.value_counts().head(5).items()},
    }


def entry_diagnostics(edf: pd.DataFrame) -> dict[str, Any]:
    if edf.empty:
        return {"n": 0}
    ts = pd.to_numeric(edf["theme_score"], errors="coerce")
    ss = pd.to_numeric(edf["sector_score"], errors="coerce")
    return {
        "n": int(len(edf)),
        "theme_context_coverage": float(ts.notna().mean()),
        "theme_score_mean": float(ts.mean()) if ts.notna().any() else None,
        "theme_score_median": float(ts.median()) if ts.notna().any() else None,
        "activation_entry_share": float(edf["theme_active"].fillna(False).astype(bool).mean()),
        "sector_score_mean": float(ss.mean()) if ss.notna().any() else None,
        "theme_concentration": concentration(edf["best_theme"]),
        "sector_concentration": concentration(edf["sector"]),
    }


def pack(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": v["metrics"],
        "rolling_252": v["rolling_252"],
        "trade_stats": v["trade_stats"],
        "entry_diagnostics": entry_diagnostics(v["entries"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    print("BUILD group context", flush=True)
    ctx = build_group_context(root, matrices)

    sims: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        print(f"SIM {variant}", flush=True)
        sims[variant] = simulate(meta, matrices, ctx, variant)

    baseline = sims["STOCK_RS189"]
    result: dict[str, Any] = {
        "status": "ORDINARY_STOCK_THEME_RANKING_AUDIT",
        "question": "In normal ordinary-stock vacancy fills, does sector/theme context improve stock-only RS189 ranking?",
        "frozen_portfolio_mechanics": "NQSAR+breadth market mode; 12 attack slots / 4 selective slots; no breadth trim; Red next-open exit; no biweekly rank prune; daily candidate refresh; next-session vacancy refill; same wide trailing-stop proxy across variants.",
        "theme_definition": {
            "continuous_score": "mean(theme RS63 cross-sectional percentile, cross-sectional percentile of 20d theme-rank change, constituent breadth above EMA21)",
            "activation_preference": "theme RS63 percentile>=80 AND 20d rank change>=15pt AND breadth above EMA21>=60%",
        },
        "taxonomy_warning": "Current ticker→theme/industry/sector memberships are applied retrospectively. Treat theme-ranking gains as a robust-selection hypothesis unless they survive confirmation period and portfolio block bootstrap; this is not a historical-taxonomy-perfect proof.",
        "coverage": ctx["coverage"],
        "variants": {},
        "comparisons_vs_stock_rs189": {},
    }
    for variant, sim in sims.items():
        result["variants"][variant] = pack(sim)
        sim["equity"].rename("equity").to_csv(out / f"equity_{variant}.csv")
        sim["trades"].to_csv(out / f"trades_{variant}.csv", index=False)
        sim["entries"].to_csv(out / f"entries_{variant}.csv", index=False)
        if variant != "STOCK_RS189":
            result["comparisons_vs_stock_rs189"][variant] = {
                "block20_win_probability_variant_vs_baseline": base.bootstrap_block_win(
                    sim["equity"], baseline["equity"], block=20, reps=10000, seed=92000 + VARIANTS.index(variant)
                ),
                "full_cagr_delta": sim["metrics"]["full"].get("cagr", np.nan) - baseline["metrics"]["full"].get("cagr", np.nan),
                "confirmation_cagr_delta": sim["metrics"]["confirmation"].get("cagr", np.nan) - baseline["metrics"]["confirmation"].get("cagr", np.nan),
                "full_mdd_delta": sim["metrics"]["full"].get("mdd", np.nan) - baseline["metrics"]["full"].get("mdd", np.nan),
                "confirmation_sharpe_delta": sim["metrics"]["confirmation"].get("sharpe", np.nan) - baseline["metrics"]["confirmation"].get("sharpe", np.nan),
            }

    (out / "summary_theme_ranking.json").write_text(
        json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== ORDINARY_STOCK_THEME_RANKING_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ORDINARY_STOCK_THEME_RANKING_JSON ===", flush=True)


if __name__ == "__main__":
    main()
