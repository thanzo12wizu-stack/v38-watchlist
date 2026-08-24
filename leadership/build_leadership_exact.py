from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

try:
    from leadership import build_leadership as base
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    import build_leadership as base


PHASE_LABEL = {
    "EMERGING": "🚀 EMERGING",
    "LEADING": "🔥 LEADING",
    "MATURE": "⚠️ MATURE",
    "LOSING": "↓ LOSING",
}


def read_universe_exact(path: Path) -> dict[str, dict[str, Any]]:
    """Keep every unique source symbol. Market-data eligibility is analytical only."""
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


def metric_value(raw: dict[str, Any], name: str) -> float | None:
    target = base.norm_key(name)
    for key, value in raw.items():
        nk = base.norm_key(key)
        if nk == target or nk.endswith("_" + target):
            x = base.num(value)
            if x is not None:
                return x
    return None


def breakout_signal(stock: dict[str, Any]) -> dict[str, Any]:
    price = base.num(stock.get("price"))
    sma50 = base.num(stock.get("sma50"))
    rvol = base.num(stock.get("volume_ratio"))
    rs63 = base.num(stock.get("rs63"))
    rs21 = base.num(stock.get("rs21"))
    accel = base.num(stock.get("acceleration"))
    near_high = base.num(stock.get("near_high"))
    d20 = base.num(stock.get("breakout20_pct"))
    d50 = base.num(stock.get("breakout50_pct"))
    c20 = (base.num(stock.get("breakout20_cross")) or 0.0) >= 0.5
    c50 = (base.num(stock.get("breakout50_cross")) or 0.0) >= 0.5

    if price is None or (d20 is None and d50 is None):
        return {"status": "NO_DATA", "score": None, "reason": "ブレイク判定データ不足"}
    if sma50 is not None and price < sma50 * 0.99:
        return {"status": "NONE", "score": 0.0, "reason": "50SMA下"}

    distances = [x for x in (d20, d50) if x is not None]
    nearest = min(distances, key=lambda x: abs(x)) if distances else None
    quality = 72.0
    if c20:
        quality += 10.0
    if c50:
        quality += 8.0
    if rvol is not None:
        if rvol >= 1.5:
            quality += 6.0
        elif rvol >= 1.2:
            quality += 4.0
        elif rvol >= 1.0:
            quality += 2.0
        elif rvol < 0.75:
            quality -= 8.0
    if rs63 is not None and rs63 >= 90:
        quality += 3.0
    if rs21 is not None and rs21 >= 90:
        quality += 3.0
    if accel is not None and accel >= 5:
        quality += 2.0
    if near_high is not None and near_high >= -15:
        quality += 2.0
    quality = max(0.0, min(100.0, quality))

    if c20 or c50:
        levels = []
        if c50:
            levels.append("50日")
        if c20:
            levels.append("20日")
        vol = f" / RVOL {rvol:.1f}x" if rvol is not None else ""
        return {
            "status": "BREAKOUT_NOW",
            "score": round(quality, 1),
            "reason": f"{'・'.join(levels)}Pivotを本日終値で突破{vol}",
            "distance": round(nearest, 2) if nearest is not None else None,
        }
    if nearest is not None and 0.0 <= nearest <= 4.0:
        return {
            "status": "BREAKOUT_RECENT",
            "score": round(max(78.0, quality - 5.0), 1),
            "reason": f"Pivot突破後 +{nearest:.1f}%圏",
            "distance": round(nearest, 2),
        }
    if nearest is not None and -1.5 <= nearest < 0.0:
        return {
            "status": "BREAKOUT_WATCH",
            "score": round(max(70.0, quality - 8.0), 1),
            "reason": f"Pivotまで {nearest:.1f}% — ブレイク直前監視",
            "distance": round(nearest, 2),
        }
    if nearest is not None and nearest > 8.0:
        return {
            "status": "EXTENDED",
            "score": 35.0,
            "reason": f"Pivotから +{nearest:.1f}% — 追わない",
            "distance": round(nearest, 2),
        }
    return {"status": "NONE", "score": 45.0, "reason": "Pivot初動待ち", "distance": round(nearest, 2) if nearest is not None else None}


