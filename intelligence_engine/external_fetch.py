from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

PROVIDER_POLICY_VERSION = "1.2.0"
FILES = {
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


def _merge_rows(
    old: pd.DataFrame,
    new: pd.DataFrame,
    replace_tickers: set[str],
) -> pd.DataFrame:
    if not old.empty and "ticker" in old.columns:
        old = old[
            ~old["ticker"].astype(str).str.upper().isin(replace_tickers)
        ]
    if old.empty:
        return new.reset_index(drop=True)
    if new.empty:
        return old.reset_index(drop=True)
    return pd.concat([old, new], ignore_index=True, sort=False)


def _fresh_tickers(
    root: Path,
    ttl_hours: float,
    now: datetime,
) -> set[str]:
    coverage = _read(root / "provider_coverage.csv")
    if coverage.empty or not {"ticker", "fetched_at"}.issubset(coverage.columns):
        return set()
    fetched = pd.to_datetime(
        coverage["fetched_at"],
        utc=True,
        errors="coerce",
    )
    ok = fetched.ge(now - timedelta(hours=ttl_hours))
    if "status" in coverage.columns:
        ok &= coverage["status"].fillna("").isin({"ok", "partial"})
    return set(coverage.loc[ok, "ticker"].astype(str).str.upper())


def _calendar_dates(calendar: Any) -> list[str]:
    values: list[Any] = []
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date") or calendar.get("EarningsDate") or []
        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    elif isinstance(calendar, pd.DataFrame) and not calendar.empty:
        columns = {
            str(column).strip().lower(): column for column in calendar.columns
        }
        date_column = next(
            (
                columns[name]
                for name in ("earnings date", "earningsdate", "date")
                if name in columns
            ),
            None,
        )
        if date_column is not None:
            values = calendar[date_column].tolist()
        else:
            values = list(calendar.to_numpy().ravel())
    dates = []
    for value in values:
        try:
            date_value = pd.Timestamp(value)
        except Exception:
            continue
        if pd.isna(date_value):
            continue
        dates.append(date_value.date().isoformat())
    return sorted(set(dates))


def _number(value: Any) -> float | None:
    result = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(result) else float(result)


def _revision_value(row: pd.Series, names: tuple[str, ...]) -> float | None:
    mapping = {str(key).strip().lower(): key for key in row.index}
    for name in names:
        key = mapping.get(name.lower())
        if key is not None:
            value = _number(row.get(key))
            if value is not None:
                return value
    return None


def _append_eps_revisions(
    ticker: str,
    frame: Any,
    now: str,
    rows: list[dict],
) -> bool:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return False
    added = False
    for period, row in frame.iterrows():
        up_30 = _revision_value(
            row,
            ("up last 30 days", "up_30d", "up30d"),
        )
        down_30 = _revision_value(
            row,
            ("down last 30 days", "down_30d", "down30d"),
        )
        up_7 = _revision_value(
            row,
            ("up last 7 days", "up_7d", "up7d"),
        )
        down_7 = _revision_value(
            row,
            ("down last 7 days", "down_7d", "down7d"),
        )
        denominator = (up_30 or 0) + (down_30 or 0)
        breadth = (
            ((up_30 or 0) - (down_30 or 0)) / denominator * 100
            if denominator
            else None
        )
        rows.append(
            {
                "ticker": ticker,
                "metric": "eps",
                "record_type": "revision_breadth",
                "period": str(period),
                "up_7d": up_7,
                "down_7d": down_7,
                "up_30d": up_30,
                "down_30d": down_30,
                "revision_breadth_30d_pct": breadth,
                "source": "yfinance",
                "fetched_at": now,
            }
        )
        added = True
    return added


def _append_estimate_levels(
    ticker: str,
    metric: str,
    frame: Any,
    now: str,
    rows: list[dict],
) -> bool:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return False
    for period, row in frame.iterrows():
        growth = _number(row.get("growth"))
        rows.append(
            {
                "ticker": ticker,
                "metric": metric,
                "record_type": "estimate_level",
                "period": str(period),
                "current": _number(row.get("avg")),
                "low": _number(row.get("low")),
                "high": _number(row.get("high")),
                "estimate_growth_pct": None
                if growth is None
                else growth * 100
                if abs(growth) <= 2
                else growth,
                "source": "yfinance",
                "fetched_at": now,
            }
        )
    return True


def refresh_external_data(
    tickers: list[str],
    root: Path,
    *,
    ttl_hours: float = 20.0,
    max_tickers: int = 120,
) -> dict:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat().replace("+00:00", "Z")
    requested = sorted(
        {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    )
    fresh = _fresh_tickers(root, ttl_hours, now_dt)
    pending = [ticker for ticker in requested if ticker not in fresh][:max_tickers]
    rows = {key: [] for key in FILES}
    coverage_rows = []

    for ticker in pending:
        coverage = {key: False for key in FILES}
        status = "ok"
        errors: list[str] = []
        try:
            obj = yf.Ticker(ticker)

            try:
                dates = _calendar_dates(obj.calendar)
                for event_date in dates:
                    rows["earnings"].append(
                        {
                            "ticker": ticker,
                            "event_date": event_date,
                            "source": "yfinance",
                            "fetched_at": now,
                        }
                    )
                coverage["earnings"] = bool(dates)
            except Exception as exc:
                errors.append(f"calendar:{type(exc).__name__}")

            try:
                explicit_revisions = _append_eps_revisions(
                    ticker,
                    getattr(obj, "eps_revisions", None),
                    now,
                    rows["revisions"],
                )
                estimate_rows = False
                for metric, frame in (
                    ("eps", getattr(obj, "earnings_estimate", None)),
                    ("revenue", getattr(obj, "revenue_estimate", None)),
                ):
                    estimate_rows |= _append_estimate_levels(
                        ticker,
                        metric,
                        frame,
                        now,
                        rows["revisions"],
                    )
                coverage["revisions"] = explicit_revisions or estimate_rows
            except Exception as exc:
                errors.append(f"revisions:{type(exc).__name__}")

            try:
                ticker_news = obj.news or []
                for item in ticker_news:
                    content = item.get("content") or item
                    title = str(content.get("title") or "")
                    summary = str(
                        content.get("summary")
                        or content.get("description")
                        or ""
                    )
                    text = (title + " " + summary).lower()
                    event_type = (
                        "M&A"
                        if any(
                            token in text
                            for token in (
                                "acquire",
                                "acquisition",
                                "merger",
                                "buyout",
                            )
                        )
                        else "CONTRACT"
                        if any(
                            token in text
                            for token in (
                                "contract",
                                "award",
                                "order",
                                "partnership",
                            )
                        )
                        else "GUIDANCE"
                        if any(
                            token in text
                            for token in ("guidance", "outlook", "forecast")
                        )
                        else "NEWS"
                    )
                    published = (
                        content.get("pubDate")
                        or content.get("providerPublishTime")
                    )
                    rows["news"].append(
                        {
                            "ticker": ticker,
                            "published_at": published,
                            "headline": title,
                            "summary": summary,
                            "event_type": event_type,
                            "source": "yfinance",
                            "fetched_at": now,
                        }
                    )
                    if event_type == "GUIDANCE":
                        rows["guidance"].append(
                            {
                                "ticker": ticker,
                                "published_at": published,
                                "direction": "UNKNOWN",
                                "text": title,
                                "source": "yfinance",
                                "fetched_at": now,
                            }
                        )
                coverage["news"] = bool(ticker_news)
                coverage["guidance"] = any(
                    row["ticker"] == ticker for row in rows["guidance"]
                )
            except Exception as exc:
                errors.append(f"news:{type(exc).__name__}")

            try:
                insider = getattr(obj, "insider_transactions", None)
                if isinstance(insider, pd.DataFrame) and not insider.empty:
                    for _, row in insider.head(100).iterrows():
                        rows["insider"].append(
                            {
                                "ticker": ticker,
                                "filed_at": row.get("Start Date"),
                                "insider": row.get("Insider"),
                                "transaction": row.get("Transaction"),
                                "shares": row.get("Shares"),
                                "value": row.get("Value"),
                                "source": "yfinance",
                                "fetched_at": now,
                            }
                        )
                    coverage["insider"] = True
            except Exception as exc:
                errors.append(f"insider:{type(exc).__name__}")

            try:
                holders = getattr(obj, "institutional_holders", None)
                if isinstance(holders, pd.DataFrame) and not holders.empty:
                    for _, row in holders.iterrows():
                        rows["13f"].append(
                            {
                                "ticker": ticker,
                                "holder": row.get("Holder"),
                                "shares": row.get("Shares"),
                                "date_reported": row.get("Date Reported"),
                                "pct_out": row.get("% Out"),
                                "value": row.get("Value"),
                                "source": "yfinance",
                                "fetched_at": now,
                            }
                        )
                    coverage["13f"] = True
            except Exception as exc:
                errors.append(f"13f:{type(exc).__name__}")
        except Exception as exc:
            errors.append(f"ticker:{type(exc).__name__}")

        if errors and any(coverage.values()):
            status = "partial"
        elif errors:
            status = "error"
        coverage_rows.append(
            {
                "ticker": ticker,
                **coverage,
                "status": status,
                "error": ";".join(errors)[:500],
                "fetched_at": now,
            }
        )

    for key, filename in FILES.items():
        new = pd.DataFrame(rows[key])
        replace = (
            set(new["ticker"].astype(str).str.upper())
            if not new.empty
            else set()
        )
        _write(
            _merge_rows(_read(root / filename), new, replace),
            root / filename,
        )
    _write(
        _merge_rows(
            _read(root / "provider_coverage.csv"),
            pd.DataFrame(coverage_rows),
            set(pending),
        ),
        root / "provider_coverage.csv",
    )
    return {
        "provider": "yfinance",
        "policy_version": PROVIDER_POLICY_VERSION,
        "requested": len(requested),
        "fresh_skipped": len(fresh.intersection(requested)),
        "attempted": len(pending),
        "remaining": max(
            0,
            len(requested)
            - len(fresh.intersection(requested))
            - len(pending),
        ),
        "succeeded": sum(row["status"] == "ok" for row in coverage_rows),
        "partial": sum(row["status"] == "partial" for row in coverage_rows),
        "failed": sum(row["status"] == "error" for row in coverage_rows),
        "fetched_at": now,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--root", default="data/external")
    parser.add_argument("--ttl-hours", type=float, default=20.0)
    parser.add_argument("--max-tickers", type=int, default=120)
    args = parser.parse_args()
    frame = pd.read_csv(args.universe)
    column = next(
        column
        for column in frame.columns
        if str(column).lower() in {"ticker", "symbol", "ティッカー", "シンボル"}
    )
    print(
        refresh_external_data(
            frame[column].dropna().astype(str).str.upper().tolist(),
            Path(args.root),
            ttl_hours=args.ttl_hours,
            max_tickers=args.max_tickers,
        )
    )


if __name__ == "__main__":
    main()
