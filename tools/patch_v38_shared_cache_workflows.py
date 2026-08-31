#!/usr/bin/env python3
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


def patch_dashboard() -> None:
    path = Path('.github/workflows/dashboard.yml')
    text = path.read_text(encoding='utf-8')
    text = replace_once(
        text,
        "      - 'build_v38_strict_loo_live.py'\n      - 'build_v38_tqqq_live.py'\n      - 'build_v38_sleeve_live.py'\n",
        "      - 'build_v38_strict_loo_live.py'\n      - 'build_v38_strict_loo_with_cache.py'\n      - 'build_v38_tqqq_live.py'\n      - 'build_v38_sleeve_live.py'\n      - 'build_v38_sleeve_live_from_cache.py'\n",
        'dashboard push paths',
    )
    text = replace_once(
        text,
        "          python -m py_compile build_dashboard.py build_v38_companion.py build_v38_strict_loo_live.py build_v38_tqqq_live.py build_v38_sleeve_live.py v38_rules.py\n",
        "          python -m py_compile build_dashboard.py build_v38_companion.py build_v38_strict_loo_live.py build_v38_strict_loo_with_cache.py build_v38_tqqq_live.py build_v38_sleeve_live.py build_v38_sleeve_live_from_cache.py v38_rules.py\n",
        'dashboard compile',
    )
    text = replace_once(
        text,
        "          python build_v38_strict_loo_live.py \\\n            --state state.json \\\n",
        "          V38_SHARED_PRICE_CACHE=v38-shared-price-cache.pkl python build_v38_strict_loo_with_cache.py \\\n            --state state.json \\\n",
        'strict loo shared cache call',
    )
    text = replace_once(
        text,
        "          python build_v38_sleeve_live.py \\\n            --companion v38-live-state.json \\\n",
        "          V38_SHARED_PRICE_CACHE=v38-shared-price-cache.pkl python build_v38_sleeve_live_from_cache.py \\\n            --companion v38-live-state.json \\\n",
        'sleeve shared cache call',
    )
    old_validation = '''          if sleeve.get("status") == "READY":
              for key in ("normal_stock", "rsi_reset"):
                  if (sleeve.get(key) or {}).get("desired_pct") is None:
                      raise SystemExit(f"READY sleeve is missing desired_pct: {key}")
              if tqqq.get("sleeve_live_status") != "READY":
                  raise SystemExit("READY sleeves were not merged into TQQQ state")
              if tqqq.get("normal_stock_desired_pct") is None or tqqq.get("reset_desired_pct") is None:
                  raise SystemExit("merged Gross100 sleeve inputs are missing")
'''
    new_validation = '''          if sleeve.get("status") != "READY":
              raise SystemExit(f"V38 live sleeves are not READY: {sleeve.get('reason')}")
          for key in ("normal_stock", "rsi_reset"):
              if (sleeve.get(key) or {}).get("desired_pct") is None:
                  raise SystemExit(f"READY sleeve is missing desired_pct: {key}")
          if tqqq.get("sleeve_live_status") != "READY":
              raise SystemExit("READY sleeves were not merged into TQQQ state")
          if tqqq.get("normal_stock_desired_pct") is None or tqqq.get("reset_desired_pct") is None:
              raise SystemExit("merged Gross100 sleeve inputs are missing")
          gross = companion.get("gross100_allocation") or {}
          if gross.get("status") != "LIVE ALLOCATION READY":
              raise SystemExit(f"Gross100 live allocation is not READY: {gross.get('status')}")
          if gross.get("gross_allocated_pct") is None or float(gross["gross_allocated_pct"]) > 100.000001:
              raise SystemExit(f"invalid Gross100 allocation: {gross.get('gross_allocated_pct')}")
'''
    text = replace_once(text, old_validation, new_validation, 'sleeve hard READY validation')
    text = replace_once(
        text,
        "build_dashboard.py build_v38_companion.py build_v38_strict_loo_live.py build_v38_tqqq_live.py build_v38_sleeve_live.py v38-normal-sleeve-seed.json",
        "build_dashboard.py build_v38_companion.py build_v38_strict_loo_live.py build_v38_strict_loo_with_cache.py build_v38_tqqq_live.py build_v38_sleeve_live.py build_v38_sleeve_live_from_cache.py v38-normal-sleeve-seed.json",
        'source drift guard',
    )
    path.write_text(text, encoding='utf-8')


def patch_audit() -> None:
    path = Path('.github/workflows/v38-audit-check.yml')
    text = path.read_text(encoding='utf-8')
    text = replace_once(
        text,
        "      - 'build_v38_strict_loo_live.py'\n      - 'build_v38_tqqq_live.py'\n      - 'build_v38_sleeve_live.py'\n",
        "      - 'build_v38_strict_loo_live.py'\n      - 'build_v38_strict_loo_with_cache.py'\n      - 'build_v38_tqqq_live.py'\n      - 'build_v38_sleeve_live.py'\n      - 'build_v38_sleeve_live_from_cache.py'\n",
        'audit paths',
    )
    text = replace_once(
        text,
        "            build_v38_strict_loo_live.py \\\n            build_v38_tqqq_live.py \\\n            build_v38_sleeve_live.py \\\n",
        "            build_v38_strict_loo_live.py \\\n            build_v38_strict_loo_with_cache.py \\\n            build_v38_tqqq_live.py \\\n            build_v38_sleeve_live.py \\\n            build_v38_sleeve_live_from_cache.py \\\n",
        'audit compile',
    )
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    patch_dashboard()
    patch_audit()
    print('patched dashboard and audit workflows')
