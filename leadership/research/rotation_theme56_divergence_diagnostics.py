from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


YAHOO_EXCHANGE_SUFFIXES = {
    ".KS", ".KQ", ".HK", ".T", ".TW", ".DE", ".SW", ".AS", ".L", ".HE",
    ".MI", ".PA", ".CO", ".LS", ".TO", ".TA", ".AX", ".JO", ".OL", ".ST",
    ".SS", ".SZ", ".SA", ".NS", ".BO", ".JK", ".IS", ".VI", ".MC", ".SN",
    ".SI", ".BK", ".KL",
}
HORIZONS = (5, 10, 20)


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected object: {path}")
    return obj


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def yahoo_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if any(s.endswith(suffix) for suffix in YAHOO_EXCHANGE_SUFFIXES):
        return s
    return s.replace(".", "-") if "." in s else s


def normalize_holdings(path: Path, source: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["sector_etf", "symbol", "weight_pct", "name", "source"])
    df = pd.read_csv(path)
    if not {"sector_etf", "symbol"}.issubset(df.columns):
        raise RuntimeError(f"holdings columns missing: {path}")
    out = df.copy()
    out["sector_etf"] = out["sector_etf"].astype(str).str.upper().str.strip()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out = out[~out["symbol"].isin({"", "NAN", "-", "--"})]
    out["weight_pct"] = pd.to_numeric(out["weight_pct"], errors="coerce") if "weight_pct" in out.columns else np.nan
    out["name"] = out["name"].fillna("").astype(str) if "name" in out.columns else ""
    out["source"] = source
    return out[["sector_etf", "symbol", "weight_pct", "name", "source"]]