def entry_status_v2(stock: dict[str, Any]) -> dict[str, Any]:
    price = base.num(stock.get("price"))
    sma50 = base.num(stock.get("sma50"))
    strength = base.num(stock.get("strength")) or 0.0
    rvol = base.num(stock.get("volume_ratio"))
    bo = stock.get("breakout") if isinstance(stock.get("breakout"), dict) else {}
    bo_status = str(bo.get("status") or "")
    bo_score = base.num(bo.get("score")) or 0.0
    bo_dist = base.num(bo.get("distance"))

    live_inputs = sum(
        base.num(stock.get(key)) is not None
        for key in (
            "ema21", "sma50", "vwap63", "atr14", "pivot", "pivot50",
            "breakout20_pct", "breakout50_pct",
        )
    )
    if int(stock.get("metric_count") or 0) == 0 or live_inputs == 0:
        return {"status": "NO_DATA", "quality": None, "reason": "Entry判定用のライブ市場データ不足"}
    if price is None:
        return {"status": "NO_DATA", "quality": None, "reason": "Entry判定用の価格データ不足"}
    if sma50 is not None and price < sma50 * 0.99:
        return {"status": "AVOID", "quality": 10.0, "reason": "50SMA下。主導株候補でも新規は見送る"}
    if strength < 70:
        return {"status": "AVOID", "quality": 20.0, "reason": "Leader強度70未満"}

    if bo_status == "BREAKOUT_NOW":
        if bo_dist is not None and bo_dist > 5.0:
            return {"status": "WAIT", "quality": 55.0, "reason": str(bo.get("reason")) + " / ギャップ拡大型で追わない"}
        if strength >= 78 and (rvol is None or rvol >= 0.75):
            return {"status": "ENTRY", "quality": max(94.0, bo_score), "reason": str(bo.get("reason"))}
        return {"status": "WATCH", "quality": max(75.0, bo_score), "reason": str(bo.get("reason")) + " / 主導性または出来高確認待ち"}
    if bo_status == "BREAKOUT_RECENT" and strength >= 82:
        return {"status": "ENTRY", "quality": max(88.0, bo_score), "reason": str(bo.get("reason"))}
    if bo_status == "BREAKOUT_WATCH":
        return {"status": "WATCH", "quality": max(78.0, bo_score), "reason": str(bo.get("reason"))}
    if bo_status == "EXTENDED":
        return {"status": "WAIT", "quality": 40.0, "reason": str(bo.get("reason"))}

    fallback = base.entry_status(stock)
    if fallback.get("status") == "ENTRY" and bo_status not in {"BREAKOUT_NOW", "BREAKOUT_RECENT"}:
        fallback = dict(fallback)
        fallback["quality"] = min(89.0, base.num(fallback.get("quality")) or 89.0)
    return fallback


def assign_roles_v2(ranked: list[dict[str, Any]]) -> None:
    for idx, stock in enumerate(ranked):
        stock["breakout"] = breakout_signal(stock)
        rs21 = base.num(stock.get("rs21"))
        rs63 = base.num(stock.get("rs63"))
        accel = base.num(stock.get("acceleration"))
        near_high = base.num(stock.get("near_high"))
        strength = base.num(stock.get("strength")) or 0.0
        price = base.num(stock.get("price"))
        sma50 = base.num(stock.get("sma50"))
        trend_ok = price is None or sma50 is None or price >= sma50
        bo_status = str(stock["breakout"].get("status") or "")
        breakout_context = bo_status in {"BREAKOUT_NOW", "BREAKOUT_RECENT", "BREAKOUT_WATCH"}

        if (
            trend_ok
            and rs21 is not None and rs21 >= 88
            and rs63 is not None and rs63 >= 72
            and accel is not None and accel >= 5
            and (near_high is None or near_high >= -20)
            and (breakout_context or (rs21 >= 93 and accel >= 7))
        ):
            stock["role"] = "PIONEER"
        elif trend_ok and strength >= 82 and (rs63 or 0) >= 78:
            stock["role"] = "LEADER"
        elif idx <= max(1, int(len(ranked) * 0.30)) and strength >= 76 and trend_ok:
            stock["role"] = "LEADER"
        else:
            stock["role"] = "FOLLOWER"
        stock["entry"] = entry_status_v2(stock)


def pct(values: list[bool]) -> float:
    return 100.0 * sum(1 for x in values if x) / len(values) if values else 0.0


