from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .research_contracts import FactObservation

US_GAAP_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "debt": ("LongTermDebt", "LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent"),
}
IFRS_TAGS = {
    "revenue": ("Revenue",),
    "eps": ("DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("ProfitLossFromOperatingActivities", "OperatingProfitLoss"),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
    "capex": ("PurchaseOfPropertyPlantAndEquipment",),
    "shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "cash": ("CashAndCashEquivalents",),
    "debt": ("NoncurrentBorrowings", "CurrentBorrowings"),
}


@dataclass(frozen=True)
class _Point:
    metric: str
    start: date | None
    end: date
    value: float
    form: str
    filed: date | None
    accession: str | None
    frame: str | None
    derived: bool = False

    @property
    def duration(self) -> int | None:
        return (self.end - self.start).days if self.start else None


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _namespace(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any], dict[str, tuple[str, ...]]]:
    facts = payload.get("facts") or {}
    if "us-gaap" in facts:
        return "us-gaap", facts["us-gaap"], US_GAAP_TAGS
    if "ifrs-full" in facts:
        return "ifrs-full", facts["ifrs-full"], IFRS_TAGS
    return None, {}, {}


def _unit_rows(node: dict[str, Any]) -> list[dict[str, Any]]:
    units = node.get("units") or {}
    for name in ("USD", "USD/shares", "shares"):
        if name in units:
            return list(units[name] or [])
    return list(next(iter(units.values()), []) or [])


def _raw_points(namespace: dict[str, Any], metric: str, tags: Iterable[str]) -> list[_Point]:
    """Treat taxonomy tags as ordered alternatives, never additive duplicates."""
    for tag in tags:
        points: list[_Point] = []
        for row in _unit_rows(namespace.get(tag) or {}):
            try:
                value = float(row["val"])
            except (KeyError, TypeError, ValueError):
                continue
            end = _to_date(row.get("end"))
            if end is None or not np.isfinite(value):
                continue
            points.append(
                _Point(
                    metric,
                    _to_date(row.get("start")),
                    end,
                    value,
                    str(row.get("form") or ""),
                    _to_date(row.get("filed")),
                    row.get("accn"),
                    row.get("frame"),
                )
            )
        if not points:
            continue
        dedup: dict[tuple[Any, ...], _Point] = {}
        for point in sorted(points, key=lambda p: (p.filed or date.min, p.end, p.accession or "")):
            dedup[(point.start, point.end, point.form)] = point
        return list(dedup.values())
    return []


def _quarterize(points: list[_Point], *, allow_derived: bool = True) -> list[_Point]:
    valid = [
        point
        for point in points
        if point.form in {"10-Q", "10-K", "20-F", "6-K"}
        and point.start is not None
        and point.duration is not None
    ]
    direct = [point for point in valid if 70 <= int(point.duration or 0) <= 120]
    cumulative = [point for point in valid if 150 <= int(point.duration or 0) <= 380] if allow_derived else []

    selected: dict[date, _Point] = {}
    for point in sorted(direct, key=lambda p: (p.end, p.filed or date.min)):
        selected[point.end] = point

    by_start: dict[date, list[_Point]] = {}
    for point in cumulative:
        by_start.setdefault(point.start or point.end, []).append(point)
    for start, group in by_start.items():
        prior: _Point | None = None
        for cumulative_point in sorted(group, key=lambda p: (p.end, p.filed or date.min)):
            if cumulative_point.end in selected:
                prior = cumulative_point
                continue
            base = prior
            if base is None:
                candidates = [
                    point
                    for point in direct
                    if point.start == start and point.end < cumulative_point.end
                ]
                base = max(candidates, key=lambda p: p.end) if candidates else None
            if base is not None:
                derived = _Point(
                    metric=cumulative_point.metric,
                    start=base.end,
                    end=cumulative_point.end,
                    value=cumulative_point.value - base.value,
                    form=cumulative_point.form,
                    filed=cumulative_point.filed,
                    accession=cumulative_point.accession,
                    frame=cumulative_point.frame,
                    derived=True,
                )
                if 55 <= int(derived.duration or 0) <= 130:
                    selected[derived.end] = derived
            prior = cumulative_point
    return sorted(selected.values(), key=lambda point: (point.end, point.filed or date.min))


def _instant_points(points: list[_Point]) -> list[_Point]:
    selected: dict[date, _Point] = {}
    for point in sorted(points, key=lambda p: (p.end, p.filed or date.min)):
        selected[point.end] = point
    return sorted(selected.values(), key=lambda p: (p.end, p.filed or date.min))


