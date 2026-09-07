from __future__ import annotations

import json
from pathlib import Path


def shape(value, depth=0):
    if depth >= 3:
        if isinstance(value, dict):
            return {"type": "dict", "len": len(value), "keys": list(value)[:12]}
        if isinstance(value, list):
            return {"type": "list", "len": len(value), "sample_type": type(value[0]).__name__ if value else None}
        return {"type": type(value).__name__, "value": value if isinstance(value, (str, int, float, bool, type(None))) else None}
    if isinstance(value, dict):
        return {"type": "dict", "len": len(value), "sample": {str(k): shape(v, depth + 1) for k, v in list(value.items())[:8]}}
    if isinstance(value, list):
        return {"type": "list", "len": len(value), "sample": [shape(v, depth + 1) for v in value[:3]]}
    return {"type": type(value).__name__, "value": value if isinstance(value, (str, int, float, bool, type(None))) else None}


def main():
    p = Path("v38-strict-loo-history.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    print("TOP", json.dumps(shape(data), ensure_ascii=False))
    if isinstance(data, dict):
        for key in data:
            v = data[key]
            if isinstance(v, dict):
                keys = list(v)
                print("DICT", key, "len", len(v), "first", keys[:5], "last", keys[-5:])
            elif isinstance(v, list):
                print("LIST", key, "len", len(v))
                if v:
                    print("LIST_FIRST", key, json.dumps(shape(v[0]), ensure_ascii=False))
                    print("LIST_LAST", key, json.dumps(shape(v[-1]), ensure_ascii=False))
            else:
                print("SCALAR", key, repr(v))


if __name__ == "__main__":
    main()
