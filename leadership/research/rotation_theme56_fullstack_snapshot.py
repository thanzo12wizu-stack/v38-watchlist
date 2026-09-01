from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import rotation_live_snapshot as live
import validate_pioneer_leader as pl


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def latest_num(series: pd.Series) -> float | None:
    x = pd.to_numeric(series, errors="coerce").dropna()
    return None if x.empty else float(x.iloc[-1])


def normalize_holdings(df: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    required = {"sector_etf", "symbol"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"holdings missing columns: {sorted(required - set(df.columns))}")
    out = df.copy()
    out["sector_etf"] = out["sector_etf"].astype(str).str.upper().str.strip()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out = out[out["sector_etf"].isin(universe)]
    out = out[~out["symbol"].isin({"", "NAN", "-", "--"})]
    return out.drop_duplicates(["sector_etf", "symbol"], keep="first")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Theme56 Price + Internals + official Exact Flow snapshot")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--price-json", type=Path, default=Path("leadership/research/rotation_theme56_live/theme56_price.json"))
    ap.add_argument("--provider-qa", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_provider_qa.csv"))
    ap.add_argument("--holdings", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_current_holdings.csv"))
    ap.add_argument("--holdings-expansion", type=Path, default=Path("leadership/research/rotation_theme56_holdings_expansion/exact_current_holdings_expansion.csv"))
    ap.add_argument("--flows", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_flows.csv"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_fullstack"))
    ap.add_argument("--download-start", default="2025-10-01")
    ap.add_argument("--download-end", default="2026-09-02")
    ap.add_argument("--min-source-coverage", type=float, default=0.80)
    args = ap.parse_args()

    cfg = load_json(args.config)
    themes = cfg.get("themes") if isinstance(cfg.get("themes"), list) else []
    labels = {str(x.get("ticker") or "").upper().strip(): str(x.get("label") or x.get("ticker") or "") for x in themes if isinstance(x, dict)}
    if len(labels) != 56:
        raise RuntimeError("Theme56 config must contain 56 unique tickers")
    universe = set(labels)

    price_obj = load_json(args.price_json)
    price_rows = price_obj.get("rows") if isinstance(price_obj.get("rows"), list) else []
    price = {str(x.get("ticker") or "").upper(): x for x in price_rows if isinstance(x, dict)}

    qa = pd.read_csv(args.provider_qa)
    if "full_stack_adapter" not in qa.columns:
        raise RuntimeError("provider QA missing full_stack_adapter")
    flow_mask = qa["full_stack_adapter"].astype(str).str.lower().isin({"true", "1", "yes"})
    flow_tickers = sorted(set(qa.loc[flow_mask, "ticker"].astype(str).str.upper()) & universe)
    if not flow_tickers:
        raise RuntimeError("no official Exact Flow tickers")

    frames = [normalize_holdings(pd.read_csv(args.holdings), universe)]
    if args.holdings_expansion.exists():
        frames.append(normalize_holdings(pd.read_csv(args.holdings_expansion), universe))
    holdings = pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"], keep="first")
    internal_tickers = [t for t in labels if t in set(holdings["sector_etf"])]
    if not internal_tickers:
        raise RuntimeError("no exact current holdings tickers")

    members = sorted({s for s in holdings["symbol"] if s and " " not in s})
    ohlcv, dl_diag = pl.download_ohlcv(members, args.download_start, args.download_end, 20)
    internal_parts, internal_score, internal_delta20, internal_diag = live.build_internal(
        ohlcv, holdings, internal_tickers, args.min_source_coverage
    )
    diag_by = {str(x.get("ticker")): x for x in internal_diag if isinstance(x, dict)}

    flow = pd.read_csv(
        args.flows,
        usecols=lambda c: c in {"date", "ticker", "provider", "aum", "flow_1d", "flow_5d", "flow_20d", "flow_20d_pct_aum", "source_url"},
    )
    flow["ticker"] = flow["ticker"].astype(str).str.upper()
    flow["date"] = pd.to_datetime(flow["date"], errors="coerce")
    flow = flow[flow["ticker"].isin(flow_tickers)].dropna(subset=["date"]).sort_values(["ticker", "date"])
    flow_latest = {t: g.iloc[-1].to_dict() for t, g in flow.groupby("ticker", observed=True) if not g.empty}

    rows: list[dict[str, Any]] = []
    for ticker in labels:
        p = price.get(ticker, {})
        i_diag = diag_by.get(ticker, {})
        f = flow_latest.get(ticker)
        i_score = latest_num(internal_score[ticker]) if ticker in internal_score.columns else None
        i_delta = latest_num(internal_delta20[ticker]) if ticker in internal_delta20.columns else None
        price_ok = p.get("quality") == "MARKET_PRICE_SERIES"
        internal_ok = i_score is not None
        flow_ok = f is not None and pd.notna(f.get("flow_20d_pct_aum"))
        if price_ok and internal_ok and flow_ok:
            quality = "MEASURED_FULL_STACK_UNVALIDATED"
        elif price_ok and internal_ok:
            quality = "MEASURED_PRICE_INTERNAL_FLOW_MISSING"
        elif price_ok:
            quality = "MEASURED_PRICE_ONLY"
        else:
            quality = "DATA_REQUIRED"
        rec: dict[str, Any] = {
            "ticker": ticker,
            "label": labels[ticker],
            "price_quality": p.get("quality") or "DATA_REQUIRED",
            "price_score_56": p.get("price_score"),
            "rs63_rank_56": p.get("rs63_rank"),
            "rs189_rank_56": p.get("rs189_rank"),
            "ret_1d_pct": p.get("ret_1d_pct"),
            "ret_5d_pct": p.get("ret_5d_pct"),
            "ret_20d_pct": p.get("ret_20d_pct"),
            "holdings_adapter": "PASS" if ticker in internal_tickers else "DATA_REQUIRED",
            "exact_flow_adapter": "PASS" if ticker in flow_tickers else "DATA_REQUIRED",
            "source_members": i_diag.get("source_members"),
            "downloaded_members": i_diag.get("downloaded_members"),
            "source_member_coverage": i_diag.get("source_member_coverage"),
            "internal_score_56": i_score,
            "internal_delta20_56": i_delta,
            "internal_score_available_cross_section": i_score,
            "internal_delta20_available_cross_section": i_delta,
            "flow_asof": None if f is None else str(pd.Timestamp(f["date"]).date()),
            "flow_1d_usd": None if f is None or pd.isna(f.get("flow_1d")) else float(f["flow_1d"]),
            "flow_5d_usd": None if f is None or pd.isna(f.get("flow_5d")) else float(f["flow_5d"]),
            "flow_20d_usd": None if f is None or pd.isna(f.get("flow_20d")) else float(f["flow_20d"]),
            "flow_20d_pct_aum": None if f is None or pd.isna(f.get("flow_20d_pct_aum")) else float(f["flow_20d_pct_aum"]),
            "flow_provider": None if f is None or pd.isna(f.get("provider")) else f.get("provider"),
            "quality": quality,
            "state": "VALIDATION_REQUIRED" if price_ok and internal_ok else ("PRICE_ONLY" if price_ok else "DATA_REQUIRED"),
        }
        for name in live.COMPONENTS:
            frame = internal_parts.get(name)
            rec[name] = latest_num(frame[ticker]) if isinstance(frame, pd.DataFrame) and ticker in frame.columns else None
            rank_frame = internal_parts.get(f"{name}_rank")
            rec[f"{name}_rank_56"] = latest_num(rank_frame[ticker]) if isinstance(rank_frame, pd.DataFrame) and ticker in rank_frame.columns else None
        rows.append(rec)

    out = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output / "theme56_fullstack_snapshot.csv", index=False)
    full = out[out["quality"] == "MEASURED_FULL_STACK_UNVALIDATED"]
    pi = out[out["quality"].isin(["MEASURED_FULL_STACK_UNVALIDATED", "MEASURED_PRICE_INTERNAL_FLOW_MISSING"])]
    price_ready = out[out["price_quality"] == "MARKET_PRICE_SERIES"]
    report = {
        "schema": 2,
        "research_only": True,
        "asof": price_obj.get("asof"),
        "universe_count": 56,
        "price_ready_count": int(len(price_ready)),
        "exact_holdings_count": int(len(internal_tickers)),
        "internal_measured_count": int(len(pi)),
        "exact_flow_count": int(len(flow_tickers)),
        "measured_full_stack_count": int(len(full)),
        "measured_full_stack_tickers": full["ticker"].tolist(),
        "internal_measured_tickers": pi["ticker"].tolist(),
        "price_only_or_missing_tickers": out.loc[~out["quality"].isin(["MEASURED_FULL_STACK_UNVALIDATED", "MEASURED_PRICE_INTERNAL_FLOW_MISSING"]), "ticker"].tolist(),
        "internal_cross_section_note": "Internals are ranked across the current Theme56 ETFs with exact current provider holdings and sufficient member-price coverage.",
        "state_contract": "No legacy 15-ETF trading signal is claimed. Theme56 public states are descriptive observation labels only.",
        "download_diagnostics": dl_diag,
        "internal_diagnostics": internal_diag,
        "rows": rows,
    }
    (args.output / "theme56_fullstack_snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("universe_count", "price_ready_count", "exact_holdings_count", "internal_measured_count", "exact_flow_count", "measured_full_stack_count")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
