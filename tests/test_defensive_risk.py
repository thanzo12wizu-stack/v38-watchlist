from intelligence_engine.defensive_risk import (
    Candidate,
    Decision,
    Holding,
    MarketState,
    RiskPolicy,
    allocate_candidates,
    candidate_from_mapping,
    evaluate_candidates,
    hard_gate,
    portfolio_heat,
    recommend,
    time_stop_action,
)


def base_candidate(**overrides):
    data = dict(
        ticker="AAA",
        sector="Technology",
        theme="Semiconductors",
        market_state=MarketState.BLUE,
        market_stage="2A",
        individual_stage="2A",
        setup="PULLBACK",
        stop_fraction=0.04,
        reward_risk=4.0,
        days_to_earnings=10,
        extension_atr=1.0,
        sector_stage_score=75,
        sector_stage_change_21d=5,
        sector_rs_rank=90,
        alpha_rank=95,
        leadership_quality=90,
        entry_quality=85,
        price=1000,
    )
    data.update(overrides)
    return Candidate(**data)


def test_red_market_cannot_be_offset_by_high_alpha():
    result = recommend(base_candidate(market_state=MarketState.RED, alpha_rank=100))
    assert result.decision == Decision.REJECT
    assert "MARKET_RED" in result.hard_blocks
    assert result.recommended_position_jpy == 0


def test_default_position_is_capped_at_eight_percent_and_split():
    result = recommend(base_candidate())
    assert result.decision == Decision.NORMAL
    assert result.capped_position_jpy == 640_000
    assert result.recommended_position_jpy == 640_000
    assert result.first_tranche_jpy == 320_000
    assert result.second_tranche_jpy == 320_000
    assert result.planned_loss_full_jpy == 25_600


def test_yellow_and_mature_stage_reduce_size_non_symmetrically():
    result = recommend(base_candidate(
        market_state=MarketState.YELLOW,
        market_stage="3A",
        individual_stage="2C",
    ))
    assert result.decision == Decision.FIRST_TRANCHE
    assert result.market_multiplier == 0.5
    assert result.stage_multiplier == 0.5
    assert result.recommended_position_jpy == 160_000


def test_sector_heat_caps_new_position():
    holdings = [Holding(
        ticker="OLD",
        sector="Technology",
        theme="Semiconductors",
        market_value_jpy=1_800_000,
        stop_fraction=0.04,
    )]
    heat = portfolio_heat(holdings, 8_000_000)
    assert round(heat.sector_fraction["Technology"], 4) == 0.009
    result = recommend(base_candidate(), holdings)
    assert result.recommended_position_jpy == 600_000
    assert round(result.sector_heat_after_full, 4) == 0.012


def test_stop_and_reward_are_hard_gates():
    blocks, _ = hard_gate(base_candidate(stop_fraction=0.08, reward_risk=2.5), RiskPolicy())
    assert "STOP_TOO_WIDE" in blocks
    assert "REWARD_RISK_BELOW_3R" in blocks


def test_priority_only_orders_gate_passers():
    good = base_candidate(ticker="GOOD", alpha_rank=80)
    red = base_candidate(ticker="RED", market_state=MarketState.RED, alpha_rank=100)
    results = evaluate_candidates([red, good])
    assert results[0].ticker == "GOOD"
    assert results[-1].ticker == "RED"
    assert results[-1].decision == Decision.REJECT


def test_daily_new_position_limit_is_hard_gate():
    result = recommend(base_candidate(), new_positions_today=2)
    assert result.decision == Decision.REJECT
    assert "DAILY_NEW_POSITION_LIMIT" in result.hard_blocks


def test_time_stop_order():
    assert time_stop_action(holding_days=3, progress_r=0.2) == "WARN_NO_FOLLOW_THROUGH"
    assert time_stop_action(holding_days=5, progress_r=0.7) == "REDUCE_HALF_OR_EXIT"
    assert time_stop_action(holding_days=10, progress_r=0.9) == "EXIT_TIME_STOP"
    assert time_stop_action(holding_days=1, progress_r=0.0, price_stop_breached=True) == "EXIT_PRICE_STOP"


def test_allocation_reserves_full_heat_and_limits_daily_entries():
    candidates = [
        base_candidate(ticker="A", alpha_rank=99, sector="Tech", theme="Semi"),
        base_candidate(ticker="B", alpha_rank=98, sector="Health", theme="Tools"),
        base_candidate(ticker="C", alpha_rank=97, sector="Energy", theme="Oil"),
    ]
    results = allocate_candidates(candidates)
    assert [item.ticker for item in results] == ["A", "B", "C"]
    assert results[0].decision == Decision.NORMAL
    assert results[1].decision == Decision.NORMAL
    assert results[2].decision == Decision.REJECT
    assert "DAILY_NEW_POSITION_LIMIT" in results[2].hard_blocks


def test_nan_hard_block_is_not_truthy_and_binary_event_is_blocked():
    candidate = candidate_from_mapping({
        "ticker": "AAA",
        "market_state": "BLUE",
        "individual_stage": "2A",
        "hard_block": float("nan"),
        "stop_risk_pct": 4,
        "reward_risk_raw": 4,
        "event_risk": True,
    })
    assert candidate.hard_block is False
    result = recommend(candidate)
    assert "BINARY_EVENT_RISK" in result.hard_blocks
