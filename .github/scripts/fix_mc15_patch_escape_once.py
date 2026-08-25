from pathlib import Path

p = Path('.github/scripts/implement_mc15_once.py')
s = p.read_text(encoding='utf-8')
old = r'''            sys.stderr.write("[mc15] daily_log MRI migration skipped: %r\n" % (repr(_e)[:100],))'''
new = r'''            sys.stderr.write("[mc15] daily_log MRI migration skipped: %r" % (repr(_e)[:100],))'''
if s.count(old) != 1:
    raise SystemExit(f'escape-fix target count={s.count(old)}')
p.write_text(s.replace(old, new), encoding='utf-8')
print('MC15 patch-script escape fixed')
