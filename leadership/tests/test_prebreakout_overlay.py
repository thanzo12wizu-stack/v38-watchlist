from __future__ import annotations

import unittest

from leadership.prebreakout_overlay import apply_prebreakout_overlay, stock_prebreakout
from leadership.render_public import render_public_html


def strong_stock(symbol: str, *, breakout_status: str = "BREAKOUT_WATCH", gap: float = 1.2, rvol: float = 0.72) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "role": "PIONEER",
        "strength": 91.0,
        "rs189": 86.0,
        "rs63": 94.0,
        "rs21": 98.0,
        "acceleration": 4.0,
        "near_high": -3.0,
        "volume_ratio": rvol,
        "price": 100.0,
        "sma50": 91.0,
        "breakout20_pct": -gap,
        "breakout50_pct": -(gap + 0.4),
        "breakout": {"status": breakout_status, "score": 80.0},
        "entry": {"status": "WATCH", "quality": 78.0, "reason": "Pivot直前"},
        "structure": {
            "score": 74.0,
            "label": "Supply吸収中",
            "supply_distance_pct": gap,
            "demand_distance_pct": 2.5,
            "absorption_score": 76.0,
            "demand_score": 88.0,
            "volume_dryup_score": 90.0,
        },
    }


def group_with(stock: dict) -> dict:
    return {
        "name": "Semiconductor Equipment",
        "sector": "Electronic Technology",
        "phase": "EMERGING",
        "score": 82.0,
        "leadership_score": 82.0,
        "structure_score": 75.0,
        "priority_score": 79.2,
        "pioneer_score": 88.0,
        "breadth_score": 66.0,
        "leader_breakouts": 0,
        "stocks": [stock],
    }


class PreBreakoutOverlayTests(unittest.TestCase):
    def test_ready_setup_is_selected_before_trigger(self) -> None:
        stock = strong_stock("AAA")
        pre = stock_prebreakout(stock, group_with(stock))
        self.assertEqual(pre["status"], "READY")
        self.assertGreaterEqual(pre["score"], 80)
        self.assertAlmostEqual(pre["pivot_gap_pct"], 1.2)

    def test_sharp_rs_deceleration_cannot_be_ready(self) -> None:
        stock = strong_stock("DECEL")
        stock["acceleration"] = -12.0
        stock["rs21"] = 82.0
        pre = stock_prebreakout(stock, group_with(stock))
        self.assertNotEqual(pre["status"], "READY")
        self.assertIn(pre["status"], {"COILED", "WATCH", "NOT_READY"})

    def test_today_breakout_is_excluded_from_prebreakout_candidates(self) -> None:
        stock = strong_stock("AAA", breakout_status="BREAKOUT_NOW", gap=-0.5, rvol=1.7)
        pre = stock_prebreakout(stock, group_with(stock))
        self.assertEqual(pre["status"], "ALREADY_BROKE")
        self.assertEqual(pre["score"], 0.0)

    def test_overlay_replaces_actionable_with_prebreakout_ready(self) -> None:
        ready = strong_stock("READY")
        broke = strong_stock("BROKE", breakout_status="BREAKOUT_NOW", gap=-0.5, rvol=1.8)
        g1 = group_with(ready)
        g2 = dict(group_with(broke), name="Medical - Development Biotech", stocks=[broke])
        model = {
            "schema": 5,
            "market": {"status": "GO"},
            "coverage": {},
            "groups": [g1, g2],
            "sectors": [],
            "actionable": [{"symbol": "BROKE"}],
            "waiting": [],
        }
        out = apply_prebreakout_overlay(model)
        self.assertEqual(out["candidate_mode"], "PRE_BREAKOUT_FIRST")
        self.assertEqual(out["actionable"][0]["symbol"], "READY")
        self.assertNotIn("BROKE", [x["symbol"] for x in out["actionable"]])
        self.assertEqual(out["confirmed_breakouts"][0]["symbol"], "BROKE")

    def test_public_copy_says_prebreakout_first(self) -> None:
        ready = strong_stock("AAA")
        group = group_with(ready)
        model = {
            "schema": 4,
            "market": {"status": "GO", "mri": 72.0, "gate": "Green", "ftd": "FTD_ACTIVE"},
            "coverage": {"stocks": 1, "groups": 1, "rs63": 1, "confidence": "HIGH", "metric_source": "test"},
            "groups": [group],
            "sectors": [],
            "actionable": [],
            "waiting": [],
        }
        page = render_public_html(model)
        self.assertIn("発火前・最優先", page)
        self.assertIn("発火前READY", page)
        self.assertIn("ブレイクする前だけを表示", page)


if __name__ == "__main__":
    unittest.main()
