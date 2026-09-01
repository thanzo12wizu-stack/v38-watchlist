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


def main() -> None:
    ap = argparse.ArgumentParser(description="Build measured Theme56 Price + Internals + Exact Flow snapshot without assigning legacy states")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--price-json", type=Path, default=Path("leadership/research/rotation_theme56_live/theme56_price.json"))
    ap.add_argument("--provider-qa", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_provider_qa.csv"))
    ap.add_argument("--holdings", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_current_holdings.csv"))
    ap.add_argument("--flows", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_flows.csv"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_fullstack"))
    ap.add_argument("--download-start", default="2025-10-01")
    ap.add_argument("--download-end", default="2026-09-02")
    ap.add_argument("--min-source-coverage", type=float, default=0.80)
    args = ap.parse_args()

    cfg = load_json(args.config)
    themes = cfg.get("themes") if isinstance(cfg.get("themes"), list) else []
    labels = {str(x.get("ticker") or "").upper(): str(x.get("label") or x.get("ticker") or "") for x in themes if isinstance(x, dict)}
    if len(labels) != 56:
        raise RuntimeError("Theme56 config must contain 56 unique tickers")

    price_obj = load_json(args.price_json)
    price_rows = price_obj.get("rows") if isinstance(price_obj.get("rows"), list) else []
    price = {str(x.get("ticker") or "").upper(): x for x in price_rows if isinstance(x, dict)}

    qa = pd.read_csv(args.provider_qa)
    if "full_stack_adapter" not in qa.columns:
        raise RuntimeError("provider QA missing full_stack_adapter")
    full_mask = qa["full_stack_adapter"].astype(str).str.lower().isin({"true", "1", "yes"})
    full_tickers = sorted(qa.loc[full_mask, "ticker"].astype(str).str.upper().unique().tolist())
    if not full_tickers:
        raise RuntimeError("no provider full-stack tickers")

    holdings = pd.read_csv(args.holdings)
    holdings["sector_etf"] = holdings["sector_etf"].astype(str).str.upper()
    holdings["symbol"] = holdings["symbol"].astype(str).str.upper()
    holdings = holdings[holdings["sector_etf"].isin(full_tickers)].copy()
    if holdings.empty:
        raise RuntimeError("exact current holdings input empty")

    members = sorted({s for s in holdings["symbol"].tolist() if s and s not in {"NAN", "-"}})
    ohlcv, dl_diag = pl.download_ohlcv(members, args.download_start, args.download_end, 20)
    internal_parts, internal_score, internal_delta20, internal_diag = live.build_internal(
        ohlcv, holdings, full_tickers, args.min_source_coverage
    )
    diag_by = {str(x.get("ticker")): x for x in internal_diag if isinstance(x, dict)}

    flow = pd.read_csv(
        args.flows,
        usecols=lambda c: c in {"date", "ticker", "provider", "aum", "flow_1d", "flow_5d", "flow_20d", "flow_20d_pct_aum", "source_url"},
    )
    flow["ticker"] = flow["ticker"].astype(str).str.upper()
    flow["date"] = pd.to_datetime(flow["date"], errors="coerce")
    flow = flow[flow["ticker"].isin(full_tickers)].dropna(subset=["date"]).sort_values(["ticker", "date"])
    flow_latest = {t: g.iloc[-1].to_dict() for t, g in flow.groupby("ticker", observed=True) if not g.empty}

    rows: list[dict[str, Any]] = []
    for ticker in labels:
        p = price.get(ticker, {})
        i_diag = diag_by.get(ticker, {})
        f = flow_latest.get(ticker)
        has_provider = ticker in full_tickers
        i_score = latest_num(internal_score[ticker]) if ticker in internal_score.columns else None
        i_delta = latest_num(internal_delta20[ticker]) if ticker in internal_delta20.columns else None
        rec: dict[str, Any] = {
            "ticker": ticker,
            "label": labels[ticker],
            "price_quality": p.get("quality") or "DATA_REQUIRED",
            "price_score_56": p.get("price_score"),
            "rs63_rank_56": p.get("rs63_rank"),
            "rs189_rank_56": p.get("rs189_rank"),
            "ret_20d_pct": p.get("ret_20d_pct"),
            "provider_adapter": "PASS" if has_provider else "DATA_REQUIRED",
            "source_members": i_diag.get("source_members"),
            "downloaded_members": i_diag.get("downloaded_members"),
            "source_member_coverage": i_diag.get("source_member_coverage"),
            "internal_score_available_cross_section": i_score,
            "internal_delta20_available_cross_section": i_delta,
            "flow_asof": None if f is None else str(pd.Timestamp(f["date"]).date()),
            "flow_1d_usd": None if f is None or pd.isna(f.get("flow_1d")) else float(f["flow_1d"]),
            "flow_5d_usd": None if f is None or pd.isna(f.get("flow_5d")) else float(f["flow_5d"]),
            "flow_20d_usd": None if f is None or pd.isna(f.get("flow_20d")) else float(f["flow_20d"]),
            "flow_20d_pct_aum": None if f is None or pd.isna(f.get("flow_20d_pct_aum")) else float(f["flow_20d_pct_aum"]),
            "flow_provider": None if f is None or pd.isna(f.get("provider")) else f.get("provider"),
            "quality": "MEASURED_FULL_STACK_UNVALIDATED" if p.get("quality") == "MARKET_PRICE_SERIES" and i_score is not None and f is not None else "DATA_REQUIRED",
            "state": "VALIDATION_REQUIRED" if p.get("quality") == "MARKET_PRICE_SERIES" and i_score is not None and f is not None else "DATA_REQUIRED",
        }
        for name in live.COMPONENTS:
            frame = internal_parts.get(name)
            rec[name] = latest_num(frame[ticker]) if isinstance(frame, pd.DataFrame) and ticker in frame.columns else None
            rank_frame = internal_parts.get(f"{name}_rank")
            rec[f"{name}_rank_available"] = latest_num(rank_frame[ticker]) if isinstance(rank_frame, pd.DataFrame) and ticker in rank_frame.columns else None
        rows.append(rec)

    out = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output / "theme56_fullstack_snapshot.csv", index=False)
    measured = out[out["quality"] == "MEASURED_FULL_STACK_UNVALIDATED"]
    report = {
        "schema": 1,
        "research_only": True,
        "asof": price_obj.get("asof"),
        "universe_count": 56,
        "provider_full_stack_count": len(full_tickers),
        "measured_full_stack_count": int(len(measured)),
        "measured_full_stack_tickers": measured["ticker"].tolist(),
        "data_required_tickers": out.loc[out["quality"] != "MEASURED_FULL_STACK_UNVALIDATED", "ticker"].tolist(),
        "internal_cross_section_note": "Internal ranks are provisional ranks among currently provider-complete ETFs. Recompute over the final supported Theme56 universe before state validation.",
        "state_contract": "No legacy 15-ETF state is assigned. Every measured row remains VALIDATION_REQUIRED until Theme56 PIT validation is complete.",
        "download_diagnostics": dl_diag,
        "internal_diagnostics": internal_diag,
        "rows": rows,
    }
    (args.output / "theme56_fullstack_snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "universe_count": report["universe_count"],
        "provider_full_stack_count": report["provider_full_stack_count"],
        "measured_full_stack_count": report["measured_full_stack_count"],
        "measured_full_stack_tickers": report["measured_full_stack_tickers"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