def extract_companyfacts_history(payload: dict[str, Any], ticker: str | None = None) -> pd.DataFrame:
    standard, namespace, tags = _namespace(payload)
    if standard is None:
        return pd.DataFrame()
    symbol = str(ticker or payload.get("entityName") or "").upper().strip()
    observations: list[dict[str, Any]] = []
    instant = {"cash", "debt"}
    for metric, metric_tags in tags.items():
        raw = _raw_points(namespace, metric, metric_tags)
        points = (
            _instant_points(raw)
            if metric in instant
            else _quarterize(raw, allow_derived=metric not in {"eps", "shares"})
        )
        for point in points:
            if point.filed is None:
                continue
            observation = FactObservation(
                ticker=symbol,
                metric=metric,
                value=point.value,
                period_start=point.start.isoformat() if point.start else None,
                period_end=point.end.isoformat(),
                filed_at=point.filed.isoformat(),
                available_at=point.filed.isoformat(),
                form=point.form,
                accession=point.accession,
                accounting_standard=standard,
                derived_quarter=point.derived,
                confidence=0.9 if point.derived else 1.0,
            )
            observations.append(observation.to_dict())
    frame = pd.DataFrame(observations)
    if frame.empty:
        return frame
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame = frame.dropna(subset=["available_at", "period_end", "metric", "value"])
    return frame.sort_values(["ticker", "available_at", "period_end", "metric"]).reset_index(drop=True)


def _metric_series(available: pd.DataFrame, metric: str) -> pd.Series:
    subset = available[available["metric"] == metric]
    if subset.empty:
        return pd.Series(dtype=float)
    subset = subset.sort_values(["period_end", "available_at"]).drop_duplicates("period_end", keep="last")
    return pd.Series(
        pd.to_numeric(subset["value"], errors="coerce").to_numpy(),
        index=pd.DatetimeIndex(subset["period_end"]),
    )


