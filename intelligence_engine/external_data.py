from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

EXTERNAL_DATA_POLICY_VERSION = "1.1.0"


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = (
                    payload.get("records")
                    or payload.get("data")
                    or payload.get("items")
                    or []
                )
            return pd.DataFrame(payload)
        return pd.read_csv(path)
    except (OSError, json.JSONDecodeError, pd.errors.ParserError):
        return pd.DataFrame()


def _norm_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    cols = {str(c).strip().lower(): c for c in frame.columns}
    source = next(
        (
            cols[name]
            for name in ("ticker", "symbol", "ティッカー", "シンボル")
            if name in cols
        ),
        None,
    )
    if source is None:
        return pd.DataFrame()
    out = frame.rename(columns={source: "ticker"}).copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    return out[out["ticker"].ne("") & out["ticker"].ne("NAN")]


def _latest_by_ticker(
    frame: pd.DataFrame,
    date_names: tuple[str, ...],
) -> dict[str, dict]:
    frame = _norm_ticker(frame)
    if frame.empty:
        return {}
    cols = {str(c).strip().lower(): c for c in frame.columns}
    date_col = next((cols[name] for name in date_names if name in cols), None)
    if date_col is not None:
        frame["_date"] = pd.to_datetime(frame[date_col], utc=True, errors="coerce")
        frame = frame.sort_values(["ticker", "_date"])
    return {
        str(ticker): group.iloc[-1].drop(labels=["_date"], errors="ignore").to_dict()
        for ticker, group in frame.groupby("ticker")
    }


def _num(value):
    converted = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(converted) else float(converted)


def _first_num(mapping: dict[str, Any], names: tuple[str, ...]):
    for name in names:
        if name in mapping:
            value = _num(mapping.get(name))
            if value is not None:
                return value
    return None


def _revision_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    frame = _norm_ticker(frame)
    if frame.empty:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for ticker, group in frame.groupby("ticker"):
        work = group.copy()
        date_col = next(
            (
                col
                for col in work.columns
                if str(col).strip().lower()
                in {"asof", "date", "updated_at", "fetched_at"}
            ),
            None,
        )
        if date_col is not None:
            work["_date"] = pd.to_datetime(work[date_col], utc=True, errors="coerce")
            work = work.sort_values("_date")
        record: dict[str, Any] = {}
        for _, row in work.iterrows():
            raw = row.drop(labels=["_date"], errors="ignore").to_dict()
            metric = str(raw.get("metric") or "").lower()
            explicit_eps = _first_num(
                raw,
                (
                    "eps_revision_30d_pct",
                    "eps_revision_pct",
                    "revision_pct",
                    "revision_breadth_30d_pct",
                ),
            )
            explicit_revenue = _first_num(
                raw,
                (
                    "revenue_revision_30d_pct",
                    "revenue_revision_pct",
                ),
            )
            if metric == "eps" and explicit_eps is not None:
                record["eps_revision_30d_pct"] = explicit_eps
            elif metric == "revenue" and explicit_revenue is not None:
                record["revenue_revision_30d_pct"] = explicit_revenue
            else:
                if explicit_eps is not None:
                    record["eps_revision_30d_pct"] = explicit_eps
                if explicit_revenue is not None:
                    record["revenue_revision_30d_pct"] = explicit_revenue

            growth = _first_num(raw, ("estimate_growth_pct", "growth"))
            if growth is not None and metric in {"eps", "revenue"}:
                record[f"{metric}_estimate_growth_pct"] = growth

            for key in ("period", "source", "fetched_at"):
                if raw.get(key) is not None and not pd.isna(raw.get(key)):
                    record[key] = raw.get(key)
        result[str(ticker)] = record
    return result


