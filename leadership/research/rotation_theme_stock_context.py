from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import rotation_live_snapshot as rotation

INDUSTRY_ETFS = ["XBI", "XME", "SOXX", "IGV"]
PHASES = {"EMERGING", "LEADING", "MATURE", "LOSING"}
LEADER_ROLES = {"PIONEER", "LEADER"}


def safe_num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if pd.notna(x) else None


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def build_stock_index(model: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Index only stocks exported in each existing Leadership group's top-15 list."""
    groups = model.get("groups") if isinstance(model.get("groups"), list) else []
    stock_index: dict[str, dict[str, Any]] = {}
    group_rows: list[dict[str, Any]] = []

    for group_rank, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        phase = str(group.get("phase") or "")
        if phase not in PHASES:
            phase = "UNKNOWN"
        stocks = group.get("stocks") if isinstance(group.get("stocks"), list) else []
        group_rows.append({
            "group_rank": group_rank,
            "group": group.get("name"),
            "sector": group.get("sector"),
            "phase": phase,
            "score": safe_num(group.get("score")),
            "pioneer_score": safe_num(group.get("pioneer_score")),
            "breadth_score": safe_num(group.get("breadth_score")),
            "leader_breakouts": group.get("leader_breakouts"),
            "exported_stock_rows": len(stocks),
        })
        for stock_rank, stock in enumerate(stocks, start=1):
            if not isinstance(stock, dict):
                continue
            symbol = str(stock.get("symbol") or "").strip().upper()
            if not symbol or symbol in stock_index:
                continue
            breakout = stock.get("breakout") if isinstance(stock.get("breakout"), dict) else {}
            stock_index[symbol] = {
                "symbol": symbol,
                "name": stock.get("name"),
                "group": group.get("name"),
                "group_sector": group.get("sector"),
                "group_phase": phase,
                "group_rank": group_rank,
                "group_score": safe_num(group.get("score")),
                "group_pioneer_score": safe_num(group.get("pioneer_score")),
                "group_breadth_score": safe_num(group.get("breadth_score")),
                "stock_rank_within_group": stock_rank,
                "role": stock.get("role"),
                "strength": safe_num(stock.get("strength")),
                "rs189": safe_num(stock.get("rs189")),
                "rs63": safe_num(stock.get("rs63")),
                "rs21": safe_num(stock.get("rs21")),
                "acceleration": safe_num(stock.get("acceleration")),
                "slow_acceleration": safe_num(stock.get("slow_acceleration")),
                "breakout_status": breakout.get("status"),
            }
    return stock_index, group_rows


def matrix_lookup(path: Path) -> dict[str, dict[str, Any]]:
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        raise RuntimeError("latest_matrix.csv missing ticker")
    out: dict[str, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            out[ticker] = row
    return out


def compact_matrix(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"quality": "DATA_REQUIRED"}
    keys = [
        "asof", "ticker", "state", "state_evidence", "state_reason",
        "matrix_price_score", "matrix_internal_score", "matrix_internal_delta20",
        "flow_asof", "flow_1d_usd", "flow_5d_usd", "flow_20d_usd", "flow_20d_pct_aum",
        "weekly_rsi14", "rs63_vs_spy", "rs189_vs_spy",
    ]
    return {k: (None if pd.isna(row.get(k)) else row.get(k)) for k in keys}


def main() -> None:
    ap = argparse.ArgumentParser(description="Join current Industry ETF membership to the existing Leadership exported group/stock context")
    ap.add_argument("--leadership", type=Path, required=True)
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    model = load_json(args.leadership)
    stock_index, group_rows = build_stock_index(model)
    matrix = matrix_lookup(args.matrix)

    session = requests.Session()
    holdings, holdings_diag = rotation.fetch_all_holdings(session)
    diag_by_ticker = {str(x.get("ticker")): x for x in holdings_diag if isinstance(x, dict)}

    context_rows: list[dict[str, Any]] = []
    industries: list[dict[str, Any]] = []
    for etf in INDUSTRY_ETFS:
        h = holdings[holdings["sector_etf"] == etf].copy()
        h["symbol"] = h["symbol"].astype(str).str.upper()
        intersected: list[dict[str, Any]] = []
        for holding_rank, hr in enumerate(h.to_dict("records"), start=1):
            symbol = str(hr.get("symbol") or "").upper()
            lead = stock_index.get(symbol)
            if not lead:
                continue
            rec = {
                "etf": etf,
                "holding_rank": holding_rank,
                "holding_weight_pct": safe_num(hr.get("weight_pct")),
                **lead,
            }
            intersected.append(rec)
            context_rows.append(rec)

        # Preserve the existing Leadership order. No new composite score or stock rank is created here.
        intersected.sort(key=lambda x: (int(x["group_rank"]), int(x["stock_rank_within_group"]), int(x["holding_rank"])))
        leaders = [x for x in intersected if str(x.get("role")) in LEADER_ROLES]
        emerging_or_leading = [x for x in leaders if str(x.get("group_phase")) in {"EMERGING", "LEADING"}]
        industries.append({
            "etf": etf,
            "rotation": compact_matrix(matrix.get(etf)),
            "holdings_source": diag_by_ticker.get(etf),
            "membership_rows": int(len(h)),
            "leadership_group_top15_intersections": int(len(intersected)),
            "leadership_group_top15_intersection_pct": 100.0 * len(intersected) / len(h) if len(h) else None,
            "existing_leadership_leaders_in_top15_intersection": leaders[:15],
            "existing_emerging_or_leading_leaders_in_top15_intersection": emerging_or_leading[:15],
            "guardrail": "Context join only. The existing Leadership model exports up to 15 stocks per group, so non-intersection is not missing-data evidence. Ordering preserves existing Leadership group/stock order; no Rotation stock score or V38 entry decision is added.",
        })

    coverage = model.get("coverage") if isinstance(model.get("coverage"), dict) else {}
    report = {
        "schema": 3,
        "research_only": True,
        "leadership_generated_at": model.get("generated_at"),
        "leadership_market": model.get("market"),
        "leadership_coverage": coverage,
        "industry_context": industries,
        "guardrails": [
            "Rotation does not create a new stock ranking. Existing Leadership group and stock ordering are reused.",
            "The join is against each existing Leadership group's exported top-15 stocks, not the full 3,858-stock model; non-intersection is not a data-quality failure.",
            "Industry ETF memberships are current exact provider holdings, not historical PIT holdings.",
            "Industry Rotation states remain descriptive/WATCH context because historical PIT holdings for SOXX/IGV were not validated.",
            "Legacy Leadership entry metadata is deliberately excluded. Formal V38 eligibility, ranking, gates, and exits remain separate.",
        ],
    }
    (args.output / "rotation_theme_stock_context.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(context_rows).to_csv(args.output / "rotation_theme_stock_context.csv", index=False)
    pd.DataFrame(group_rows).to_csv(args.output / "leadership_groups.csv", index=False)

    summary_rows = []
    for item in industries:
        rot = item["rotation"]
        summary_rows.append({
            "etf": item["etf"],
            "rotation_state": rot.get("state"),
            "price_score": rot.get("matrix_price_score"),
            "internal_score": rot.get("matrix_internal_score"),
            "internal_delta20": rot.get("matrix_internal_delta20"),
            "flow_20d_usd": rot.get("flow_20d_usd"),
            "membership_rows": item["membership_rows"],
            "leadership_group_top15_intersections": item["leadership_group_top15_intersections"],
            "emerging_leading_leaders": len(item["existing_emerging_or_leading_leaders_in_top15_intersection"]),
        })
    pd.DataFrame(summary_rows).to_csv(args.output / "industry_context_summary.csv", index=False)

    print(json.dumps({
        "leadership_asof": coverage.get("market_asof"),
        "leadership_confidence": coverage.get("confidence"),
        "industries": summary_rows,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
