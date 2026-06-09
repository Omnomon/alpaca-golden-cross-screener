from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alpaca.data.enums import DataFeed
from dotenv import load_dotenv

from .alpaca_data import (
    clients_from_environment,
    fetch_daily_bars,
    get_tradable_symbols,
)
from .strategy import ScreenConfig, screen_bars


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find recent golden crosses confirmed by a volume spike."
    )
    universe = parser.add_mutually_exclusive_group()
    universe.add_argument(
        "--symbols",
        help="Comma-separated symbols. Defaults to all active tradable US equities.",
    )
    universe.add_argument(
        "--symbols-file",
        type=Path,
        help="Text file containing one symbol per line.",
    )
    parser.add_argument("--limit-universe", type=int)
    parser.add_argument("--cross-lookback", type=int, default=5)
    parser.add_argument("--volume-window", type=int, default=20)
    parser.add_argument("--volume-multiplier", type=float, default=1.5)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-average-volume", type=float, default=100_000.0)
    parser.add_argument("--feed", choices=["iex", "sip"], default="iex")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--output", type=Path, help="Write results to .csv or .json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()

    try:
        data_client, trading_client = clients_from_environment()
        symbols = _load_symbols(args, trading_client)
        clock = trading_client.get_clock()
        bars = fetch_daily_bars(
            data_client,
            symbols,
            feed=DataFeed.SIP if args.feed == "sip" else DataFeed.IEX,
            incomplete_session_date=clock.timestamp.date() if clock.is_open else None,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    config = ScreenConfig(
        crossover_lookback=args.cross_lookback,
        volume_window=args.volume_window,
        volume_multiplier=args.volume_multiplier,
        min_price=args.min_price,
        min_average_volume=args.min_average_volume,
    )
    results = screen_bars(bars, config).head(args.top)

    if args.output:
        _write_results(results, args.output)

    if results.empty:
        print("No symbols matched the golden-cross and volume-spike criteria.")
    else:
        print(results.to_string(index=False))
    print(f"\nScreened {len(bars)} symbols with sufficient Alpaca bar data.")
    return 0


def _load_symbols(args: argparse.Namespace, trading_client: object) -> list[str]:
    if args.symbols:
        return [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.symbols_file:
        return [
            line.strip().upper()
            for line in args.symbols_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    return get_tradable_symbols(trading_client, args.limit_universe)


def _write_results(results: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        results.to_json(path, orient="records", indent=2)
    elif path.suffix.lower() == ".csv":
        results.to_csv(path, index=False)
    else:
        raise ValueError("--output must end in .csv or .json")


if __name__ == "__main__":
    raise SystemExit(main())
