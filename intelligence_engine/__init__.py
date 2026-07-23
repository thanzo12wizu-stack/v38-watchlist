"""Investment Intelligence Engine.

A sidecar data and scoring layer. It intentionally does not import or mutate the
legacy dashboard builder.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Type

__all__ = ["__version__"]
__version__ = "0.1.0"


def _is_research_command(arguments: list[str]) -> bool:
    for argument in arguments:
        text = str(argument).replace("\\", "/")
        name = Path(text).name
        stem = Path(text).stem
        if "intelligence_engine.research_pipeline" in text:
            return True
        if name == "research_pipeline.py" or stem == "research_pipeline":
            return True
    return False


_RESEARCH_COMMAND = _is_research_command(list(sys.argv))
_RESEARCH_FAILED = False
_RESEARCH_ERROR_PATH = Path("private/research-error-detail.json")
_ORIGINAL_EXCEPTOOK = sys.excepthook
_ORIGINAL_EXIT = sys.exit


def _safe_error_template(error: BaseException | str) -> str:
    """Return a useful error shape without persisting ticker or financial values."""
    text = str(error).replace("\n", " ").strip()
    text = re.sub(r"/home/runner/[^\s:]+", "<path>", text)
    text = re.sub(r"'[^']{1,120}'", "'<value>'", text)
    text = re.sub(r'"[^"]{1,120}"', '"<value>"', text)
    return text[:500] or type(error).__name__


def _write_research_failure(payload: dict) -> None:
    try:
        document = {
            "schema_version": "1.1",
            **payload,
            "privacy": "No ticker, price, portfolio or financial values are persisted.",
        }
        _RESEARCH_ERROR_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RESEARCH_ERROR_PATH.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _research_excepthook(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    global _RESEARCH_FAILED
    _RESEARCH_FAILED = True
    frames = []
    try:
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
    except Exception:
        frames = []
    _write_research_failure(
        {
            "failure_kind": "uncaught_exception",
            "error_type": exc_type.__name__,
            "error_template": _safe_error_template(exc_value),
            "frames": frames[-12:],
        }
    )
    _ORIGINAL_EXCEPTOOK(exc_type, exc_value, exc_traceback)


def _research_exit(code: object = 0) -> None:
    global _RESEARCH_FAILED
    numeric = code if isinstance(code, int) else 1
    if numeric not in (0, None):
        _RESEARCH_FAILED = True
        _write_research_failure(
            {
                "failure_kind": "system_exit",
                "error_type": "SystemExit",
                "exit_code": int(numeric),
                "error_template": _safe_error_template(code),
                "frames": [],
            }
        )
    _ORIGINAL_EXIT(code)


def _research_signal(signum: int, _frame: object) -> None:
    global _RESEARCH_FAILED
    _RESEARCH_FAILED = True
    try:
        name = signal.Signals(signum).name
    except ValueError:
        name = f"SIGNAL_{signum}"
    _write_research_failure(
        {
            "failure_kind": "signal",
            "error_type": name,
            "signal": int(signum),
            "error_template": f"Research process terminated by {name}",
            "frames": [],
        }
    )
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _remove_stale_research_error() -> None:
    if _RESEARCH_COMMAND and not _RESEARCH_FAILED:
        try:
            _RESEARCH_ERROR_PATH.unlink(missing_ok=True)
        except OSError:
            pass


if _RESEARCH_COMMAND and os.environ.get("V38_DISABLE_RESEARCH_ERROR_HOOK") != "1":
    sys.excepthook = _research_excepthook
    sys.exit = _research_exit
    for _signal in (signal.SIGTERM, signal.SIGINT, signal.SIGABRT):
        try:
            signal.signal(_signal, _research_signal)
        except (OSError, RuntimeError, ValueError):
            pass
    atexit.register(_remove_stale_research_error)
