from __future__ import annotations

import unittest

from leadership.structure_overlay import apply_structure_overlay, enrich_group, stock_structure


def stock(symbol: str, *, supply_near: bool, breakout_now: bool) -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "role": "LEADER",
        "strength": 88.0,
        "rs189": 82.0,
        "rs63": 88.0 if breakout_now else 76.0,
        "rs21": 96.0 if breakout_now else 79.0,
        "acceleration": 8.0 if breakout_now else 3.0,
        "near_high": -3.0,
        "volume_ratio": 1.6 if breakout_now else 1.1,
        "price": 100.0,
        "ema21": 98.0 if breakout_now else 94.0,
        "vwap63": 97.0 if breakout_now else 95.0,
        "sma50": 95.0,
        "pivot": 90.0 if not supply_near else 102.0,
        "pivot50": 92.0 if not supply_near else 103.0,
        "breakout": {
            "status": "BREAKOUT_NOW" if breakout_now else "NONE",
            "score": 96.0 if breakout_now else 45.0,
        },
        "entry": {"status": "ENTRY", "quality": 96.0, "reason": "50日・20日Pivotを本日終値で突破" if breakout_now else "21EMA押し目"},
        "eps_label": "ACCEL_CONFIRMED",
    }


class StructureOverlayTests(unittest.TestCase):
    def test_stock_structure_penalizes_near_overhead_supply(self):
        blocked = stock_structure(stock("BLOCK", supply_near=True, breakout_now=False))
        clear = stock_structure(stock("CLEAR", supply_near=False, breakout_now=True))
        self.assertEqual(blocked["state"], "SUPPLY_NEAR")
        self.assertLess(blocked["score"], 55)
        self.assertAlmostEqual(blocked["supply_distance_pct"], 2.0, places=1)
        self.assertEqual(clear["state"], "CLEAR")
        self.assertGreater(clear["score"], 80)
        self.assertIsNone(clear["supply_distance_pct"])
        self.assertLessEqual(clear["demand_distance_pct"], 3.0)

    def test_group_combines_leadership_and_structure_without_overwriting_leadership(self):
        group = {
            "name": "Semiconductor Equipment",
            "sector": "Electronic Technology",
            "phase": "LEADING",
            "score": 84.0,
            "pioneer_score": 88.0,
            "breadth_score": 76.0,
            "leader_breakouts": 1,
            "stocks": [stock("AAA", supply_near=False, breakout_now=True)],
        }
        enriched = enrich_group(group)
        self.assertEqual(enriched["leadership_score"], 84.0)
        self.assertGreater(enriched["structure_score"], 80)
        self.assertGreater(enriched["priority_score"], 80)
        self.assertEqual(enriched["structure_state"], "CLEAR")

    def test_supply_near_group_is_waiting_while_clear_breakout_is_actionable(self):
        blocked_group = {
            "name": "Blocked Group",
            "sector": "Health Technology",
            "phase": "LEADING",
            "score": 86.0,
            "pioneer_score": 86.0,
            "breadth_score": 75.0,
            "leader_breakouts": 0,
            "stocks": [stock("BLOCK", supply_near=True, breakout_now=False)],
        }
        clear_group = {
            "name": "Clear Group",
            "sector": "Electronic Technology",
            "phase": "EMERGING",
            "score": 81.0,
            "pioneer_score": 90.0,
            "breadth_score": 60.0,
            "leader_breakouts": 1,
            "stocks": [stock("BREAK", supply_near=False, breakout_now=True)],
        }
        model = {
            "schema": 4,
            "market": {"status": "GO"},
            "coverage": {"stocks": 2, "groups": 2},
            "sectors": [
                {"name": "Health Technology", "phase": "LEADING", "score": 80.0},
                {"name": "Electronic Technology", "phase": "EMERGING", "score": 78.0},
            ],
            "groups": [blocked_group, clear_group],
            "actionable": [],
            "waiting": [],
        }
        out = apply_structure_overlay(model)
        self.assertEqual(out["groups"][0]["name"], "Clear Group")
        self.assertEqual(out["actionable"][0]["symbol"], "BREAK")
        blocked = next(x for x in out["waiting"] if x["symbol"] == "BLOCK")
        self.assertEqual(blocked["status"], "WAIT")
        self.assertIn("Supply直下", blocked["reason"])
        self.assertEqual(out["coverage"]["structure_groups"], 2)
        self.assertEqual(out["schema"], 5)


if __name__ == "__main__":
    unittest.main()
