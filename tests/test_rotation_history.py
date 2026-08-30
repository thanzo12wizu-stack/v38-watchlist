import json

from build_v38_companion import build_state


def test_rotation_history_is_never_inferred_without_exact_route(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"v50": 1, "sec": "Healthcare", "sth": "Biotech", "rs189": 80, "rs": 78} for i in range(40)}
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["rotation_intelligence"]["history"]["status"] == "DATA_REQUIRED"
    assert state["rotation_intelligence"]["sector_groups"][0]["history"]["status"] == "DATA_REQUIRED"


def test_exact_rotation_history_exposes_only_supplied_dated_events(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"v50": 1, "sec": "Healthcare", "sth": "Biotech", "rs189": 80, "rs": 78} for i in range(40)}
    source = tmp_path / "command-center.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    (tmp_path / "rotation-history.json").write_text(json.dumps({
        "groups": {
            "Healthcare": {
                "exact": True,
                "asof": "2026-08-28",
                "source": "fixture",
                "changes": {"price_5d": 8, "internal_5d": 12},
                "events": [
                    {"date": "2026-08-21", "type": "INTERNAL_TURNED_UP", "detail": "EW internal slope changed positive"},
                    {"date": "2026-08-25", "type": "PRICE_CONFIRMED", "detail": "price score crossed configured research level"},
                ],
            }
        }
    }), encoding="utf-8")
    state = build_state(source)
    history = state["rotation_intelligence"]["history"]
    group = state["rotation_intelligence"]["sector_groups"][0]
    assert history["status"] == "EXACT"
    assert history["exact_groups"] == 1
    assert group["history"]["events"][0]["date"] == "2026-08-21"
    assert group["history"]["changes"]["internal_5d"] == 12.0
