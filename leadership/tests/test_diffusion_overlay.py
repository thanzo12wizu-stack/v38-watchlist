from __future__ import annotations

import unittest

from leadership.diffusion_overlay import apply_diffusion_overlay


class DiffusionOverlayTests(unittest.TestCase):
    def test_attaches_sector_and_early_leader_without_changing_legacy_role(self) -> None:
        model = {
            "schema": 7,
            "coverage": {},
            "sectors": [{"name": "Technology"}],
            "groups": [{
                "name": "Semiconductors",
                "sector": "Technology",
                "stocks": [
                    {"symbol": "AAA", "role": "FOLLOWER", "strength": 75},
                    {"symbol": "BBB", "role": "LEADER", "strength": 90},
                ],
            }],
        }
        snapshot = {"diffusion": {
            "status": "OK",
            "method": "test",
            "uses_stock_capture": False,
            "coverage": {},
            "sectors": {"Technology": {"state": "IGNITION", "event_age": 1, "event_score": 82}},
            "stocks": {"AAA": {"early_leader": True, "lead_score": 91, "entry": {"status": "WATCH"}}},
        }}
        out = apply_diffusion_overlay(model, snapshot)
        group = out["groups"][0]
        self.assertEqual(group["sector_diffusion"]["state"], "IGNITION")
        self.assertEqual(group["stocks"][0]["symbol"], "AAA")
        self.assertEqual(group["stocks"][0]["role"], "FOLLOWER")
        self.assertEqual(group["stocks"][0]["diffusion_role"], "EARLY_LEADER")
        self.assertTrue(out["coverage"]["diffusion_enabled"])


if __name__ == "__main__":
    unittest.main()
