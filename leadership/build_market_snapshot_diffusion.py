from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

try:
    from leadership import build_market_snapshot as base
    from leadership.diffusion import compute_diffusion_snapshot
except ModuleNotFoundError:  # direct execution
    import build_market_snapshot as base
    from diffusion import compute_diffusion_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Leadership market snapshot with eventized diffusion")
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    parser.add_argument("--output", type=Path, default=Path("leadership/market_snapshot.json"))
    parser.add_argument("--benchmark", default="QQQ")
    parser.add_argument("--period", default="15mo")
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--pause", type=float, default=0.15)
    parser.add_argument("--max-symbols", type=int, default=0, help="PR smoke-test cap only; 0 = exact full source universe")
    args = parser.parse_args()

    source_universe = base.load_universe(args.universe)
    source_symbols = [row.symbol for row in source_universe]
    source_total = len(source_symbols)
    fingerprint = base.universe_fingerprint(source_symbols)

    download_rows = source_universe
    if args.max_symbols > 0:
        download_rows = source_universe[:args.max_symbols]
    symbols = [row.symbol for row in download_rows if row.symbol != args.benchmark]
    print(f"leadership source_universe={source_total} download_request={len(symbols)} diffusion=enabled")

    benchmark_query = base.yahoo_symbol(args.benchmark)
    benchmark_data = base._download_batch([benchmark_query], args.period)
    benchmark_frame = base._extract_ohlcv(benchmark_data, benchmark_query, 1)
    if benchmark_frame is None or len(benchmark_frame) < 190:
        raise RuntimeError(f"benchmark history unavailable: {args.benchmark}")
    benchmark_metrics = base.compute_raw_metrics(benchmark_frame)

    frames, failed = base.download_history(symbols, batch_size=args.batch_size, period=args.period, pause=args.pause)
    raw: dict[str, dict[str, float | None]] = {}
    for symbol, frame in frames.items():
        values = base.compute_raw_metrics(frame)
        if values:
            raw[symbol] = values

    enriched = base.enrich_relative_strength(raw, benchmark_metrics)
    metric_maps = base.to_metric_maps(enriched)
    metric_payload = {
        (key if key == "rs63" else f"metric_{key}"): values
        for key, values in metric_maps.items()
    }
    diffusion = compute_diffusion_snapshot(frames, benchmark_frame, download_rows)

    output = {
        "schema": 4,
        "source": "Yahoo Finance daily adjusted OHLCV (independent Leadership flow)",
        "universe_source": str(args.universe),
        "universe_policy": "exact source universe; no Leadership-only symbol filter",
        "universe_source_total": source_total,
        "universe_fingerprint": fingerprint,
        "asof": str(benchmark_frame.index[-1].date()),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark": args.benchmark,
        "universe_requested": len(symbols),
        "universe_valid": len(enriched),
        "failed_sample": sorted(set(failed))[:100],
        "diffusion": diffusion,
        **metric_payload,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "asof": output["asof"],
        "source_total": source_total,
        "requested": output["universe_requested"],
        "valid": output["universe_valid"],
        "rs21": len(metric_maps.get("rs21", {})),
        "rs63": len(metric_maps.get("rs63", {})),
        "rs189": len(metric_maps.get("rs189", {})),
        "entry_inputs": len(metric_maps.get("ema21", {})),
        "breakout_inputs": len(metric_maps.get("breakout20_cross", {})),
        "diffusion": diffusion.get("coverage", {}),
        "fingerprint": fingerprint,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
