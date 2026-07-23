from __future__ import annotations

"""Compatibility package for the production research runner.

The original implementation remains in ``intelligence_engine/research_pipeline.py``
for source compatibility.  Python prefers this package when executing
``python -m intelligence_engine.research_pipeline``; public attributes are
re-exported from the original module so existing imports and tests keep working.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_legacy() -> ModuleType:
    name = "intelligence_engine._research_pipeline_legacy"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    source = Path(__file__).resolve().parent.parent / "research_pipeline.py"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load legacy research pipeline from {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = _load_legacy()

for _name in dir(legacy):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(legacy, _name))

__all__ = [name for name in dir(legacy) if not name.startswith("_")]