def merge_membership(base: Path, supplement: Path, fallback: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    exact_parts = [normalize_holdings(base, "issuer_exact"), normalize_holdings(supplement, "issuer_exact_supplement")]
    exact_raw = pd.concat(exact_parts, ignore_index=True)
    exact_tickers = set(exact_raw["sector_etf"].dropna().astype(str))
    fallback_raw = normalize_holdings(fallback, "validated_fallback")
    fallback_raw = fallback_raw[~fallback_raw["sector_etf"].isin(exact_tickers)]
    raw = pd.concat([exact_raw, fallback_raw], ignore_index=True)
    raw["has_weight"] = raw["weight_pct"].notna().astype(int)
    raw["has_name"] = raw["name"].ne("").astype(int)
    # Membership is unchanged. For duplicate members only, prefer the row carrying richer metadata.
    raw = raw.sort_values(["sector_etf", "symbol", "has_weight", "has_name"], ascending=[True, True, False, False])
    merged = raw.drop_duplicates(["sector_etf", "symbol"], keep="first").drop(columns=["has_weight", "has_name"])
    quality = {t: ("ISSUER_EXACT_CURRENT" if t in exact_tickers else "VALIDATED_CURRENT") for t in set(merged["sector_etf"])}
    return merged.reset_index(drop=True), quality


def download_close(symbols: list[str], start: str, end: str, batch_size: int = 40) -> tuple[pd.DataFrame, dict[str, Any]]:
    requested = list(dict.fromkeys(str(x).upper().strip() for x in symbols if str(x).strip() and " " not in str(x)))
    collected: dict[str, pd.Series] = {}
    failed = 0

    def one_batch(batch: list[str]) -> None:
        nonlocal failed
        ysyms = [yahoo_symbol(x) for x in batch]
        reverse = {yahoo_symbol(x): x for x in batch}
        try:
            raw = yf.download(ysyms, start=start, end=end, auto_adjust=True, actions=False, progress=False, group_by="ticker", threads=True, timeout=30)
        except Exception:
            failed += 1
            return
        if raw is None or raw.empty:
            failed += 1
            return
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for ys in ysyms:
                if ys not in level0:
                    continue
                part = raw[ys]
                if "Close" in part.columns:
                    s = pd.to_numeric(part["Close"], errors="coerce")
                    if s.notna().any():
                        collected[reverse[ys]] = s
        elif len(batch) == 1 and "Close" in raw.columns:
            s = pd.to_numeric(raw["Close"], errors="coerce")
            if s.notna().any():
                collected[batch[0]] = s

    for pos in range(0, len(requested), batch_size):
        one_batch(requested[pos:pos + batch_size])
        print(f"DIVERGENCE_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)

    missing = [s for s in requested if s not in collected]
    for pos in range(0, len(missing), 5):
        one_batch(missing[pos:pos + 5])
    still = [s for s in requested if s not in collected]
    for sym in still:
        one_batch([sym])

    if not collected:
        raise RuntimeError("no constituent close data")
    close = pd.DataFrame(collected)
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index().replace([np.inf, -np.inf], np.nan)
    return close, {
        "requested": len(requested),
        "downloaded": len(collected),
        "coverage": len(collected) / len(requested) if requested else 0.0,
        "failed_batches": failed,
        "start": str(close.index.min().date()),
        "end": str(close.index.max().date()),
    }


def period_return(close: pd.DataFrame, horizon: int) -> pd.Series:
    if len(close) <= horizon:
        return pd.Series(index=close.columns, dtype=float)
    latest = close.ffill().iloc[-1]
    previous = close.ffill().iloc[-1 - horizon]
    return (latest / previous - 1.0) * 100.0


def horizon_stats(members: pd.DataFrame, returns: pd.Series, horizon: int) -> dict[str, Any]:
    symbols = [s for s in members["symbol"].astype(str) if s in returns.index and pd.notna(returns.get(s))]
    vals = pd.to_numeric(returns.reindex(symbols), errors="coerce").dropna()
    member_count = int(len(members))
    out: dict[str, Any] = {
        "horizon": horizon,
        "return_members": int(len(vals)),
        "return_coverage": float(len(vals) / member_count) if member_count else 0.0,
        "positive_breadth_pct": float((vals > 0).mean() * 100.0) if len(vals) else None,
        "median_return_pct": float(vals.median()) if len(vals) else None,
        "equal_weight_return_pct": float(vals.mean()) if len(vals) else None,
    }

    weighted = members[members["symbol"].isin(vals.index) & members["weight_pct"].notna()].copy()
    weighted["ret"] = weighted["symbol"].map(vals)
    weighted = weighted.dropna(subset=["ret", "weight_pct"])
    if not weighted.empty and float(weighted["weight_pct"].clip(lower=0).sum()) > 0:
        weighted["w"] = weighted["weight_pct"].clip(lower=0)
        den = float(weighted["w"].sum())
        weighted["wn"] = weighted["w"] / den
        weighted["contrib"] = weighted["wn"] * weighted["ret"]
        weighted["abs_contrib"] = weighted["contrib"].abs()
        top = weighted.sort_values("w", ascending=False).head(5)
        abs_total = float(weighted["abs_contrib"].sum())
        out.update({
            "weighted_return_pct": float(weighted["contrib"].sum()),
            "top5_abs_move_share_pct": float(top["abs_contrib"].sum() / abs_total * 100.0) if abs_total > 1e-12 else None,
            "top5_directional_contribution_pct": float(top["contrib"].sum()),
        })
    else:
        out.update({"weighted_return_pct": None, "top5_abs_move_share_pct": None, "top5_directional_contribution_pct": None})
    return out


def concentration(members: pd.DataFrame) -> dict[str, Any]:
    total = int(len(members))
    weighted = members[members["weight_pct"].notna()].copy()
    weighted["weight_pct"] = pd.to_numeric(weighted["weight_pct"], errors="coerce")
    weighted = weighted.dropna(subset=["weight_pct"])
    weighted = weighted[weighted["weight_pct"] >= 0]
    known_sum = float(weighted["weight_pct"].sum()) if not weighted.empty else 0.0
    member_cov = float(len(weighted) / total) if total else 0.0
    ready = len(weighted) >= 5 and member_cov >= 0.70 and known_sum >= 60.0
    if weighted.empty or known_sum <= 0:
        return {
            "quality": "DATA_REQUIRED", "weighted_members": 0, "member_weight_coverage": member_cov,
            "reported_weight_sum_pct": known_sum, "top5_weight_pct": None, "top10_weight_pct": None,
            "effective_holdings": None, "top_holdings": [],
        }
    ranked = weighted.sort_values("weight_pct", ascending=False)
    norm = ranked["weight_pct"] / known_sum
    hhi = float((norm ** 2).sum())
    top = ranked.head(10)
    return {
        "quality": "WEIGHT_READY" if ready else "WEIGHT_PARTIAL",
        "weighted_members": int(len(weighted)),
        "member_weight_coverage": member_cov,
        "reported_weight_sum_pct": known_sum,
        "top5_weight_pct": float(ranked.head(5)["weight_pct"].sum()),
        "top10_weight_pct": float(ranked.head(10)["weight_pct"].sum()),
        "effective_holdings": float(1.0 / hhi) if hhi > 0 else None,
        "top_holdings": [
            {"symbol": str(r.symbol), "name": str(r.name or ""), "weight_pct": float(r.weight_pct)}
            for r in top.itertuples(index=False)
        ],
    }


def early_phase(h5: dict[str, Any], h10: dict[str, Any], h20: dict[str, Any]) -> dict[str, str]:
    b5 = safe_float(h5.get("positive_breadth_pct"))
    b10 = safe_float(h10.get("positive_breadth_pct"))
    b20 = safe_float(h20.get("positive_breadth_pct"))
    m5 = safe_float(h5.get("median_return_pct"))
    m10 = safe_float(h10.get("median_return_pct"))
    if None in (b5, b10, b20):
        return {"key": "DATA_REQUIRED", "label": "短期方向未取得"}
    if b5 >= 65 and b20 < 50 and (m5 or 0) > 0:
        return {"key": "IGNITION_5D", "label": "5日初動・20日未確認"}
    if b10 >= 60 and b20 < 55 and (m10 or 0) > 0:
        return {"key": "EXPANSION_10D", "label": "10日拡大・20日未確認"}
    if b5 - b20 >= 15 and (m5 or 0) > 0:
        return {"key": "SHORT_LEAD", "label": "短期改善が20日に先行"}
    if b5 <= 40 and b20 >= 60:
        return {"key": "ROLLING_OVER_5D", "label": "20日強いが直近5日失速"}
    if b10 <= 45 and b20 >= 60:
        return {"key": "ROLLING_OVER_10D", "label": "20日強いが直近10日失速"}
    if b20 >= 60:
        return {"key": "CONFIRMED_20D", "label": "20日まで広がり確認"}
    if b5 >= 55 and b10 >= 55:
        return {"key": "BUILDING", "label": "5・10日で広がり形成中"}
    if b5 < 45 and b10 < 45:
        return {"key": "WEAK_SHORT", "label": "短期の広がり弱い"}
    return {"key": "MIXED_SHORT", "label": "短期は移行中"}


def classify_cause(price_score: float | None, internal_score: float | None, phase: dict[str, str], conc: dict[str, Any], h5: dict[str, Any], h10: dict[str, Any]) -> dict[str, str]:
    b5 = safe_float(h5.get("positive_breadth_pct"))
    b10 = safe_float(h10.get("positive_breadth_pct"))
    move_share = safe_float(h5.get("top5_abs_move_share_pct"))
    weight_ready = conc.get("quality") == "WEIGHT_READY"
    top5_weight = safe_float(conc.get("top5_weight_pct"))
    early = phase.get("key") in {"IGNITION_5D", "EXPANSION_10D", "SHORT_LEAD", "BUILDING"}
    rolling = phase.get("key") in {"ROLLING_OVER_5D", "ROLLING_OVER_10D"}

    if price_score is None or internal_score is None:
        return {"key": "DATA_REQUIRED", "label": "原因分析未取得", "confidence": "LOW"}

    if price_score >= 65 and internal_score < 55:
        if weight_ready and move_share is not None and move_share >= 55 and b5 is not None and b5 < 50:
            return {"key": "TOP_WEIGHT_LED_NARROW", "label": "上位構成銘柄主導・広がり不足", "confidence": "HIGH"}
        if b5 is not None and b10 is not None and b5 < 45 and b10 < 50:
            return {"key": "PRICE_LEAD_NARROW", "label": "ETF価格先行・構成株の広がり不足", "confidence": "MEDIUM"}
        if rolling:
            return {"key": "PRICE_HOLD_INTERNAL_ROLLOVER", "label": "ETF高止まり・内部は失速", "confidence": "MEDIUM"}
        return {"key": "PRICE_LEAD_MIXED", "label": "ETF価格先行・原因は混合", "confidence": "LOW" if not weight_ready else "MEDIUM"}

    if price_score < 60 and internal_score >= 60:
        if early and b5 is not None and b5 >= 55:
            return {"key": "BROAD_INTERNAL_IGNITION", "label": "構成株が先行・短期の広がり拡大", "confidence": "HIGH" if h5.get("return_coverage", 0) >= 0.8 else "MEDIUM"}
        return {"key": "INTERNAL_LEAD", "label": "構成株が先行・ETF価格は未追随", "confidence": "MEDIUM"}

    if price_score >= 60 and internal_score >= 60:
        if rolling:
            return {"key": "STRONG_ROLLING_OVER", "label": "テーマは強いが直近は失速", "confidence": "MEDIUM"}
        if weight_ready and top5_weight is not None and top5_weight >= 45 and move_share is not None and move_share >= 55 and b5 is not None and b5 < 55:
            return {"key": "STRONG_TOP_HEAVY", "label": "強いが上位構成銘柄への依存大", "confidence": "HIGH"}
        return {"key": "BROAD_STRENGTH", "label": "価格と構成株が広く強い", "confidence": "MEDIUM"}

    if price_score < 50 and internal_score < 50:
        if early:
            return {"key": "WEAK_EARLY_RECOVERY", "label": "まだ弱いが短期初動あり", "confidence": "MEDIUM"}
        return {"key": "BROAD_WEAK", "label": "価格・構成株とも弱く初動未確認", "confidence": "MEDIUM"}

    if early:
        return {"key": "MIXED_EARLY", "label": "現在は混合だが短期初動あり", "confidence": "MEDIUM"}
    if rolling:
        return {"key": "MIXED_ROLLOVER", "label": "現在は混合・短期は失速", "confidence": "MEDIUM"}
    return {"key": "MIXED", "label": "価格・構成株の方向が混合", "confidence": "LOW"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Theme56 ETF/constituent divergence diagnostics and pre-20D motion context")
    ap.add_argument("--brief", type=Path, required=True)
    ap.add_argument("--base-holdings", type=Path, required=True)
    ap.add_argument("--supplement-holdings", type=Path, required=True)
    ap.add_argument("--fallback-holdings", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--download-start", required=True)
    ap.add_argument("--download-end", required=True)
    args = ap.parse_args()

    brief = load_json(args.brief)
    membership, membership_quality = merge_membership(args.base_holdings, args.supplement_holdings, args.fallback_holdings)
    symbols = sorted(set(membership["symbol"].astype(str)))
    close, dl = download_close(symbols, args.download_start, args.download_end)
    returns = {h: period_return(close, h) for h in HORIZONS}

    theme_rows: list[dict[str, Any]] = []
    for values in ((brief.get("observations") or {}).get("rotation_buckets") or {}).values():
        if isinstance(values, list):
            theme_rows.extend(x for x in values if isinstance(x, dict))
    row_by = {str(x.get("ticker") or "").upper(): x for x in theme_rows}

    diagnostics: list[dict[str, Any]] = []
    for ticker, row in row_by.items():
        members = membership[membership["sector_etf"] == ticker].copy()
        if members.empty:
            diagnostics.append({"ticker": ticker, "status": "DATA_REQUIRED", "reason": "current membership unavailable"})
            continue
        hs = {h: horizon_stats(members, returns[h], h) for h in HORIZONS}
        conc = concentration(members)
        # Attach returns to top holdings for direct inspection.
        for top in conc.get("top_holdings", []):
            sym = str(top.get("symbol") or "")
            top["ret_5d_pct"] = safe_float(returns[5].get(sym))
            top["ret_10d_pct"] = safe_float(returns[10].get(sym))
            top["ret_20d_pct"] = safe_float(returns[20].get(sym))
        phase = early_phase(hs[5], hs[10], hs[20])
        cause = classify_cause(safe_float(row.get("price_score")), safe_float(row.get("internal_score")), phase, conc, hs[5], hs[10])
        diagnostics.append({
            "ticker": ticker,
            "status": "READY",
            "membership_quality": membership_quality.get(ticker),
            "member_count": int(len(members)),
            "downloaded_member_count": int(sum(1 for s in members["symbol"] if s in close.columns)),
            "concentration": conc,
            "horizons": {str(h): hs[h] for h in HORIZONS},
            "early_phase": phase,
            "divergence_cause": cause,
            "analysis_contract": "Descriptive only. ETF holding weight is used as the direct price-impact proxy; this does not assert market-cap class. 5D/10D context is explicitly separated from 20D confirmation.",
        })

    ready = [x for x in diagnostics if x.get("status") == "READY"]
    out = {
        "schema": 1,
        "status": "READY" if len(ready) >= 50 else "PARTIAL",
        "asof": brief.get("asof"),
        "theme_count": len(diagnostics),
        "ready_count": len(ready),
        "download": dl,
        "method": {
            "mismatch": "ETF Price Score vs existing equal-weight constituent Internal Score",
            "concentration": "current ETF holding weights; WEIGHT_READY requires >=70% member weight coverage and >=60% reported weight sum",
            "movement_concentration": "share of absolute normalized weighted constituent move attributable to the five highest-weight constituents",
            "early_motion": "5D and 10D constituent positive-return breadth and median return, shown separately from 20D confirmation",
            "large_cap_note": "High ETF weight is a more direct ETF-price influence measure than company market cap. Labels therefore say 上位構成銘柄主導 rather than asserting market-cap class when market-cap data is not used.",
            "trading": "No entry/exit/gate/ranking points are created.",
        },
        "themes": diagnostics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "asof": out["asof"], "ready": len(ready), "themes": len(diagnostics), "download": dl}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
