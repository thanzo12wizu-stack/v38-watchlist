from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

PROVIDER_POLICY_VERSION = "1.1.0"
DATASETS = {
    "earnings": "earnings_calendar.csv",
    "revisions": "estimate_revisions.csv",
    "guidance": "guidance.csv",
    "news": "news.csv",
    "insider": "insider.csv",
    "13f": "holdings_13f.csv",
}


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path) if path.exists() else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _merge_rows(old: pd.DataFrame, new: pd.DataFrame, refreshed: set[str]) -> pd.DataFrame:
    if not old.empty and "ticker" in old.columns:
        old = old[~old["ticker"].astype(str).str.upper().isin(refreshed)]
    if old.empty:
        return new.reset_index(drop=True)
    if new.empty:
        return old.reset_index(drop=True)
    return pd.concat([old, new], ignore_index=True, sort=False)


def _fresh_tickers(root: Path, ttl_hours: float, now: datetime) -> set[str]:
    coverage = _read(root / "provider_coverage.csv")
    if coverage.empty or not {"ticker", "fetched_at"}.issubset(coverage.columns):
        return set()
    fetched = pd.to_datetime(coverage["fetched_at"], utc=True, errors="coerce")
    ok = fetched.ge(now - timedelta(hours=ttl_hours))
    if "status" in coverage.columns:
        ok &= coverage["status"].fillna("").eq("ok")
    return set(coverage.loc[ok, "ticker"].astype(str).str.upper())


def refresh_external_data(tickers: list[str], root: Path, *, ttl_hours: float = 20.0, max_tickers: int = 250) -> dict:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
    requested = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    fresh = _fresh_tickers(root, ttl_hours, now_dt)
    pending = [ticker for ticker in requested if ticker not in fresh][:max_tickers]
    refreshed = set(pending)
    rows = {key: [] for key in DATASETS}
    coverage_rows = []

    for ticker in pending:
        cov = {key: False for key in DATASETS}
        status, error = "ok", ""
        try:
            obj = yf.Ticker(ticker)
            calendar = obj.calendar
            if isinstance(calendar, dict):
                values = calendar.get("Earnings Date") or calendar.get("EarningsDate") or []
                if not isinstance(values, (list, tuple)):
                    values = [values]
                for value in values:
                    try:
                        event_date = pd.Timestamp(value).date().isoformat()
                    except Exception:
                        continue
                    rows["earnings"].append({"ticker": ticker, "event_date": event_date, "source": "yfinance", "fetched_at": now})
                cov["earnings"] = any(row["ticker"] == ticker for row in rows["earnings"])

            for kind, frame in (("eps", getattr(obj, "earnings_estimate", None)), ("revenue", getattr(obj, "revenue_estimate", None))):
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    for period, row in frame.iterrows():
                        rows["revisions"].append({"ticker": ticker, "metric": kind, "period": str(period), "current": row.get("avg"), "revision_7d": row.get("growth"), "source": "yfinance", "fetched_at": now})
                    cov["revisions"] = True

            ticker_news = obj.news or []
            for item in ticker_news:
                content = item.get("content") or item
                title = str(content.get("title") or "")
                summary = str(content.get("summary") or content.get("description") or "")
                text = (title + " " + summary).lower()
                event_type = "M&A" if any(x in text for x in ("acquire", "acquisition", "merger", "buyout")) else "CONTRACT" if any(x in text for x in ("contract", "award", "order", "partnership")) else "GUIDANCE" if "guidance" in text else "NEWS"
                published = content.get("pubDate") or content.get("providerPublishTime")
                rows["news"].append({"ticker": ticker, "published_at": published, "headline": title, "summary": summary, "event_type": event_type, "source": "yfinance", "fetched_at": now})
                if event_type == "GUIDANCE":
                    rows["guidance"].append({"ticker": ticker, "published_at": published, "direction": "UNKNOWN", "text": title, "source": "yfinance", "fetched_at": now})
            cov["news"] = bool(ticker_news)
            cov["guidance"] = any(row["ticker"] == ticker for row in rows["guidance"])

            insider = getattr(obj, "insider_transactions", None)
            if isinstance(insider, pd.DataFrame) and not insider.empty:
                for _, row in insider.head(100).iterrows():
                    rows["insider"].append({"ticker": ticker, "filed_at": row.get("Start Date"), "insider": row.get("Insider"), "transaction": row.get("Transaction"), "shares": row.get("Shares"), "value": row.get("Value"), "source": "yfinance", "fetched_at": now})
                cov["insider"] = True

            holders = getattr(obj, "institutional_holders", None)
            if isinstance(holders, pd.DataFrame) and not holders.empty:
                for _, row in holders.iterrows():
                    rows["13f"].append({"ticker": ticker, "holder": row.get("Holder"), "shares": row.get("Shares"), "date_reported": row.get("Date Reported"), "pct_out": row.get("% Out"), "value": row.get("Value"), "source": "yfinance", "fetched_at": now})
                cov["13f"] = True
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
        coverage_rows.append({"ticker": ticker, **cov, "status": status, "error": error, "fetched_at": now})

    for key, filename in DATASETS.items():
        _write(_merge_rows(_read(root / filename), pd.DataFrame(rows[key]), refreshed), root / filename)
    _write(_merge_rows(_read(root / "provider_coverage.csv"), pd.DataFrame(coverage_rows), refreshed), root / "provider_coverage.csv")
    return {
        "provider": "yfinance",
        "requested": len(requested),
        "fresh_skipped": len(fresh.intersection(requested)),
        "attempted": len(pending),
        "remaining": max(0, len(requested) - len(fresh.intersection(requested)) - len(pending)),
        "succeeded": sum(row["status"] == "ok" for row in coverage_rows),
        "failed": sum(row["status"] != "ok" for row in coverage_rows),
        "fetched_at": now,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--root", default="data/external")
    parser.add_argument("--ttl-hours", type=float, default=20.0)
    parser.add_argument("--max-tickers", type=int, default=250)
    args = parser.parse_args()
    frame = pd.read_csv(args.universe)
    column = next(c for c in frame.columns if str(c).lower() in {"ticker", "symbol", "ティッカー", "シンボル"})
    print(refresh_external_data(frame[column].dropna().astype(str).str.upper().tolist(), Path(args.root), ttl_hours=args.ttl_hours, max_tickers=args.max_tickers))


if __name__ == "__main__":
    main()
