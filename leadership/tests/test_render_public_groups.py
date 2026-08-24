from __future__ import annotations

import unittest

from leadership.render_public import render_public_html


class PublicGroupVisibilityTests(unittest.TestCase):
    def _model(self):
        groups = []
        for i in range(1, 11):
            groups.append({
                "name": f"Active Group {i}",
                "sector": "Technology Services",
                "phase": "EMERGING" if i % 2 else "LEADING",
                "score": 90 - i,
                "pioneer_score": 92 - i,
                "breadth_score": 65 + i,
                "top_acceleration": 7.0 if i % 2 else 1.0,
                "positive_accel_share": 70.0,
                "leader_breakouts": i % 3,
                "leaders": 2 + i,
                "pioneers": 1,
                "leader_density": 25.0,
                "acceleration": 5.0,
                "stocks": [],
            })
        groups.append({
            "name": "Medical - Development Biotech",
            "sector": "Health Technology",
            "phase": "LOSING",
            "score": 55.0,
            "pioneer_score": 60.0,
            "breadth_score": 50.0,
            "top_acceleration": -6.0,
            "positive_accel_share": 30.0,
            "leader_breakouts": 0,
            "leaders": 1,
            "pioneers": 0,
            "leader_density": 5.0,
            "acceleration": -2.0,
            "stocks": [],
        })
        return {
            "market": {"status": "GO", "mri": 72.6, "gate": "Green", "ftd": "FTD_ACTIVE", "asof": "2026-08-21"},
            "coverage": {"market_asof": "2026-08-21", "rs63": 3762, "confidence": "HIGH", "metric_source": "leadership/market_snapshot.json", "stocks": 3843, "groups": 11, "entry_inputs": 3809},
            "sectors": [],
            "groups": groups,
            "actionable": [],
            "waiting": [],
        }

    def test_rotation_sections_show_active_groups_beyond_first_screen(self):
        page = render_public_html(self._model())
        self.assertIn("今の資金移動", page)
        self.assertIn("急浮上", page)
        self.assertIn("主導中", page)
        self.assertIn('data-group="Active Group 9"', page)
        self.assertIn('data-group="Active Group 10"', page)
        self.assertNotIn("Pioneer 81.0", page)

    def test_inactive_industry_group_remains_inspectable(self):
        page = render_public_html(self._model())
        self.assertIn("失速グループを見る（1）", page)
        self.assertIn('data-group="Medical - Development Biotech"', page)
        self.assertIn("細分類Industry Group", page)


if __name__ == "__main__":
    unittest.main()
