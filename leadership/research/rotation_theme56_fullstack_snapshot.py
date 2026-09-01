from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

import rotation_live_snapshot as live


YAHOO_EXCHANGE_SUFFIXES = {
    ".KS", ".KQ", ".HK", ".T", ".TW", ".DE", ".SW", ".AS", ".L", ".HE",
    ".MI", ".PA", ".CO", ".LS", ".TO", ".TA", ".AX", ".JO", ".OL", ".ST",
    ".SS", ".SZ", ".SA", ".NS", ".BO", ".JK", ".IS", ".VI", ".MC", ".SN",
}
FIELDS = ("Close", "High", "Low", "Volume")
FLOW_COLS = {"date", "ticker", "provider", "aum", "flow_1d", "flow_5d", "flow_20d", "flow_20d_pct_aum", "source_url"}


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def latest_num(series: pd.Series) -> float | None:
    x = pd.to_numeric(series, errors="coerce").dropna()
    return None if x.empty else float(x.iloc[-1])


def normalize_holdings(df: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    required = {"sector_etf", "symbol"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"holdings missing columns: {sorted(required - set(df.columns))}")
    out = df.copy()
    out["sector_etf"] = out["sector_etf"].astype(str).str.upper().str.strip()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out = out[out["sector_etf"].isin(universe)]
    out = out[~out["symbol"].isin({"", "NAN", "-", "--"})]
    return out.drop_duplicates(["sector_etf", "symbol"], keep="first")


def yahoo_market_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if not s:
        return s
    if any(s.endswith(suffix) for suffix in YAHOO_EXCHANGE_SUFFIXES):
        return s
    if "." in s:
        return s.replace(".", "-")
    return s


def _download_batch(batch: list[str], start: str, end: str) -> dict[str, dict[str, pd.Series]]:
    yf_names = [yahoo_market_symbol(s) for s in batch]
    reverse = {yahoo_market_symbol(s): s for s in batch}
    raw = yf.download(
        yf_names,
        start=start,
        end=end,
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by="ticker",
        threads=True,
        timeout=30,
    )
    result: dict[str, dict[str, pd.Series]] = {field: {} for field in FIELDS}
    if raw is None or raw.empty:
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = {str(x) for x in raw.columns.get_level_values(0)}
        for ysym in yf_names:
            if ysym not in level0:
                continue
            part = raw[ysym]
            sym = reverse.get(ysym)
            if not sym:
                continue
            for field in FIELDS:
                if field in part.columns:
                    sr = pd.to_numeric(part[field], errors="coerce")
                    if sr.notna().any():
                        result[field][sym] = sr
    elif len(batch) == 1:
        sym = batch[0]
        for field in FIELDS:
            if field in raw.columns:
                sr = pd.to_numeric(raw[field], errors="coerce")
                if sr.notna().any():
                    result[field][sym] = sr
    return result


def download_theme56_ohlcv(symbols: list[str], start: str, end: str, batch_size: int = 20) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    requested = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    collected: dict[str, dict[str, pd.Series]] = {field: {} for field in FIELDS}
    failed_batches = 0

    def merge(result: dict[str, dict[str, pd.Series]]) -> None:
        for field in FIELDS:
            collected[field].update(result.get(field, {}))

    for pos in range(0, len(requested), batch_size):
        batch = requested[pos:pos + batch_size]
        try:
            merge(_download_batch(batch, start, end))
        except Exception:
            failed_batches += 1
        print(f"THEME56_DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)}", flush=True)

    def common_symbols() -> set[str]:
        sets = [set(collected[field]) for field in FIELDS]
        return set.intersection(*sets) if sets else set()

    initial_common = common_symbols()
    missing = [s for s in requested if s not in initial_common]
    retry_batches = 0
    for pos in range(0, len(missing), 5):
        batch = missing[pos:pos + 5]
        retry_batches += 1
        try:
            merge(_download_batch(batch, start, end))
        except Exception:
            pass

    still_missing = [s for s in requested if s not in common_symbols()]
    individual_attempts = 0
    for sym in still_missing:
        individual_attempts += 1
        try:
            merge(_download_batch([sym], start, end))
        except Exception:
            pass

    final_common = sorted(common_symbols())
    if not final_common:
        raise RuntimeError("Yahoo download returned no usable common OHLCV data")

    out: dict[str, pd.DataFrame] = {}
    for field in FIELDS:
        df = pd.DataFrame({s: collected[field][s] for s in final_common if s in collected[field]})
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index().replace([np.inf, -np.inf], np.nan)
        out[field.lower()] = df[final_common]

    diag = {
        "requested": len(requested),
        "downloaded_common_ohlcv": len(final_common),
        "initial_downloaded_common_ohlcv": len(initial_common),
        "retry_requested": len(missing),
        "retry_recovered": len(set(final_common) - initial_common),
        "retry_batches": retry_batches,
        "individual_retry_attempts": individual_attempts,
        "final_missing": len(requested) - len(final_common),
        "rows": int(len(out["close"])),
        "start": str(out["close"].index.min().date()),
        "end": str(out["close"].index.max().date()),
        "failed_batches": failed_batches,
        "ticker_mapping_note": "Foreign Yahoo exchange suffixes are preserved; dot-to-hyphen conversion is only used for non-exchange dotted symbols such as US class shares.",
    }
    return out, diag


def _read_flow_csv(path: Path, universe: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(f"flow file missing: {path}")
    df = pd.read_csv(path, usecols=lambda c: c in FLOW_COLS)
    missing = {"date", "ticker", "flow_20d_pct_aum"} - set(df.columns)
    if missing:
        raise RuntimeError(f"flow file missing columns {sorted(missing)}: {path}")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df[df["ticker"].isin(universe)].dropna(subset=["date"]).sort_values(["ticker", "date"])


def build_flow_stack(
    issuer_flows_path: Path,
    etfcom_flows_path: Path,
    etfcom_qa_path: Path,
    universe: set[str],
) -> tuple[dict[str, dict[str, Any]], set[str], set[str], dict[str, Any]]:
    qa = load_json(etfcom_qa_path)
    if qa.get("aggregate_validation_pass") is not True:
        raise RuntimeError("ETF.com Theme56 flow fallback has not passed aggregate validation")
    if int(qa.get("canonical_reference_tickers") or 0) < 12 or int(qa.get("canonical_reference_provider_count") or 0) < 2:
        raise RuntimeError("ETF.com fallback lacks sufficiently broad issuer cross-validation")

    validation = qa.get("validation") if isinstance(qa.get("validation"), list) else []
    issuer_clean = {
        str(x.get("ticker") or "").upper()
        for x in validation
        if isinstance(x, dict) and x.get("status") == "PASS"
    } & universe
    anomalies = {
        str(x).upper() for x in (qa.get("reference_unit_anomalies") or [])
    } & universe
    if issuer_clean & anomalies:
        raise RuntimeError("flow QA marks a ticker both clean and anomalous")

    fallback_status = qa.get("status") if isinstance(qa.get("status"), list) else []
    fallback_ready = {
        str(x.get("ticker") or "").upper()
        for x in fallback_status
        if isinstance(x, dict) and x.get("status") == "PASS"
    } & universe

    issuer = _read_flow_csv(issuer_flows_path, universe)
    fallback = _read_flow_csv(etfcom_flows_path, universe)
    issuer = issuer[issuer["ticker"].isin(issuer_clean)]
    fallback = fallback[fallback["ticker"].isin(fallback_ready)]

    issuer_latest = {t: g.iloc[-1].to_dict() for t, g in issuer.groupby("ticker", observed=True) if not g.empty}
    fallback_latest = {t: g.iloc[-1].to_dict() for t, g in fallback.groupby("ticker", observed=True) if not g.empty}

    selected: dict[str, dict[str, Any]] = {}
    source_counts = {"ISSUER_EXACT_OFFICIAL": 0, "ETFCOM_VALIDATED_ACTUAL": 0}
    for ticker in sorted(universe):
        i = issuer_latest.get(ticker)
        e = fallback_latest.get(ticker)
        if i is not None and pd.notna(i.get("flow_20d_pct_aum")):
            row = dict(i)
            row["flow_quality"] = "ISSUER_EXACT_OFFICIAL"
            selected[ticker] = row
            source_counts["ISSUER_EXACT_OFFICIAL"] += 1
        elif e is not None and pd.notna(e.get("flow_20d_pct_aum")):
            row = dict(e)
            row["flow_quality"] = "ETFCOM_VALIDATED_ACTUAL"
            selected[ticker] = row
            source_counts["ETFCOM_VALIDATED_ACTUAL"] += 1

    diag = {
        "aggregate_validation_pass": True,
        "issuer_exact_clean_tickers": sorted(issuer_clean),
        "issuer_reference_unit_anomalies": sorted(anomalies),
        "etfcom_validated_ready_tickers": sorted(fallback_ready),
        "selected_flow_tickers": sorted(selected),
        "source_counts": source_counts,
        "contract": "Clean issuer-derived Exact Flow is preferred. ETF.com validated actual fund flow is used as fallback. Reference-unit anomalies are never used as issuer-exact flow.",
    }
    return selected, issuer_clean, fallback_ready, diag


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Theme56 Price + Internals + validated actual Flow snapshot")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--price-json", type=Path, default=Path("leadership/research/rotation_theme56_live/theme56_price.json"))
    ap.add_argument("--holdings", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_current_holdings.csv"))
    ap.add_argument("--holdings-expansion", type=Path, default=Path("leadership/research/rotation_theme56_holdings_expansion/exact_current_holdings_expansion.csv"))
    ap.add_argument("--issuer-flows", "--flows", dest="issuer_flows", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_flows.csv"))
    ap.add_argument("--etfcom-flows", type=Path, default=Path("leadership/research/rotation_theme56_etfcom_flow/theme56_etfcom_daily_flows.csv"))
    ap.add_argument("--etfcom-flow-qa", type=Path, default=Path("leadership/research/rotation_theme56_etfcom_flow/etfcom_flow_qa.json"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_fullstack"))
    ap.add_argument("--download-start", default="2025-10-01")
    ap.add_argument("--download-end", default="2026-09-02")
    ap.add_argument("--min-source-coverage", type=float, default=0.80)
    args = ap.parse_args()

    cfg = load_json(args.config)
    themes = cfg.get("themes") if isinstance(cfg.get("themes"), list) else []
    labels = {str(x.get("ticker") or "").upper().strip(): str(x.get("label") or x.get("ticker") or "") for x in themes if isinstance(x, dict)}
    if len(labels) != 56:
        raise RuntimeError("Theme56 config must contain 56 unique tickers")
    universe = set(labels)

    price_obj = load_json(args.price_json)
    price_rows = price_obj.get("rows") if isinstance(price_obj.get("rows"), list) else []
    price = {str(x.get("ticker") or "").upper(): x for x in price_rows if isinstance(x, dict)}

    frames = [normalize_holdings(pd.read_csv(args.holdings), universe)]
    if args.holdings_expansion.exists():
        frames.append(normalize_holdings(pd.read_csv(args.holdings_expansion), universe))
    holdings = pd.concat(frames, ignore_index=True).drop_duplicates(["sector_etf", "symbol"], keep="first")
    internal_tickers = [t for t in labels if t in set(holdings["sector_etf"])]
    if not internal_tickers:
        raise RuntimeError("no exact current holdings tickers")

    members = sorted({s for s in holdings["symbol"] if s and " " not in s})
    ohlcv, dl_diag = download_theme56_ohlcv(members, args.download_start, args.download_end, 20)
    internal_parts, internal_score, internal_delta20, internal_diag = live.build_internal(
        ohlcv, holdings, internal_tickers, args.min_source_coverage
    )
    diag_by = {str(x.get("ticker")): x for x in internal_diag if isinstance(x, dict)}

    flow_latest, issuer_exact_clean, fallback_ready, flow_diag = build_flow_stack(
        args.issuer_flows, args.etfcom_flows, args.etfcom_flow_qa, universe
    )
    flow_ready = set(flow_latest)

    rows: list[dict[str, Any]] = []
    for ticker in labels:
        p = price.get(ticker, {})
        i_diag = diag_by.get(ticker, {})
        f = flow_latest.get(ticker)
        i_score = latest_num(internal_score[ticker]) if ticker in internal_score.columns else None
        i_delta = latest_num(internal_delta20[ticker]) if ticker in internal_delta20.columns else None
        price_ok = p.get("quality") == "MARKET_PRICE_SERIES"
        internal_ok = i_score is not None
        flow_ok = f is not None and pd.notna(f.get("flow_20d_pct_aum"))
        if price_ok and internal_ok and flow_ok:
            quality = "MEASURED_FULL_STACK_UNVALIDATED"
        elif price_ok and internal_ok:
            quality = "MEASURED_PRICE_INTERNAL_FLOW_MISSING"
        elif price_ok:
            quality = "MEASURED_PRICE_ONLY"
        else:
            quality = "DATA_REQUIRED"
        flow_quality = None if f is None else f.get("flow_quality")
        rec: dict[str, Any] = {
            "ticker": ticker,
            "label": labels[ticker],
            "price_quality": p.get("quality") or "DATA_REQUIRED",
            "price_score_56": p.get("price_score"),
            "rs63_rank_56": p.get("rs63_rank"),
            "rs189_rank_56": p.get("rs189_rank"),
            "ret_1d_pct": p.get("ret_1d_pct"),
            "ret_5d_pct": p.get("ret_5d_pct"),
            "ret_20d_pct": p.get("ret_20d_pct"),
            "holdings_adapter": "PASS" if ticker in internal_tickers else "DATA_REQUIRED",
            "exact_flow_adapter": "PASS" if ticker in issuer_exact_clean else "DATA_REQUIRED",
            "actual_flow_adapter": "PASS" if ticker in flow_ready else "DATA_REQUIRED",
            "source_members": i_diag.get("source_members"),
            "downloaded_members": i_diag.get("downloaded_members"),
            "source_member_coverage": i_diag.get("source_member_coverage"),
            "internal_score_56": i_score,
            "internal_delta20_56": i_delta,
            "internal_score_available_cross_section": i_score,
            "internal_delta20_available_cross_section": i_delta,
            "flow_asof": None if f is None else str(pd.Timestamp(f["date"]).date()),
            "flow_1d_usd": None if f is None or pd.isna(f.get("flow_1d")) else float(f["flow_1d"]),
            "flow_5d_usd": None if f is None or pd.isna(f.get("flow_5d")) else float(f["flow_5d"]),
            "flow_20d_usd": None if f is None or pd.isna(f.get("flow_20d")) else float(f["flow_20d"]),
            "flow_20d_pct_aum": None if f is None or pd.isna(f.get("flow_20d_pct_aum")) else float(f["flow_20d_pct_aum"]),
            "flow_provider": None if f is None or pd.isna(f.get("provider")) else f.get("provider"),
            "flow_quality": flow_quality,
            "quality": quality,
            "state": "VALIDATION_REQUIRED" if price_ok and internal_ok else ("PRICE_ONLY" if price_ok else "DATA_REQUIRED"),
        }
        for name in live.COMPONENTS:
            frame = internal_parts.get(name)
            rec[name] = latest_num(frame[ticker]) if isinstance(frame, pd.DataFrame) and ticker in frame.columns else None
            rank_frame = internal_parts.get(f"{name}_rank")
            rec[f"{name}_rank_56"] = latest_num(rank_frame[ticker]) if isinstance(rank_frame, pd.DataFrame) and ticker in rank_frame.columns else None
        rows.append(rec)

    out = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output / "theme56_fullstack_snapshot.csv", index=False)
    full = out[out["quality"] == "MEASURED_FULL_STACK_UNVALIDATED"]
    pi = out[out["quality"].isin(["MEASURED_FULL_STACK_UNVALIDATED", "MEASURED_PRICE_INTERNAL_FLOW_MISSING"])]
    price_ready = out[out["price_quality"] == "MARKET_PRICE_SERIES"]
    flow_source_counts = {str(k): int(v) for k, v in out["flow_quality"].dropna().value_counts().to_dict().items()}
    report = {
        "schema": 4,
        "research_only": True,
        "asof": price_obj.get("asof"),
        "universe_count": 56,
        "price_ready_count": int(len(price_ready)),
        "exact_holdings_count": int(len(internal_tickers)),
        "internal_measured_count": int(len(pi)),
        "exact_flow_count": int(len(issuer_exact_clean)),
        "issuer_exact_flow_count": int(len(issuer_exact_clean)),
        "validated_actual_flow_count": int(len(fallback_ready)),
        "flow_ready_count": int(len(flow_ready)),
        "flow_source_counts": flow_source_counts,
        "measured_full_stack_count": int(len(full)),
        "measured_full_stack_tickers": full["ticker"].tolist(),
        "internal_measured_tickers": pi["ticker"].tolist(),
        "price_only_or_missing_tickers": out.loc[~out["quality"].isin(["MEASURED_FULL_STACK_UNVALIDATED", "MEASURED_PRICE_INTERNAL_FLOW_MISSING"]), "ticker"].tolist(),
        "flow_data_required_tickers": sorted(universe - flow_ready),
        "flow_diagnostics": flow_diag,
        "internal_cross_section_note": "Internals are ranked across the current Theme56 ETFs with exact current provider holdings and sufficient member-price coverage.",
        "flow_contract": "Issuer-derived Exact Flow is used only for cross-validated canonical-unit references. ETF.com validated actual fund flow fills the remaining supported themes. No price-volume proxy is used.",
        "state_contract": "No legacy 15-ETF trading signal is claimed. Theme56 public states are descriptive observation labels only.",
        "download_diagnostics": dl_diag,
        "internal_diagnostics": internal_diag,
        "rows": rows,
    }
    (args.output / "theme56_fullstack_snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("universe_count", "price_ready_count", "exact_holdings_count", "internal_measured_count", "issuer_exact_flow_count", "flow_ready_count", "measured_full_stack_count", "flow_data_required_tickers")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
