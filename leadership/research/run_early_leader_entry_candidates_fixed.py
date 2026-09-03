from __future__ import annotations

import pandas as pd


def _df_between(self: pd.DataFrame, left, right, inclusive: str = "both") -> pd.DataFrame:
    if inclusive == "both":
        return (self >= left) & (self <= right)
    if inclusive == "left":
        return (self >= left) & (self < right)
    if inclusive == "right":
        return (self > left) & (self <= right)
    if inclusive == "neither":
        return (self > left) & (self < right)
    raise ValueError(f"invalid inclusive={inclusive!r}")


# pandas DataFrame has no between(); the research script intentionally applies
# the scalar bounds elementwise across a DataFrame. Patch only this research run.
pd.DataFrame.between = _df_between  # type: ignore[attr-defined]

import audit_early_leader_entry_candidates as audit


if __name__ == "__main__":
    audit.main()
