from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SEC_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
TICKER_COLUMN_ALIASES = ("ticker", "symbol", "シンボル", "ティッカー")


def _request(url: str) -> urllib.request.Request:
    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is required")
    # urllib does not transparently decode gzip transfer encoding. Requesting
    # identity prevents a gzip-wrapped ZIP from being saved as a broken .zip.
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/zip, application/json;q=0.9, */*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )


def _open_with_retry(url: str, *, timeout: int, attempts: int = 4):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(_request(url), timeout=timeout)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(30, 2**attempt))
    detail = type(last_error).__name__
    if isinstance(last_error, urllib.error.HTTPError):
        detail = f"HTTPError:{last_error.code}"
    raise RuntimeError(f"SEC request failed after {attempts} attempts: {detail}") from last_error


def download(url: str, target: Path) -> dict[str, int | str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    bytes_written = 0
    try:
        with _open_with_retry(url, timeout=300) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                bytes_written += len(chunk)
        if bytes_written <= 0:
            raise RuntimeError("SEC bulk download returned an empty body")
        with zipfile.ZipFile(temporary) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"SEC ZIP integrity check failed at {bad_member}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"url": url, "bytes": bytes_written, "target": str(target)}


def ticker_to_cik() -> dict[str, int]:
    with _open_with_retry(TICKER_MAP_URL, timeout=120) as response:
        raw = json.load(response)
    return {str(value["ticker"]).upper(): int(value["cik_str"]) for value in raw.values()}


def extract_selected(zip_path: Path, output_dir: Path, tickers: set[str]) -> dict[str, int]:
    mapping = ticker_to_cik()
    reverse = {cik: ticker for ticker, cik in mapping.items() if ticker in tickers}
    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            base = Path(name).name
            if not base.startswith("CIK") or not base.endswith(".json"):
                continue
            try:
                cik = int(base[3:-5])
            except ValueError:
                continue
            ticker = reverse.get(cik)
            if ticker:
                (output_dir / f"{ticker}.json").write_bytes(archive.read(name))
                written += 1
    return {"requested": len(tickers), "matched": len(reverse), "written": written}


def load_universe_tickers(path: Path) -> set[str]:
    """Load tickers from either normalized or TradingView-export universe CSVs."""
    import pandas as pd

    universe = pd.read_csv(path)
    columns = {str(column).strip().lower(): column for column in universe.columns}
    source = next((columns[name.lower()] for name in TICKER_COLUMN_ALIASES if name.lower() in columns), None)
    if source is None:
        available = ", ".join(str(column) for column in universe.columns[:12])
        raise ValueError(
            "universe CSV requires ticker/symbol/シンボル/ティッカー column; "
            f"available columns: {available}"
        )
    values = universe[source].dropna().astype(str).str.upper().str.strip()
    return {ticker for ticker in values if ticker and ticker != "NAN"}


def _write_report(path: str, payload: dict) -> None:
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--zip", default="data/sec/companyfacts.zip")
    parser.add_argument("--output", default="data/sec_companyfacts")
    parser.add_argument("--report", default="")
    parser.add_argument("--skip-download", action="store_true")
    arguments = parser.parse_args()

    stage = "LOAD_UNIVERSE"
    try:
        tickers = load_universe_tickers(Path(arguments.universe))
        if not tickers:
            raise RuntimeError("universe CSV produced zero usable tickers")
        zip_path = Path(arguments.zip)

        download_report: dict[str, int | str] | None = None
        stage = "DOWNLOAD_BULK_ZIP"
        if not arguments.skip_download:
            download_report = download(SEC_BULK_URL, zip_path)
        elif not zip_path.exists():
            raise FileNotFoundError(zip_path)

        stage = "EXTRACT_SELECTED"
        extraction = extract_selected(zip_path, Path(arguments.output), tickers)
        if extraction["written"] <= 0:
            raise RuntimeError("SEC extraction produced zero company-fact files")

        payload = {
            "status": "success",
            "stage": "COMPLETE",
            "download": download_report,
            "extraction": extraction,
        }
        _write_report(arguments.report, payload)
        print(json.dumps(payload, indent=2, allow_nan=False))
    except Exception as exc:
        failure = {
            "status": "failure",
            "stage": stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
        _write_report(arguments.report, failure)
        print(json.dumps(failure, indent=2, allow_nan=False), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
