from __future__ import annotations

import argparse
from pathlib import Path

from .score_policy import validate_score_policy


REQUIRED_FILES = (
    "intelligence_engine/ARCHITECTURE.md",
    "intelligence_engine/README.md",
    "intelligence_engine/pipeline.py",
    "intelligence_engine/scoring.py",
    "intelligence_engine/score_policy.py",
    "intelligence_engine/validate_inputs.py",
    "intelligence_engine/validate_outputs.py",
    "intelligence_engine/validation.py",
    ".github/workflows/intelligence-engine.yml",
    "tests/test_intelligence_engine.py",
)

FORBIDDEN_IMPORTS = ("import build_dashboard", "from build_dashboard")


def run(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).exists():
            errors.append(f"missing required file: {relative}")
    errors.extend(validate_score_policy())
    package = root / "intelligence_engine"
    if package.exists():
        for path in package.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_IMPORTS:
                if forbidden in text:
                    errors.append(f"legacy dashboard dependency in {path.name}: {forbidden}")
    workflow = root / ".github/workflows/intelligence-engine.yml"
    if workflow.exists():
        text = workflow.read_text(encoding="utf-8")
        for token in ("pull_request:", "validate generated contract", "data/intelligence"):
            if token.lower() not in text.lower():
                errors.append(f"workflow missing safety token: {token}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Static release gate for the intelligence sidecar")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    errors = run(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("INTELLIGENCE RELEASE CHECK OK")


if __name__ == "__main__":
    main()
