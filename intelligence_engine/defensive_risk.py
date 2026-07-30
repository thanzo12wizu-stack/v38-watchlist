from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence


class Decision(StrEnum):
    REJECT = "REJECT"
    WATCH = "WATCH"
    FIRST_TRANCHE = "FIRST_TRANCHE"
    NORMAL = "NORMAL"


class MarketState(StrEnum):
    BLUE = "BLUE"
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass(frozen=True)
class RiskPolicy:
    account_equity_jpy: float = 8_000_000.0
    risk_per_trade: float = 0.006
    max_position_fraction: float = 0.08
    max_stop_fraction: float = 0.06
    min_reward_risk: float = 3.0
    earnings_blackout_sessions: int = 3
    max_extension_atr: float = 3.0
    max_gap_chase_fraction: float = 0.05
    min_close_location_on_heavy_volume: float = 0.35
    heavy_volume_ratio: float = 2.0
    max_new_positions_per_day: int = 2
    first_tranche_fraction: float = 0.50
    minimum_actionable_position_fraction: float = 0.01
    market_heat_limits: Mapping[MarketState, float] = field(default_factory=lambda: {
        MarketState.BLUE: 0.024,
        MarketState.GREEN: 0.018,
        MarketState.YELLOW: 0.006,
        MarketState.RED: 0.0,
    })
    market_multipliers: Mapping[MarketState, float] = field(default_factory=lambda: {
        MarketState.BLUE: 1.0,
        MarketState.GREEN: 0.75,
        MarketState.YELLOW: 0.50,
        MarketState.RED: 0.0,
    })
    stage_multipliers: Mapping[str, float] = field(default_factory=lambda: {
        "2A": 1.0, "2B": 1.0,
        "1A": 0.75, "1B": 0.75,
        "2C": 0.50, "3A": 0.50,
        "3B": 0.25,
        "4A": 0.0, "4B": 0.0, "4C": 0.0,
        "NA": 0.50,
    })
    sector_heat_limit: float = 0.012
    theme_heat_limit: float = 0.012
    event_heat_limit: float = 0.006
    allow_event_risk: bool = False


@dataclass(frozen=True)
class Holding:
    ticker: str
    sector: str = "UNKNOWN"
    theme: str = "UNKNOWN"
    market_value_jpy: float = 0.0
    stop_fraction: float = 0.0
    event_risk: bool = False

    @property
    def planned_loss_jpy(self) -> float:
        return max(0.0, float(self.market_value_jpy)) * max(0.0, float(self.stop_fraction))


@dataclass(frozen=True)
class PortfolioHeat:
    total_fraction: float
    sector_fraction: Mapping[str, float]
    theme_fraction: Mapping[str, float]
    event_fraction: float
    gross_fraction: float


@dataclass(frozen=True)
class Candidate:
    ticker: str
    sector: str = "UNKNOWN"
    theme: str = "UNKNOWN"
    market_state: MarketState = MarketState.YELLOW
    market_stage: str = "NA"
    individual_stage: str = "NA"
    setup: str = "WATCH"
    hard_block: bool = False
    stop_fraction: float | None = None
    reward_risk: float | None = None
    days_to_earnings: float | None = None
    extension_atr: float | None = None
    gap_fraction: float | None = None
    consecutive_up_days: float | None = None
    close_location: float | None = None
    volume_ratio: float | None = None
    sector_stage_score: float | None = None
    sector_stage_change_21d: float | None = None
    sector_rs_rank: float | None = None
    alpha_rank: float | None = None
    leadership_quality: float | None = None
    entry_quality: float | None = None
    price: float | None = None
    available_cash_jpy: float | None = None
    event_risk: bool = False


