from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

TICKERS = ["CIBR", "GRID", "WCLD", "PHO", "TAN", "PKB", "PEJ", "BLOK", "IBUY", "BOAT", "WGMI", "JETS"]
BASE = "https://api-prod.etf.com/private/fund/{ticker}/holdings"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Origin": "https://www.etf.com",
    "Referer": "https://www.etf.com/",
}

VARIANTS = [
    ("base", {"type": "securities", "formatValues": "true"}, {}),
    ("limit500", {"type": "securities", "formatValues": "true", "limit": "500"}, {}),
    ("pageSize500", {"type": "securities", "formatValues": "true", "pageSize": "500"}, {}),
    ("size500", {"type": "securities", "formatValues": "true", "size": "500"}, {}),
    ("offset_limit", {"type": "securities", "formatValues": "true", "offset": "0", "limit": "500"}, {}),
    ("xlimit", {"type": "securities", "formatValues": "true"}, {"x-limit": "500"}),
    ("xlimit_offset", {"type": "securities", "formatValues": "true"}, {"x-limit": "500", "x-offset": "0"}),
    ("page1_limit500", {"type": "securities", "formatValues": "true", "page": "1", "limit": "500"}, {}),
]


def summarize(obj: Any) -> dict[str, Any]:
    lists = []
    scalars = []

    def walk(x: Any, path: str = "$", depth: int = 0) -> None:
        if depth > 7:
            return
        if isinstance(x, list):
            rows = [r for r in x if isinstance(r, dict)]
            symbolish = sum(1 for r in rows if any(str(k).lower() in {"symbol", "ticker", "securitysymbol", "holdingsymbol"} for k in r))
            lists.append({"path": path, "length": len(x), "dict_rows": len(rows), "symbolish_rows": symbolish})
            for i, item in enumerate(x[:2]):
                walk(item, f"{path}[{i}]", depth + 1)
        elif isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}"
                if isinstance(v, (dict, list)):
                    walk(v, p, depth + 1)
                elif any(token in str(k).lower() for token in ("count", "total", "page", "limit", "offset", "size")):
                    scalars.append({"path": p, "value": v})

    walk(obj)
    lists.sort(key=lambda z: (z["symbolish_rows"], z["length"]), reverse=True)
    return {"lists": lists[:15], "paging_scalars": scalars[:30]}


def main() -> None:
    out = Path("leadership/research/rotation_theme56_etfcom_holdings_paging_probe")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    report = {"schema": 1, "tickers": {}}
    for ticker in TICKERS:
        trows = []
        for name, params, extra_headers in VARIANTS:
            url = BASE.format(ticker=ticker) + "?" + urlencode(params)
            try:
                r = session.get(url, headers={**HEADERS, **extra_headers}, timeout=35)
                status = r.status_code
                r.raise_for_status()
                obj = r.json()
                s = summarize(obj)
                trows.append({"variant": name, "status_code": status, **s})
            except Exception as exc:
                trows.append({"variant": name, "error": f"{type(exc).__name__}: {exc}"})
        report["tickers"][ticker] = trows
        best = max((max((x.get("symbolish_rows", 0) for x in row.get("lists", [])), default=0), row.get("variant")) for row in trows)
        print(json.dumps({"ticker": ticker, "best_symbolish": best[0], "best_variant": best[1]}, ensure_ascii=False), flush=True)
    (out / "paging_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
