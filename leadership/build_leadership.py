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
    "rel20": ("rel20", "rel_20", "qqq_rel20", "qqq_rel_20", "excess20", "excess_20"),
    "rel63": ("rel63", "rel_63", "qqq_rel63", "qqq_rel_63", "excess63", "excess_63"),
    "ret20": ("ret20", "ret_20", "return20", "return_20", "perf20", "perf_20", "chg20", "chg_20"),
    "ret63": ("ret63", "ret_63", "return63", "return_63", "perf63", "perf_63", "chg63", "chg_63"),
    "near_high": ("pct_from_52w_high", "from_52w_high", "dist_52w_high", "near_high", "high52_dist"),
    "volume_ratio": ("volume_ratio", "vol_ratio", "rvol", "relative_volume", "volume_multiple"),
    "price": ("price", "close", "last", "last_price"),
    "ema21": ("ema21", "ema_21", "21ema", "ema21_low"),
    "vwap63": ("vwap63", "vwap_63", "63vwap", "rvwap63", "rolling_vwap63"),
    "atr14": ("atr14", "atr_14", "atr"),
    "pivot": ("pivot", "pivot_price", "breakout_level", "darvas_high"),
}

DISPLAY_PHASE = {
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
            sym = (row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
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


def merge_scalar_dict(target: dict[str, Any], source: dict[str, Any], prefix: str = "") -> None:
    for key, value in source.items():
        nk = norm_key(f"{prefix}_{key}" if prefix else key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            target.setdefault(nk, value)


def extract_symbol_metrics(snapshot: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read existing snapshot shapes without importing the existing dashboard builder.

    Supported shapes are symbol/ticker records, metric -> {TICKER: scalar}
    maps, and TICKER -> {metric: scalar} maps. Unknown shapes are ignored.
    """
    metrics: dict[str, dict[str, Any]] = defaultdict(dict)
    diagnostics: dict[str, Any] = {
        "top_level_keys": [],
        "metric_maps": [],
        "record_lists": [],
        "ticker_records": [],
    }
    if isinstance(snapshot, dict):
        diagnostics["top_level_keys"] = list(snapshot.keys())[:80]

    seen: set[int] = set()

    def walk(node: Any, path: str = "root", depth: int = 0) -> None:
        if depth > 7 or id(node) in seen:
            return
        if isinstance(node, (dict, list)):
            seen.add(id(node))

        if isinstance(node, dict):
            lowered = {norm_key(k): k for k in node.keys()}
            sym_key = next((lowered[k] for k in ("symbol", "ticker", "sym", "code") if k in lowered), None)
            if sym_key is not None and is_ticker(node.get(sym_key)):
                sym = str(node[sym_key]).upper()
                merge_scalar_dict(metrics[sym], node)
                diagnostics["ticker_records"].append(path)

            items = list(node.items())
            ticker_keys = [(str(k).upper(), v) for k, v in items if is_ticker(k)]
            if ticker_keys and len(ticker_keys) >= max(3, int(len(items) * 0.45)):
                scalar_count = sum(1 for _, v in ticker_keys if num(v) is not None)
                dict_count = sum(1 for _, v in ticker_keys if isinstance(v, dict))
                if scalar_count >= max(3, int(len(ticker_keys) * 0.6)):
                    metric_name = norm_key(path.rsplit(".", 1)[-1])
                    diagnostics["metric_maps"].append(path)
                    for sym, value in ticker_keys:
                        if num(value) is not None:
                            metrics[sym].setdefault(metric_name, value)
                elif dict_count >= max(3, int(len(ticker_keys) * 0.4)):
                    diagnostics["ticker_records"].append(path)
                    for sym, value in ticker_keys:
                        if isinstance(value, dict):
                            merge_scalar_dict(metrics[sym], value)

            for key, value in items:
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}.{norm_key(key)}", depth + 1)

        elif isinstance(node, list):
            if node and isinstance(node[0], dict):
                diagnostics["record_lists"].append(path)
            for idx, value in enumerate(node[:20000]):
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}[{idx}]", depth + 1)

    walk(snapshot)
    diagnostics["metric_maps"] = diagnostics["metric_maps"][:80]
    diagnostics["record_lists"] = diagnostics["record_lists"][:80]
    diagnostics["ticker_records"] = diagnostics["ticker_records"][:80]
    diagnostics["symbols_extracted"] = len(metrics)
    return dict(metrics), diagnostics


def alias_value(raw: dict[str, Any], alias: str) -> float | None:
    aliases = set(ALIASES[alias])
    for key, value in raw.items():
        if norm_key(key) in aliases:
            x = num(value)
            if x is not None:
                return x
    for key, value in raw.items():
        nk = norm_key(key)
        if any(nk.endswith("_" + a) or nk == a for a in aliases):
            x = num(value)
            if x is not None:
                return x
    return None


def percentile(values: list[float], value: float | None) -> float | None:
    if value is None or not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return 50.0
    below = sum(v < value for v in ordered)
    equal = sum(v == value for v in ordered)
    return 100.0 * (below + 0.5 * equal) / len(ordered)


def normalized_rs(value: float | None, population: list[float]) -> float | None:
    if value is None:
        return None
    if 0 <= value <= 100:
        return value
    return percentile(population, value)


def earnings_feature(raw: dict[str, Any]) -> tuple[float, str, int | None]:
    eps = raw.get("eps") if isinstance(raw, dict) else None
    if not isinstance(eps, dict):
        return 0.0, "EPS dataなし", None
    trend = str(eps.get("trend") or "")
    streak = int(eps.get("accel_streak") or 0) if num(eps.get("accel_streak")) is not None else None
    latest_yoy = num(eps.get("latest_yoy"))
    bonus = 0.0
    if trend == "ACCEL_PERSISTENT" or (streak is not None and streak >= 3):
        bonus = 8.0
    elif trend in {"ACCEL_CONFIRMED", "ACCEL_STRONG"} or (streak is not None and streak >= 2):
        bonus = 5.0
    elif trend == "ACCEL_ONE_Q" or (streak is not None and streak == 1):
        bonus = 2.0
    elif trend in {"DECEL", "DECELERATING"}:
        bonus = -3.0
    if latest_yoy is not None and latest_yoy >= 50:
        bonus += 2.0
    label = trend or "EPS dataあり"
    if streak:
        label += f" / {streak}Q加速"
    return bonus, label, streak


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
    return {
        "status": status,
        "label": label,
        "mri": mri,
        "gate": gate,
        "ftd": ftd,
        "asof": state.get("date"),
    }


def entry_status(stock: dict[str, Any]) -> dict[str, Any]:
    price = num(stock.get("price"))
    ema = num(stock.get("ema21"))
    vwap = num(stock.get("vwap63"))
    atr = num(stock.get("atr14"))
    pivot = num(stock.get("pivot"))
    strength = num(stock.get("strength")) or 0.0

    signals: list[tuple[str, float]] = []
    reasons: list[str] = []
    extended = False

    if price is not None and atr and atr > 0 and ema is not None:
        dist_atr = (price - ema) / atr
        if -0.3 <= dist_atr <= 1.0:
            signals.append(("21EMA近接", 90.0))
        elif dist_atr > 2.0:
            extended = True
            reasons.append(f"21EMAから+{dist_atr:.1f}ATR")
    if price is not None and vwap and vwap > 0:
        dist = 100.0 * (price / vwap - 1.0)
        if -1.5 <= dist <= 3.0:
            signals.append(("63VWAP近接", 88.0))
        elif dist > 10.0:
            extended = True
            reasons.append(f"63VWAPから+{dist:.1f}%")
    if price is not None and pivot and pivot > 0:
        dist = 100.0 * (price / pivot - 1.0)
        if 0 <= dist <= 5.0:
            signals.append(("Pivot突破直後", 92.0))
        elif dist > 10.0:
            extended = True
            reasons.append(f"Pivotから+{dist:.1f}%")

    if extended:
        return {"status": "WAIT", "quality": 40.0, "reason": " / ".join(reasons[:2]) or "延伸"}
    if signals and strength >= 75:
        best = max(signals, key=lambda x: x[1])
        return {"status": "ENTRY", "quality": best[1], "reason": best[0]}
    if signals:
        best = max(signals, key=lambda x: x[1])
        return {"status": "WATCH", "quality": min(74.0, best[1]), "reason": best[0] + "だがLeader強度不足"}
    return {"status": "NO_DATA", "quality": None, "reason": "Entry判定用の21EMA/63VWAP/Pivotデータ不足"}


def build_model(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_json(root / "state.json", {})
    snapshot = load_json(root / "sector_snapshot.json", {})
    earnings = load_json(root / "earnings.json", {})
    universe = read_universe(root / "universe.csv")
    industry_map = read_industry_map(root / "industry_map.json")
    extracted, diagnostics = extract_symbol_metrics(snapshot)

    s2i = snapshot.get("s2i", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(s2i, dict):
        s2i = {}

    symbols = sorted(set(universe) | set(extracted) | {s.upper() for s in s2i if is_ticker(s)})
    raw_populations: dict[str, list[float]] = {}
    for metric in ("rs189", "rs63", "rs21", "rel20", "rel63", "ret20", "ret63"):
        vals = [v for sym in symbols if (v := alias_value(extracted.get(sym, {}), metric)) is not None]
        raw_populations[metric] = vals

    stocks: list[dict[str, Any]] = []
    for sym in symbols:
        u = universe.get(sym, {})
        sec, ind = industry_map.get(sym, (str(u.get("sector") or ""), str(u.get("industry") or "")))
        detailed = str(s2i.get(sym) or "").strip()
        group = detailed or ind or sec or "Unclassified"
        security_type = str(u.get("security_type") or "").lower()
        if security_type and security_type != "stock":
            continue
        if "ETF" in group.upper() or "ETN" in group.upper():
            continue

        raw = extracted.get(sym, {})
        rs189_raw = alias_value(raw, "rs189")
        rs63_raw = alias_value(raw, "rs63")
        rs21_raw = alias_value(raw, "rs21")
        rs189 = normalized_rs(rs189_raw, raw_populations["rs189"])
        rs63 = normalized_rs(rs63_raw, raw_populations["rs63"])
        rs21 = normalized_rs(rs21_raw, raw_populations["rs21"])
        rel20 = alias_value(raw, "rel20")
        rel63 = alias_value(raw, "rel63")
        ret20 = alias_value(raw, "ret20")
        ret63 = alias_value(raw, "ret63")
        near_high = alias_value(raw, "near_high")
        vol_ratio = alias_value(raw, "volume_ratio")
        price = alias_value(raw, "price") or num(u.get("price"))
        ema21 = alias_value(raw, "ema21")
        vwap63 = alias_value(raw, "vwap63")
        atr14 = alias_value(raw, "atr14")
        pivot = alias_value(raw, "pivot")
        day_change = num(u.get("day_change"))
        eps_bonus, eps_label, eps_streak = earnings_feature(
            earnings.get(sym, {}) if isinstance(earnings, dict) else {}
        )

        strength_parts: list[tuple[float, float]] = []
        if rs189 is not None:
            strength_parts.append((rs189, 0.32))
        if rs63 is not None:
            strength_parts.append((rs63, 0.28))
        if rs21 is not None:
            strength_parts.append((rs21, 0.18))
        if rel63 is not None:
            p = percentile(raw_populations["rel63"], rel63)
            if p is not None:
                strength_parts.append((p, 0.12))
        if rel20 is not None:
            p = percentile(raw_populations["rel20"], rel20)
            if p is not None:
                strength_parts.append((p, 0.10))
        if not strength_parts and day_change is not None:
            day_pop = [num(x.get("day_change")) for x in universe.values()]
            day_pop = [x for x in day_pop if x is not None]
            p = percentile(day_pop, day_change)
            if p is not None:
                strength_parts.append((p, 1.0))

        if strength_parts:
            denom = sum(w for _, w in strength_parts)
            base_strength = sum(v * w for v, w in strength_parts) / denom
            strength = max(0.0, min(100.0, base_strength + eps_bonus))
        else:
            strength = None

        acceleration = None
        if rs21 is not None and rs63 is not None:
            acceleration = rs21 - rs63
        elif rs63 is not None and rs189 is not None:
            acceleration = rs63 - rs189
        elif rel20 is not None and rel63 is not None:
            acceleration = rel20 - rel63

        stocks.append({
            "symbol": sym,
            "name": u.get("name") or sym,
            "sector": sec,
            "industry": ind,
            "group": group,
            "strength": round(strength, 1) if strength is not None else None,
            "rs189": round(rs189, 1) if rs189 is not None else None,
            "rs63": round(rs63, 1) if rs63 is not None else None,
            "rs21": round(rs21, 1) if rs21 is not None else None,
            "acceleration": round(acceleration, 1) if acceleration is not None else None,
            "day_change": round(day_change, 2) if day_change is not None else None,
            "ret20": ret20,
            "ret63": ret63,
            "rel20": rel20,
            "rel63": rel63,
            "near_high": near_high,
            "volume_ratio": vol_ratio,
            "market_cap": u.get("market_cap"),
            "price": price,
            "ema21": ema21,
            "vwap63": vwap63,
            "atr14": atr14,
            "pivot": pivot,
            "eps_label": eps_label,
            "eps_streak": eps_streak,
            "metric_count": len(strength_parts),
        })

    group_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stocks:
        if stock["strength"] is not None:
            group_map[stock["group"]].append(stock)

    groups: list[dict[str, Any]] = []
    for group, members in group_map.items():
        if len(members) < 3:
            continue
        strengths = [float(m["strength"]) for m in members if m["strength"] is not None]
        accels = [float(m["acceleration"]) for m in members if m["acceleration"] is not None]
        rs90 = sum(1 for m in members if (m.get("rs63") or 0) >= 90)
        rs80 = sum(1 for m in members if (m.get("rs63") or m.get("strength") or 0) >= 80)
        strong_ratio = rs80 / len(members)
        median_strength = median(strengths)
        top_strength = median(sorted(strengths, reverse=True)[: max(2, min(5, len(strengths)))])
        accel = median(accels) if accels else 0.0
        leader_density = min(100.0, 100.0 * strong_ratio * 1.25 + 8.0 * rs90)
        score = 0.55 * top_strength + 0.30 * median_strength + 0.15 * leader_density
        if accel > 0:
            score += min(6.0, accel * 0.35)
        score = max(0.0, min(100.0, score))

        if score >= 72 and accel >= 3:
            phase = "EMERGING"
        elif score >= 72:
            phase = "LEADING"
        elif score >= 60 and accel < -3:
            phase = "MATURE"
        else:
            phase = "LOSING"

        ranked = sorted(
            members,
            key=lambda x: (x["strength"] or -1, x["acceleration"] or -999),
            reverse=True,
        )
        for idx, stock in enumerate(ranked):
            accel_s = stock.get("acceleration")
            if idx <= max(0, int(len(ranked) * 0.18)) and accel_s is not None and accel_s >= 3:
                stock["role"] = "PIONEER"
            elif idx <= max(1, int(len(ranked) * 0.35)):
                stock["role"] = "LEADER"
            else:
                stock["role"] = "FOLLOWER"
            stock["entry"] = entry_status(stock)

        groups.append({
            "group": group,
            "score": round(score, 1),
            "phase": phase,
            "phase_label": DISPLAY_PHASE[phase],
            "median_strength": round(median_strength, 1),
            "acceleration": round(accel, 1),
            "leader_density": round(leader_density, 1),
            "leaders": rs80,
            "members": len(members),
            "stocks": ranked[:12],
        })

    groups.sort(
        key=lambda g: (g["phase"] in {"EMERGING", "LEADING"}, g["score"], g["acceleration"]),
        reverse=True,
    )

    actionable: list[dict[str, Any]] = []
    extended: list[dict[str, Any]] = []
    for group in groups[:12]:
        if group["phase"] not in {"EMERGING", "LEADING"}:
            continue
        for stock in group["stocks"][:5]:
            if stock.get("role") not in {"PIONEER", "LEADER"}:
                continue
            item = {
                "symbol": stock["symbol"],
                "group": group["group"],
                "strength": stock["strength"],
                "role": stock["role"],
                **stock["entry"],
            }
            if stock["entry"]["status"] == "ENTRY":
                actionable.append(item)
            elif stock["entry"]["status"] == "WAIT":
                extended.append(item)
    actionable = sorted(
        actionable,
        key=lambda x: (x.get("quality") or 0, x.get("strength") or 0),
        reverse=True,
    )[:8]
    extended = sorted(extended, key=lambda x: x.get("strength") or 0, reverse=True)[:8]

    coverage = {
        "stocks": len(stocks),
        "groups": len(groups),
        "extracted_symbols": diagnostics.get("symbols_extracted", 0),
        "rs189": sum(1 for s in stocks if s.get("rs189") is not None),
        "rs63": sum(1 for s in stocks if s.get("rs63") is not None),
        "rs21": sum(1 for s in stocks if s.get("rs21") is not None),
        "entry_inputs": sum(
            1
            for s in stocks
            if s.get("ema21") is not None or s.get("vwap63") is not None or s.get("pivot") is not None
        ),
    }
    coverage["confidence"] = (
        "HIGH" if coverage["rs63"] >= 300 else "MEDIUM" if coverage["rs63"] >= 80 else "LOW"
    )

    model = {
        "schema": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": market_permission(state if isinstance(state, dict) else {}),
        "coverage": coverage,
        "groups": groups[:30],
        "actionable": actionable,
        "extended": extended,
    }
    diagnostics["coverage"] = coverage
    diagnostics["sample_metric_keys"] = sorted(
        {k for sym in list(extracted)[:500] for k in extracted[sym].keys()}
    )[:200]
    return model, diagnostics


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model["market"]
    top = model.get("groups", [])[:8]
    top_cards = "".join(
        f'<button class="group-card phase-{esc(g["phase"].lower())}" data-group="{esc(g["group"])}">'
        f'<span class="phase">{esc(g["phase_label"])}</span><strong>{esc(g["group"])}</strong>'
        f'<span class="score">{esc(g["score"])}<small>/100</small></span>'
        f'<span class="meta">Density {esc(g["leader_density"])} · Accel {esc(g["acceleration"])}</span></button>'
        for g in top
    ) or '<div class="empty">有効なグループデータがありません。</div>'

    actionable = model.get("actionable", [])
    action_html = "".join(
        f'<div class="ticker-chip"><b>{esc(x["symbol"])}</b><span>{esc(x["group"])}</span><em>{esc(x["reason"])}</em></div>'
        for x in actionable
    ) or '<div class="empty">Entry条件まで揃った主導株は現在なし。強いだけの株を無理に買わない。</div>'

    confidence = model.get("coverage", {}).get("confidence", "LOW")
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leadership Command</title>
<style>
:root{{--bg:#071018;--panel:#0d1722;--panel2:#101d2a;--line:#223142;--text:#eaf1f7;--muted:#8ea1b4;--green:#36d399;--lime:#9fe870;--yellow:#f4c95d;--red:#ff6b78;--blue:#58a6ff}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#061019,#09131d 45%,#071018);color:var(--text);font:14px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:1440px;margin:auto;padding:22px}}header{{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:18px}}h1{{font-size:26px;letter-spacing:.08em;margin:0}}.sub{{color:var(--muted);margin-top:5px}}.asof{{color:var(--muted);text-align:right;font-size:12px}}
.permission{{display:grid;grid-template-columns:1.1fr 2fr;gap:14px;margin-bottom:18px}}.panel{{background:rgba(13,23,34,.94);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,.18)}}.market{{display:flex;align-items:center;gap:16px}}.market-badge{{font-weight:900;font-size:34px;letter-spacing:.05em}}.market-badge.GO{{color:var(--green)}}.market-badge.SELECTIVE{{color:var(--yellow)}}.market-badge.STOP{{color:var(--red)}}.mri{{margin-left:auto;text-align:right}}.mri b{{font-size:30px}}.mri small{{color:var(--muted)}}
.flow{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.flow span{{background:#111f2d;border:1px solid #24384b;border-radius:999px;padding:7px 10px;color:#c7d6e4}}.flow i{{color:#53687b}}h2{{font-size:14px;letter-spacing:.1em;text-transform:uppercase;color:#b8cad9;margin:0 0 12px}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}.group-card{{appearance:none;text-align:left;color:inherit;background:var(--panel2);border:1px solid var(--line);border-radius:13px;padding:13px;cursor:pointer;min-height:126px;display:grid;grid-template-columns:1fr auto;gap:8px}}.group-card:hover{{border-color:#48627a;transform:translateY(-1px)}}.group-card strong{{font-size:14px;grid-column:1/3}}.group-card .phase{{font-size:11px;color:var(--muted);grid-column:1/3}}.group-card .score{{font-size:26px;font-weight:800}}.group-card .score small{{font-size:10px;color:var(--muted)}}.group-card .meta{{font-size:11px;color:var(--muted);text-align:right;align-self:end}}.phase-emerging{{border-top:2px solid var(--lime)}}.phase-leading{{border-top:2px solid var(--green)}}.phase-mature{{border-top:2px solid var(--yellow)}}
.actions{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:18px 0}}.chips{{display:flex;gap:8px;flex-wrap:wrap}}.ticker-chip{{background:#102419;border:1px solid #25573d;border-radius:11px;padding:9px 11px;min-width:145px}}.ticker-chip b{{display:block;font-size:17px;color:#9ff0c7}}.ticker-chip span,.ticker-chip em{{display:block;color:var(--muted);font-size:10px;font-style:normal;margin-top:2px}}
.table-wrap{{overflow:auto;border-radius:12px;border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse;min-width:980px}}th,td{{padding:10px 11px;border-bottom:1px solid #1b2a39;text-align:right;white-space:nowrap}}th{{color:#89a0b5;font-size:10px;letter-spacing:.06em;background:#0a141e;position:sticky;top:0}}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}}tbody tr:hover{{background:#101f2d}}.role-PIONEER{{color:var(--lime);font-weight:800}}.role-LEADER{{color:#75d6ff;font-weight:700}}.entry-ENTRY{{color:var(--green);font-weight:800}}.entry-WAIT{{color:var(--yellow)}}.entry-NO_DATA{{color:#70869a}}.dim{{color:var(--muted)}}.empty{{color:var(--muted);padding:12px}}.footer{{margin-top:12px;color:#6f8396;font-size:11px}}.warn{{color:var(--yellow)}}
@media(max-width:900px){{.wrap{{padding:12px}}header{{align-items:flex-start;flex-direction:column}}.permission,.actions{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.market-badge{{font-size:28px}}}}@media(max-width:520px){{.grid{{grid-template-columns:1fr}}}}
</style></head>
<body><main class="wrap">
<header><div><h1>LEADERSHIP COMMAND</h1><div class="sub">市場 → 主導グループ → 先導株 / 主導株 → 今入れるか、だけを見る。</div></div><div class="asof">AS OF {esc(market.get("asof"))}<br>DATA CONFIDENCE: <b>{esc(confidence)}</b></div></header>
<section class="permission"><div class="panel market"><div><div class="dim">MARKET PERMISSION</div><div class="market-badge {esc(market["status"])}">{esc(market["status"])}</div><div>{esc(market["label"])}</div></div><div class="mri"><small>MRI</small><br><b>{esc(market.get("mri"))}</b><br><small>{esc(market.get("gate"))} · {esc(market.get("ftd"))}</small></div></div><div class="panel"><h2>Decision Flow</h2><div class="flow"><span>MARKET</span><i>→</i><span>ROTATION</span><i>→</i><span>GROUP</span><i>→</i><span>LEADER</span><i>→</i><span>ENTRY</span></div><div class="footer">強い株と、今買える株を分離。Entryデータ不足時は推測せず NO_DATA に落とす。</div></div></section>
<section class="panel"><h2>Leadership Rotation</h2><div class="grid" id="groupGrid">{top_cards}</div></section>
<section class="actions"><div class="panel"><h2>🎯 Actionable Now</h2><div class="chips">{action_html}</div></div><div class="panel"><h2>Rule</h2><div>① 市場がGO/SELECTIVE → ② EMERGING/LEADINGだけ → ③ PIONEER/LEADERだけ → ④ ENTRYだけ。</div><div class="footer warn">Leader Scoreが高くてもEntryがWAITなら買わない。</div></div></section>
<section class="panel"><h2 id="boardTitle">Leadership Board</h2><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Role</th><th>Leader</th><th>RS189</th><th>RS63</th><th>RS21</th><th>Accel</th><th>1D%</th><th>EPS</th><th>Entry</th><th>理由</th></tr></thead><tbody id="board"></tbody></table></div><div class="footer" id="coverage"></div></section>
</main><script id="payload" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('payload').textContent);const board=document.getElementById('board');
function v(x){{return x===null||x===undefined?'—':x}}function render(name){{const g=data.groups.find(x=>x.group===name)||data.groups[0];if(!g)return;document.getElementById('boardTitle').textContent=`Leadership Board — ${{g.group}} · ${{g.phase_label}} · ${{g.score}}/100`;board.innerHTML=g.stocks.map(s=>`<tr><td><b>${{s.symbol}}</b><div class="dim">${{s.name||''}}</div></td><td class="role-${{s.role}}">${{s.role}}</td><td><b>${{v(s.strength)}}</b></td><td>${{v(s.rs189)}}</td><td>${{v(s.rs63)}}</td><td>${{v(s.rs21)}}</td><td>${{v(s.acceleration)}}</td><td>${{v(s.day_change)}}</td><td>${{s.eps_label||'—'}}</td><td class="entry-${{s.entry.status}}">${{s.entry.status}}</td><td>${{s.entry.reason}}</td></tr>`).join('')}}
document.querySelectorAll('[data-group]').forEach(el=>el.addEventListener('click',()=>render(el.dataset.group)));render(data.groups[0]?.group);const c=data.coverage;document.getElementById('coverage').textContent=`Coverage: stocks ${{c.stocks}} / groups ${{c.groups}} / RS63 ${{c.rs63}} / entry inputs ${{c.entry_inputs}} · confidence ${{c.confidence}}`;
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build isolated Leadership Command dashboard from read-only V38 artifacts"
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
    (output / "index.html").write_text(render_html(model), encoding="utf-8")
    print(json.dumps({
        "market": model["market"],
        "coverage": model["coverage"],
        "top_groups": [
            {k: g[k] for k in ("group", "phase", "score", "acceleration")}
            for g in model["groups"][:8]
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
