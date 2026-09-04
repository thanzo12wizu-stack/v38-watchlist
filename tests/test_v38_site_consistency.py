from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_reset_active_count_comes_from_positions():
    text = (ROOT / "build_v38_sleeve_live.py").read_text(encoding="utf-8")
    assert '"active_positions": len(reset.get("positions", []))' in text

def test_companion_exposes_reset_positions():
    text = (ROOT / "build_v38_companion.py").read_text(encoding="utf-8")
    assert '"positions": [dict(p) for p in reset_sleeve.get("positions", [])' in text

def test_v38_ui_uses_production_rotation_and_names_reset_holdings():
    text = (ROOT / "command-center-v38.html").read_text(encoding="utf-8")
    assert "rotation/data/rotation-theme56.json" in text
    assert "research/rotation-exact-flow-internals" not in text
    assert 'id="resetHoldingRows"' in text
    assert 'id="resetFreeSlots"' in text
    assert "正式保有 ${resetNames.join(' / ')}" in text
    assert "空き枠があっても追加買いしません" in text
