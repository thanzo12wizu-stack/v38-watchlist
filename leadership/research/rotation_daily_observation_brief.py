from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

STATE_BUCKETS = {
    "CURRENT_STRENGTH": "MAINSTREAM_CURRENT_STRENGTH",
    "EARLY_ROTATION_WATCH": "WATCH_ONLY",
    "DISTRIBUTION_WARNING": "DISTRIBUTION_WARNING",
    "REDEMPTION_DIVERGENCE": "HOLD_DIVERGENCE",
    "WEAK_BREAKDOWN": "BREAKDOWN",
    "MIXED_HOLD": "HOLD_MIXED",
    "DATA_REQUIRED": "DATA_REQUIRED",
}
RATE_SENSITIVE = ("XLU", "XLRE")


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def num(value: Any) -> float | None:
    return float(value) if finite(value) else None


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt_num(value: Any, digits: int = 1) -> str:
    x = num(value)
    return "DATA REQUIRED" if x is None else f"{x:.{digits}f}"


def fmt_money(value: Any) -> str:
    x = num(value)
    if x is None:
        return "DATA REQUIRED"
    ax = abs(x)
    if ax >= 1e9:
        return f"{x / 1e9:+.2f}B"
    if ax >= 1e6:
        return f"{x / 1e6:+.0f}M"
    return f"{x:+.0f}"


def state_metric_source(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    if str(row.get("level") or "").upper() == "SECTOR":
        p = num(row.get("validated_price_score"))
        i = num(row.get("validated_internal_score"))
        d = num(row.get("validated_internal_delta20"))
        if p is not None and i is not None:
            return p, i, d
    return num(row.get("matrix_price_score")), num(row.get("matrix_internal_score")), num(row.get("matrix_internal_delta20"))


def input_alignment(rotation: dict[str, Any], v38: dict[str, Any]) -> dict[str, Any]:
    r = str(rotation.get("asof") or "")
    v = str(v38.get("asof") or "")
    ok = bool(r and v and r == v)
    return {
        "status": "OK" if ok else "STALE_INPUT_MISMATCH",
        "rotation_asof": r or None,
        "v38_asof": v or None,
        "same_asof": ok,
    }


def rotation_buckets(matrix: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "mainstream": [], "watch": [], "distribution": [], "divergence": [],
        "breakdown": [], "mixed": [], "data_required": [],
    }
    target = {
        "CURRENT_STRENGTH": "mainstream",
        "EARLY_ROTATION_WATCH": "watch",
        "DISTRIBUTION_WARNING": "distribution",
        "REDEMPTION_DIVERGENCE": "divergence",
        "WEAK_BREAKDOWN": "breakdown",
        "MIXED_HOLD": "mixed",
        "DATA_REQUIRED": "data_required",
    }
    for raw in matrix:
        if not isinstance(raw, dict):
            continue
        state = str(raw.get("state") or "DATA_REQUIRED")
        p, i, d = state_metric_source(raw)
        row = {
            "ticker": raw.get("ticker"),
            "level": raw.get("level"),
            "state": state,
            "bucket": STATE_BUCKETS.get(state, "DATA_REQUIRED"),
            "state_evidence": raw.get("state_evidence"),
            "state_reason": raw.get("state_reason"),
            "price_score": p,
            "internal_score": i,
            "internal_delta20": d,
            "flow_1d_usd": num(raw.get("flow_1d_usd")),
            "flow_5d_usd": num(raw.get("flow_5d_usd")),
            "flow_20d_usd": num(raw.get("flow_20d_usd")),
            "flow_20d_pct_aum": num(raw.get("flow_20d_pct_aum")),
            "weekly_rsi14": num(raw.get("weekly_rsi14")),
        }
        out[target.get(state, "data_required")].append(row)
    for rows in out.values():
        rows.sort(key=lambda x: str(x.get("ticker") or ""))
    return out


def flow_observations(matrix: list[dict[str, Any]], n: int = 4) -> dict[str, list[dict[str, Any]]]:
    usable = [r for r in matrix if isinstance(r, dict) and finite(r.get("flow_20d_usd"))]
    leaders = sorted(usable, key=lambda r: float(r["flow_20d_usd"]), reverse=True)[:n]
    laggards = sorted(usable, key=lambda r: float(r["flow_20d_usd"]))[:n]

    def compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"ticker": r.get("ticker"), "flow_20d_usd": num(r.get("flow_20d_usd")), "state": r.get("state")} for r in rows]

    return {"leaders": compact(leaders), "laggards": compact(laggards)}


