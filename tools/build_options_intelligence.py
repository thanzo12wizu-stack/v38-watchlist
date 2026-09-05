#!/usr/bin/env python3
"""Build a standalone Options Intelligence snapshot from existing V38 option data.

This module does not fetch market data and does not change Dashboard/V38 ranking logic.
It merges the detailed daily options snapshot with the wide rotating scan, adds a
transparent research-only heuristic classification, and appends a deduplicated signal
history that can be backtested later.
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

POSITIONING = Path(os.environ.get("V38_OPT_JSON", "options_positioning.json"))
DETAIL_HISTORY = Path(os.environ.get("V38_OPT_HISTORY", "options_history.csv"))
SCAN_HISTORY = Path(os.environ.get("V38_OPT_SCAN_HISTORY", "options_scan_history.csv"))
UNIVERSE = Path(os.environ.get("V38_UNIVERSE_CSV", "universe.csv"))
OUT_JSON = Path(os.environ.get("V38_OPT_INTEL_JSON", "options_intelligence.json"))
OUT_HISTORY = Path(os.environ.get("V38_OPT_INTEL_HISTORY", "options_intelligence_history.csv"))
TAPE_JSON = Path(os.environ.get("V38_OPT_TAPE_JSON", "options_tape.json"))

SIGNALS = ("ACCELERATION", "SUPPORTIVE", "BREAKOUT WATCH", "NEUTRAL", "HEADWIND", "DATA LOW")


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _read_csv(path: Path):
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _day(v):
    if not v:
        return ""
    return str(v)[:10]


def _age_days(day: str, today: str):
    try:
        return max(0, (datetime.fromisoformat(today) - datetime.fromisoformat(day)).days)
    except Exception:
        return None


def _latest_two(rows):
    grouped = defaultdict(list)
    for row in rows:
        tk = str(row.get("ticker") or "").strip().upper()
        if tk:
            grouped[tk].append(row)
    out = {}
    for tk, vals in grouped.items():
        vals.sort(key=lambda r: (_day(r.get("date")), str(r.get("expiry") or "")))
        by_date = {}
        for row in vals:
            by_date[_day(row.get("date"))] = row
        ordered = [by_date[k] for k in sorted(by_date)]
        out[tk] = (ordered[-1], ordered[-2] if len(ordered) >= 2 else None)
    return out


def _universe_meta():
    out = {}
    for row in _read_csv(UNIVERSE):
        tk = str(row.get("シンボル") or row.get("ticker") or "").strip().upper()
        if not tk:
            continue
        out[tk] = {
            "name": row.get("名称") or row.get("name") or "",
            "sector": row.get("セクター") or row.get("sector") or "",
            "industry": row.get("業種") or row.get("industry") or "",
        }
    return out


def _hist_obs(row):
    if not row:
        return None
    return {
        "date": _day(row.get("date")),
        "expiry": row.get("expiry"),
        "spot": _f(row.get("spot")),
        "atr14": _f(row.get("atr14")),
        "call_wall": _f(row.get("call_wall")),
        "put_wall": _f(row.get("put_wall")),
        "gamma_flip": _f(row.get("gamma_flip")),
        "net_gex": _f(row.get("net_gex")),
        "regime": str(row.get("regime") or "UNKNOWN"),
        "confidence": str(row.get("confidence") or "").upper(),
        "total_oi": _f(row.get("total_oi")),
        "n_strikes": _f(row.get("n_strikes")),
    }


def _current_obs(ticker, rec, asof):
    if not isinstance(rec, dict):
        return None
    exp_key = rec.get("selected_expiry") or rec.get("nearest")
    exp = (rec.get("expiries") or {}).get(exp_key) if exp_key else None
    spot = _f(rec.get("spot"))
    return {
        "date": _day(rec.get("asof") or asof),
        "expiry": exp_key,
        "spot": spot,
        "atr14": _f(rec.get("atr14")),
        "call_wall": _f((rec.get("call_wall") or {}).get("px")),
        "put_wall": _f((rec.get("put_wall") or {}).get("px")),
        "gamma_flip": _f((rec.get("gamma_flip") or {}).get("px")),
        "net_gex": _f(rec.get("net_gex")),
        "regime": str(rec.get("regime") or "UNKNOWN"),
        "confidence": str(rec.get("confidence") or "").upper(),
        "total_oi": _f((exp or {}).get("total_oi")),
        "n_strikes": _f((exp or {}).get("n_strikes")),
        "call_oi": _f((exp or {}).get("call_oi")),
        "put_oi": _f((exp or {}).get("put_oi")),
        "call_wall_share": _f((exp or {}).get("call_wall_share")),
        "put_wall_share": _f((exp or {}).get("put_wall_share")),
        "call_wall_vs_second": _f((exp or {}).get("call_wall_vs_second")),
        "put_wall_vs_second": _f((exp or {}).get("put_wall_vs_second")),
        "refresh_failed": bool(rec.get("refresh_failed")),
        "stale": bool(rec.get("stale")),
        "tech": rec.get("tech") or {},
        "selected_expiry": exp_key,
        "detail": True,
    }


def _regime_for(spot, flip, atr):
    if spot is None or flip is None:
        return "UNKNOWN"
    if atr and atr > 0 and abs(spot - flip) / atr <= 1.0:
        return "NEAR_FLIP"
    return "POSITIVE_GAMMA" if spot > flip else "NEGATIVE_GAMMA"


def _multi_expiry(rec):
    if not isinstance(rec, dict):
        return None
    spot, atr = _f(rec.get("spot")), _f(rec.get("atr14"))
    regimes = []
    for exp in (rec.get("expiries") or {}).values():
        regimes.append(_regime_for(spot, _f((exp or {}).get("gamma_flip")), atr))
    if not regimes:
        return None
    c = Counter(regimes)
    return {
        "count": len(regimes),
        "positive": c.get("POSITIVE_GAMMA", 0),
        "near": c.get("NEAR_FLIP", 0),
        "negative": c.get("NEGATIVE_GAMMA", 0),
        "unknown": c.get("UNKNOWN", 0),
    }


def _crossed_previous_call(prev, cur):
    if not prev:
        return False
    ps, pcw, cs = prev.get("spot"), prev.get("call_wall"), cur.get("spot")
    if None in (ps, pcw, cs):
        return False
    return ps < pcw and cs > pcw * 1.002


def _dist_atr(level, spot, atr):
    if level is None or spot is None or not atr or atr <= 0:
        return None
    return (level - spot) / atr


def _classify(cur, prev=None, multi=None, age=None):
    spot, atr = cur.get("spot"), cur.get("atr14")
    cw, pw, gf = cur.get("call_wall"), cur.get("put_wall"), cur.get("gamma_flip")
    conf = str(cur.get("confidence") or "").upper()
    reg = cur.get("regime") or _regime_for(spot, gf, atr)
    if cur.get("stale") or spot is None or conf == "LOW" or (age is not None and age > 18):
        return "DATA LOW", 0, ["データ量または鮮度が不足"]

    call_atr = _dist_atr(cw, spot, atr)
    put_atr = _dist_atr(pw, spot, atr)
    prev_break = _crossed_previous_call(prev, cur)
    multi_positive = bool(multi and multi.get("positive", 0) > multi.get("negative", 0))

    score = 50
    reasons = []
    if reg == "POSITIVE_GAMMA":
        score += 18; reasons.append("Gamma Flip上")
    elif reg == "NEGATIVE_GAMMA":
        score -= 28; reasons.append("Gamma Flip下の増幅側")
    elif reg == "NEAR_FLIP":
        score -= 4; reasons.append("Gamma Flip近辺")
    if put_atr is not None and put_atr < 0 and abs(put_atr) <= 2.2:
        score += 10; reasons.append("Put支持候補が近い")
    if call_atr is not None:
        if 0 < call_atr <= 1.2:
            score += 4; reasons.append("Call Wall接近")
        elif call_atr > 1.2:
            score += 6; reasons.append("上側Wallまで余地")
    if _f(cur.get("net_gex")) is not None and cur.get("net_gex") > 0:
        score += 5; reasons.append("Net GEXプラス")
    if conf in ("HIGH", "OK"):
        score += 4
    if multi_positive:
        score += 5; reasons.append("複数満期も上側優勢")
    if prev_break:
        score += 18; reasons.append("前回Call Wallを突破")
    score = max(0, min(100, int(round(score))))

    if prev_break and reg != "NEGATIVE_GAMMA":
        return "ACCELERATION", score, reasons
    if reg == "NEGATIVE_GAMMA":
        return "HEADWIND", score, reasons
    if reg in ("POSITIVE_GAMMA", "NEAR_FLIP") and call_atr is not None and 0 < call_atr <= 1.2:
        return "BREAKOUT WATCH", score, reasons
    if reg == "POSITIVE_GAMMA":
        return "SUPPORTIVE", score, reasons
    return "NEUTRAL", score, reasons


def _plan(cur, signal):
    spot = cur.get("spot")
    cw, pw, gf = cur.get("call_wall"), cur.get("put_wall"), cur.get("gamma_flip")
    if signal == "ACCELERATION":
        entry = "突破済みWallが支持へ変わるか確認。高値追いより初押し優先。"
    elif signal == "BREAKOUT WATCH" and cw is not None:
        entry = f"Call Wall {cw:.2f} を終値突破し、次の足でも維持できれば加速候補。"
    elif signal == "SUPPORTIVE":
        if gf is not None and spot is not None and gf < spot:
            entry = f"Gamma Flip {gf:.2f} 付近への押しで反発確認を優先。"
        elif pw is not None:
            entry = f"Put Wall {pw:.2f} 付近の反発確認を優先。"
        else:
            entry = "上昇追随より押し目反発の確認を優先。"
    elif signal == "HEADWIND":
        entry = f"Gamma Flip {gf:.2f} の奪回待ち。" if gf is not None else "新規追随は見送り。"
    else:
        entry = "Gamma Flipから方向が離れるまで待つ。"

    invalid = "明確な無効化水準なし"
    if gf is not None and spot is not None and gf < spot:
        invalid = f"Gamma Flip {gf:.2f} 終値割れで構造悪化"
        if pw is not None and pw < spot:
            invalid += f"、Put Wall {pw:.2f} 割れで支持シナリオ失効"
    elif pw is not None and spot is not None and pw < spot:
        invalid = f"Put Wall {pw:.2f} 終値割れで支持シナリオ失効"
    elif gf is not None and spot is not None and gf > spot:
        invalid = f"Gamma Flip {gf:.2f} を奪回できない間は上方向シナリオ保留"

    target = f"次のCall Wall {cw:.2f}" if cw is not None else "上側Call Wallなし"
    rr = None
    if None not in (spot, cw, gf) and gf < spot < cw:
        risk = spot - gf
        reward = cw - spot
        if risk > 0:
            rr = reward / risk
    return {"entry": entry, "invalid": invalid, "target": target, "rr_to_call_vs_flip": round(rr, 2) if rr is not None else None}


def _load_tape():
    if not TAPE_JSON.is_file():
        return {}
    try:
        raw = json.loads(TAPE_JSON.read_text(encoding="utf-8"))
        return raw.get("tickers", raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def build():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    today = now.date().isoformat()
    positioning = {}
    asof = ""
    quality = {}
    if POSITIONING.is_file():
        raw = json.loads(POSITIONING.read_text(encoding="utf-8"))
        positioning = raw.get("tickers") or {}
        asof = raw.get("asof") or ""
        quality = raw.get("quality") or {}

    detail_hist = _latest_two(_read_csv(DETAIL_HISTORY))
    scan_hist = _latest_two(_read_csv(SCAN_HISTORY))
    meta = _universe_meta()
    tape = _load_tape()
    tickers = set(meta) | set(detail_hist) | set(scan_hist) | set(positioning)
    records = []

    for tk in sorted(tickers):
        detailed = positioning.get(tk)
        if detailed:
            cur = _current_obs(tk, detailed, asof)
            prev_row = (detail_hist.get(tk) or (None, None))[1]
            prev = _hist_obs(prev_row)
            source = "DETAIL"
        else:
            latest, previous = scan_hist.get(tk) or detail_hist.get(tk) or (None, None)
            cur = _hist_obs(latest)
            prev = _hist_obs(previous)
            source = "SCAN" if tk in scan_hist else "HISTORY"
        if not cur:
            continue
        cur["stale"] = bool(cur.get("stale"))
        age = _age_days(cur.get("date"), today)
        multi = _multi_expiry(detailed)
        signal, score, reasons = _classify(cur, prev, multi, age)
        rec = {
            "ticker": tk,
            "name": (meta.get(tk) or {}).get("name", ""),
            "sector": (meta.get(tk) or {}).get("sector", ""),
            "industry": (meta.get(tk) or {}).get("industry", ""),
            "source": source,
            "age_days": age,
            "signal": signal,
            "score": score,
            "reasons": reasons,
            "current": cur,
            "previous": prev,
            "multi_expiry": multi,
            "plan": _plan(cur, signal),
            "tape": tape.get(tk) if isinstance(tape, dict) else None,
            "trade_direction_available": bool(isinstance(tape, dict) and tape.get(tk)),
        }
        records.append(rec)

    order = {name: i for i, name in enumerate(SIGNALS)}
    records.sort(key=lambda r: (order.get(r["signal"], 99), -r["score"], r["ticker"]))
    counts = Counter(r["signal"] for r in records)
    payload = {
        "schema_version": "1.0",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "positioning_asof": asof,
        "quality": quality,
        "method": "research_heuristic_not_v38_ranking",
        "trade_tape": "optional_options_tape_json" if tape else "unavailable_from_current_provider",
        "summary": {"coverage": len(records), **{s: counts.get(s, 0) for s in SIGNALS}},
        "records": records,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _append_history(records, today)
    return payload


def _append_history(records, today):
    fields = ["date", "ticker", "signal", "score", "spot", "atr14", "call_wall", "put_wall", "gamma_flip", "net_gex", "regime", "confidence", "source"]
    merged = {}
    if OUT_HISTORY.is_file():
        for row in _read_csv(OUT_HISTORY):
            key = (row.get("date", ""), row.get("ticker", ""))
            if all(key):
                merged[key] = row
    for rec in records:
        cur = rec["current"]
        row = {
            "date": today,
            "ticker": rec["ticker"],
            "signal": rec["signal"],
            "score": rec["score"],
            "spot": cur.get("spot"),
            "atr14": cur.get("atr14"),
            "call_wall": cur.get("call_wall"),
            "put_wall": cur.get("put_wall"),
            "gamma_flip": cur.get("gamma_flip"),
            "net_gex": cur.get("net_gex"),
            "regime": cur.get("regime"),
            "confidence": cur.get("confidence"),
            "source": rec["source"],
        }
        merged[(today, rec["ticker"])] = row
    with OUT_HISTORY.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for key in sorted(merged):
            writer.writerow({k: merged[key].get(k, "") for k in fields})


def main():
    payload = build()
    print(json.dumps({"coverage": payload["summary"]["coverage"], "summary": payload["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
