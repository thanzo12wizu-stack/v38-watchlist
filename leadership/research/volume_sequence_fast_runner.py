from __future__ import annotations

import validate_dynamic_pioneer_followthrough as dpf
import validate_volume_sequence as vs
from dynamic_followthrough_fast_patch import build_followthrough_rows_fast

if __name__ == "__main__":
    dpf.build_followthrough_rows = build_followthrough_rows_fast
    vs.dpf.build_followthrough_rows = build_followthrough_rows_fast
    vs.main()
