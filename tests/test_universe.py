import pandas as pd

from alpaca_screener.universe import (
    UniverseFilterConfig,
    filter_universe,
    market_cap_bucket,
    volume_stats_from_bars,
)


def fundamentals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "pe": 12,
                "market_cap": 1_000_000_000,
                "market_cap_bucket": "small",
                "industry": "Software",
                "sector": "Technology",
            },
            {
                "symbol": "BBB",
                "pe": 22,
                "market_cap": 5_000_000_000,
                "market_cap_bucket": "mid",
                "industry": "Banks",
                "sector": "Financial Services",
            },
            {
                "symbol": "CCC",
                "pe": 35,
                "market_cap": 500_000_000_000,
                "market_cap_bucket": "large",
                "industry": "Semiconductors",
                "sector": "Technology",
            },
        ]
    )


def test_market_cap_bucket():
    assert market_cap_bucket(1_000_000_000) == "small"
    assert market_cap_bucket(5_000_000_000) == "mid"
    assert market_cap_bucket(50_000_000_000) == "large"


def test_filter_by_pe_industry_and_cap_bucket():
    config = UniverseFilterConfig(
        pe_min=10,
        pe_max=25,
        industries=("Technology",),
        market_caps=("small",),
    )

    symbols = filter_universe(["AAA", "BBB", "CCC"], config, fundamentals=fundamentals())

    assert symbols == ["AAA"]


def test_medium_cap_alias_is_supported():
    config = UniverseFilterConfig(market_caps=("medium",))

    symbols = filter_universe(["AAA", "BBB", "CCC"], config, fundamentals=fundamentals())

    assert symbols == ["BBB"]


def test_volume_stats_from_bars_and_volume_filter():
    dates = pd.bdate_range("2026-01-01", periods=30)
    bars = {
        "AAA": pd.DataFrame({"close": 10, "volume": 1000}, index=dates),
        "BBB": pd.DataFrame({"close": 20, "volume": 10}, index=dates),
    }
    volume_stats = volume_stats_from_bars(bars)
    config = UniverseFilterConfig(min_30d_share_volume=20_000)

    symbols = filter_universe(["AAA", "BBB"], config, volume_stats=volume_stats)

    assert symbols == ["AAA"]
    assert volume_stats.loc[volume_stats["symbol"] == "AAA", "share_volume_30d"].iloc[0] == 30_000


def test_cap_mix_selects_by_percentage_and_volume():
    fund = fundamentals()
    volume_stats = pd.DataFrame(
        [
            {"symbol": "AAA", "share_volume_30d": 100, "dollar_volume_30d": 100},
            {"symbol": "BBB", "share_volume_30d": 200, "dollar_volume_30d": 200},
            {"symbol": "CCC", "share_volume_30d": 300, "dollar_volume_30d": 300},
        ]
    )
    config = UniverseFilterConfig(
        cap_mix={"small": 50, "large": 50},
        max_symbols=2,
    )

    symbols = filter_universe(
        ["AAA", "BBB", "CCC"],
        config,
        fundamentals=fund,
        volume_stats=volume_stats,
    )

    assert symbols == ["AAA", "CCC"]
