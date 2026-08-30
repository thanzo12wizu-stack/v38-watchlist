"""Audited V38 production state transitions (2026-08-30).

This module is intentionally independent from the legacy dashboard.  Signals
use completed closes and every order is scheduled for the next session open.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

NORMAL_TQQQ_WEIGHT = 0.30
PANIC_TQQQ_WEIGHT = 0.80
NORMAL_STOCK_BUDGET = 0.70
PANIC_RESET_WEIGHT = 0.029
PANIC_RESET_MAX_POSITIONS = 4
PANIC_RESET_MAX_THEME_POSITIONS = 2
NORMAL_STOCK_MAX_POSITIONS = 12
SELECTIVE_NEW_ENTRY_LIMIT = 4
GROSS_EXPOSURE_LIMIT = 1.0


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
    """Selective's four is an entry ceiling, never a trim target."""
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
    """Evaluate one completed daily close; returned action executes next open."""
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
        return replace(current, partial_taken=True, remaining_fraction=0.75,
                       pending_action="PARTIAL25_NEXT_OPEN", pending_fraction=0.25)
    return current


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


def capped_tqqq_target(panic_active: bool, other_gross: float) -> float:
    """Enforce gross<=100% without inventing an unverified trim priority."""
    desired = PANIC_TQQQ_WEIGHT if panic_active else NORMAL_TQQQ_WEIGHT
    return max(0.0, min(desired, GROSS_EXPOSURE_LIMIT - max(0.0, float(other_gross))))
