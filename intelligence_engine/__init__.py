"""Investment Intelligence Engine.

A sidecar data and scoring layer. It intentionally does not import or mutate the
legacy dashboard builder.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Type

__all__ = ["__version__"]
__version__ = "0.1.0"


_RESEARCH_COMMAND = any(
    str(argument).endswith("intelligence_engine.research_pipeline")
    or "research_pipeline" in str(argument)
    for argument in sys.argv
)
_RESEARCH_FAILED = False
_RESEARCH_ERROR_PATH = Path("private/research-error-detail.json")
_ORIGINAL_EXCEPTOOK = sys.excepthook


def _safe_error_template(error: BaseException) -> str:
    """Return a useful error shape without persisting ticker or financial values."""
    text = str(error).replace("\n", " ").strip()
    text = re.sub(r"/home/runner/[^\s:]+", "<path>", text)
    text = re.sub(r"'[^']{1,120}'", "'<value>'", text)
    text = re.sub(r'"[^"]{1,120}"', '"<value>"', text)
    return text[:500] or type(error).__name__


def _research_excepthook(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    global _RESEARCH_FAILED
    _RESEARCH_FAILED = True
    try:
        frames = []
        for frame in traceback.extract_tb(exc_traceback):
            normalized = frame.filename.replace("\\", "/")
            if "/intelligence_engine/" not in normalized:
                continue
            frames.append(
                {
                    "module": Path(normalized).name,
                    "function": frame.name,
                    "line": int(frame.lineno),
                }
            )
        payload = {
            "schema_version": "1.0",
            "error_type": exc_type.__name__,
            "error_template": _safe_error_template(exc_value),
            "frames": frames[-12:],
            "privacy": "No ticker, price, portfolio or financial values are persisted.",
        }
        _RESEARCH_ERROR_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RESEARCH_ERROR_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    _ORIGINAL_EXCEPTOOK(exc_type, exc_value, exc_traceback)


def _remove_stale_research_error() -> None:
    if _RESEARCH_COMMAND and not _RESEARCH_FAILED:
        try:
            _RESEARCH_ERROR_PATH.unlink(missing_ok=True)
        except OSError:
            pass


if _RESEARCH_COMMAND and os.environ.get("V38_DISABLE_RESEARCH_ERROR_HOOK") != "1":
    sys.excepthook = _research_excepthook
    atexit.register(_remove_stale_research_error)
