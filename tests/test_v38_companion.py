import json

from build_v38_companion import build_state


def test_companion_reads_legacy_without_rewriting_and_fails_closed_for_attack_theme(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5 if i < 26 else -5, "rs189": 90, "rs": 90,
            "sth": "Theme A",
        }
    source = tmp_path / "command-center.html"
    original = (f'<script>window.CALC={json.dumps(calc)};</script>'
                f'<script>window.DET={json.dumps(det)};</script>')
    source.write_text(original, encoding="utf-8")
    state = build_state(source)
    assert source.read_text(encoding="utf-8") == original
    assert state["market"]["mode"] == "ATTACK"
    assert state["market"]["breadth50"] == 65
    assert state["ranking"]["mode"] == "LOO_THEME30_DATA_REQUIRED"
    assert state["candidates"][0]["peer_theme_score"] is None


def test_companion_selective_uses_rs189_and_never_theme_approximation(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {}
    for i in range(40):
        det[f"T{i}"] = {
            "px": 100, "dvol": 20, "ma5020": True, "v200": 5,
            "v50": 5 if i < 22 else -5, "rs189": 99 - i / 10,
            "rs": 90, "sth": "Theme A",
        }
    source = tmp_path / "legacy.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["market"]["mode"] == "SELECTIVE"
    assert state["ranking"]["mode"] == "RS189_ONLY"
    assert state["candidates"][0]["final_rank"] == 1


def test_companion_coverage_guard_stops_new_entries(tmp_path):
    calc = {"asof": "2026-08-28", "color": "Green"}
    det = {f"T{i}": {"v50": 1 if i < 10 else None} for i in range(40)}
    source = tmp_path / "legacy.html"
    source.write_text(
        f'<script>window.CALC={json.dumps(calc)};</script>'
        f'<script>window.DET={json.dumps(det)};</script>', encoding="utf-8")
    state = build_state(source)
    assert state["market"]["mode"] == "STOP"
    assert not state["market"]["coverage_ok"]
