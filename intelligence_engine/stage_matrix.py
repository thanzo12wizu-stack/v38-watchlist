from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Any

STAGE_POLICY_VERSION = "1.0.0"
STAGES = (
    ("1A", "上向き転換", "amber"), ("1B", "押し目回復", "yellow"),
    ("2A", "上昇トレンド", "mint"), ("2B", "ブレイク確認", "green"),
    ("2C", "上昇過熱", "purple"), ("3A", "上昇失速", "blue"),
    ("3B", "失速確認", "sky"), ("4A", "下降トレンド", "pink"),
    ("4B", "下方ブレイク", "red"), ("4C", "下落過熱", "magenta"),
    ("NA", "判定不能", "gray"),
)
STAGE_ORDER = tuple(x[0] for x in STAGES)
META = {key: {"label_ja": label, "tone": tone} for key, label, tone in STAGES}


def f(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def features(stock: dict) -> dict:
    value = stock.get("features")
    return value if isinstance(value, dict) else stock


def classify_stage(x: dict) -> str:
    price, ma10, ma50, ma200 = (f(x.get(k)) for k in ("price", "sma10", "sma50", "sma200"))
    ext = f(x.get("extension_atr"))
    if price is None or ma50 is None:
        return "NA"
    long_bull = price >= ma50 and (ma200 is None or ma50 >= ma200)
    if long_bull and ext is not None and ext >= 7:
        return "2C"
    if long_bull and ma10 is not None and price >= ma10:
        return "2B" if x.get("above_pivot") else "2A"
    if long_bull and ma10 is not None and price < ma10:
        return "3A"
    if ma200 is not None and price >= ma200 and price < ma50:
        return "3B"
    if x.get("near_ema21_low") and price >= ma50 * .95:
        return "1B"
    if ma10 is not None and price >= ma10 and price >= ma50 * .95:
        return "1A"
    if ext is not None and ext <= -4:
        return "4C"
    if x.get("hard_block") or (ma10 is not None and price < ma10 < ma50) or (ma200 is not None and price < ma50 < ma200):
        return "4B"
    return "4A"


def rs_score(x: dict) -> float | None:
    pairs = (("pct_rs_raw_63", .2), ("pct_rs_raw_126", .3), ("pct_rs_raw_189", .5))
    valid = [(f(x.get(k)), w) for k, w in pairs]
    valid = [(v, w) for v, w in valid if v is not None]
    return sum(v * w for v, w in valid) / sum(w for _, w in valid) if valid else None


def group_rows(items: list[dict], key: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        buckets[str(item.get(key) or "Unclassified")].append(item)
    rows = []
    for name, members in buckets.items():
        rs = [f(x.get("rs")) for x in members if f(x.get("rs")) is not None]
        rs_mean = mean(rs) if rs else 0
        s2 = sum(x["stage"] in {"2A", "2B", "2C"} for x in members) / len(members)
        bear = sum(x["stage"] in {"4A", "4B", "4C"} for x in members) / len(members)
        rows.append({key: name, "count": len(members), "rs": rs_mean, "stage2_share": s2, "bearish_share": bear,
                     "score": max(0, min(100, rs_mean * .65 + s2 * 35 - bear * 25))})
    rows.sort(key=lambda x: (-x["score"], x[key]))
    half = max(1, math.ceil(len(rows) / 2))
    for rank, row in enumerate(rows, 1):
        row.update(rank=rank, top_half=rank <= half)
    return rows


def build_stage_matrix(stocks: list[dict], market: dict | None = None, *, candidates: list[dict] | None = None,
                       external: list[dict] | None = None, generated_at: str | None = None) -> dict:
    market = market or {}
    c_map = {str(x.get("ticker", "")).upper(): x for x in candidates or []}
    e_map = {str(x.get("ticker", "")).upper(): x for x in external or []}
    blocked = str(market.get("entry_gate", "")).upper() in {"CLOSED", "RED", "BLOCKED", "NO_NEW_ENTRIES"}
    items = []
    for stock in stocks or []:
        ticker = str(stock.get("ticker") or "").upper()
        if not ticker:
            continue
        x, c, e = features(stock), c_map.get(ticker, {}), e_map.get(ticker, {})
        stage, rs = classify_stage(x), rs_score(x)
        days = e.get("days_to_earnings", c.get("days_to_earnings"))
        item = {"ticker": ticker, "sector": stock.get("sector") or "Unclassified",
                "industry": stock.get("industry") or "Unclassified", "stage": stage,
                "price": f(x.get("price")), "rs": rs, "rs63": f(x.get("pct_rs_raw_63")),
                "rs126": f(x.get("pct_rs_raw_126")), "rs189": f(x.get("pct_rs_raw_189")),
                "extension": f(x.get("extension_atr")), "rr": f(x.get("reward_risk_raw")),
                "volume": f(x.get("volume_ratio_20d")), "adr": f(x.get("adr_pct")),
                "pivot_distance": f(x.get("distance_pivot_pct")), "hard_block": bool(x.get("hard_block")),
                "setup": c.get("setup_ja") or c.get("setup") or x.get("setup"), "days_to_earnings": days}
        items.append(item)
    sectors, industries = group_rows(items, "sector"), group_rows(items, "industry")
    sec = {x["sector"]: x for x in sectors}; ind = {x["industry"]: x for x in industries}
    for item in items:
        group = ind.get(item["industry"], sec.get(item["sector"], {})); g = f(group.get("score")) or 0
        rs, ext, rr = f(item.get("rs")) or 0, f(item.get("extension")), f(item.get("rr"))
        reasons = []
        if blocked: reasons.append("市場ゲート停止")
        if not group.get("top_half"): reasons.append("業界下位50%")
        if rs < 80: reasons.append("RS80未満")
        if ext is None or not 0 <= ext <= 4: reasons.append("ATR Entry帯外")
        if rr is None or rr < 2.5: reasons.append("R/R不足")
        try:
            if item["days_to_earnings"] is not None and int(item["days_to_earnings"]) <= 5: reasons.append("決算5日以内")
        except (TypeError, ValueError):
            pass
        if item["hard_block"]: reasons.append("Hard Block")
        stage = item["stage"]
        if stage in {"4A", "4B", "4C"}: action = "AVOID"
        elif stage == "3B": action = "EXIT"
        elif stage == "3A": action = "REDUCE"
        elif stage == "2C": action = "TRIM"
        elif stage in {"1A", "1B"}: action = "WATCH"
        elif stage in {"2A", "2B"}: action = "BUYABLE" if not reasons else "WAIT"
        else: action = "NA"
        quality = max(0, min(100, rs * .45 + g * .35 + ({"2B": 100, "2A": 90, "1A": 65, "1B": 60}.get(stage, 20)) * .2
                               - (15 if blocked else 0) - (20 if item["hard_block"] else 0)))
        item.update(action=action, reasons=reasons[:4] or ["条件通過"], group_score=g, group_rank=group.get("rank"),
                    group_top_half=bool(group.get("top_half")), quality=quality,
                    grade="A+" if stage in {"2A", "2B"} and rs >= 95 and g >= 75 else
                          "A" if stage in {"2A", "2B"} and rs >= 90 and g >= 60 else
                          "A-" if stage in {"1A", "1B", "2A", "2B"} and rs >= 85 and g >= 50 else "B" if rs >= 70 else "C")
        item["leader_grade"] = item["grade"]
        item["badges"] = (["GROUP50"] if item["group_top_half"] else []) + (["RS90"] if rs >= 90 else []) + \
                          (["VOL"] if (f(item.get("volume")) or 0) >= 1.5 else []) + (["EXT"] if (ext or 0) >= 7 else [])
    items.sort(key=lambda x: (-x["quality"], -(x["rs"] or 0), x["ticker"]))
    columns = []
    for stage in STAGE_ORDER:
        members = [x for x in items if x["stage"] == stage]
        buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for item in members: buckets[(item["sector"], item["industry"])].append(item)
        groups = [{"sector": s, "industry": i, "score": (ind.get(i) or {}).get("score"),
                   "rank": (ind.get(i) or {}).get("rank"), "items": sorted(v, key=lambda x: (-x["quality"], x["ticker"]))}
                  for (s, i), v in buckets.items()]
        groups.sort(key=lambda x: (-(x["score"] or 0), x["industry"]))
        columns.append({"stage": stage, **META[stage], "count": len(members), "groups": groups})
    counts = {stage: sum(x["stage"] == stage for x in items) for stage in STAGE_ORDER}
    bullish = sum(counts[x] for x in ("1A", "1B", "2A", "2B", "2C"))
    return {"schema_version": "1.0", "policy_version": STAGE_POLICY_VERSION, "generated_at": generated_at,
            "scope": "CURATED_CANDIDATE_POOL", "stage_order": list(STAGE_ORDER), "stages": columns,
            "items": items, "sectors": sectors, "industries": industries,
            "summary": {"pool_count": len(items), "stage_counts": counts, "bullish_pct": bullish / len(items) if items else None,
                        "buyable_count": sum(x["action"] == "BUYABLE" for x in items),
                        "risk_action_count": sum(x["action"] in {"TRIM", "REDUCE", "EXIT", "AVOID"} for x in items),
                        "market_gate": market.get("entry_gate"), "market_regime": market.get("regime")},
            "implementation": {"score_is_probability": False, "command_center_modified": False,
                               "notes": ["V38独自の透明なStage分類", "品質値は並べ替え専用で確率ではない"]}}
