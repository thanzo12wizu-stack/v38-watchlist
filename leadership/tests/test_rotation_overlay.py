from __future__ import annotations

import unittest

from leadership.rotation_overlay import apply_rotation_overlay, enrich_rotation_group

# Public Leadership is intentionally organized around granular sector rotation first.


def stock(symbol: str, pre_status: str = "READY") -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "role": "PIONEER",
        "strength": 91.0,
        "rs63": 94.0,
        "rs21": 98.0,
        "acceleration": 4.0,
        "prebreakout": {"status": pre_status, "score": 86.0, "pivot_gap_pct": 1.2},
    }


class RotationOverlayTests(unittest.TestCase):
    def test_emerging_group_with_acceleration_is_rising(self) -> None:
        group = {
            "name": "Medical - Development Biotech",
            "phase": "EMERGING",
            "pioneer_score": 84.0,
            "breadth_score": 61.0,
            "top_acceleration": 8.0,
            "positive_accel_share": 68.0,
            "structure_score": 72.0,
            "priority_score": 78.0,
            "structure_state": "ABSORBING",
            "pioneers": 1,
            "leaders": 2,
            "stocks": [stock("AAA")],
        }
        out = enrich_rotation_group(group)
        self.assertEqual(out["rotation_state"], "RISING")
        self.assertEqual(out["rotation_label"], "急浮上")
        self.assertEqual(out["prebreakout_ready"], 1)
        self.assertIn("AAA", out["rotation_leader_symbols"])
        self.assertIn("上値抵抗を吸収中", out["rotation_reason"])

    def test_mature_decelerating_group_is_topping(self) -> None:
        group = {
            "name": "Gold Miners",
            "phase": "MATURE",
            "pioneer_score": 70.0,
            "breadth_score": 66.0,
            "top_acceleration": -7.0,
            "positive_accel_share": 35.0,
            "structure_score": 64.0,
            "stocks": [stock("BBB", "COILED")],
        }
        out = enrich_rotation_group(group)
        self.assertEqual(out["rotation_state"], "TOPPING")
        self.assertIn(out["rotation_direction"], {"鈍化", "減速"})

    def test_overlay_buckets_groups_by_rotation(self) -> None:
        model = {
            "schema": 6,
            "coverage": {},
            "groups": [
                {"name": "A", "phase": "EMERGING", "pioneer_score": 80, "breadth_score": 60, "top_acceleration": 7, "positive_accel_share": 70, "stocks": []},
                {"name": "B", "phase": "LEADING", "pioneer_score": 75, "breadth_score": 70, "top_acceleration": 1, "positive_accel_share": 60, "stocks": []},
            ],
        }
        out = apply_rotation_overlay(model)
        self.assertEqual(out["view_mode"], "SECTOR_ROTATION_FIRST")
        self.assertEqual(out["rotation"]["rising"][0]["name"], "A")
        self.assertEqual(out["rotation"]["leading"][0]["name"], "B")


if __name__ == "__main__":
    unittest.main()
