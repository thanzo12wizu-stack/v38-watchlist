from pathlib import Path

import pandas as pd

from tools import build_options_positioning as options


def test_data_confidence_is_data_depth_not_legacy_ok():
    assert options._data_confidence(400, 20, 200, 200)[0] == "LOW"
    assert options._data_confidence(2_000, 12, 1_200, 800)[0] == "MEDIUM"
    assert options._data_confidence(20_000, 40, 12_000, 8_000)[0] == "HIGH"


def test_wall_concentration_matches_the_directional_displayed_side():
    gex = pd.DataFrame(
        {
            "kind": ["C", "C", "C", "P", "P", "P"],
            "strike": [90.0, 105.0, 110.0, 90.0, 95.0, 110.0],
            "gex": [1_000.0, 300.0, 100.0, -200.0, -600.0, -2_000.0],
        }
    )
    call_share, _ = options._wall_concentration(gex, "C", spot=100.0)
    put_share, _ = options._wall_concentration(gex, "P", spot=100.0)

    assert call_share == 0.75  # ignores the stronger but wrong-side 90 Call
    assert put_share == 0.75  # ignores the stronger but wrong-side 110 Put


def test_options_copy_describes_proxy_and_atr_units():
    base = Path(options.__file__).read_text(encoding="utf-8")
    directional = Path("tools/build_options_positioning_directional.py").read_text(
        encoding="utf-8"
    )
    renderer = Path("tools/render_options_html.py").read_text(encoding="utf-8")

    assert "OI×推定Gamma" in base
    assert "実ディーラーGammaではない" in base
    assert "ATR。" in directional
    assert "値動き{days:.1f}日分" not in directional
    assert "Call GEX集中帯" in renderer
    assert "Put GEX集中帯" in renderer
    assert "Gamma Flip推定" in renderer


def test_options_workflow_watches_every_options_source_file():
    workflow = Path(".github/workflows/options.yml").read_text(encoding="utf-8")
    for path in (
        "tools/build_options_positioning.py",
        "tools/build_options_positioning_directional.py",
        "tools/render_options_html.py",
    ):
        assert path in workflow
