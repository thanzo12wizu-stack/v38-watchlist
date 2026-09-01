from pathlib import Path

path = Path('leadership/research/rotation_theme56_holdings_expansion.py')
text = path.read_text(encoding='utf-8')

old_dict = '''    "NO": ".OL", "SS": ".ST",\n}'''
new_dict = '''    "NO": ".OL", "SS": ".ST",\n    "SP": ".SI", "TB": ".BK", "BZ": ".SA", "MK": ".KL", "IJ": ".JK",\n    "C1": ".SS", "C2": ".SZ",\n}'''
if old_dict not in text:
    raise SystemExit('SPACE_SUFFIX dictionary anchor not found')
text = text.replace(old_dict, new_dict, 1)

old_re = '''(KS|KQ|HK|JP|JT|TT|GR|GY|SW|NA|LN|FH|IM|FP|DC|PL|CN|IT|AU|SJ|NO|SS)'''
new_re = '''(KS|KQ|HK|JP|JT|TT|GR|GY|SW|NA|LN|FH|IM|FP|DC|PL|CN|IT|AU|SJ|NO|SS|SP|TB|BZ|MK|IJ|C1|C2)'''
if old_re not in text:
    raise SystemExit('space suffix regex anchor not found')
text = text.replace(old_re, new_re, 1)

old_cash = '''    if not raw or raw in {"NAN", "--", "-", "CASH&OTHER", "CASH"}:\n        return ""\n'''
new_cash = '''    if not raw or raw in {"NAN", "--", "-", "CASH&OTHER", "CASH"} or "CASH" in raw:\n        return ""\n'''
if old_cash not in text:
    raise SystemExit('cash guard anchor not found')
text = text.replace(old_cash, new_cash, 1)

path.write_text(text, encoding='utf-8')
print('patched', path)