def _growth(series: pd.Series) -> tuple[float | None, float | None, float | None, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        return None, None, None, None
    latest = float(clean.iloc[-1])
    yoy = prev_yoy = acceleration = None
    if len(clean) >= 5 and clean.iloc[-5] != 0:
        yoy = latest / float(clean.iloc[-5]) - 1.0
    if len(clean) >= 6 and clean.iloc[-6] != 0:
        prev_yoy = float(clean.iloc[-2]) / float(clean.iloc[-6]) - 1.0
    if yoy is not None and prev_yoy is not None:
        acceleration = yoy - prev_yoy
    stability = float(clean.pct_change(4, fill_method=None).tail(4).std()) if len(clean) >= 8 else None
    return latest, yoy, acceleration, stability


def _value_at(series: pd.Series, period: pd.Timestamp) -> float | None:
    if period not in series.index:
        return None
    value = pd.to_numeric(series.loc[period], errors="coerce")
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def _snapshot(available: pd.DataFrame, available_at: pd.Timestamp) -> dict[str, Any]:
    revenue = _metric_series(available, "revenue")
    eps = _metric_series(available, "eps")
    gp = _metric_series(available, "gross_profit")
    op = _metric_series(available, "operating_income")
    ocf = _metric_series(available, "operating_cash_flow")
    capex = _metric_series(available, "capex")
    shares = _metric_series(available, "shares")
    cash = _metric_series(available, "cash")
    debt = _metric_series(available, "debt")

    revenue_value, revenue_yoy, revenue_acceleration, revenue_stability = _growth(revenue)
    eps_value, eps_yoy, eps_acceleration, eps_stability = _growth(eps)
    latest_period = revenue.index[-1] if not revenue.empty else (eps.index[-1] if not eps.empty else None)

    gross_margin = operating_margin = gross_margin_delta = operating_margin_delta = None
    fcf = fcf_yoy = fcf_margin = None
    if latest_period is not None and revenue_value not in (None, 0):
        gp_value = _value_at(gp, latest_period)
        op_value = _value_at(op, latest_period)
        gross_margin = gp_value / revenue_value if gp_value is not None else None
        operating_margin = op_value / revenue_value if op_value is not None else None
        prior_periods = list(revenue.index)
        if len(prior_periods) >= 5:
            prior_period = prior_periods[-5]
            prior_revenue = _value_at(revenue, prior_period)
            if prior_revenue not in (None, 0):
                prior_gp = _value_at(gp, prior_period)
                prior_op = _value_at(op, prior_period)
                if gross_margin is not None and prior_gp is not None:
                    gross_margin_delta = gross_margin - prior_gp / prior_revenue
                if operating_margin is not None and prior_op is not None:
                    operating_margin_delta = operating_margin - prior_op / prior_revenue
        ocf_value = _value_at(ocf, latest_period)
        capex_value = _value_at(capex, latest_period) or 0.0
        if ocf_value is not None:
            fcf = ocf_value - abs(capex_value)
            fcf_margin = fcf / revenue_value
            fcf_series = ocf.copy()
            if not fcf_series.empty:
                aligned_capex = capex.reindex(fcf_series.index).fillna(0.0).abs()
                fcf_series = fcf_series - aligned_capex
                _, fcf_yoy, _, _ = _growth(fcf_series)

    shares_yoy = None
    if len(shares) >= 5 and shares.iloc[-5] != 0:
        shares_yoy = float(shares.iloc[-1] / shares.iloc[-5] - 1.0)

    latest_cash = float(cash.iloc[-1]) if not cash.empty else None
    latest_debt = float(debt.iloc[-1]) if not debt.empty else None
    net_cash = latest_cash - latest_debt if latest_cash is not None and latest_debt is not None else None

    evidence_values = [
        revenue_yoy,
        revenue_acceleration,
        eps_yoy,
        eps_acceleration,
        gross_margin_delta,
        operating_margin_delta,
        fcf_yoy,
        shares_yoy,
    ]
    evidence_count = sum(value is not None and np.isfinite(value) for value in evidence_values)
    accounting = (
        available["accounting_standard"].dropna().iloc[-1]
        if "accounting_standard" in available and available["accounting_standard"].notna().any()
        else None
    )
    return {
        "available_at": available_at,
        "latest_period_end": latest_period,
        "latest_filing_date": available_at.date().isoformat(),
        "accounting_standard": accounting,
        "revenue": revenue_value,
        "revenue_yoy": revenue_yoy,
        "revenue_acceleration": revenue_acceleration,
        "revenue_growth_stability": revenue_stability,
        "eps": eps_value,
        "eps_yoy": eps_yoy,
        "eps_acceleration": eps_acceleration,
        "eps_growth_stability": eps_stability,
        "gross_margin": gross_margin,
        "gross_margin_delta": gross_margin_delta,
        "operating_margin": operating_margin,
        "operating_margin_delta": operating_margin_delta,
        "free_cash_flow": fcf,
        "free_cash_flow_yoy": fcf_yoy,
        "fcf_margin": fcf_margin,
        "shares_yoy": shares_yoy,
        "cash": latest_cash,
        "debt": latest_debt,
        "net_cash": net_cash,
        "fundamental_evidence_count": evidence_count,
        "fundamental_confidence": evidence_count / len(evidence_values),
    }


def build_financial_snapshots(facts: pd.DataFrame) -> pd.DataFrame:
    if facts is None or facts.empty:
        return pd.DataFrame()
    work = facts.copy()
    work["available_at"] = pd.to_datetime(work["available_at"], errors="coerce")
    work["period_end"] = pd.to_datetime(work["period_end"], errors="coerce")
    work = work.dropna(subset=["ticker", "available_at", "period_end"])
    snapshots: list[dict[str, Any]] = []
    for ticker, ticker_facts in work.groupby("ticker", sort=True):
        for available_at in sorted(ticker_facts["available_at"].unique()):
            available = ticker_facts[ticker_facts["available_at"] <= available_at]
            snapshots.append({"ticker": ticker, **_snapshot(available, pd.Timestamp(available_at))})
    return pd.DataFrame(snapshots).sort_values(["ticker", "available_at"]).reset_index(drop=True)


def merge_financial_snapshots(price_panel: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    if price_panel.empty:
        return price_panel.copy()
    if snapshots is None or snapshots.empty:
        out = price_panel.copy()
        out["fundamental_confidence"] = 0.0
        return out
    left = price_panel.copy()
    left["date"] = pd.to_datetime(left["date"], errors="coerce")
    right = snapshots.copy()
    right["available_at"] = pd.to_datetime(right["available_at"], errors="coerce")
    pieces: list[pd.DataFrame] = []
    for ticker, group in left.groupby("ticker", sort=False):
        history = right[right["ticker"] == ticker].drop(columns=["ticker"], errors="ignore")
        if history.empty:
            enriched = group.copy()
            enriched["fundamental_confidence"] = 0.0
        else:
            enriched = pd.merge_asof(
                group.sort_values("date"),
                history.sort_values("available_at"),
                left_on="date",
                right_on="available_at",
                direction="backward",
                allow_exact_matches=True,
            )
        pieces.append(enriched)
    return pd.concat(pieces, ignore_index=True) if pieces else left
