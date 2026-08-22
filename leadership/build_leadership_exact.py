from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from leadership import build_leadership as base
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    import build_leadership as base


def read_universe_exact(path: Path) -> dict[str, dict[str, Any]]:
    """Read every unique non-empty symbol from the existing universe.csv.

    Leadership is not allowed to redefine the source universe. Security type,
    price, market cap, liquidity, Yahoo availability and history length are data
    attributes only; none of them may remove a source symbol here.
    """
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if not sym or sym in out:
                continue
            out[sym] = {
                "name": row.get("名称") or row.get("name") or sym,
                "price": base.num(row.get("価格") or row.get("price")),
                "day_change": base.num(row.get("価格変動 %, 1日") or row.get("change_pct")),
                "volume": base.num(row.get("出来高, 1日") or row.get("volume")),
                "market_cap": base.num(row.get("時価総額") or row.get("market_cap")),
                "sector": row.get("セクター") or row.get("sector") or "",
                "industry": row.get("業種") or row.get("industry") or "",
                "security_type": row.get("証券種別") or row.get("security_type") or "",
                "security_subtype": row.get("証券サブタイプ") or row.get("security_subtype") or "",
            }
    return out


def build_model(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = base.load_json(root / "state.json", {})
    sector_snapshot = base.load_json(root / "sector_snapshot.json", {})
    market_snapshot = base.load_json(root / "leadership" / "market_snapshot.json", {})
    earnings = base.load_json(root / "earnings.json", {})
    universe = read_universe_exact(root / "universe.csv")
    industry_map = base.read_industry_map(root / "industry_map.json")

    live_ok = (
        isinstance(market_snapshot, dict)
        and isinstance(market_snapshot.get("rs63"), dict)
        and len(market_snapshot.get("rs63", {})) >= 3
    )
    metric_source = market_snapshot if live_ok else sector_snapshot
    extracted, diagnostics = base.extract_symbol_metrics(metric_source)
    diagnostics["metric_source"] = (
        "leadership/market_snapshot.json" if live_ok else "sector_snapshot.json fallback"
    )
    diagnostics["market_snapshot_asof"] = (
        market_snapshot.get("asof") if isinstance(market_snapshot, dict) else None
    )

    s2i = sector_snapshot.get("s2i", {}) if isinstance(sector_snapshot, dict) else {}
    if not isinstance(s2i, dict):
        s2i = {}

    # Exact source universe, in source order. Never union in a symbol that is not
    # in universe.csv and never remove a symbol because market data is missing.
    symbols = list(universe)
    stocks: list[dict[str, Any]] = []
    for sym in symbols:
        u = universe[sym]
        raw = extracted.get(sym, {})
        sec, ind = industry_map.get(
            sym,
            (str(u.get("sector") or ""), str(u.get("industry") or "")),
        )
        detailed = str(s2i.get(sym) or "").strip()
        group = detailed or ind or sec or "Unclassified"

        rs189 = base.alias_value(raw, "rs189")
        rs63 = base.alias_value(raw, "rs63")
        rs21 = base.alias_value(raw, "rs21")
        near_high = base.alias_value(raw, "near_high")
        rvol = base.alias_value(raw, "volume_ratio")
        eps_bonus, eps_label, eps_streak = base.earnings_feature(
            earnings.get(sym, {}) if isinstance(earnings, dict) else {}
        )
        strength, metric_count = base.leader_strength(
            rs189, rs63, rs21, near_high, rvol, eps_bonus
        )
        acceleration = rs21 - rs63 if rs21 is not None and rs63 is not None else None
        slow_accel = rs63 - rs189 if rs63 is not None and rs189 is not None else None

        stock = {
            "symbol": sym,
            "name": u.get("name") or sym,
            "sector": sec or "Unclassified",
            "industry": ind,
            "group": group,
            "security_type": u.get("security_type"),
            "security_subtype": u.get("security_subtype"),
            "strength": round(strength, 1) if strength is not None else None,
            "rs189": round(rs189, 1) if rs189 is not None else None,
            "rs63": round(rs63, 1) if rs63 is not None else None,
            "rs21": round(rs21, 1) if rs21 is not None else None,
            "acceleration": round(acceleration, 1) if acceleration is not None else None,
            "slow_acceleration": round(slow_accel, 1) if slow_accel is not None else None,
            "day_change": (
                round(base.num(u.get("day_change")), 2)
                if base.num(u.get("day_change")) is not None
                else None
            ),
            "near_high": near_high,
            "volume_ratio": rvol,
            "market_cap": u.get("market_cap"),
            "price": base.alias_value(raw, "price") or base.num(u.get("price")),
            "ema21": base.alias_value(raw, "ema21"),
            "sma50": base.alias_value(raw, "sma50"),
            "vwap63": base.alias_value(raw, "vwap63"),
            "atr14": base.alias_value(raw, "atr14"),
            "pivot": base.alias_value(raw, "pivot"),
            "rel21": base.alias_value(raw, "rel21"),
            "rel63": base.alias_value(raw, "rel63"),
            "rel189": base.alias_value(raw, "rel189"),
            "ret21": base.alias_value(raw, "ret21"),
            "ret63": base.alias_value(raw, "ret63"),
            "ret189": base.alias_value(raw, "ret189"),
            "eps_label": eps_label,
            "eps_streak": eps_streak,
            "metric_count": metric_count,
        }
        stock["role"] = "FOLLOWER" if strength is not None else "NO_DATA"
        stock["entry"] = base.entry_status(stock)
        stocks.append(stock)

    # Rotation/leadership scores use only symbols with sufficient metrics, but
    # this is an analytical eligibility mask, not a universe filter.
    sector_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stocks:
        if stock.get("strength") is None:
            continue
        sector_map[stock["sector"]].append(stock)
        group_map[stock["group"]].append(stock)

    sectors: list[dict[str, Any]] = []
    for name, members in sector_map.items():
        bucket = base.aggregate_bucket(name, members, "sector")
        if bucket:
            sectors.append(bucket)
    sectors.sort(
        key=lambda x: (
            x["phase"] in {"EMERGING", "LEADING"},
            x["score"],
            x["acceleration"],
        ),
        reverse=True,
    )

    groups: list[dict[str, Any]] = []
    for name, members in group_map.items():
        bucket = base.aggregate_bucket(name, members, "group")
        if not bucket:
            continue
        ranked = sorted(
            members,
            key=lambda s: (s.get("strength") or -1, s.get("acceleration") or -999),
            reverse=True,
        )
        base.assign_roles(ranked)
        sector_votes: dict[str, int] = defaultdict(int)
        for stock in members:
            sector_votes[stock["sector"]] += 1
        bucket["sector"] = (
            max(sector_votes, key=sector_votes.get) if sector_votes else "Unclassified"
        )
        bucket["stocks"] = ranked[:15]
        groups.append(bucket)
    groups.sort(
        key=lambda x: (
            x["phase"] in {"EMERGING", "LEADING"},
            x["score"],
            x["acceleration"],
        ),
        reverse=True,
    )

    market = base.market_permission(state if isinstance(state, dict) else {})
    actionable: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for group in groups[:15]:
        if group["phase"] not in {"EMERGING", "LEADING"}:
            continue
        for stock in group["stocks"][:7]:
            if stock.get("role") not in {"PIONEER", "LEADER"}:
                continue
            item = {
                "symbol": stock["symbol"],
                "group": group["name"],
                "sector": group["sector"],
                "strength": stock["strength"],
                "role": stock["role"],
                **stock["entry"],
            }
            if stock["entry"]["status"] == "ENTRY" and market["status"] != "STOP":
                actionable.append(item)
            elif stock["entry"]["status"] in {"WAIT", "WATCH"}:
                waiting.append(item)
    actionable.sort(
        key=lambda x: (x.get("quality") or 0, x.get("strength") or 0), reverse=True
    )
    waiting.sort(
        key=lambda x: (x.get("strength") or 0, x.get("quality") or 0), reverse=True
    )

    source_total = len(universe)
    snapshot_total = (
        int(market_snapshot.get("universe_source_total"))
        if isinstance(market_snapshot, dict)
        and base.num(market_snapshot.get("universe_source_total")) is not None
        else None
    )
    coverage = {
        "stocks": len(stocks),
        "universe_total": source_total,
        "universe_exact": len(stocks) == source_total and (
            snapshot_total is None or snapshot_total == source_total
        ),
        "sectors": len(sectors),
        "groups": len(groups),
        "extracted_symbols": diagnostics.get("symbols_extracted", 0),
        "market_data_symbols": sum(1 for s in stocks if s.get("metric_count", 0) > 0),
        "no_data": sum(1 for s in stocks if s.get("entry", {}).get("status") == "NO_DATA"),
        "rs189": sum(1 for s in stocks if s.get("rs189") is not None),
        "rs63": sum(1 for s in stocks if s.get("rs63") is not None),
        "rs21": sum(1 for s in stocks if s.get("rs21") is not None),
        "entry_inputs": sum(
            1
            for s in stocks
            if any(s.get(k) is not None for k in ("ema21", "vwap63", "pivot"))
        ),
        "metric_source": diagnostics["metric_source"],
        "market_asof": diagnostics.get("market_snapshot_asof"),
    }
    coverage["confidence"] = (
        "HIGH"
        if coverage["rs63"] >= 300
        else "MEDIUM"
        if coverage["rs63"] >= 80
        else "LOW"
    )

    model = {
        "schema": 3,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": market,
        "coverage": coverage,
        "sectors": sectors[:20],
        "groups": groups[:40],
        "actionable": actionable[:10],
        "waiting": waiting[:10],
    }
    diagnostics["coverage"] = coverage
    diagnostics["sample_metric_keys"] = sorted(
        {k for sym in list(extracted)[:500] for k in extracted[sym]}
    )[:200]
    return model, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build isolated Leadership Command with exact source universe"
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    model, diagnostics = build_model(root)
    (output / "leadership.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "index.html").write_text(base.render_html(model), encoding="utf-8")
    print(
        json.dumps(
            {
                "market": model["market"],
                "coverage": model["coverage"],
                "top_sectors": [
                    {k: s[k] for k in ("name", "phase", "score", "acceleration")}
                    for s in model["sectors"][:8]
                ],
                "top_groups": [
                    {k: g[k] for k in ("name", "phase", "score", "acceleration")}
                    for g in model["groups"][:8]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
