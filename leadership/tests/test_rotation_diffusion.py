from __future__ import annotations

import unittest

from leadership.rotation_diffusion import apply_diffusion_rotation


class DiffusionRotationTests(unittest.TestCase):
    def test_diffusion_event_is_primary_over_legacy_rotation(self) -> None:
        model = {
            "schema": 8,
            "coverage": {},
            "diffusion": {"enabled": True},
            "groups": [
                {
                    "name": "Semis",
                    "sector": "Technology",
                    "phase": "LOSING",
                    "pioneer_score": 50,
                    "breadth_score": 58,
                    "top_acceleration": -2,
                    "positive_accel_share": 40,
                    "stocks": [{
                        "symbol": "AAA", "name": "AAA", "role": "FOLLOWER", "strength": 82,
                        "rs63": 90, "rs21": 92, "acceleration": 2,
                        "diffusion": {"early_leader": True, "lead_score": 88, "lead_days": 5, "entry": {"status": "PULLBACK_RECLAIM"}},
                    }],
                    "sector_diffusion": {"state": "IGNITION", "event_age": 1, "relative_high_5d": 42, "relative_high_delta_5d": 12, "leader_density": 18, "event_score": 85},
                    "early_leader_count": 1,
                    "diffusion_entry_count": 1,
                    "max_lead_score": 88,
                },
                {
                    "name": "OldWinner",
                    "sector": "Industrials",
                    "phase": "LEADING",
                    "pioneer_score": 90,
                    "breadth_score": 85,
                    "top_acceleration": 10,
                    "positive_accel_share": 80,
                    "stocks": [],
                    "sector_diffusion": {"state": "NONE", "event_score": 20},
                },
            ],
        }
        out = apply_diffusion_rotation(model)
        self.assertEqual(out["view_mode"], "SECTOR_DIFFUSION_FIRST")
        self.assertEqual(out["rotation"]["rising"][0]["name"], "Semis")
        old = next(x for x in out["groups"] if x["name"] == "OldWinner")
        self.assertEqual(old["rotation_state"], "FADING")
        self.assertEqual(out["rotation"]["rising"][0]["rotation_leaders"][0]["status"], "押し目発火")


if __name__ == "__main__":
    unittest.main()
