from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .alpaca_data import (
    DEFAULT_EXCHANGES,
    clients_from_environment,
    fetch_daily_bars,
    get_tradable_symbols,
)
from .strategy import ScreenConfig, screen_bars
from .universe import (
    UniverseFilterConfig,
    filter_universe,
    is_common_stock_symbol,
    load_fundamentals_file,
    volume_stats_from_bars,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Screen weekly technical strength: EMA/SMA 50 > 200, AO, volume "
            "change, nearby 3M/6M lows, and UO confirmation."
        )
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
    parser.add_argument(
        "--exchanges",
        default=",".join(DEFAULT_EXCHANGES),
        help="Comma-separated Alpaca exchanges to include. Defaults to NASDAQ,NYSE.",
    )
    parser.add_argument(
        "--include-non-common",
        action="store_true",
        help="Include preferred shares, warrants, and units in the base universe.",
    )
    parser.add_argument(
        "--fundamentals-file",
        type=Path,
        help=(
            "CSV with symbol, pe, market_cap, industry, and/or sector columns. "
            "Required for P/E, cap, cap-mix, or industry filters."
        ),
    )
    parser.add_argument("--pe-min", type=float)
    parser.add_argument("--pe-max", type=float)
    parser.add_argument(
        "--industries",
        default="",
        help="Comma-separated industries or sectors to include.",
    )
    parser.add_argument(
        "--market-caps",
        default="",
        help="Comma-separated cap buckets to include: small,mid,medium,large.",
    )
    parser.add_argument(
        "--cap-mix",
        default="",
        help="Target cap bucket percentages, for example small:20,mid:30,large:50.",
    )
    parser.add_argument("--min-30d-share-volume", type=float)
    parser.add_argument("--min-30d-dollar-volume", type=float)
    parser.add_argument(
        "--performance-windows",
        default="",
        help="Comma-separated performance windows to rank: 1m,3m,6m.",
    )
    parser.add_argument(
        "--top-performance-pct",
        type=float,
        help="Keep stocks in the top N percent for any selected performance window.",
    )
    parser.add_argument(
        "--min-performance",
        default="",
        help="Comma-separated thresholds such as 3m:25,6m:40.",
    )
    parser.add_argument(
        "--max-filtered-symbols",
        type=int,
        help="Cap the filtered universe before fetching full strategy bars.",
    )
    parser.add_argument("--ema-fast-window", type=int, default=50)
    parser.add_argument("--ema-slow-window", type=int, default=200)
    parser.add_argument("--sma-fast-window", type=int, default=50)
    parser.add_argument("--sma-slow-window", type=int, default=200)
    parser.add_argument("--ao-fast-window", type=int, default=5)
    parser.add_argument("--ao-slow-window", type=int, default=34)
    parser.add_argument(
        "--ao-min",
        type=float,
        default=0.5,
        help="Minimum weekly Awesome Oscillator value.",
    )
    parser.add_argument(
        "--volume-change-pct",
        type=float,
        default=5.0,
        help="Minimum latest weekly volume increase versus the prior week.",
    )
    parser.add_argument("--low-near-short-weeks", type=int, default=13)
    parser.add_argument("--low-near-long-weeks", type=int, default=26)
    parser.add_argument(
        "--low-near-min-pct",
        type=float,
        default=0.0,
        help="Minimum percent that the short-window low is above the long-window low.",
    )
    parser.add_argument(
        "--low-near-max-pct",
        type=float,
        default=3.0,
        help="Maximum percent that the short-window low is above the long-window low.",
    )
    parser.add_argument("--uo-short-window", type=int, default=7)
    parser.add_argument("--uo-medium-window", type=int, default=14)
    parser.add_argument("--uo-long-window", type=int, default=28)
    parser.add_argument("--uo-cross-level", type=float, default=50.0)
    parser.add_argument(
        "--no-require-uo-cross-up",
        action="store_true",
        help="Accept UO above the level without requiring a fresh upward cross.",
    )
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-weekly-volume", type=float, default=100_000.0)
    parser.add_argument("--feed", choices=["iex", "sip"], default="iex")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--output", type=Path, help="Write results to .csv or .json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_dotenv()

    try:
        data_client, trading_client = clients_from_environment()
        symbols = _load_symbols(args, trading_client)
        if not args.include_non_common:
            symbols = [symbol for symbol in symbols if is_common_stock_symbol(symbol)]
        universe_config = UniverseFilterConfig(
            fundamentals_file=str(args.fundamentals_file) if args.fundamentals_file else None,
            pe_min=args.pe_min,
            pe_max=args.pe_max,
            industries=_parse_csv(args.industries),
            market_caps=_parse_csv(args.market_caps),
            cap_mix=_parse_cap_mix(args.cap_mix),
            min_30d_share_volume=args.min_30d_share_volume,
            min_30d_dollar_volume=args.min_30d_dollar_volume,
            performance_windows=_parse_csv(args.performance_windows),
            top_performance_pct=args.top_performance_pct,
            min_performance=_parse_performance_thresholds(args.min_performance),
            max_symbols=args.max_filtered_symbols,
        )
        clock = trading_client.get_clock()
        symbols = _filter_symbols(
            data_client,
            symbols,
            universe_config,
            feed=_data_feed(args.feed),
            incomplete_session_date=clock.timestamp.date() if clock.is_open else None,
        )
        bars = fetch_daily_bars(
            data_client,
            symbols,
            feed=_data_feed(args.feed),
            incomplete_session_date=clock.timestamp.date() if clock.is_open else None,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    config = ScreenConfig(
        ema_fast_window=args.ema_fast_window,
        ema_slow_window=args.ema_slow_window,
        sma_fast_window=args.sma_fast_window,
        sma_slow_window=args.sma_slow_window,
        ao_fast_window=args.ao_fast_window,
        ao_slow_window=args.ao_slow_window,
        ao_min=args.ao_min,
        volume_change_pct=args.volume_change_pct,
        low_near_short_weeks=args.low_near_short_weeks,
        low_near_long_weeks=args.low_near_long_weeks,
        low_near_min_pct=args.low_near_min_pct,
        low_near_max_pct=args.low_near_max_pct,
        uo_short_window=args.uo_short_window,
        uo_medium_window=args.uo_medium_window,
        uo_long_window=args.uo_long_window,
        uo_cross_level=args.uo_cross_level,
        require_uo_cross_up=not args.no_require_uo_cross_up,
        min_price=args.min_price,
        min_weekly_volume=args.min_weekly_volume,
    )
    results = screen_bars(bars, config).head(args.top)

    if args.output:
        _write_results(results, args.output)

    if results.empty:
        print("No symbols matched the weekly technical strategy criteria.")
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
    return get_tradable_symbols(
        trading_client,
        args.limit_universe,
        common_only=not args.include_non_common,
        exchanges=_parse_csv(args.exchanges),
    )


def _write_results(results: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        results.to_json(path, orient="records", indent=2)
    elif path.suffix.lower() == ".csv":
        results.to_csv(path, index=False)
    else:
        raise ValueError("--output must end in .csv or .json")


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_cap_mix(value: str) -> dict[str, float]:
    cap_mix: dict[str, float] = {}
    for item in _parse_csv(value):
        if ":" not in item:
            raise ValueError("--cap-mix entries must look like small:20")
        bucket, pct = item.split(":", 1)
        cap_mix[bucket.strip().lower()] = float(pct)
    return cap_mix


def _parse_performance_thresholds(value: str) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for item in _parse_csv(value):
        if ":" not in item:
            raise ValueError("--min-performance entries must look like 3m:25")
        window, threshold = item.split(":", 1)
        thresholds[window.strip().lower()] = float(threshold)
    return thresholds


def _data_feed(value: str) -> object:
    from alpaca.data.enums import DataFeed

    return DataFeed.SIP if value == "sip" else DataFeed.IEX


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv()


def _filter_symbols(
    data_client: object,
    symbols: list[str],
    config: UniverseFilterConfig,
    *,
    feed: object,
    incomplete_session_date: object,
) -> list[str]:
    if not (
        config.needs_fundamentals
        or config.needs_volume
        or config.needs_performance
        or config.max_symbols
    ):
        return symbols

    fundamentals = None
    if config.needs_fundamentals:
        if not getattr(config, "fundamentals_file", None):
            raise RuntimeError(
                "P/E, market-cap, cap-mix, and industry filters require "
                "--fundamentals-file. This avoids Yahoo/yfinance rate limits."
            )
        fundamentals = load_fundamentals_file(str(config.fundamentals_file))
    volume_stats = None
    if config.needs_volume or config.needs_performance:
        volume_bars = fetch_daily_bars(
            data_client,
            symbols,
            calendar_days=210,
            feed=feed,
            incomplete_session_date=incomplete_session_date,
        )
        volume_stats = volume_stats_from_bars(volume_bars)
    return filter_universe(
        symbols,
        config,
        fundamentals=fundamentals,
        volume_stats=volume_stats,
    )


if __name__ == "__main__":
    raise SystemExit(main())
