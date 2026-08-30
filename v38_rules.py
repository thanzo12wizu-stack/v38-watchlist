"""Audited V38 production state transitions (2026-08-30).

This module is intentionally independent from the legacy dashboard.  Signals
use completed closes and every order is scheduled for the next session open.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

CURRENT30_NORMAL_EXPOSURE = 0.30
PANIC_TQQQ_FLOOR = 0.80
PANIC_TQQQ_CANDIDATE = "M30_TOUCH30_F80_D10"
NORMAL_STOCK_BUDGET = 0.70
PANIC_RESET_WEIGHT = 0.029
PANIC_RESET_MAX_POSITIONS = 4
PANIC_RESET_MAX_THEME_POSITIONS = 2
NORMAL_STOCK_MAX_POSITIONS = 12
SELECTIVE_NEW_ENTRY_LIMIT = 4
GROSS_EXPOSURE_LIMIT = 1.0
CLINICAL_BIOTECH_INDUSTRIES = frozenset({"Biotechnology", "Pharmaceuticals: Other"})
CLINICAL_BIOTECH_MAX_MARKET_CAP = 10_000_000_000.0
CLINICAL_BIOTECH_MAX_REVENUE_TTM = 50_000_000.0


@dataclass(frozen=True)
class MarketMode:
    name: str
    new_entry_limit: int
    reason: str
    force_exit_next_open: bool = False


def market_mode(nqsar: Optional[str], breadth50: Optional[float], coverage_ok: bool = True) -> MarketMode:
    """Resolve normal-stock mode; breadth accepts either 0..1 or 0..100."""
    color = str(nqsar or "").strip().title()
    if color == "Red":
        return MarketMode("DEFENSE", 0, "NQSAR RED", True)
    if color == "Yellow":
        return MarketMode("STOP", 0, "NQSAR YELLOW")
    if color not in {"Blue", "Green"}:
        return MarketMode("STOP", 0, "NQSAR UNKNOWN")
    if not coverage_ok or breadth50 is None:
        return MarketMode("STOP", 0, f"NQSAR {color.upper()} / Breadth DATA INCOMPLETE")
    breadth = float(breadth50)
    if breadth <= 1.5:
        breadth *= 100.0
    if breadth >= 60:
        return MarketMode("ATTACK", 12, f"NQSAR {color.upper()} / Breadth {breadth:.1f}%")
    if breadth >= 50:
        return MarketMode("SELECTIVE", 4, f"NQSAR {color.upper()} / Breadth {breadth:.1f}%")
    return MarketMode("STOP", 0, f"NQSAR {color.upper()} / Breadth {breadth:.1f}%")


def new_entry_capacity(mode: MarketMode, existing_positions: int) -> int:
    """Return additions allowed before the sleeve reaches the mode's total cap.

    In SELECTIVE, four is the maximum total normal-stock count reachable by
    new entries.  Holdings above four are not trimmed, but no stock can be
    added until ordinary exits reduce the count below four.
    """
    return max(0, mode.new_entry_limit - max(0, int(existing_positions)))


@dataclass(frozen=True)
class NormalPosition:
    entry: float
    peak_close: float
    partial_taken: bool = False
    remaining_fraction: float = 1.0
    pending_action: Optional[str] = None
    pending_fraction: float = 0.0

    @property
    def initial_stop(self) -> float:
        return self.entry * 0.92

    @property
    def peak30_stop(self) -> float:
        return self.peak_close * 0.70

    @property
    def final_stop(self) -> float:
        return max(self.initial_stop, self.peak30_stop)


def evaluate_normal_close(position: NormalPosition, close: float, nqsar: Optional[str] = None) -> NormalPosition:
    """Evaluate one completed daily close and schedule, but do not execute, an order.

    Peak is updated only from ``close``.  Entry and Peak Close are never reset
    after a partial sale.  The caller must apply a pending order at the next
    session open with :func:`apply_pending_at_open`.
    """
    price = float(close)
    peak = max(float(position.peak_close), price)
    current = replace(position, peak_close=peak, pending_action=None, pending_fraction=0.0)
    if str(nqsar or "").strip().title() == "Red":
        return replace(current, pending_action="EXIT_NQSAR_RED_NEXT_OPEN",
                       pending_fraction=current.remaining_fraction)
    stop = max(current.entry * 0.92, peak * 0.70)
    if price <= stop:
        reason = ("INITIAL_STOP_NEXT_OPEN" if current.entry * 0.92 >= peak * 0.70
                  else "PEAK30_STOP_NEXT_OPEN")
        return replace(current, pending_action=reason,
                       pending_fraction=current.remaining_fraction)
    if not current.partial_taken and price >= current.entry * 1.24:
        return replace(current, pending_action="PARTIAL25_NEXT_OPEN", pending_fraction=0.25)
    return current


def apply_pending_at_open(position: NormalPosition) -> NormalPosition:
    """Apply the order scheduled by the prior close without resetting Entry/Peak."""
    if position.pending_action == "PARTIAL25_NEXT_OPEN":
        return replace(position, partial_taken=True, remaining_fraction=0.75,
                       pending_action=None, pending_fraction=0.0)
    if position.pending_action in {
        "INITIAL_STOP_NEXT_OPEN", "PEAK30_STOP_NEXT_OPEN", "EXIT_NQSAR_RED_NEXT_OPEN"
    }:
        return replace(position, remaining_fraction=0.0,
                       pending_action=None, pending_fraction=0.0)
    return position


def peer_theme_score(theme_rs63_pct: float, acceleration_pct: float,
                     breadth21_pct: float) -> float:
    """Equal-weight Full3 score; every input must already be peer-only LOO."""
    values = [float(theme_rs63_pct), float(acceleration_pct), float(breadth21_pct)]
    if not all(0.0 <= value <= 100.0 for value in values):
        raise ValueError("peer theme components must be percentiles/percent in [0, 100]")
    return sum(values) / 3.0


def select_peer_theme(theme_scores: dict[str, Optional[float]]) -> tuple[Optional[str], Optional[float]]:
    """Use the highest valid LOO score across memberships; missing stays missing."""
    valid = {str(name): float(score) for name, score in theme_scores.items()
             if score is not None and 0.0 <= float(score) <= 100.0}
    if not valid:
        return None, None
    name = max(valid, key=valid.get)
    return name, valid[name]


def attack_rank_score(stock_rs189: float, selected_peer_score: Optional[float]) -> float:
    """Attack score. Research code uses neutral 50 when no valid Theme exists."""
    peer = 50.0 if selected_peer_score is None else float(selected_peer_score)
    return 0.70 * float(stock_rs189) + 0.30 * peer


@dataclass(frozen=True)
class ClinicalBiotechDecision:
    excluded: bool
    revenue_missing_fail_open: bool
    reason: str


def clinical_biotech_exclusion(industry: Optional[str], market_cap: Optional[float],
                               revenue_ttm: Optional[float]) -> ClinicalBiotechDecision:
    """Apply the audited structural Clinical Biotech exclusion.

    A legacy Theme label is deliberately not accepted. Revenue missing is a
    fail-open condition, so it is visible in the decision but never excludes.
    """
    industry_name = str(industry or "").strip()
    if industry_name not in CLINICAL_BIOTECH_INDUSTRIES:
        return ClinicalBiotechDecision(False, False, "INDUSTRY_NOT_TARGETED")
    try:
        cap = float(market_cap)
    except (TypeError, ValueError):
        return ClinicalBiotechDecision(False, False, "MARKET_CAP_DATA_REQUIRED_PASS")
    if cap >= CLINICAL_BIOTECH_MAX_MARKET_CAP:
        return ClinicalBiotechDecision(False, False, "MARKET_CAP_GTE_10B_PASS")
    try:
        revenue = float(revenue_ttm)
    except (TypeError, ValueError):
        return ClinicalBiotechDecision(False, True, "REVENUE_MISSING_FAIL_OPEN")
    if revenue < CLINICAL_BIOTECH_MAX_REVENUE_TTM:
        return ClinicalBiotechDecision(True, False, "STRUCTURAL_CLINICAL_BIOTECH_EXCLUDED")
    return ClinicalBiotechDecision(False, False, "REVENUE_GTE_50M_PASS")


def crash_seed(vix_close: float, qqq_close: float, qqq_sma50: float,
               qqq_atr14: float, qqq_drawdown10: float) -> bool:
    if qqq_atr14 is None or float(qqq_atr14) <= 0:
        return False
    deviation = (float(qqq_close) - float(qqq_sma50)) / float(qqq_atr14)
    return float(vix_close) >= 23 and deviation <= -0.5 and float(qqq_drawdown10) <= -0.02


def tqqq_panic_entry(seed_age_sessions: Optional[int], rsi4h: Optional[float],
                     prior_rsi4h: Optional[float], mc57: Optional[float]) -> bool:
    """Stage56 TOUCH30 F80 gate; the signal executes next session open."""
    if None in (seed_age_sessions, rsi4h, prior_rsi4h, mc57):
        return False
    return (0 <= int(seed_age_sessions) <= 30 and float(prior_rsi4h) > 30
            and float(rsi4h) <= 30 and float(mc57) >= 20)


def tqqq_panic_exit(held_sessions: int, mc57: Optional[float]) -> Optional[str]:
    if mc57 is not None and float(mc57) < 20:
        return "MC57_LT20_NEXT_OPEN"
    if int(held_sessions) >= 10:
        return "MAX10_NEXT_OPEN"
    return None


@dataclass(frozen=True)
class TqqqAllocation:
    underlying_target: float
    requested_target: float
    other_sleeve_exposure: float
    available_capacity: float
    executable_target: float
    shortfall: float


def tqqq_allocation(underlying_target: float, panic_active: bool,
                    other_sleeve_exposure: float) -> TqqqAllocation:
    """Separate Stage56's F80 request from executable exposure under Gross 100%.

    F80 is a floor over the pre-existing CURRENT30 hierarchy, not a fixed 80%
    target.  This function never liquidates another sleeve or invents a capital
    priority; it only reports the capacity-constrained executable amount.
    """
    underlying = min(1.0, max(0.0, float(underlying_target)))
    other = min(1.0, max(0.0, float(other_sleeve_exposure)))
    requested = max(underlying, PANIC_TQQQ_FLOOR) if panic_active else underlying
    available = max(0.0, GROSS_EXPOSURE_LIMIT - other)
    executable = min(requested, available)
    return TqqqAllocation(underlying, requested, other, available, executable,
                          max(0.0, requested - executable))


@dataclass(frozen=True)
class Gross100Allocation:
    reset_desired: float
    tqqq_desired: float
    normal_stock_desired: float
    reset_allocated: float
    tqqq_protected: float
    normal_stock_allocated: float
    tqqq_extra: float
    tqqq_allocated: float
    gross_allocated: float
    remaining_capacity: float


def gross100_allocation(reset_desired: float, tqqq_desired: float,
                        normal_stock_desired: float) -> Gross100Allocation:
    """Gross100 research candidate: Reset -> TQQQ80 -> Normal -> TQQQ extra.

    This is the scalar equivalent of research function
    ``reset_first_tqqq_floor(..., floor=.80)``.  The 80% value is neither a
    TQQQ cap nor a fixed target; it is the amount protected before normal
    stocks only when sleeves compete for Gross100 capacity.
    """
    reset = max(0.0, float(reset_desired))
    tqqq = max(0.0, float(tqqq_desired))
    normal = max(0.0, float(normal_stock_desired))

    reset_alloc = min(reset, GROSS_EXPOSURE_LIMIT)
    remaining = GROSS_EXPOSURE_LIMIT - reset_alloc
    protected = min(tqqq, PANIC_TQQQ_FLOOR, remaining)
    remaining -= protected
    normal_alloc = min(normal, remaining)
    remaining -= normal_alloc
    extra = min(max(tqqq - protected, 0.0), remaining)
    remaining -= extra
    tqqq_alloc = protected + extra
    gross = reset_alloc + normal_alloc + tqqq_alloc
    return Gross100Allocation(
        reset, tqqq, normal, reset_alloc, protected, normal_alloc, extra,
        tqqq_alloc, gross, max(0.0, remaining),
    )