def aggregate_group_v2(name: str, members: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [m for m in members if m.get("strength") is not None]
    if len(eligible) < 2:
        return None

    ranked = sorted(
        eligible,
        key=lambda s: (base.num(s.get("strength")) or -1, base.num(s.get("acceleration")) or -999),
        reverse=True,
    )
    assign_roles_v2(ranked)

    strengths = [float(m["strength"]) for m in eligible]
    rs63s = [float(m["rs63"]) for m in eligible if m.get("rs63") is not None]
    accels = [float(m["acceleration"]) for m in eligible if m.get("acceleration") is not None]
    top = ranked[: min(5, len(ranked))]
    top_strength = median([float(m["strength"]) for m in top])
    top_rs63_vals = [float(m["rs63"]) for m in top if m.get("rs63") is not None]
    top_rs21_vals = [float(m["rs21"]) for m in top if m.get("rs21") is not None]
    top_accels = [float(m["acceleration"]) for m in top if m.get("acceleration") is not None]
    top_rs63 = median(top_rs63_vals) if top_rs63_vals else 50.0
    top_rs21 = median(top_rs21_vals) if top_rs21_vals else 50.0
    top_accel = median(top_accels) if top_accels else 0.0
    accel_score = max(0.0, min(100.0, 50.0 + top_accel * 4.0))

    breakout_scores = [
        base.num(m.get("breakout", {}).get("score")) or 0.0
        for m in top
        if isinstance(m.get("breakout"), dict)
        and str(m["breakout"].get("status")) in {"BREAKOUT_NOW", "BREAKOUT_RECENT", "BREAKOUT_WATCH"}
    ]
    breakout_impulse = median(sorted(breakout_scores, reverse=True)[:3]) if breakout_scores else 0.0
    pioneer_score = (
        0.30 * top_strength
        + 0.20 * top_rs63
        + 0.15 * top_rs21
        + 0.15 * accel_score
        + 0.20 * breakout_impulse
    )
    if len(eligible) < 4:
        pioneer_score -= 3.0
    pioneer_score = max(0.0, min(100.0, pioneer_score))

    med_strength = median(strengths)
    med_rs63 = median(rs63s) if rs63s else 50.0
    leader_density = pct([(base.num(m.get("strength")) or 0) >= 80 for m in eligible])
    above50 = pct([
        base.num(m.get("price")) is not None
        and base.num(m.get("sma50")) is not None
        and float(m["price"]) >= float(m["sma50"])
        for m in eligible
        if base.num(m.get("price")) is not None and base.num(m.get("sma50")) is not None
    ])
    positive_accel = pct([(base.num(m.get("acceleration")) or -999) > 0 for m in eligible if m.get("acceleration") is not None])
    breadth_score = (
        0.30 * med_strength
        + 0.25 * med_rs63
        + 0.20 * leader_density
        + 0.15 * above50
        + 0.10 * positive_accel
    )
    breadth_score = max(0.0, min(100.0, breadth_score))

    breakout_now = sum(1 for m in eligible if str((m.get("breakout") or {}).get("status")) == "BREAKOUT_NOW")
    breakout_recent = sum(1 for m in eligible if str((m.get("breakout") or {}).get("status")) == "BREAKOUT_RECENT")
    breakout_watch = sum(1 for m in eligible if str((m.get("breakout") or {}).get("status")) == "BREAKOUT_WATCH")
    pioneers = sum(1 for m in eligible if m.get("role") == "PIONEER")
    leaders = sum(1 for m in eligible if m.get("role") in {"PIONEER", "LEADER"})
    leader_breakouts = sum(
        1 for m in eligible
        if m.get("role") in {"PIONEER", "LEADER"}
        and str((m.get("breakout") or {}).get("status")) in {"BREAKOUT_NOW", "BREAKOUT_RECENT"}
    )
    med_accel = median(accels) if accels else 0.0
    score = max(0.0, min(100.0, 0.60 * pioneer_score + 0.40 * breadth_score))

    emerging_trigger = (
        pioneer_score >= 72
        and (leader_breakouts >= 1 or top_accel >= 5 or top_rs21 >= 90)
        and breadth_score < 72
    )
    if emerging_trigger:
        phase = "EMERGING"
    elif pioneer_score >= 68 and breadth_score >= 62:
        phase = "LEADING"
    elif breadth_score >= 58 and (med_accel < 0 or pioneer_score < 68):
        phase = "MATURE"
    else:
        phase = "LOSING"

    return {
        "name": name,
        "kind": "group",
        "score": round(score, 1),
        "phase": phase,
        "phase_label": PHASE_LABEL[phase],
        "pioneer_score": round(pioneer_score, 1),
        "breadth_score": round(breadth_score, 1),
        "median_strength": round(med_strength, 1),
        "acceleration": round(med_accel, 1),
        "top_acceleration": round(top_accel, 1),
        "leader_density": round(leader_density, 1),
        "above50_share": round(above50, 1),
        "positive_accel_share": round(positive_accel, 1),
        "pioneers": pioneers,
        "leaders": leaders,
        "leader_breakouts": leader_breakouts,
        "breakout_now": breakout_now,
        "breakout_recent": breakout_recent,
        "breakout_watch": breakout_watch,
        "members": len(eligible),
        "stocks": ranked[:15],
    }


def group_sort_key(group: dict[str, Any]) -> tuple[Any, ...]:
    phase_rank = {"EMERGING": 3, "LEADING": 2, "MATURE": 1, "LOSING": 0}
    return (
        phase_rank.get(str(group.get("phase")), 0),
        base.num(group.get("pioneer_score")) or 0,
        int(group.get("leader_breakouts") or 0),
        base.num(group.get("score")) or 0,
        base.num(group.get("breadth_score")) or 0,
    )


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
    diagnostics["metric_source"] = "leadership/market_snapshot.json" if live_ok else "sector_snapshot.json fallback"
    diagnostics["market_snapshot_asof"] = market_snapshot.get("asof") if isinstance(market_snapshot, dict) else None

    s2i = sector_snapshot.get("s2i", {}) if isinstance(sector_snapshot, dict) else {}
    if not isinstance(s2i, dict):
        s2i = {}

    stocks: list[dict[str, Any]] = []
    for sym, u in universe.items():
        raw = extracted.get(sym, {})
        sec, ind = industry_map.get(sym, (str(u.get("sector") or ""), str(u.get("industry") or "")))
        detailed = str(s2i.get(sym) or "").strip()
        group = detailed or ind or sec or "Unclassified"

        rs189 = base.alias_value(raw, "rs189")
        rs63 = base.alias_value(raw, "rs63")
        rs21 = base.alias_value(raw, "rs21")
        near_high = base.alias_value(raw, "near_high")
        rvol = base.alias_value(raw, "volume_ratio")
        eps_bonus, eps_label, eps_streak = base.earnings_feature(earnings.get(sym, {}) if isinstance(earnings, dict) else {})
        strength, metric_count = base.leader_strength(rs189, rs63, rs21, near_high, rvol, eps_bonus)
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
            "day_change": round(base.num(u.get("day_change")), 2) if base.num(u.get("day_change")) is not None else None,
            "near_high": near_high,
            "volume_ratio": rvol,
            "market_cap": u.get("market_cap"),
            "price": base.alias_value(raw, "price") or base.num(u.get("price")),
            "ema21": base.alias_value(raw, "ema21"),
            "sma50": base.alias_value(raw, "sma50"),
            "vwap63": base.alias_value(raw, "vwap63"),
            "atr14": base.alias_value(raw, "atr14"),
            "pivot": base.alias_value(raw, "pivot"),
            "pivot50": metric_value(raw, "pivot50"),
            "breakout20_pct": metric_value(raw, "breakout20_pct"),
            "breakout50_pct": metric_value(raw, "breakout50_pct"),
            "breakout20_cross": metric_value(raw, "breakout20_cross"),
            "breakout50_cross": metric_value(raw, "breakout50_cross"),
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
        stock["breakout"] = breakout_signal(stock)
        stock["entry"] = entry_status_v2(stock)
        stocks.append(stock)

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
    sectors.sort(key=lambda x: (x["phase"] in {"EMERGING", "LEADING"}, x["score"], x["acceleration"]), reverse=True)

    groups: list[dict[str, Any]] = []
    for name, members in group_map.items():
        bucket = aggregate_group_v2(name, members)
        if not bucket:
            continue
        sector_votes: dict[str, int] = defaultdict(int)
        for stock in members:
            sector_votes[stock["sector"]] += 1
        bucket["sector"] = max(sector_votes, key=sector_votes.get) if sector_votes else "Unclassified"
        groups.append(bucket)
    groups.sort(key=group_sort_key, reverse=True)

    market = base.market_permission(state if isinstance(state, dict) else {})
    actionable: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for group in groups:
        if group["phase"] not in {"EMERGING", "LEADING"}:
            continue
        for stock in group["stocks"]:
            if stock.get("role") not in {"PIONEER", "LEADER"}:
                continue
            item = {
                "symbol": stock["symbol"],
                "group": group["name"],
                "sector": group["sector"],
                "group_phase": group["phase"],
                "pioneer_score": group.get("pioneer_score"),
                "breadth_score": group.get("breadth_score"),
                "strength": stock["strength"],
                "role": stock["role"],
                "breakout_status": (stock.get("breakout") or {}).get("status"),
                **stock["entry"],
            }
            if stock["entry"]["status"] == "ENTRY" and market["status"] != "STOP":
                actionable.append(item)
            elif stock["entry"]["status"] in {"WAIT", "WATCH"}:
                waiting.append(item)

    def action_key(x: dict[str, Any]) -> tuple[Any, ...]:
        breakout_rank = {"BREAKOUT_NOW": 3, "BREAKOUT_RECENT": 2, "BREAKOUT_WATCH": 1}
        return (
            breakout_rank.get(str(x.get("breakout_status")), 0),
            base.num(x.get("quality")) or 0,
            base.num(x.get("pioneer_score")) or 0,
            base.num(x.get("strength")) or 0,
        )

    actionable.sort(key=action_key, reverse=True)
    waiting.sort(key=action_key, reverse=True)

    source_total = len(universe)
    snapshot_total = (
        int(market_snapshot.get("universe_source_total"))
        if isinstance(market_snapshot, dict) and base.num(market_snapshot.get("universe_source_total")) is not None
        else None
    )
    coverage = {
        "stocks": len(stocks),
        "universe_total": source_total,
        "universe_exact": len(stocks) == source_total and (snapshot_total is None or snapshot_total == source_total),
        "sectors": len(sectors),
        "groups": len(groups),
        "groups_retained": len(groups),
        "extracted_symbols": diagnostics.get("symbols_extracted", 0),
        "market_data_symbols": sum(1 for s in stocks if s.get("metric_count", 0) > 0),
        "no_data": sum(1 for s in stocks if s.get("entry", {}).get("status") == "NO_DATA"),
        "rs189": sum(1 for s in stocks if s.get("rs189") is not None),
        "rs63": sum(1 for s in stocks if s.get("rs63") is not None),
        "rs21": sum(1 for s in stocks if s.get("rs21") is not None),
        "entry_inputs": sum(1 for s in stocks if any(s.get(k) is not None for k in ("ema21", "vwap63", "pivot"))),
        "breakout_inputs": sum(1 for s in stocks if s.get("breakout20_cross") is not None),
        "breakout_now": sum(1 for s in stocks if str((s.get("breakout") or {}).get("status")) == "BREAKOUT_NOW"),
        "metric_source": diagnostics["metric_source"],
        "market_asof": diagnostics.get("market_snapshot_asof"),
    }
    coverage["confidence"] = "HIGH" if coverage["rs63"] >= 300 else "MEDIUM" if coverage["rs63"] >= 80 else "LOW"

    model = {
        "schema": 4,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": market,
        "coverage": coverage,
        "sectors": sectors[:20],
        "groups": groups,
        "actionable": actionable[:15],
        "waiting": waiting[:15],
    }
    diagnostics["coverage"] = coverage
    diagnostics["sample_metric_keys"] = sorted({k for sym in list(extracted)[:500] for k in extracted[sym]})[:200]
    return model, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Build isolated Leadership Command with exact source universe")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    model, diagnostics = build_model(root)
    (output / "leadership.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(base.render_html(model), encoding="utf-8")
    print(json.dumps({
        "market": model["market"],
        "coverage": model["coverage"],
        "top_sectors": [{k: s[k] for k in ("name", "phase", "score", "acceleration")} for s in model["sectors"][:8]],
        "top_groups": [{k: g[k] for k in ("name", "phase", "score", "pioneer_score", "breadth_score", "leader_breakouts")} for g in model["groups"][:12]],
        "actionable_breakouts": [x for x in model["actionable"] if x.get("breakout_status") in {"BREAKOUT_NOW", "BREAKOUT_RECENT"}][:10],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
