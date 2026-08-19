from pathlib import Path

p = Path("build_dashboard.py")
s = p.read_text(encoding="utf-8")

old = '''    ipo = ipo_recent(m)\n    keep = elig & (entry_worthy(m) | ipo) & \\\n        ((loc_roll & ((rs >= MULTI_VWAP_RS189_MIN) | ipo)) | loc_all)\n'''
new = '''    ipo = ipo_recent(m)\n    # 63/252 VWAP keep the existing leader/IPO gate.\n    keep_roll = elig & (entry_worthy(m) | ipo) & loc_roll & \\\n        ((rs >= MULTI_VWAP_RS189_MIN) | ipo)\n    # Inception VWAP is independent of RS189/short-term leadership.\n    # Use the existing base quality/liquidity/security gate only.\n    keep_all = setup_eligible_core(m) & loc_all\n    keep = keep_roll | keep_all\n'''

count = s.count(old)
if count != 1:
    raise SystemExit(f"expected exact Multi VWAP gate once, found {count}")
s = s.replace(old, new, 1)

# Regression invariants: do not disturb existing VWAP semantics or 63/252 threshold.
assert '_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))' in s
assert 'MULTI_VWAP_RS189_MIN' in s
assert 'keep_all = setup_eligible_core(m) & loc_all' in s

p.write_text(s, encoding="utf-8")
print("MULTI_VWAP_INCEPTION_GATE_FIXED")