@dataclass(frozen=True)
class RiskRecommendation:
    ticker: str
    decision: Decision
    hard_blocks: tuple[str, ...]
    warnings: tuple[str, ...]
    market_state: MarketState
    individual_stage: str
    base_risk_budget_jpy: float
    uncapped_risk_position_jpy: float
    capped_position_jpy: float
    market_multiplier: float
    stage_multiplier: float
    heat_limited_position_jpy: float
    recommended_position_jpy: float
    first_tranche_jpy: float
    second_tranche_jpy: float
    recommended_shares: int | None
    first_tranche_shares: int | None
    second_tranche_shares: int | None
    planned_loss_full_jpy: float
    portfolio_heat_before: float
    portfolio_heat_after_first: float
    portfolio_heat_after_full: float
    sector_heat_after_full: float
    theme_heat_after_full: float
    priority_key: tuple[float, ...]
    second_tranche_condition: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        payload["market_state"] = self.market_state.value
        payload["hard_blocks"] = list(self.hard_blocks)
        payload["warnings"] = list(self.warnings)
        payload["priority_key"] = list(self.priority_key)
        return payload


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fraction(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    number = abs(number)
    return number / 100.0 if number > 1.0 else number


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(value, (int, float)):
        number = _num(value)
        return bool(number) if number is not None else False
    return bool(value)


def _rank_unit(value: Any) -> float:
    number = _num(value)
    if number is None:
        return -1.0
    return number / 100.0 if abs(number) > 1.0 else number


def market_state_from_stage(stage: Any) -> MarketState:
    value = str(stage or "NA").upper()
    if value in {"2A", "2B"}:
        return MarketState.BLUE
    if value in {"1A", "1B"}:
        return MarketState.GREEN
    if value in {"2C", "3A", "3B", "NA"}:
        return MarketState.YELLOW
    return MarketState.RED


def portfolio_heat(holdings: Iterable[Holding], equity_jpy: float) -> PortfolioHeat:
    equity = max(float(equity_jpy), 1.0)
    sector: dict[str, float] = {}
    theme: dict[str, float] = {}
    event_loss = total_loss = gross = 0.0
    for holding in holdings:
        loss = holding.planned_loss_jpy
        total_loss += loss
        gross += max(0.0, holding.market_value_jpy)
        sector[holding.sector] = sector.get(holding.sector, 0.0) + loss
        theme[holding.theme] = theme.get(holding.theme, 0.0) + loss
        if holding.event_risk:
            event_loss += loss
    return PortfolioHeat(
        total_fraction=total_loss / equity,
        sector_fraction={key: value / equity for key, value in sector.items()},
        theme_fraction={key: value / equity for key, value in theme.items()},
        event_fraction=event_loss / equity,
        gross_fraction=gross / equity,
    )


def candidate_from_mapping(row: Mapping[str, Any]) -> Candidate:
    stage = str(row.get("individual_stage") or row.get("stage") or "NA").upper()
    market_stage = str(row.get("market_stage") or "NA").upper()
    market_raw = str(row.get("market_state") or "").upper()
    try:
        market = MarketState(market_raw) if market_raw else market_state_from_stage(market_stage)
    except ValueError:
        market = market_state_from_stage(market_stage)
    return Candidate(
        ticker=str(row.get("ticker") or "").upper(),
        sector=str(row.get("sector") or "UNKNOWN"),
        theme=str(row.get("theme") or row.get("subtheme") or row.get("industry") or "UNKNOWN"),
        market_state=market,
        market_stage=market_stage,
        individual_stage=stage,
        setup=str(row.get("setup") or row.get("entry_state") or "WATCH").upper(),
        hard_block=_truthy(row.get("hard_block")) or _truthy(row.get("hard_block_numeric")),
        stop_fraction=_fraction(row.get("stop_fraction") if row.get("stop_fraction") is not None else row.get("stop_risk_pct")),
        reward_risk=_num(row.get("reward_risk") if row.get("reward_risk") is not None else row.get("reward_risk_raw")),
        days_to_earnings=_num(row.get("days_to_earnings")),
        extension_atr=_num(row.get("extension_atr")),
        gap_fraction=_fraction(row.get("gap_fraction") if row.get("gap_fraction") is not None else row.get("gap_pct")),
        consecutive_up_days=_num(row.get("consecutive_up_days")),
        close_location=_num(row.get("close_location")),
        volume_ratio=_num(row.get("volume_ratio") if row.get("volume_ratio") is not None else row.get("volume_ratio_20d")),
        sector_stage_score=_num(row.get("sector_stage_score")),
        sector_stage_change_21d=_num(row.get("sector_stage_change_21d")),
        sector_rs_rank=_num(row.get("sector_rs_rank") if row.get("sector_rs_rank") is not None else row.get("sector_rank_pct")),
        alpha_rank=_num(row.get("alpha_rank") if row.get("alpha_rank") is not None else row.get("a_rank")),
        leadership_quality=_num(row.get("leadership_quality")),
        entry_quality=_num(row.get("entry_quality")),
        price=_num(row.get("price") if row.get("price") is not None else row.get("price_jpy")),
        available_cash_jpy=_num(row.get("available_cash_jpy")),
        event_risk=_truthy(row.get("event_risk")),
    )


def hard_gate(candidate: Candidate, policy: RiskPolicy) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blocks: list[str] = []
    warnings: list[str] = []
    if not candidate.ticker:
        blocks.append("TICKER_MISSING")
    if candidate.market_state == MarketState.RED:
        blocks.append("MARKET_RED")
    if candidate.event_risk and not policy.allow_event_risk:
        blocks.append("BINARY_EVENT_RISK")
    if candidate.hard_block or candidate.setup in {"AVOID", "BROKEN"}:
        blocks.append("LONG_TREND_BROKEN")
    if candidate.individual_stage in {"4A", "4B", "4C"}:
        blocks.append("INDIVIDUAL_STAGE_BROKEN")
    if candidate.stop_fraction is None or candidate.stop_fraction <= 0:
        blocks.append("STOP_UNDEFINED")
    elif candidate.stop_fraction > policy.max_stop_fraction:
        blocks.append("STOP_TOO_WIDE")
    if candidate.reward_risk is None:
        blocks.append("REWARD_RISK_UNDEFINED")
    elif candidate.reward_risk < policy.min_reward_risk:
        blocks.append("REWARD_RISK_BELOW_3R")
    if candidate.days_to_earnings is not None and -policy.earnings_blackout_sessions <= candidate.days_to_earnings <= policy.earnings_blackout_sessions:
        blocks.append("EARNINGS_BLACKOUT")
    if candidate.extension_atr is not None and candidate.extension_atr > policy.max_extension_atr:
        blocks.append("OVEREXTENDED")
    if candidate.gap_fraction is not None and candidate.gap_fraction > policy.max_gap_chase_fraction and candidate.setup not in {"PULLBACK", "RECLAIM"}:
        blocks.append("GAP_CHASE")
    if candidate.consecutive_up_days is not None and candidate.consecutive_up_days >= 3 and (candidate.extension_atr or 0.0) >= 1.5:
        blocks.append("THREE_DAY_CHASE")
    if candidate.close_location is not None and candidate.volume_ratio is not None and candidate.volume_ratio >= policy.heavy_volume_ratio and candidate.close_location < policy.min_close_location_on_heavy_volume:
        blocks.append("HEAVY_VOLUME_REJECTION")
    if candidate.sector_stage_change_21d is not None and candidate.sector_stage_change_21d < -10:
        blocks.append("SECTOR_FLOW_REVERSAL")
    elif candidate.sector_stage_change_21d is not None and candidate.sector_stage_change_21d < 0:
        warnings.append("SECTOR_MOMENTUM_SOFT")
    if candidate.sector_stage_score is not None and candidate.sector_stage_score < 35:
        blocks.append("SECTOR_TOO_WEAK")
    elif candidate.sector_stage_score is not None and candidate.sector_stage_score < 50:
        warnings.append("SECTOR_NOT_CONFIRMED")
    if candidate.market_state == MarketState.YELLOW:
        warnings.append("MARKET_YELLOW_A_GRADE_ONLY")
    if candidate.individual_stage in {"2C", "3A", "3B", "NA"}:
        warnings.append("STAGE_SIZE_REDUCTION")
    return tuple(dict.fromkeys(blocks)), tuple(dict.fromkeys(warnings))


def priority_key(candidate: Candidate) -> tuple[float, ...]:
    """Lexicographic ordering after hard gates; no good field can cancel a block."""
    return (
        _rank_unit(candidate.alpha_rank),
        _rank_unit(candidate.sector_rs_rank),
        _rank_unit(candidate.leadership_quality),
        _rank_unit(candidate.entry_quality),
        candidate.reward_risk if candidate.reward_risk is not None else -1.0,
        -(candidate.extension_atr if candidate.extension_atr is not None else 999.0),
    )


def _floor_shares(amount_jpy: float, price_jpy: float | None) -> int | None:
    if price_jpy is None or price_jpy <= 0:
        return None
    return max(0, int(amount_jpy // price_jpy))


def recommend(candidate: Candidate, holdings: Sequence[Holding] = (), *, policy: RiskPolicy | None = None, new_positions_today: int = 0) -> RiskRecommendation:
    policy = policy or RiskPolicy()
    equity = policy.account_equity_jpy
    heat = portfolio_heat(holdings, equity)
    blocks, warnings = hard_gate(candidate, policy)
    if candidate.ticker in {holding.ticker.upper() for holding in holdings}:
        blocks = tuple((*blocks, "ALREADY_HELD_USE_ADDON_WORKFLOW"))
    risk_budget = equity * policy.risk_per_trade
    stop = candidate.stop_fraction or 0.0
    uncapped = risk_budget / stop if stop > 0 else 0.0
    capped = min(uncapped, equity * policy.max_position_fraction)
    market_mult = float(policy.market_multipliers[candidate.market_state])
    stage_mult = float(policy.stage_multipliers.get(candidate.individual_stage, 0.50))
    if new_positions_today >= policy.max_new_positions_per_day:
        blocks = tuple((*blocks, "DAILY_NEW_POSITION_LIMIT"))
    total_remaining_loss = max(0.0, equity * float(policy.market_heat_limits[candidate.market_state]) - equity * heat.total_fraction)
    sector_remaining_loss = max(0.0, equity * policy.sector_heat_limit - equity * heat.sector_fraction.get(candidate.sector, 0.0))
    theme_remaining_loss = max(0.0, equity * policy.theme_heat_limit - equity * heat.theme_fraction.get(candidate.theme, 0.0))
    event_remaining_loss = max(0.0, equity * policy.event_heat_limit - equity * heat.event_fraction) if candidate.event_risk else float("inf")
    loss_capacity = min(total_remaining_loss, sector_remaining_loss, theme_remaining_loss, event_remaining_loss)
    heat_limited = loss_capacity / stop if stop > 0 and math.isfinite(loss_capacity) else capped
    available_cash = candidate.available_cash_jpy if candidate.available_cash_jpy is not None and candidate.available_cash_jpy >= 0 else float("inf")
    target = max(0.0, min(capped * market_mult * stage_mult, heat_limited, available_cash))
    if blocks:
        target = 0.0
        decision = Decision.REJECT
    elif target < equity * policy.minimum_actionable_position_fraction:
        target = 0.0
        decision = Decision.WATCH
        warnings = tuple((*warnings, "POSITION_BELOW_MINIMUM"))
    elif market_mult < 1.0 or stage_mult < 1.0:
        decision = Decision.FIRST_TRANCHE
    else:
        decision = Decision.NORMAL
    first = target * policy.first_tranche_fraction
    second = target - first
    full_loss = target * stop
    first_loss = first * stop
    total_before = heat.total_fraction
    shares = _floor_shares(target, candidate.price)
    first_shares = _floor_shares(first, candidate.price)
    second_shares = None if shares is None or first_shares is None else max(0, shares - first_shares)
    return RiskRecommendation(
        ticker=candidate.ticker,
        decision=decision,
        hard_blocks=tuple(dict.fromkeys(blocks)),
        warnings=tuple(dict.fromkeys(warnings)),
        market_state=candidate.market_state,
        individual_stage=candidate.individual_stage,
        base_risk_budget_jpy=risk_budget,
        uncapped_risk_position_jpy=uncapped,
        capped_position_jpy=capped,
        market_multiplier=market_mult,
        stage_multiplier=stage_mult,
        heat_limited_position_jpy=max(0.0, heat_limited),
        recommended_position_jpy=target,
        first_tranche_jpy=first,
        second_tranche_jpy=second,
        recommended_shares=shares,
        first_tranche_shares=first_shares,
        second_tranche_shares=second_shares,
        planned_loss_full_jpy=full_loss,
        portfolio_heat_before=total_before,
        portfolio_heat_after_first=total_before + first_loss / equity,
        portfolio_heat_after_full=total_before + full_loss / equity,
        sector_heat_after_full=heat.sector_fraction.get(candidate.sector, 0.0) + full_loss / equity,
        theme_heat_after_full=heat.theme_fraction.get(candidate.theme, 0.0) + full_loss / equity,
        priority_key=priority_key(candidate),
        second_tranche_condition="ブレイク定着・2nd Pivot・支持転換のいずれかを確認。含み損への追加は禁止。追加後もPortfolio Heat上限内であること。",
    )


def evaluate_candidates(candidates: Iterable[Candidate | Mapping[str, Any]], holdings: Sequence[Holding] = (), *, policy: RiskPolicy | None = None, new_positions_today: int = 0) -> list[RiskRecommendation]:
    policy = policy or RiskPolicy()
    normalized = [item if isinstance(item, Candidate) else candidate_from_mapping(item) for item in candidates]
    recommendations = [recommend(item, holdings, policy=policy, new_positions_today=new_positions_today) for item in normalized]
    return sorted(recommendations, key=lambda item: (
        item.decision == Decision.REJECT,
        item.decision == Decision.WATCH,
        tuple(-value for value in item.priority_key),
        item.ticker,
    ))


def allocate_candidates(candidates: Iterable[Candidate | Mapping[str, Any]], holdings: Sequence[Holding] = (), *, policy: RiskPolicy | None = None) -> list[RiskRecommendation]:
    """Executable first-tranche plan; selected candidates reserve full-position heat."""
    policy = policy or RiskPolicy()
    normalized = [item if isinstance(item, Candidate) else candidate_from_mapping(item) for item in candidates]
    normalized.sort(key=lambda item: (tuple(-value for value in priority_key(item)), item.ticker))
    working = list(holdings)
    output: list[RiskRecommendation] = []
    new_positions = 0
    for candidate in normalized:
        result = recommend(candidate, working, policy=policy, new_positions_today=new_positions)
        output.append(result)
        if result.decision in {Decision.NORMAL, Decision.FIRST_TRANCHE} and result.recommended_position_jpy > 0:
            working.append(Holding(
                ticker=candidate.ticker,
                sector=candidate.sector,
                theme=candidate.theme,
                market_value_jpy=result.recommended_position_jpy,
                stop_fraction=candidate.stop_fraction or 0.0,
                event_risk=candidate.event_risk,
            ))
            new_positions += 1
    return output


def time_stop_action(*, holding_days: int, progress_r: float, second_pivot_confirmed: bool = False, environment_deteriorated: bool = False, price_stop_breached: bool = False) -> str:
    if price_stop_breached:
        return "EXIT_PRICE_STOP"
    if environment_deteriorated:
        return "REDUCE_OR_EXIT_ENVIRONMENT"
    if holding_days >= 10 and progress_r < 1.0:
        return "EXIT_TIME_STOP"
    if holding_days >= 5 and progress_r < 1.0 and not second_pivot_confirmed:
        return "REDUCE_HALF_OR_EXIT"
    if holding_days >= 3 and progress_r < 0.5:
        return "WARN_NO_FOLLOW_THROUGH"
    return "HOLD"