def load_external_layer(root: Path) -> dict[str, Any]:
    root = Path(root)
    earnings = _latest_by_ticker(
        _read_table(root / "earnings_calendar.csv"),
        ("earnings_date", "event_date", "date", "report_date", "fetched_at"),
    )
    revisions = _revision_by_ticker(_read_table(root / "estimate_revisions.csv"))
    guidance = _latest_by_ticker(
        _read_table(root / "guidance.csv"),
        ("date", "published_at", "asof", "issued_at", "fetched_at"),
    )
    news = _norm_ticker(_read_table(root / "news.csv"))
    insider = _latest_by_ticker(
        _read_table(root / "insider.csv"),
        ("transaction_date", "date", "filed_at", "fetched_at"),
    )
    holdings_13f = _norm_ticker(_read_table(root / "holdings_13f.csv"))
    return {
        "earnings": earnings,
        "revisions": revisions,
        "guidance": guidance,
        "news": news,
        "insider": insider,
        "holdings_13f": holdings_13f,
    }


def build_external_records(
    tickers: list[str],
    layer: dict[str, Any],
    today: pd.Timestamp | None = None,
) -> list[dict]:
    today = (today or pd.Timestamp.utcnow()).tz_localize(None).normalize()
    news = (
        layer.get("news")
        if isinstance(layer.get("news"), pd.DataFrame)
        else pd.DataFrame()
    )
    holdings = (
        layer.get("holdings_13f")
        if isinstance(layer.get("holdings_13f"), pd.DataFrame)
        else pd.DataFrame()
    )
    records = []
    for ticker in tickers:
        earnings = (layer.get("earnings") or {}).get(ticker, {})
        revisions = (layer.get("revisions") or {}).get(ticker, {})
        guidance = (layer.get("guidance") or {}).get(ticker, {})
        insider = (layer.get("insider") or {}).get(ticker, {})

        earnings_date = pd.to_datetime(
            earnings.get("earnings_date")
            or earnings.get("event_date")
            or earnings.get("date")
            or earnings.get("report_date"),
            errors="coerce",
        )
        days_to = (
            int((earnings_date.normalize() - today).days)
            if pd.notna(earnings_date)
            else None
        )
        eps_revision = _first_num(
            revisions,
            (
                "eps_revision_30d_pct",
                "eps_revision_pct",
                "revision_pct",
                "revision_breadth_30d_pct",
            ),
        )
        revenue_revision = _first_num(
            revisions,
            ("revenue_revision_30d_pct", "revenue_revision_pct"),
        )
        guidance_direction = str(
            guidance.get("direction")
            or guidance.get("guidance_direction")
            or "UNKNOWN"
        ).upper()

        news_rows = (
            news[news["ticker"].eq(ticker)]
            if not news.empty and "ticker" in news
            else pd.DataFrame()
        )
        if not news_rows.empty:
            date_col = next(
                (
                    column
                    for column in news_rows.columns
                    if str(column).lower()
                    in {"date", "published_at", "timestamp", "fetched_at"}
                ),
                None,
            )
            if date_col is not None:
                news_rows = news_rows.assign(
                    _date=pd.to_datetime(
                        news_rows[date_col],
                        utc=True,
                        errors="coerce",
                    )
                ).sort_values("_date", ascending=False)
            news_rows = news_rows.head(10)

        event_types = []
        for _, row in news_rows.iterrows():
            declared = str(row.get("event_type") or "").upper()
            if declared in {"M&A", "CONTRACT", "GUIDANCE", "NEWS"}:
                event_types.append(declared)
                continue
            text = " ".join(str(row.get(column, "")) for column in news_rows.columns).lower()
            if any(keyword in text for keyword in ("merger", "acquisition", "acquire", "m&a")):
                event_types.append("M&A")
            elif any(keyword in text for keyword in ("contract", "award", "order", "deal")):
                event_types.append("CONTRACT")
            elif any(keyword in text for keyword in ("guidance", "outlook", "forecast")):
                event_types.append("GUIDANCE")
            else:
                event_types.append("NEWS")

        holder_rows = (
            holdings[holdings["ticker"].eq(ticker)]
            if not holdings.empty and "ticker" in holdings
            else pd.DataFrame()
        )
        holder_col = next(
            (column for column in ("manager", "holder") if column in holder_rows.columns),
            None,
        )
        institutional_holders = (
            int(holder_rows[holder_col].nunique())
            if not holder_rows.empty and holder_col is not None
            else int(len(holder_rows))
        )
        ownership_change = (
            _num(holder_rows["position_change_pct"].median())
            if not holder_rows.empty and "position_change_pct" in holder_rows
            else None
        )

        insider_type = str(
            insider.get("transaction_type")
            or insider.get("transaction")
            or insider.get("type")
            or "UNKNOWN"
        ).upper()
        insider_value = _first_num(
            insider,
            ("transaction_value", "value"),
        )

        warnings = []
        positives = []
        if days_to is not None and -3 <= days_to <= 3:
            warnings.append("earnings_window")
        if eps_revision is not None and eps_revision <= -3:
            warnings.append("eps_revisions_down")
        if guidance_direction in {"DOWN", "LOWERED", "NEGATIVE"}:
            warnings.append("guidance_cut")
        if (
            insider_type in {"SALE", "SELL"}
            and insider_value is not None
            and insider_value >= 1_000_000
        ):
            warnings.append("large_insider_sale")
        if eps_revision is not None and eps_revision >= 3:
            positives.append("eps_revisions_up")
        if revenue_revision is not None and revenue_revision >= 2:
            positives.append("revenue_revisions_up")
        if guidance_direction in {"UP", "RAISED", "POSITIVE"}:
            positives.append("guidance_raised")
        if insider_type in {"PURCHASE", "BUY"}:
            positives.append("insider_buy")

        event_types = sorted(set(event_types))
        earnings_iso = (
            earnings_date.date().isoformat() if pd.notna(earnings_date) else None
        )
        records.append(
            {
                "ticker": ticker,
                "earnings_date": earnings_iso,
                "next_earnings_date": earnings_iso,
                "days_to_earnings": days_to,
                "earnings_window": "earnings_window" in warnings,
                "eps_revision_30d_pct": eps_revision,
                "revenue_revision_30d_pct": revenue_revision,
                "eps_estimate_growth_pct": _num(
                    revisions.get("eps_estimate_growth_pct")
                ),
                "revenue_estimate_growth_pct": _num(
                    revisions.get("revenue_estimate_growth_pct")
                ),
                "guidance_direction": guidance_direction,
                "guidance": guidance_direction,
                "news_count": int(len(news_rows)),
                "event_types": event_types,
                "event_type": event_types[0] if event_types else None,
                "insider_transaction_type": insider_type,
                "insider_signal": insider_type,
                "insider_transaction_value": insider_value,
                "institutional_holder_count": institutional_holders,
                "institutional_position_change_pct": ownership_change,
                "warnings": warnings,
                "positives": positives,
                "coverage": {
                    "earnings": bool(earnings),
                    "revisions": bool(revisions),
                    "guidance": bool(guidance),
                    "news": not news_rows.empty,
                    "insider": bool(insider),
                    "holdings_13f": not holder_rows.empty,
                },
            }
        )
    return records


def apply_external_context(
    candidates: list[dict],
    records: list[dict],
) -> list[dict]:
    lookup = {record["ticker"]: record for record in records}
    output = []
    for item in candidates:
        record = dict(item)
        external = lookup.get(record.get("ticker"), {})
        record["external_data"] = external
        record["earnings_window"] = bool(external.get("earnings_window"))
        record["warnings"] = list(
            dict.fromkeys(
                list(record.get("warnings") or [])
                + list(external.get("warnings") or [])
            )
        )
        if "earnings_window" in record["warnings"]:
            record["actionable"] = False
        output.append(record)
    return output
