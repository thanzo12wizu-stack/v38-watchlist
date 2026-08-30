import math

import pytest

from v38_rules import (
    NormalPosition, capped_tqqq_target, crash_seed, evaluate_normal_close,
    market_mode, new_entry_capacity, tqqq_panic_entry, tqqq_panic_exit,
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


def test_selective_is_not_a_trim_target():
    selective = market_mode("Green", 55)
    assert new_entry_capacity(selective, 8) == 0
    assert new_entry_capacity(selective, 3) == 1


def test_coverage_failure_stops_entries_only():
    mode = market_mode("Green", 65, coverage_ok=False)
    assert mode.name == "STOP" and not mode.force_exit_next_open


def test_plus24_partial_once():
    pos = evaluate_normal_close(NormalPosition(100, 100), 124)
    assert pos.pending_action == "PARTIAL25_NEXT_OPEN"
    assert pos.partial_taken and math.isclose(pos.remaining_fraction, .75)
    assert evaluate_normal_close(pos, 130).pending_action is None


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


def test_strict_crash_seed():
    assert crash_seed(23, 95, 100, 10, -.02)
    assert not crash_seed(22.99, 95, 100, 10, -.02)


def test_tqqq_touch30_f80_and_exits():
    assert tqqq_panic_entry(30, 29.9, 30.1, 20)
    assert not tqqq_panic_entry(31, 29.9, 30.1, 20)
    assert not tqqq_panic_entry(30, 29.9, 30.1, 19.99)
    assert tqqq_panic_exit(3, 19.9) == "MC57_LT20_NEXT_OPEN"
    assert tqqq_panic_exit(10, 50) == "MAX10_NEXT_OPEN"


def test_gross_cap_never_exceeds_100_percent():
    assert math.isclose(capped_tqqq_target(True, .20), .80)
    assert math.isclose(capped_tqqq_target(True, .35), .65)
    assert math.isclose(capped_tqqq_target(False, .80), .20)
