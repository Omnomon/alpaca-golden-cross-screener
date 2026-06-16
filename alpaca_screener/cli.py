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
from .universe import (
    UniverseFilterConfig,
    fetch_yfinance_fundamentals,
    filter_universe,
    volume_stats_from_bars,
)


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
        "--max-filtered-symbols",
        type=int,
        help="Cap the filtered universe before fetching full strategy bars.",
    )
    parser.add_argument("--fast-window", type=int, default=50)
    parser.add_argument("--slow-window", type=int, default=200)
    parser.add_argument(
        "--ma-type",
        choices=["sma", "ema"],
        default="sma",
        help="Moving average type for the golden cross.",
    )
    parser.add_argument("--cross-lookback", type=int, default=5)
    parser.add_argument("--volume-window", type=int, default=20)
    parser.add_argument(
        "--volume-spike-lookback",
        type=int,
        default=3,
        help="Recent bars to inspect for a qualifying volume spike.",
    )
    parser.add_argument(
        "--volume-spike-pct",
        type=float,
        default=50.0,
        help="Target percent volume spike versus trailing average volume.",
    )
    parser.add_argument("--volume-multiplier", type=float, help=argparse.SUPPRESS)
    parser.add_argument(
        "--support-lookback",
        type=int,
        default=90,
        help="Bars to inspect for the most recent support pivot.",
    )
    parser.add_argument(
        "--support-modes",
        default="pivot,recent_low,1_month_low",
        help=(
            "Comma-separated support methods: pivot, recent_low, 1_month_low, "
            "3_month_low, 6_month_low, 1_year_low."
        ),
    )
    parser.add_argument(
        "--support-lookbacks",
        default="",
        help="Comma-separated custom low lookbacks, for example 21,63,126.",
    )
    parser.add_argument(
        "--support-pivot-span",
        type=int,
        default=3,
        help="Bars required on each side of a local support pivot.",
    )
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
        universe_config = UniverseFilterConfig(
            pe_min=args.pe_min,
            pe_max=args.pe_max,
            industries=_parse_csv(args.industries),
            market_caps=_parse_csv(args.market_caps),
            cap_mix=_parse_cap_mix(args.cap_mix),
            min_30d_share_volume=args.min_30d_share_volume,
            min_30d_dollar_volume=args.min_30d_dollar_volume,
            max_symbols=args.max_filtered_symbols,
        )
        clock = trading_client.get_clock()
        symbols = _filter_symbols(
            data_client,
            symbols,
            universe_config,
            feed=DataFeed.SIP if args.feed == "sip" else DataFeed.IEX,
            incomplete_session_date=clock.timestamp.date() if clock.is_open else None,
        )
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
        fast_window=args.fast_window,
        slow_window=args.slow_window,
        ma_type=args.ma_type,
        crossover_lookback=args.cross_lookback,
        volume_window=args.volume_window,
        volume_spike_lookback=args.volume_spike_lookback,
        volume_spike_pct=_volume_spike_pct(args),
        support_lookback=args.support_lookback,
        support_pivot_span=args.support_pivot_span,
        support_modes=_parse_csv(args.support_modes),
        support_lookbacks=tuple(int(item) for item in _parse_csv(args.support_lookbacks)),
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


def _volume_spike_pct(args: argparse.Namespace) -> float:
    if args.volume_multiplier is not None:
        return (args.volume_multiplier - 1.0) * 100.0
    return args.volume_spike_pct


def _filter_symbols(
    data_client: object,
    symbols: list[str],
    config: UniverseFilterConfig,
    *,
    feed: DataFeed,
    incomplete_session_date: object,
) -> list[str]:
    if not (config.needs_fundamentals or config.needs_volume or config.max_symbols):
        return symbols

    fundamentals = (
        fetch_yfinance_fundamentals(symbols) if config.needs_fundamentals else None
    )
    volume_stats = None
    if config.needs_volume:
        volume_bars = fetch_daily_bars(
            data_client,
            symbols,
            calendar_days=50,
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
