from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


TRADE_COLUMNS = (
    "trade_id", "ticker", "side", "entry_date", "exit_date", "entry_price", "exit_price",
    "quantity", "point_value", "fx_to_jpy", "fees_jpy", "taxes_jpy", "stop_price",
    "target_price", "setup", "nq_color", "sector", "industry", "theme", "entry_reason",
    "exit_reason", "rule_followed", "mistake_type", "notes", "mfe_pct", "mae_pct",
    "source", "position_id", "closed_quantity", "entry_tranches", "exit_tranches",
    "partial_exit",
)
HOLDING_COLUMNS = (
    "ticker", "quantity", "entry_price", "current_price", "fx_to_jpy", "sector", "industry",
    "theme", "stop_price", "entry_date", "setup", "nq_color", "event_risk",
)
EQUITY_COLUMNS = ("date", "equity_jpy", "cash_jpy", "deposits_jpy", "withdrawals_jpy")
CANDIDATE_COLUMNS = (
    "date", "ticker", "rank", "setup", "nq_color", "sector", "theme", "selected",
    "forward_5d_return", "forward_10d_return", "qqq_excess_10d", "mfe_10d", "mae_10d",
)


@dataclass(frozen=True)
class JournalRules:
    risk_per_trade: float = 0.006
    max_position_fraction: float = 0.08
    max_stop_fraction: float = 0.06
    min_reward_risk: float = 3.0
    max_positions: int = 4
    max_sector_fraction: float = 0.25
    max_theme_fraction: float = 0.20
    earnings_exclusion_sessions: int = 3
    max_extension_atr: float = 3.0
    max_gap_chase_fraction: float = 0.05
    second_tranche_required: bool = True
    yellow_new_entries: bool = False
    red_new_entries: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "JournalRules":
        if not payload:
            return cls()
        aliases: dict[str, tuple[str, ...]] = {
            "risk_per_trade": ("risk_per_trade", "risk_fraction", "trade_risk"),
            "max_position_fraction": ("max_position_fraction", "position_cap", "max_position_pct"),
            "max_stop_fraction": ("max_stop_fraction", "max_stop_pct"),
            "min_reward_risk": ("min_reward_risk", "min_rr", "reward_risk_min"),
            "max_positions": ("max_positions", "max_concurrent_positions"),
            "max_sector_fraction": ("max_sector_fraction", "sector_cap"),
            "max_theme_fraction": ("max_theme_fraction", "theme_cap"),
            "earnings_exclusion_sessions": ("earnings_exclusion_sessions", "earnings_buffer"),
            "max_extension_atr": ("max_extension_atr", "extension_atr_max"),
            "max_gap_chase_fraction": ("max_gap_chase_fraction", "gap_chase_max"),
            "second_tranche_required": ("second_tranche_required", "two_tranche", "split_entry"),
            "yellow_new_entries": ("yellow_new_entries", "allow_yellow_entries"),
            "red_new_entries": ("red_new_entries", "allow_red_entries"),
        }
        values = asdict(cls())
        for field_name, keys in aliases.items():
            for key in keys:
                if key in payload and payload[key] is not None:
                    values[field_name] = payload[key]
                    break
        for key in ("risk_per_trade", "max_position_fraction", "max_stop_fraction", "max_sector_fraction", "max_theme_fraction", "max_gap_chase_fraction"):
            values[key] = _fraction(values[key])
        values["min_reward_risk"] = float(values["min_reward_risk"])
        values["max_extension_atr"] = float(values["max_extension_atr"])
        values["max_positions"] = int(values["max_positions"])
        values["earnings_exclusion_sessions"] = int(values["earnings_exclusion_sessions"])
        values["second_tranche_required"] = _bool(values["second_tranche_required"])
        values["yellow_new_entries"] = _bool(values["yellow_new_entries"])
        values["red_new_entries"] = _bool(values["red_new_entries"])
        return cls(**values)


@dataclass
class JournalInput:
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)
    market_context: pd.DataFrame = field(default_factory=pd.DataFrame)
    account_equity_jpy: float | None = None
    cash_jpy: float | None = None
    nq_color: str | None = None
    rules: JournalRules = field(default_factory=JournalRules)
    price_returns: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_notes: list[str] = field(default_factory=list)


@dataclass
class JournalReport:
    as_of: pd.Timestamp
    account_equity_jpy: float
    cash_jpy: float
    nq_color: str
    trades: pd.DataFrame
    holdings: pd.DataFrame
    equity: pd.DataFrame
    monthly_returns: pd.DataFrame
    setup_analysis: pd.DataFrame
    regime_analysis: pd.DataFrame
    missed_analysis: pd.DataFrame
    candidate_comparison: pd.DataFrame
    rule_violations: pd.DataFrame
    drawdown_episodes: pd.DataFrame
    sector_allocation: pd.DataFrame
    theme_allocation: pd.DataFrame
    correlation: pd.DataFrame
    correlation_pairs: pd.DataFrame
    kpis: dict[str, Any]
    portfolio_risk: dict[str, Any]
    weekly_review: str
    source_notes: list[str]

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.date().isoformat(),
            "account_equity_jpy": self.account_equity_jpy,
            "cash_jpy": self.cash_jpy,
            "nq_color": self.nq_color,
            "kpis": _json_safe(self.kpis),
            "portfolio_risk": _json_safe(self.portfolio_risk),
            "source_notes": self.source_notes,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if pd.isna(value):
        return None
    return value


def _fraction(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number / 100.0 if abs(number) > 1.0 else number


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "followed", "ok", "遵守"}


def _text(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    text = str(value).strip()
    return text if text else default


def _num(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(default)


def _ensure_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        if column not in out:
            out[column] = np.nan
    return out


def _normalise_color(value: Any) -> str:
    text = _text(value, "UNKNOWN").upper()
    aliases = {
        "BLUE": "BLUE", "青": "BLUE", "B": "BLUE",
        "GREEN": "GREEN", "緑": "GREEN", "G": "GREEN",
        "YELLOW": "YELLOW", "黄": "YELLOW", "Y": "YELLOW",
        "RED": "RED", "赤": "RED", "R": "RED",
    }
    return aliases.get(text, text if text in {"BLUE", "GREEN", "YELLOW", "RED"} else "UNKNOWN")
