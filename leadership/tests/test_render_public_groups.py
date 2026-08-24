from __future__ import annotations

import unittest

from leadership.render_public import render_public_html


class PublicGroupVisibilityTests(unittest.TestCase):
    def _model(self):
        groups = []
        for i in range(1, 11):
            groups.append({
                "name": f"Active Group {i}",
                "phase": "EMERGING" if i % 2 else "LEADING",
                "score": 90 - i,
                "pioneer_score": 92 - i,
                "breadth_score": 65 + i,
                "leader_breakouts": i % 3,
                "leaders": 2 + i,
                "leader_density": 25.0,
                "acceleration": 5.0,
                "stocks": [],
            })
        groups.append({
            "name": "Medical - Development Biotech",
            "phase": "LOSING",
            "score": 55.0,
            "pioneer_score": 60.0,
            "breadth_score": 50.0,
            "leader_breakouts": 0,
            "leaders": 1,
            "leader_density": 5.0,
            "acceleration": -2.0,
            "stocks": [],
        })
        return {
            "market": {"status": "GO", "mri": 72.6, "gate": "Green", "ftd": "FTD_ACTIVE", "asof": "2026-08-21"},
            "coverage": {"market_asof": "2026-08-21", "rs63": 3762, "confidence": "HIGH", "metric_source": "leadership/market_snapshot.json", "stocks": 3843, "entry_inputs": 3809},
            "sectors": [],
            "groups": groups,
            "actionable": [],
            "waiting": [],
        }

    def test_active_groups_beyond_top_eight_are_visible(self):
        page = render_public_html(self._model())
        self.assertIn("全主導グループ", page)
        self.assertIn('data-group="Active Group 9"', page)
        self.assertIn('data-group="Active Group 10"', page)
        self.assertIn("P 83", page)
        self.assertIn("BO", page)

    def test_every_industry_group_is_inspectable_even_when_inactive(self):
        page = render_public_html(self._model())
        self.assertIn("全Industry Group（11）", page)
        self.assertIn('data-group="Medical - Development Biotech"', page)
        self.assertIn("新興・主導を上限なしで表示", page)


if __name__ == "__main__":
    unittest.main()
