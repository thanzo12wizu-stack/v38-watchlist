from __future__ import annotations

SCORE_POLICY_VERSION = "1.0.1"

SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "momentum": {"r63": .25, "r126": .30, "r189": .25, "r252": .10, "high": .10},
    "fundamental": {"eps": .20, "epsa": .22, "rev": .18, "reva": .20, "opm": .10, "fcf": .10},
    "improvement": {"r63": .25, "r126": .20, "r189": .10, "epsa": .25, "reva": .20},
    "leadership": {"sector": .45, "industry": .55},
    "quality": {"gross": .20, "op": .30, "fcf": .30, "shares": .20},
    "candidate": {"momentum": .30, "fundamental": .30, "improvement": .20, "leadership": .10, "quality": .10},
    "emerging": {"improvement": .45, "fundamental": .35, "momentum": .20},
    "compounder": {"fundamental": .45, "quality": .35, "momentum": .20},
    "breakout": {"momentum": .50, "volume": .25, "high": .25},
    "turnaround": {"improvement": .60, "fundamental": .25, "momentum": .15},
}


def validate_score_policy() -> list[str]:
    errors: list[str] = []
    for name, weights in SCORE_WEIGHTS.items():
        if not weights:
            errors.append(f"{name}: no weights")
            continue
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-9:
            errors.append(f"{name}: weights sum to {total:.12f}, expected 1")
        for key, value in weights.items():
            if value < 0:
                errors.append(f"{name}.{key}: negative weight")
    return errors
