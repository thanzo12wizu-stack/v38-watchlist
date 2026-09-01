#!/usr/bin/env python3
from pathlib import Path
p = Path('tests/test_v38_sleeve_live.py')
s = p.read_text(encoding='utf-8')
if 'import pandas as pd' not in s:
    s = s.replace('from pathlib import Path\n', 'from pathlib import Path\n\nimport pandas as pd\n', 1)
p.write_text(s, encoding='utf-8')
