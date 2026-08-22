from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")

ALIASES = {
    "rs189": ("rs189", "rs_189", "rs189_pct", "rs_189_pct", "rs189_rank", "rs_189_rank"),
    "rs63": ("rs63", "rs_63", "rs63_pct", "rs_63_pct", "rs63_rank", "rs_63_rank"),
    "rs21": ("rs21", "rs_21", "rs21_pct", "rs_21_pct", "rs21_rank", "rs_21_rank"),
    "rel21": ("rel21", "rel_21", "rel20", "rel_20", "qqq_rel21", "qqq_rel_21", "qqq_rel20", "qqq_rel_20"),
    "rel63": ("rel63", "rel_63", "qqq_rel63", "qqq_rel_63"),
    "rel189": ("rel189", "rel_189", "qqq_rel189", "qqq_rel_189"),
    "ret21": ("ret21", "ret_21", "ret20", "ret_20", "return21", "return_21", "return20", "return_20"),
    "ret63": ("ret63", "ret_63", "return63", "return_63"),
    "ret189": ("ret189", "ret_189", "return189", "return_189"),
    "near_high": ("pct_from_52w_high", "from_52w_high", "dist_52w_high", "near_high", "high52_dist"),
    "volume_ratio": ("volume_ratio", "vol_ratio", "rvol", "relative_volume", "volume_multiple"),
    "price": ("price", "close", "last", "last_price"),
    "ema21": ("ema21", "ema_21", "21ema", "ema21_low"),
    "sma50": ("sma50", "sma_50", "50sma", "ma50"),
    "vwap63": ("vwap63", "vwap_63", "63vwap", "rvwap63", "rolling_vwap63"),
    "atr14": ("atr14", "atr_14", "atr"),
    "pivot": ("pivot", "pivot_price", "breakout_level", "darvas_high"),
}