def macro_facts_and_hypotheses(rotation: dict[str, Any], matrix: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    macro = rotation.get("macro_why") if isinstance(rotation.get("macro_why"), dict) else {}
    fred = macro.get("fred") if isinstance(macro.get("fred"), dict) else {}
    facts: list[str] = []
    hypotheses: list[str] = []
    missing: list[str] = []
    labels = {
        "DGS10": "米10年金利",
        "DFII10": "米10年実質金利",
        "DTWEXBGS": "FRB Broad Dollar Index",
        "BAMLC0A0CM": "米投資適格社債スプレッド",
        "BAMLH0A0HYM2": "米ハイイールド社債スプレッド",
    }
    for key, label in labels.items():
        row = fred.get(key) if isinstance(fred.get(key), dict) else {}
        value, change = num(row.get("value")), num(row.get("change_20obs"))
        if value is None:
            missing.append(label)
            continue
        text = f"{label} {value:.2f}"
        if change is not None:
            text += f"（20観測変化 {change:+.2f}）"
        facts.append(text)

    vix = macro.get("vix") if isinstance(macro.get("vix"), dict) else {}
    if finite(vix.get("value")):
        facts.append(f"VIX {float(vix['value']):.2f}")
    else:
        missing.append("VIX")

    fg = macro.get("fear_greed") if isinstance(macro.get("fear_greed"), dict) else {}
    headline = fg.get("headline") if isinstance(fg.get("headline"), dict) else None
    if headline and finite(headline.get("score")):
        rating = str(headline.get("rating") or "").strip()
        facts.append(f"Fear & Greed {float(headline['score']):.0f}" + (f" / {rating}" if rating else ""))
    elif fg.get("quality") == "DATA_REQUIRED":
        missing.append("Fear & Greed components")
    if fg.get("split"):
        fears = ", ".join(map(str, fg.get("fear_components") or [])) or "none"
        greeds = ", ".join(map(str, fg.get("greed_components") or [])) or "none"
        hypotheses.append(f"Fear & Greed内部は分裂（Fear={fears} / Greed={greeds}）。Headline単独では市場内部を代表しない。")

    dxy = macro.get("dxy") if isinstance(macro.get("dxy"), dict) else {}
    if dxy.get("quality") == "DATA_REQUIRED":
        missing.append("DXY（FRB Broad DollarをDXYへ代用しない）")

    dgs10 = fred.get("DGS10") if isinstance(fred.get("DGS10"), dict) else {}
    rate_change = num(dgs10.get("change_20obs"))
    by_ticker = {str(r.get("ticker")): r for r in matrix if isinstance(r, dict)}
    weak_rate_sensitive = []
    for ticker in RATE_SENSITIVE:
        row = by_ticker.get(ticker, {})
        _p, _i, delta = state_metric_source(row) if row else (None, None, None)
        if row and (str(row.get("state")) in {"WEAK_BREAKDOWN", "DISTRIBUTION_WARNING"} or (delta is not None and delta < 0)):
            weak_rate_sensitive.append(ticker)
    if rate_change is not None and rate_change > 0 and weak_rate_sensitive:
        hypotheses.append(
            f"米10年金利の20観測上昇と {'/'.join(weak_rate_sensitive)} の内部悪化は方向として整合する。因果推定ではなくWHY候補。"
        )

    return facts, hypotheses, sorted(set(missing))


def history_events(path: Path | None, asof: str, tickers: set[str]) -> list[dict[str, Any]]:
    if path is None or not path.is_file() or not path.stat().st_size:
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    required = {"asof", "ticker", "state"}
    if not required.issubset(df.columns):
        return []
    df["asof"] = pd.to_datetime(df["asof"], errors="coerce")
    df = df.dropna(subset=["asof"]).sort_values(["ticker", "asof"])
    end = pd.Timestamp(asof)
    events: list[dict[str, Any]] = []
    for ticker, g in df[df["ticker"].astype(str).isin(tickers)].groupby("ticker", observed=True):
        g = g[g.asof <= end].copy()
        if len(g) < 2:
            continue
        states = g["state"].astype(str)
        changed = states.ne(states.shift(1))
        idxs = list(g.index[changed])
        if len(idxs) <= 1:
            continue
        row = g.loc[idxs[-1]]
        prev_pos = g.index.get_loc(idxs[-1]) - 1
        if prev_pos < 0:
            continue
        previous = g.iloc[prev_pos]
        events.append({
            "ticker": str(ticker),
            "date": str(pd.Timestamp(row["asof"]).date()),
            "type": "STATE_CHANGE",
            "from": str(previous.get("state")),
            "to": str(row.get("state")),
        })
    events.sort(key=lambda x: (x["date"], x["ticker"]), reverse=True)
    return events


def load_crosscheck_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "symbol" not in df.columns or "etf" not in df.columns:
        raise RuntimeError("V38 crosscheck CSV missing symbol/etf")
    return df


def formal_context(df: pd.DataFrame, limit_per_etf: int = 5) -> list[dict[str, Any]]:
    if "eligible" not in df.columns:
        return []
    z = df[df["eligible"].map(truthy)].copy()
    if z.empty:
        return []
    z["_attack_rank"] = pd.to_numeric(z.get("attack_rank"), errors="coerce")
    z["_selective_rank"] = pd.to_numeric(z.get("selective_rank"), errors="coerce")
    z["_rank"] = z["_attack_rank"].fillna(z["_selective_rank"]).fillna(1e9)
    out = []
    for etf, g in z.sort_values(["etf", "_rank", "symbol"]).groupby("etf", observed=True):
        stocks = []
        for r in g.head(limit_per_etf).to_dict("records"):
            stocks.append({
                "symbol": r.get("symbol"),
                "attack_rank": int(r["_attack_rank"]) if finite(r.get("_attack_rank")) else None,
                "selective_rank": int(r["_selective_rank"]) if finite(r.get("_selective_rank")) else None,
                "rs189": num(r.get("rs189")),
                "rs63": num(r.get("rs63")),
                "peer_theme": None if pd.isna(r.get("peer_theme")) else r.get("peer_theme"),
                "peer_theme_score": num(r.get("peer_theme_score")),
                "v38_status": r.get("v38_status"),
            })
        out.append({"etf": str(etf), "eligible_count": int(len(g)), "stocks": stocks})
    return out


def theme_context(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = load_json(path)
    except Exception:
        return None
    items = data.get("industry_context") if isinstance(data.get("industry_context"), list) else []
    compact = []
    for item in items:
        if not isinstance(item, dict):
            continue
        leaders = item.get("existing_emerging_or_leading_leaders_in_top15_intersection")
        leaders = leaders if isinstance(leaders, list) else []
        compact.append({
            "etf": item.get("etf"),
            "leaders": [{
                "symbol": x.get("symbol"), "group": x.get("group"), "phase": x.get("group_phase"),
                "role": x.get("role"), "rs189": num(x.get("rs189")), "rs63": num(x.get("rs63")),
            } for x in leaders[:5] if isinstance(x, dict)],
        })
    return {"status": "AVAILABLE", "items": compact}


def v38_action(v38: dict[str, Any], aligned: bool, formal: list[dict[str, Any]]) -> dict[str, Any]:
    market = v38.get("market_mode") if isinstance(v38.get("market_mode"), dict) else {}
    mode = str(market.get("mode") or "DATA_REQUIRED").upper()
    if not aligned:
        return {
            "status": "DATA_REQUIRED", "market_mode": mode, "normal_entry_limit": None,
            "normal_entry": "DATA REQUIRED: RotationとV38のasof不一致", "rotation_forced_exit": False,
            "formal_eligible_context": formal,
        }
    limit = market.get("new_entry_limit")
    if mode == "ATTACK":
        text = "正式Eligibility＋Attack Rank対象を、既存の空き枠と翌寄り執行ルールの範囲で候補化。Rotationは加点しない。"
    elif mode == "SELECTIVE":
        text = "正式EligibilityをStock RS189中心で候補化。既存のSelective容量制約に従い、Rotationは加点しない。"
    elif mode == "STOP":
        limit = 0
        text = "NORMAL ENTRY = 0。Rotation/Themeが強くても通常個別株の新規Entryはしない。"
    elif mode == "DEFENSE":
        limit = 0
        text = "NORMAL ENTRY = 0。既存positionの扱いは正式V38 Redルールに従う。Rotationから追加Exitは出さない。"
    else:
        return {
            "status": "DATA_REQUIRED", "market_mode": mode, "normal_entry_limit": None,
            "normal_entry": "DATA REQUIRED: Market Mode不明", "rotation_forced_exit": False,
            "formal_eligible_context": formal,
        }
    return {
        "status": "FORMAL_V38_CONTEXT", "market_mode": mode, "normal_entry_limit": limit,
        "normal_entry": text, "rotation_forced_exit": False, "formal_eligible_context": formal,
    }


def build_brief(
    rotation: dict[str, Any],
    v38: dict[str, Any],
    crosscheck_df: pd.DataFrame,
    *,
    history_path: Path | None = None,
    theme_context_path: Path | None = None,
) -> dict[str, Any]:
    alignment = input_alignment(rotation, v38)
    matrix = rotation.get("matrix") if isinstance(rotation.get("matrix"), list) else []
    buckets = rotation_buckets(matrix)
    flow = flow_observations(matrix)
    macro_facts, macro_hypotheses, macro_missing = macro_facts_and_hypotheses(rotation, matrix)
    formal = formal_context(crosscheck_df)
    action = v38_action(v38, bool(alignment["same_asof"]), formal)
    tickers = {str(r.get("ticker")) for r in matrix if isinstance(r, dict) and r.get("ticker")}
    events = history_events(history_path, str(rotation.get("asof") or ""), tickers) if alignment["rotation_asof"] else []
    tctx = theme_context(theme_context_path)
    quality = {
        "alignment": alignment,
        "macro_missing": macro_missing,
        "industry_internal_history": "CURRENT_HOLDINGS_BACKCAST_PROXY_UNTIL_LIVE_HISTORY_MATURES",
        "industry_pit_status": "DESCRIPTIVE_WATCH_ONLY",
        "loo_taxonomy": (v38.get("loo") or {}).get("taxonomy") if isinstance(v38.get("loo"), dict) else None,
        "theme_context": "AVAILABLE" if tctx else "DATA_REQUIRED",
    }
    return {
        "schema": 1,
        "research_only": True,
        "deterministic_formatter": True,
        "asof": alignment["rotation_asof"] if alignment["same_asof"] else None,
        "input_alignment": alignment,
        "market_when": v38.get("market_mode") if isinstance(v38.get("market_mode"), dict) else {},
        "observations": {
            "flow": flow,
            "rotation_buckets": buckets,
            "state_transitions": events,
        },
        "macro_why": {
            "facts": macro_facts,
            "hypotheses": macro_hypotheses,
            "missing": macro_missing,
            "rule": "WHY/context only; no causal claim and no V38 Gate/Exit effect",
        },
        "theme_stock": {
            "formal_v38_context": formal,
            "leadership_context": tctx or {"status": "DATA_REQUIRED"},
        },
        "v38_action": action,
        "data_quality": quality,
        "guardrails": [
            "No LLM or free-text model computes a signal; all labels come from upstream numeric state.",
            "Rotation contributes zero points to V38 ranking and is not a Gate.",
            "Industry ETF Rotation states are descriptive/WATCH only until PIT membership history is validated.",
            "DISTRIBUTION_WARNING is a warning/context state and never forces a V38 exit.",
            "Formal eligible context is not BUY; entry still requires formal Market Mode, capacity, and next-open execution.",
            "Missing inputs remain DATA REQUIRED; no proxy is silently substituted.",
        ],
    }


def state_line(row: dict[str, Any]) -> str:
    ticker = str(row.get("ticker") or "?")
    return (
        f"{ticker}: {row.get('state')} | Price {fmt_num(row.get('price_score'))} | "
        f"Internal {fmt_num(row.get('internal_score'))} (20D {fmt_num(row.get('internal_delta20'))}) | "
        f"Flow20 {fmt_money(row.get('flow_20d_usd'))}"
    )


def render_markdown(brief: dict[str, Any]) -> str:
    alignment = brief["input_alignment"]
    market = brief.get("market_when") or {}
    action = brief["v38_action"]
    obs = brief["observations"]
    buckets = obs["rotation_buckets"]
    lines = [
        f"# V38 Rotation Daily Observation Brief — {brief.get('asof') or 'DATA REQUIRED'}",
        "",
        "**RESEARCH ONLY / deterministic formatter / no LLM signal generation**",
        "",
        "## 1. WHEN — Formal V38 Market Mode",
        "",
        f"- NQSAR: **{market.get('nqsar', 'DATA REQUIRED')}**",
        f"- Breadth50: **{fmt_num(market.get('breadth50'), 2)}%**",
        f"- Market Mode: **{market.get('mode', 'DATA REQUIRED')}**",
        f"- V38 ACTION: **{action.get('normal_entry')}**",
        "- Rotation forced exit: **NO**",
        "",
        "## 2. WHERE — Observation",
        "",
    ]
    flow = obs["flow"]
    if flow["leaders"]:
        lines.append("- 20D Flow leaders: " + " / ".join(f"{x['ticker']} {fmt_money(x['flow_20d_usd'])}" for x in flow["leaders"]))
    if flow["laggards"]:
        lines.append("- 20D Flow laggards: " + " / ".join(f"{x['ticker']} {fmt_money(x['flow_20d_usd'])}" for x in flow["laggards"]))
    lines.append("")
    sections = [
        ("本流候補 / Current Strength", "mainstream", "descriptive current strength; future Alpha is not claimed"),
        ("保留 / Early Rotation WATCH", "watch", "WATCH ONLY; not a buy signal"),
        ("分配警戒", "distribution", "warning only; no forced sell"),
        ("Divergence / Flow流出でも内部強", "divergence", "do not classify as distribution from Flow alone"),
        ("崩れ", "breakdown", "price and internal weak"),
        ("Mixed / Hold", "mixed", "direction disagreement or threshold not met"),
    ]
    for title, key, note in sections:
        rows = buckets[key]
        lines += [f"### {title}", f"_{note}_"]
        if rows:
            lines.extend(f"- {state_line(r)}" for r in rows)
        else:
            lines.append("- none")
        lines.append("")

    lines += ["## 3. WHY — Macro consistency hypotheses", ""]
    facts = brief["macro_why"]["facts"]
    hypotheses = brief["macro_why"]["hypotheses"]
    lines.append("- Facts: " + (" / ".join(facts) if facts else "DATA REQUIRED"))
    if hypotheses:
        lines.extend(f"- 仮説: {x}" for x in hypotheses)
    else:
        lines.append("- 仮説: 数値stateから追加で言える機械的整合性なし。")
    if brief["macro_why"]["missing"]:
        lines.append("- DATA REQUIRED: " + " / ".join(brief["macro_why"]["missing"]))
    lines += ["", "## 4. Theme → Stock — Formal V38 context", ""]
    formal = brief["theme_stock"]["formal_v38_context"]
    if not formal:
        lines.append("- Formal eligible context: none / DATA REQUIRED")
    for item in formal:
        lines.append(f"### {item['etf']} — formal eligible {item['eligible_count']}")
        for s in item["stocks"]:
            rank = s.get("attack_rank") or s.get("selective_rank") or "-"
            theme = s.get("peer_theme") or "neutral50/no valid theme"
            lines.append(
                f"- {s['symbol']} | Rank {rank} | RS189 {fmt_num(s.get('rs189'),2)} | RS63 {fmt_num(s.get('rs63'),2)} | "
                f"strict LOO Theme: {theme} ({fmt_num(s.get('peer_theme_score'),2)})"
            )
        lines.append("")

    tctx = brief["theme_stock"]["leadership_context"]
    if tctx.get("status") == "AVAILABLE":
        lines += ["### Existing Leadership context (no new Rotation rank)"]
        for item in tctx.get("items") or []:
            leaders = item.get("leaders") or []
            if leaders:
                lines.append(f"- {item.get('etf')}: " + " / ".join(f"{x.get('group')}→{x.get('symbol')}" for x in leaders))
        lines.append("")
    else:
        lines += ["- Existing Leadership context: **DATA REQUIRED** (optional input not supplied)", ""]

    lines += ["## 5. V38 ACTION", "", f"- **{action.get('normal_entry')}**"]
    watch_names = [x["ticker"] for x in buckets["watch"]]
    dist_names = [x["ticker"] for x in buckets["distribution"]]
    if watch_names:
        lines.append("- WATCH ONLY: " + " / ".join(watch_names))
    if dist_names:
        lines.append("- DISTRIBUTION WATCH: " + " / ".join(dist_names) + " — Rotationによる強制売却なし")
    lines.append("- Formal eligible names above are context only; **BUY label is not generated**.")
    lines += ["", "## 6. State transitions / Data quality", ""]
    events = obs["state_transitions"]
    if events:
        for e in events[:10]:
            lines.append(f"- {e['date']} {e['ticker']}: {e['from']} → {e['to']}")
    else:
        lines.append("- State transition history: DATA REQUIRED / recorded history insufficient")
    lines.append(f"- Input alignment: **{alignment['status']}** (Rotation={alignment['rotation_asof']} / V38={alignment['v38_asof']})")
    lines.append(f"- Industry internal trend history: {brief['data_quality']['industry_internal_history']}")
    lines.append(f"- strict LOO taxonomy: {brief['data_quality'].get('loo_taxonomy') or 'DATA REQUIRED'}")
    lines += ["", "### Guardrails"]
    lines.extend(f"- {x}" for x in brief["guardrails"])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic research-only V38 Rotation Daily Observation Brief")
    ap.add_argument("--rotation", type=Path, required=True)
    ap.add_argument("--v38", type=Path, required=True)
    ap.add_argument("--v38-csv", type=Path, required=True)
    ap.add_argument("--history", type=Path)
    ap.add_argument("--theme-context", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    rotation = load_json(args.rotation)
    v38 = load_json(args.v38)
    crosscheck = load_crosscheck_csv(args.v38_csv)
    brief = build_brief(rotation, v38, crosscheck, history_path=args.history, theme_context_path=args.theme_context)
    (args.output / "daily_observation_brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "daily_observation_brief.md").write_text(render_markdown(brief), encoding="utf-8")

    rows = []
    for bucket, items in brief["observations"]["rotation_buckets"].items():
        for row in items:
            rows.append({"bucket": bucket, **row})
    pd.DataFrame(rows).to_csv(args.output / "daily_observation_brief_rows.csv", index=False)
    print(json.dumps({
        "asof": brief.get("asof"),
        "alignment": brief["input_alignment"],
        "market_mode": brief["v38_action"].get("market_mode"),
        "normal_entry_limit": brief["v38_action"].get("normal_entry_limit"),
        "rotation_forced_exit": brief["v38_action"].get("rotation_forced_exit"),
        "formal_context_etfs": [x["etf"] for x in brief["theme_stock"]["formal_v38_context"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
