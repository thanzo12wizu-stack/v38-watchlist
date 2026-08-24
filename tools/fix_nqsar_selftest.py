#!/usr/bin/env python3
from pathlib import Path

p = Path("build_dashboard.py")
s = p.read_text(encoding="utf-8")
old = 'if "トレンド判定" not in html: errs.append("trend pill missing")'
new = 'if "NQSAR（短期）" not in html: errs.append("trend pill missing")'
if new in s:
    print("NQSAR selftest already fixed")
elif old in s:
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print("NQSAR selftest fixed")
else:
    raise SystemExit("target selftest assertion not found")