PHASE_LABEL = {
    "EMERGING": "🚀 EMERGING",
    "LEADING": "🔥 LEADING",
    "MATURE": "⚠️ MATURE",
    "LOSING": "↓ LOSING",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def norm_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def is_ticker(value: Any) -> bool:
    return isinstance(value, str) and bool(TICKER_RE.fullmatch(value.strip().upper()))


def read_universe(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if not is_ticker(sym):
                continue
            out[sym] = {
                "name": row.get("名称") or row.get("name") or sym,
                "price": num(row.get("価格") or row.get("price")),
                "day_change": num(row.get("価格変動 %, 1日") or row.get("change_pct")),
                "volume": num(row.get("出来高, 1日") or row.get("volume")),
                "market_cap": num(row.get("時価総額") or row.get("market_cap")),
                "sector": row.get("セクター") or row.get("sector") or "",
                "industry": row.get("業種") or row.get("industry") or "",
                "security_type": row.get("証券種別") or row.get("security_type") or "",
            }
    return out


def read_industry_map(path: Path) -> dict[str, tuple[str, str]]:
    raw = load_json(path, {})
    mapping = raw.get("map", raw) if isinstance(raw, dict) else {}
    out: dict[str, tuple[str, str]] = {}
    if not isinstance(mapping, dict):
        return out
    for sym, pair in mapping.items():
        if not is_ticker(sym):
            continue
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            out[sym.upper()] = (str(pair[0] or ""), str(pair[1] or ""))
        elif isinstance(pair, dict):
            out[sym.upper()] = (
                str(pair.get("sector") or pair.get("Sector") or ""),
                str(pair.get("industry") or pair.get("Industry") or ""),
            )
    return out


def extract_symbol_metrics(snapshot: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Accept metric->{ticker:value}, ticker->{metric:value}, or record-list shapes."""
    metrics: dict[str, dict[str, Any]] = defaultdict(dict)
    diagnostics: dict[str, Any] = {"top_level_keys": [], "metric_maps": [], "ticker_records": []}
    if isinstance(snapshot, dict):
        diagnostics["top_level_keys"] = list(snapshot.keys())[:100]

    seen: set[int] = set()

    def merge(sym: str, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                metrics[sym].setdefault(norm_key(key), value)

    def walk(node: Any, path: str = "root", depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(node, (dict, list)):
            if id(node) in seen:
                return
            seen.add(id(node))
        if isinstance(node, dict):
            lowered = {norm_key(k): k for k in node}
            sym_key = next((lowered[k] for k in ("symbol", "ticker", "sym", "code") if k in lowered), None)
            if sym_key and is_ticker(node.get(sym_key)):
                sym = str(node[sym_key]).upper()
                merge(sym, node)
                diagnostics["ticker_records"].append(path)

            items = list(node.items())
            ticker_items = [(str(k).upper(), v) for k, v in items if is_ticker(k)]
            if ticker_items and len(ticker_items) >= max(3, int(len(items) * 0.45)):
                scalar = sum(1 for _, v in ticker_items if num(v) is not None)
                dicts = sum(1 for _, v in ticker_items if isinstance(v, dict))
                if scalar >= max(3, int(len(ticker_items) * 0.6)):
                    metric_name = norm_key(path.rsplit(".", 1)[-1])
                    diagnostics["metric_maps"].append(path)
                    for sym, value in ticker_items:
                        x = num(value)
                        if x is not None:
                            metrics[sym].setdefault(metric_name, x)
                elif dicts >= max(3, int(len(ticker_items) * 0.4)):
                    for sym, value in ticker_items:
                        if isinstance(value, dict):
                            merge(sym, value)
            for key, value in items:
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}.{norm_key(key)}", depth + 1)
        elif isinstance(node, list):
            for idx, value in enumerate(node[:20000]):
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}[{idx}]", depth + 1)

    walk(snapshot)
    diagnostics["symbols_extracted"] = len(metrics)
    diagnostics["metric_maps"] = diagnostics["metric_maps"][:80]
    diagnostics["ticker_records"] = diagnostics["ticker_records"][:80]
    return dict(metrics), diagnostics


def alias_value(raw: dict[str, Any], alias: str) -> float | None:
    aliases = set(ALIASES[alias])
    for key, value in raw.items():
        nk = norm_key(key)
        if nk in aliases or any(nk.endswith("_" + a) for a in aliases):
            x = num(value)
            if x is not None:
                return x
    return None


def earnings_feature(raw: dict[str, Any]) -> tuple[float, str, int | None]:
    eps = raw.get("eps") if isinstance(raw, dict) else None
    if not isinstance(eps, dict):
        return 0.0, "EPS dataなし", None
    trend = str(eps.get("trend") or "")
    streak_n = num(eps.get("accel_streak"))
    streak = int(streak_n) if streak_n is not None else None
    latest_yoy = num(eps.get("latest_yoy"))
    bonus = 0.0
    if trend == "ACCEL_PERSISTENT" or (streak is not None and streak >= 3):
        bonus = 6.0
    elif trend in {"ACCEL_CONFIRMED", "ACCEL_STRONG"} or (streak is not None and streak >= 2):
        bonus = 4.0
    elif trend == "ACCEL_ONE_Q" or streak == 1:
        bonus = 1.5
    elif trend in {"DECEL", "DECELERATING"}:
        bonus = -2.0
    if latest_yoy is not None and latest_yoy >= 50:
        bonus += 1.5
    label = trend or "EPS dataあり"
    if streak:
        label += f" / {streak}Q加速"
    return min(7.5, bonus), label, streak


def market_permission(state: dict[str, Any]) -> dict[str, Any]:
    mri = num(state.get("mri"))
    gate = str(state.get("gate") or "Unknown")
    gate_l = gate.lower()
    if mri is not None and mri >= 60 and gate_l in {"green", "blue"}:
        status, label = "GO", "主導株を積極的に探す"
    elif mri is not None and mri >= 45 and gate_l not in {"red", "black"}:
        status, label = "SELECTIVE", "上位グループだけ選別"
    else:
        status, label = "STOP", "新規は抑制"
    ftd = None
    hist = state.get("market_cycle_history") or []
    if isinstance(hist, list) and hist:
        last = hist[-1] if isinstance(hist[-1], dict) else {}
        qqq = ((last.get("indices") or {}).get("QQQ") or {}) if isinstance(last, dict) else {}
        if isinstance(qqq, dict):
            ftd = qqq.get("state")
    return {"status": status, "label": label, "mri": mri, "gate": gate, "ftd": ftd, "asof": state.get("date")}


def near_high_score(pct_from_high: float | None) -> float | None:
    if pct_from_high is None:
        return None
    return max(0.0, min(100.0, 100.0 + 5.0 * pct_from_high))


def volume_score(ratio: float | None) -> float | None:
    if ratio is None:
        return None
    return max(0.0, min(100.0, 50.0 + 40.0 * (ratio - 1.0)))


def leader_strength(rs189: float | None, rs63: float | None, rs21: float | None, near_high: float | None, rvol: float | None, eps_bonus: float) -> tuple[float | None, int]:
    parts: list[tuple[float, float]] = []
    if rs189 is not None:
        parts.append((rs189, 0.34))
    if rs63 is not None:
        parts.append((rs63, 0.30))
    if rs21 is not None:
        parts.append((rs21, 0.21))
    nh = near_high_score(near_high)
    if nh is not None:
        parts.append((nh, 0.10))
    vs = volume_score(rvol)
    if vs is not None:
        parts.append((vs, 0.05))
    if not parts:
        return None, 0
    denom = sum(w for _, w in parts)
    base = sum(v * w for v, w in parts) / denom
    return max(0.0, min(100.0, base + eps_bonus)), len(parts)


def entry_status(stock: dict[str, Any]) -> dict[str, Any]:
    price = num(stock.get("price"))
    ema = num(stock.get("ema21"))
    sma50 = num(stock.get("sma50"))
    vwap = num(stock.get("vwap63"))
    atr = num(stock.get("atr14"))
    pivot = num(stock.get("pivot"))
    rvol = num(stock.get("volume_ratio"))
    strength = num(stock.get("strength")) or 0.0

    technical_inputs = sum(x is not None for x in (ema, sma50, vwap, atr, pivot))
    if price is None or technical_inputs == 0:
        return {"status": "NO_DATA", "quality": None, "reason": "Entry判定用の価格/21EMA/63VWAP/Pivotデータ不足"}
    if sma50 is not None and price < sma50 * 0.99:
        return {"status": "AVOID", "quality": 10.0, "reason": "50SMA下。主導株候補でも新規は見送る"}
    if strength < 70:
        return {"status": "AVOID", "quality": 20.0, "reason": "Leader強度70未満"}

    signals: list[tuple[str, float]] = []
    extended: list[str] = []
    if ema is not None and atr is not None and atr > 0:
        dist_atr = (price - ema) / atr
        if -0.25 <= dist_atr <= 0.85:
            signals.append(("21EMA押し目", 92.0))
        elif dist_atr > 2.0:
            extended.append(f"21EMAから+{dist_atr:.1f}ATR")
    if vwap is not None and vwap > 0:
        dist = 100.0 * (price / vwap - 1.0)
        if -1.0 <= dist <= 3.0:
            signals.append(("63VWAP近接", 89.0))
        elif dist > 10.0:
            extended.append(f"63VWAPから+{dist:.1f}%")
    if pivot is not None and pivot > 0:
        dist = 100.0 * (price / pivot - 1.0)
        if 0.0 <= dist <= 4.0:
            q = 94.0 if rvol is not None and rvol >= 1.0 else 88.0
            label = "Pivot突破直後" if rvol is None else f"Pivot突破直後 / RVOL {rvol:.1f}x"
            signals.append((label, q))
        elif dist > 10.0:
            extended.append(f"Pivotから+{dist:.1f}%")

    if extended:
        return {"status": "WAIT", "quality": 40.0, "reason": " / ".join(extended[:2])}
    if signals and strength >= 80:
        best = max(signals, key=lambda x: x[1])
        return {"status": "ENTRY", "quality": best[1], "reason": best[0]}
    if signals:
        best = max(signals, key=lambda x: x[1])
        return {"status": "WATCH", "quality": 70.0, "reason": best[0] + "だがLeader強度80未満"}
    return {"status": "WATCH", "quality": 55.0, "reason": "主導性はあるが押し目/初動条件待ち"}


def aggregate_bucket(name: str, members: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    eligible = [m for m in members if m.get("strength") is not None]
    if len(eligible) < (5 if kind == "sector" else 3):
        return None
    strengths = [float(m["strength"]) for m in eligible]
    accels = [float(m["acceleration"]) for m in eligible if m.get("acceleration") is not None]
    top_strength = median(sorted(strengths, reverse=True)[: min(5, len(strengths))])
    med_strength = median(strengths)
    med_accel = median(accels) if accels else 0.0
    strong = sum(1 for m in eligible if (m.get("strength") or 0) >= 80)
    rs90 = sum(1 for m in eligible if (m.get("rs63") or 0) >= 90)
    density = 100.0 * strong / len(eligible)
    rs90_share = 100.0 * rs90 / len(eligible)
    accel_score = max(0.0, min(100.0, 50.0 + med_accel * 4.0))
    score = 0.42 * top_strength + 0.30 * med_strength + 0.18 * density + 0.10 * accel_score
    score = max(0.0, min(100.0, score))

    if score >= 70 and med_accel >= 5:
        phase = "EMERGING"
    elif score >= 72 and med_accel >= -4:
        phase = "LEADING"
    elif score >= 62 and med_accel < -4:
        phase = "MATURE"
    else:
        phase = "LOSING"
    return {
        "name": name, "kind": kind, "score": round(score, 1), "phase": phase,
        "phase_label": PHASE_LABEL[phase], "median_strength": round(med_strength, 1),
        "acceleration": round(med_accel, 1), "leader_density": round(density, 1),
        "rs90_share": round(rs90_share, 1), "leaders": strong, "members": len(eligible),
    }


def assign_roles(ranked: list[dict[str, Any]]) -> None:
    for idx, stock in enumerate(ranked):
        rs21 = stock.get("rs21")
        rs63 = stock.get("rs63")
        accel = stock.get("acceleration")
        near_high = stock.get("near_high")
        strength = stock.get("strength") or 0
        price = stock.get("price")
        sma50 = stock.get("sma50")
        trend_ok = price is None or sma50 is None or price >= sma50
        if (
            rs21 is not None and rs21 >= 90 and rs63 is not None and rs63 >= 75
            and accel is not None and accel >= 7 and (near_high is None or near_high >= -15) and trend_ok
        ):
            stock["role"] = "PIONEER"
        elif strength >= 84 and (rs63 or 0) >= 80 and trend_ok:
            stock["role"] = "LEADER"
        elif idx <= max(1, int(len(ranked) * 0.35)) and strength >= 75:
            stock["role"] = "LEADER"
        else:
            stock["role"] = "FOLLOWER"
        stock["entry"] = entry_status(stock)


def build_model(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_json(root / "state.json", {})
    sector_snapshot = load_json(root / "sector_snapshot.json", {})
    market_snapshot = load_json(root / "leadership" / "market_snapshot.json", {})
    earnings = load_json(root / "earnings.json", {})
    universe = read_universe(root / "universe.csv")
    industry_map = read_industry_map(root / "industry_map.json")

    live_ok = isinstance(market_snapshot, dict) and isinstance(market_snapshot.get("rs63"), dict) and len(market_snapshot.get("rs63", {})) >= 3
    metric_source = market_snapshot if live_ok else sector_snapshot
    extracted, diagnostics = extract_symbol_metrics(metric_source)
    diagnostics["metric_source"] = "leadership/market_snapshot.json" if live_ok else "sector_snapshot.json fallback"
    diagnostics["market_snapshot_asof"] = market_snapshot.get("asof") if isinstance(market_snapshot, dict) else None

    s2i = sector_snapshot.get("s2i", {}) if isinstance(sector_snapshot, dict) else {}
    if not isinstance(s2i, dict):
        s2i = {}

    symbols = sorted(set(extracted) | set(universe))
    stocks: list[dict[str, Any]] = []
    for sym in symbols:
        u = universe.get(sym, {})
        security_type = str(u.get("security_type") or "").lower()
        if security_type and security_type != "stock":
            continue
        raw = extracted.get(sym, {})
        if live_ok and not raw:
            continue
        sec, ind = industry_map.get(sym, (str(u.get("sector") or ""), str(u.get("industry") or "")))
        detailed = str(s2i.get(sym) or "").strip()
        group = detailed or ind or sec or "Unclassified"
        if "ETF" in group.upper() or "ETN" in group.upper():
            continue

        rs189 = alias_value(raw, "rs189")
        rs63 = alias_value(raw, "rs63")
        rs21 = alias_value(raw, "rs21")
        near_high = alias_value(raw, "near_high")
        rvol = alias_value(raw, "volume_ratio")
        eps_bonus, eps_label, eps_streak = earnings_feature(earnings.get(sym, {}) if isinstance(earnings, dict) else {})
        strength, metric_count = leader_strength(rs189, rs63, rs21, near_high, rvol, eps_bonus)
        acceleration = rs21 - rs63 if rs21 is not None and rs63 is not None else None
        slow_accel = rs63 - rs189 if rs63 is not None and rs189 is not None else None

        stocks.append({
            "symbol": sym, "name": u.get("name") or sym, "sector": sec or "Unclassified",
            "industry": ind, "group": group,
            "strength": round(strength, 1) if strength is not None else None,
            "rs189": round(rs189, 1) if rs189 is not None else None,
            "rs63": round(rs63, 1) if rs63 is not None else None,
            "rs21": round(rs21, 1) if rs21 is not None else None,
            "acceleration": round(acceleration, 1) if acceleration is not None else None,
            "slow_acceleration": round(slow_accel, 1) if slow_accel is not None else None,
            "day_change": round(num(u.get("day_change")), 2) if num(u.get("day_change")) is not None else None,
            "near_high": near_high, "volume_ratio": rvol, "market_cap": u.get("market_cap"),
            "price": alias_value(raw, "price") or num(u.get("price")),
            "ema21": alias_value(raw, "ema21"), "sma50": alias_value(raw, "sma50"),
            "vwap63": alias_value(raw, "vwap63"), "atr14": alias_value(raw, "atr14"),
            "pivot": alias_value(raw, "pivot"),
            "rel21": alias_value(raw, "rel21"), "rel63": alias_value(raw, "rel63"),
            "rel189": alias_value(raw, "rel189"), "ret21": alias_value(raw, "ret21"),
            "ret63": alias_value(raw, "ret63"), "ret189": alias_value(raw, "ret189"),
            "eps_label": eps_label, "eps_streak": eps_streak, "metric_count": metric_count,
        })

    sector_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stocks:
        if stock.get("strength") is None:
            continue
        sector_map[stock["sector"]].append(stock)
        group_map[stock["group"]].append(stock)

    sectors: list[dict[str, Any]] = []
    for name, members in sector_map.items():
        bucket = aggregate_bucket(name, members, "sector")
        if bucket:
            sectors.append(bucket)
    sectors.sort(key=lambda x: (x["phase"] in {"EMERGING", "LEADING"}, x["score"], x["acceleration"]), reverse=True)

    groups: list[dict[str, Any]] = []
    for name, members in group_map.items():
        bucket = aggregate_bucket(name, members, "group")
        if not bucket:
            continue
        ranked = sorted(members, key=lambda s: (s.get("strength") or -1, s.get("acceleration") or -999), reverse=True)
        assign_roles(ranked)
        sector_votes: dict[str, int] = defaultdict(int)
        for stock in members:
            sector_votes[stock["sector"]] += 1
        bucket["sector"] = max(sector_votes, key=sector_votes.get) if sector_votes else "Unclassified"
        bucket["stocks"] = ranked[:15]
        groups.append(bucket)
    groups.sort(key=lambda x: (x["phase"] in {"EMERGING", "LEADING"}, x["score"], x["acceleration"]), reverse=True)

    market = market_permission(state if isinstance(state, dict) else {})
    actionable: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for group in groups[:15]:
        if group["phase"] not in {"EMERGING", "LEADING"}:
            continue
        for stock in group["stocks"][:7]:
            if stock.get("role") not in {"PIONEER", "LEADER"}:
                continue
            item = {
                "symbol": stock["symbol"], "group": group["name"], "sector": group["sector"],
                "strength": stock["strength"], "role": stock["role"], **stock["entry"],
            }
            if stock["entry"]["status"] == "ENTRY" and market["status"] != "STOP":
                actionable.append(item)
            elif stock["entry"]["status"] in {"WAIT", "WATCH"}:
                waiting.append(item)
    actionable.sort(key=lambda x: (x.get("quality") or 0, x.get("strength") or 0), reverse=True)
    waiting.sort(key=lambda x: (x.get("strength") or 0, x.get("quality") or 0), reverse=True)

    coverage = {
        "stocks": len(stocks), "sectors": len(sectors), "groups": len(groups),
        "extracted_symbols": diagnostics.get("symbols_extracted", 0),
        "rs189": sum(1 for s in stocks if s.get("rs189") is not None),
        "rs63": sum(1 for s in stocks if s.get("rs63") is not None),
        "rs21": sum(1 for s in stocks if s.get("rs21") is not None),
        "entry_inputs": sum(1 for s in stocks if any(s.get(k) is not None for k in ("ema21", "vwap63", "pivot"))),
        "metric_source": diagnostics["metric_source"], "market_asof": diagnostics.get("market_snapshot_asof"),
    }
    coverage["confidence"] = "HIGH" if coverage["rs63"] >= 300 else "MEDIUM" if coverage["rs63"] >= 80 else "LOW"

    model = {
        "schema": 2, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": market, "coverage": coverage, "sectors": sectors[:20], "groups": groups[:40],
        "actionable": actionable[:10], "waiting": waiting[:10],
    }
    diagnostics["coverage"] = coverage
    diagnostics["sample_metric_keys"] = sorted({k for sym in list(extracted)[:500] for k in extracted[sym]})[:200]
    return model, diagnostics


def esc(value: Any) -> str:
    return html.escape(str("—" if value is None else value))


def render_cards(rows: list[dict[str, Any]], *, clickable: bool = False) -> str:
    cards = []
    for row in rows:
        attr = f' data-group="{esc(row["name"])}"' if clickable else ""
        cards.append(
            f'<button class="card phase-{esc(row["phase"].lower())}"{attr}>'
            f'<span class="phase">{esc(row["phase_label"])}</span><strong>{esc(row["name"])}</strong>'
            f'<span class="score">{esc(row["score"])}<small>/100</small></span>'
            f'<span class="meta">Density {esc(row["leader_density"])} · Accel {esc(row["acceleration"])}</span></button>'
        )
    return "".join(cards) or '<div class="empty">有効データなし</div>'


def render_chips(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">該当なし。強いだけの株を無理に買わない。</div>'
    return "".join(
        f'<div class="chip"><b>{esc(x["symbol"])}</b><span>{esc(x["role"])} · {esc(x["group"])}</span><em>{esc(x["reason"])}</em></div>'
        for x in rows
    )


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model["market"]
    cov = model["coverage"]
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Leadership Command</title>
<style>
:root{{--bg:#071018;--panel:#0d1722;--panel2:#101d2a;--line:#223142;--text:#eaf1f7;--muted:#8ea1b4;--green:#36d399;--lime:#a5ef73;--yellow:#f4c95d;--red:#ff6b78;--blue:#67b7ff}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#061019,#09131d 45%,#071018);color:var(--text);font:14px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}button{{font:inherit}}.wrap{{max-width:1480px;margin:auto;padding:22px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:18px}}h1{{margin:0;font-size:27px;letter-spacing:.09em}}.sub,.muted{{color:var(--muted)}}.asof{{text-align:right;color:var(--muted);font-size:11px}}.panel{{background:rgba(13,23,34,.95);border:1px solid var(--line);border-radius:16px;padding:15px;box-shadow:0 10px 30px rgba(0,0,0,.18)}}.permission{{display:grid;grid-template-columns:1.1fr 2fr;gap:14px;margin-bottom:14px}}.market{{display:flex;gap:18px;align-items:center}}.badge{{font-size:34px;font-weight:900}}.GO{{color:var(--green)}}.SELECTIVE{{color:var(--yellow)}}.STOP{{color:var(--red)}}.mri{{margin-left:auto;text-align:right}}.mri b{{font-size:30px}}.flow{{display:flex;gap:7px;align-items:center;flex-wrap:wrap}}.flow span{{padding:7px 10px;border:1px solid #2b4054;background:#111f2d;border-radius:999px}}.flow i{{color:#5f7385}}h2{{font-size:12px;text-transform:uppercase;letter-spacing:.11em;color:#b8cad9;margin:0 0 11px}}.section{{margin-bottom:14px}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}}.card{{color:inherit;text-align:left;background:var(--panel2);border:1px solid var(--line);border-top:2px solid #385169;border-radius:12px;padding:12px;min-height:116px;display:grid;grid-template-columns:1fr auto;gap:7px;cursor:pointer}}.card:hover{{border-color:#557089;transform:translateY(-1px)}}.phase-emerging{{border-top-color:var(--lime)}}.phase-leading{{border-top-color:var(--green)}}.phase-mature{{border-top-color:var(--yellow)}}.card .phase{{grid-column:1/3;color:var(--muted);font-size:10px}}.card strong{{grid-column:1/3;font-size:13px}}.score{{font-size:25px;font-weight:850}}.score small{{font-size:9px;color:var(--muted)}}.meta{{text-align:right;color:var(--muted);font-size:10px;align-self:end}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}.chips{{display:flex;gap:8px;flex-wrap:wrap}}.chip{{min-width:160px;padding:9px 10px;border:1px solid #26573f;background:#102419;border-radius:10px}}.chip b{{display:block;color:#a7f4cc;font-size:17px}}.chip span,.chip em{{display:block;font-style:normal;color:var(--muted);font-size:10px;margin-top:2px}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse;min-width:1100px}}th,td{{padding:10px;border-bottom:1px solid #1b2a39;text-align:right;white-space:nowrap}}th{{font-size:10px;letter-spacing:.06em;color:#8ea3b7;background:#0a141e;position:sticky;top:0}}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}tbody tr:hover{{background:#10202e}}.role-PIONEER{{color:var(--lime);font-weight:800}}.role-LEADER{{color:var(--blue);font-weight:800}}.entry-ENTRY{{color:var(--green);font-weight:800}}.entry-WAIT,.entry-WATCH{{color:var(--yellow)}}.entry-AVOID{{color:var(--red)}}.entry-NO_DATA{{color:#6f8496}}.empty{{color:var(--muted);padding:10px}}.footer{{color:#708599;font-size:10px;margin-top:9px}}@media(max-width:900px){{.wrap{{padding:12px}}header{{flex-direction:column;align-items:flex-start}}.asof{{text-align:left}}.permission,.actions{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:520px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main class="wrap"><header><div><h1>LEADERSHIP COMMAND</h1><div class="sub">市場が良い時に、主導セクター → 主導グループ → 先導株 → 今入れるか、だけを見る。</div></div><div class="asof">MARKET {esc(cov.get("market_asof") or market.get("asof"))}<br>RS COVERAGE {esc(cov.get("rs63"))} · CONFIDENCE <b>{esc(cov.get("confidence"))}</b></div></header><section class="permission"><div class="panel market"><div><div class="muted">MARKET PERMISSION</div><div class="badge {esc(market["status"])}">{esc(market["status"])}</div><div>{esc(market["label"])}</div></div><div class="mri"><span class="muted">MRI</span><br><b>{esc(market.get("mri"))}</b><br><span class="muted">{esc(market.get("gate"))} · {esc(market.get("ftd"))}</span></div></div><div class="panel"><h2>Decision Flow</h2><div class="flow"><span>MARKET</span><i>→</i><span>SECTOR</span><i>→</i><span>GROUP</span><i>→</i><span>PIONEER / LEADER</span><i>→</i><span>ENTRY</span></div><div class="footer">RSはQQQ超過の21/63/189日順位。強い株と今買える株を分離する。</div></div></section><section class="panel section"><h2>Sector Leadership</h2><div class="grid">{render_cards(model.get("sectors", [])[:8])}</div></section><section class="panel section"><h2>Group Rotation</h2><div class="grid">{render_cards(model.get("groups", [])[:12], clickable=True)}</div></section><section class="actions"><div class="panel"><h2>🎯 Actionable Now</h2><div class="chips">{render_chips(model.get("actionable", []))}</div></div><div class="panel"><h2>⏳ Strong, but wait</h2><div class="chips">{render_chips(model.get("waiting", [])[:6])}</div></div></section><section class="panel"><h2 id="boardTitle">Leadership Board</h2><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Role</th><th>Leader</th><th>RS189</th><th>RS63</th><th>RS21</th><th>Accel</th><th>52W高値差</th><th>RVOL</th><th>EPS</th><th>Entry</th><th>理由</th></tr></thead><tbody id="board"></tbody></table></div><div class="footer" id="coverage"></div></section></main><script id="payload" type="application/json">{payload}</script><script>const data=JSON.parse(document.getElementById('payload').textContent);const board=document.getElementById('board');function v(x){{return x===null||x===undefined?'—':x}}function render(name){{const g=data.groups.find(x=>x.name===name)||data.groups[0];if(!g)return;document.getElementById('boardTitle').textContent=`Leadership Board — ${{g.name}} · ${{g.phase_label}} · ${{g.score}}/100`;board.innerHTML=g.stocks.map(s=>`<tr><td><b>${{s.symbol}}</b><div class="muted">${{s.name||''}}</div></td><td class="role-${{s.role}}">${{s.role}}</td><td><b>${{v(s.strength)}}</b></td><td>${{v(s.rs189)}}</td><td>${{v(s.rs63)}}</td><td>${{v(s.rs21)}}</td><td>${{v(s.acceleration)}}</td><td>${{v(s.near_high)}}</td><td>${{v(s.volume_ratio)}}</td><td>${{s.eps_label||'—'}}</td><td class="entry-${{s.entry.status}}">${{s.entry.status}}</td><td>${{s.entry.reason}}</td></tr>`).join('')}}document.querySelectorAll('[data-group]').forEach(el=>el.addEventListener('click',()=>render(el.dataset.group)));render(data.groups[0]?.name);const c=data.coverage;document.getElementById('coverage').textContent=`Source: ${{c.metric_source}} · Stocks ${{c.stocks}} · Sectors ${{c.sectors}} · Groups ${{c.groups}} · RS63 ${{c.rs63}} · Entry inputs ${{c.entry_inputs}}`;</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Build isolated Leadership Command dashboard")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    model, diagnostics = build_model(root)
    (output / "leadership.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(render_html(model), encoding="utf-8")
    print(json.dumps({"market": model["market"], "coverage": model["coverage"], "top_sectors": [{k:s[k] for k in ("name","phase","score","acceleration")} for s in model["sectors"][:8]], "top_groups": [{k:g[k] for k in ("name","phase","score","acceleration")} for g in model["groups"][:8]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
