from __future__ import annotations

from intelligence_engine import _safe_error_template


def test_research_error_template_redacts_values_and_runner_paths() -> None:
    message = "failed for 'SECRET_TICKER' at /home/runner/work/private/file.py using \"123.45\""
    sanitized = _safe_error_template(message)
    assert "SECRET_TICKER" not in sanitized
    assert "123.45" not in sanitized
    assert "/home/runner/" not in sanitized
    assert "<path>" in sanitized
    assert "<value>" in sanitized
