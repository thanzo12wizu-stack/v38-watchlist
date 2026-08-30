import unittest

import numpy as np
import pandas as pd

from leadership.loo_theme_live import build_loo_theme_live, extract_theme_members


class LooThemeLiveTests(unittest.TestCase):
    def _frames(self, a_multiplier: float = 1.0):
        idx = pd.bdate_range("2026-01-05", periods=120)
        specs = {
            "A": (0.0010, 0.020),
            "B": (0.0020, 0.004),
            "C": (0.0018, 0.003),
            "D": (0.0016, 0.002),
            "E": (0.0003, 0.002),
            "F": (0.0002, 0.003),
            "G": (0.0001, 0.002),
            "H": (-0.0002, 0.002),
            "I": (-0.0003, 0.002),
            "J": (-0.0004, 0.002),
        }
        frames = {}
        x = np.arange(len(idx), dtype=float)
        for k, (drift, wobble) in specs.items():
            close = 100.0 * np.exp(drift * x + wobble * np.sin(x / 7.0 + len(k)))
            if k == "A":
                close = close.copy()
                close[-45:] *= a_multiplier
                close[-1] *= 1.0 + (a_multiplier - 1.0) * 2.0
            frames[k] = pd.DataFrame({"Close": close}, index=idx)
        return frames

    def _snapshot(self):
        return {
            "s2t": {
                "A": ["Theme One", "Theme Two"],
                "B": ["Theme One"], "C": ["Theme One"], "D": ["Theme One"],
                "E": ["Theme Two"], "F": ["Theme Two"], "G": ["Theme Two"],
                "H": ["Theme Three"], "I": ["Theme Three"], "J": ["Theme Three"],
            }
        }

    def test_requires_s2t_multi_membership_contract(self):
        with self.assertRaises(ValueError):
            extract_theme_members({"display_theme": {"A": "Theme One"}})

    def test_candidate_own_price_does_not_change_its_peer_theme_score(self):
        base = build_loo_theme_live(self._frames(1.0), self._snapshot(), source_universe_total=10)
        shocked = build_loo_theme_live(self._frames(4.0), self._snapshot(), source_universe_total=10)
        self.assertEqual(base["status"], "LIVE_CURRENT_TAXONOMY")
        self.assertEqual(base["taxonomy"], "CURRENT_S2T_NOT_PIT")
        a0 = base["stocks"]["A"]["selected"]
        a1 = shocked["stocks"]["A"]["selected"]
        self.assertIsNotNone(a0)
        self.assertIsNotNone(a1)
        self.assertEqual(base["stocks"]["A"]["memberships"], 2)
        self.assertAlmostEqual(a0["peer_theme_score"], a1["peer_theme_score"], places=4)
        self.assertAlmostEqual(a0["theme_rs63_pct"], a1["theme_rs63_pct"], places=4)
        self.assertAlmostEqual(a0["theme_acceleration_pct"], a1["theme_acceleration_pct"], places=4)
        self.assertAlmostEqual(a0["theme_breadth21"], a1["theme_breadth21"], places=4)

    def test_pr_smoke_cap_never_claims_live_full_status(self):
        out = build_loo_theme_live(
            self._frames(), self._snapshot(), source_universe_total=1000, full_download_requested=False
        )
        self.assertEqual(out["status"], "PARTIAL_SMOKE_ONLY")


if __name__ == "__main__":
    unittest.main()
