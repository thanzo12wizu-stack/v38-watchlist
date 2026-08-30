import math

import pytest

from v38_rules import (
    NormalPosition, apply_pending_at_open, attack_rank_score, crash_seed,
    evaluate_normal_close, market_mode, new_entry_capacity, peer_theme_score,
    select_peer_theme, tqqq_allocation, tqqq_panic_entry, tqqq_panic_exit,
)


@pytest.mark.parametrize("breadth,expected,limit", [
    (65, "ATTACK", 12), (55, "SELECTIVE", 4), (45, "STOP", 0),
])
def test_green_breadth_modes(breadth, expected, limit):
    mode = market_mode("Green", breadth)
    assert (mode.name, mode.new_entry_limit) == (expected, limit)


def test_yellow_stops_new_entries_but_does_not_force_exit():
    mode = market_mode("Yellow", 65)
    assert mode.name == "STOP" and not mode.force_exit_next_open


def test_red_forces_next_open_exit():
    mode = market_mode("Red", 65)
    assert mode.name == "DEFENSE" and mode.force_exit_next_open


def test_red_recovery_has_no_extra_confirmation():
    assert market_mode("Green", 55).new_entry_limit == 4
    assert market_mode("Green", 65).new_entry_limit == 12


@pytest.mark.parametrize("held,capacity", [(8, 0), (5, 0), (4, 0), (3, 1), (0, 4)])
def test_selective_total_count_cap_without_forced_trim(held, capacity):
    selective = market_mode("Green", 55)
    assert new_entry_capacity(selective, held) == capacity


def test_coverage_failure_stops_entries_only():
    mode = market_mode("Green", 65, coverage_ok=False)
    assert mode.name == "STOP" and not mode.force_exit_next_open


def test_plus24_partial_once():
    signaled = evaluate_normal_close(NormalPosition(100, 100), 124)
    assert signaled.pending_action == "PARTIAL25_NEXT_OPEN"
    assert not signaled.partial_taken and math.isclose(signaled.remaining_fraction, 1.0)
    executed = apply_pending_at_open(signaled)
    assert executed.partial_taken and math.isclose(executed.remaining_fraction, .75)
    assert executed.entry == 100 and executed.peak_close == 124
    assert evaluate_normal_close(executed, 130).pending_action is None


def test_peak_uses_close_and_peak30_exits_remaining():
    pos = evaluate_normal_close(NormalPosition(100, 100, True, .75), 150)
    assert pos.peak_close == 150
    pos = evaluate_normal_close(pos, 105)
    assert pos.pending_action == "PEAK30_STOP_NEXT_OPEN"
    assert math.isclose(pos.pending_fraction, .75)


def test_initial_stop_is_minus8_close_based():
    pos = NormalPosition(100, 100)
    assert evaluate_normal_close(pos, 93).pending_action is None
    assert evaluate_normal_close(pos, 92).pending_action == "INITIAL_STOP_NEXT_OPEN"


def test_plus8_does_not_move_stop_to_breakeven():
    assert evaluate_normal_close(NormalPosition(100, 100), 108).pending_action is None


def test_rank_and_theme_are_not_exit_inputs():
    pos = evaluate_normal_close(NormalPosition(100, 120, True, .75), 115)
    assert pos.pending_action is None


def test_red_overrides_position_exit():
    pos = evaluate_normal_close(NormalPosition(100, 150, True, .75), 105, "Red")
    assert pos.pending_action == "EXIT_NQSAR_RED_NEXT_OPEN"


def test_stop_execution_occurs_only_at_next_open():
    signaled = evaluate_normal_close(NormalPosition(100, 100), 92)
    assert signaled.remaining_fraction == 1.0
    executed = apply_pending_at_open(signaled)
    assert executed.remaining_fraction == 0.0


def test_partial_does_not_reset_entry_or_peak_and_intraday_high_is_not_an_input():
    signaled = evaluate_normal_close(NormalPosition(100, 150), 124)
    executed = apply_pending_at_open(signaled)
    assert (executed.entry, executed.peak_close) == (100, 150)
    # Only the completed close is accepted by the engine; an intraday high has no field.
    assert evaluate_normal_close(executed, 104.99).pending_action == "PEAK30_STOP_NEXT_OPEN"


def test_peer_theme_full3_multiple_membership_and_missing_neutral():
    full3 = peer_theme_score(80, 70, 60)
    assert full3 == 70
    assert select_peer_theme({"Theme A": full3, "Theme B": 75}) == ("Theme B", 75)
    assert select_peer_theme({}) == (None, None)
    assert attack_rank_score(90, None) == 78  # 70% Stock RS + 30% neutral 50


def test_strict_crash_seed():
    assert crash_seed(23, 95, 100, 10, -.02)
    assert not crash_seed(22.99, 95, 100, 10, -.02)


def test_tqqq_touch30_f80_and_exits():
    assert tqqq_panic_entry(0, 29.9, 30.1, 20)  # seed day is age 0 and included
    assert tqqq_panic_entry(30, 29.9, 30.1, 20)
    assert not tqqq_panic_entry(31, 29.9, 30.1, 20)
    assert not tqqq_panic_entry(5, 29.9, 29.0, 20)  # RISE30 is not TOUCH30
    assert not tqqq_panic_entry(30, 29.9, 30.1, 19.99)
    assert tqqq_panic_exit(3, 19.9) == "MC57_LT20_NEXT_OPEN"
    assert tqqq_panic_exit(10, 50) == "MAX10_NEXT_OPEN"


def test_f80_is_floor_over_underlying_target_not_fixed_80():
    assert math.isclose(tqqq_allocation(.30, True, .20).requested_target, .80)
    assert math.isclose(tqqq_allocation(.90, True, 0).requested_target, .90)


def test_requested_and_executable_tqqq_are_separate_without_auto_trim():
    a = tqqq_allocation(.30, True, .70)
    assert math.isclose(a.requested_target, .80)
    assert math.isclose(a.other_sleeve_exposure, .70)
    assert math.isclose(a.available_capacity, .30)
    assert math.isclose(a.executable_target, .30)
    assert math.isclose(a.shortfall, .50)
