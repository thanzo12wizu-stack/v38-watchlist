from __future__ import annotations

import validate_theme_ltr as core

_original_importance = core.importance

def _importance_compat(models, test):
    first = next(iter(models.values()))
    features = list(first.feature_name_)
    return _original_importance(models, test, features)

core.importance = _importance_compat

if __name__ == '__main__':
    core.main()
