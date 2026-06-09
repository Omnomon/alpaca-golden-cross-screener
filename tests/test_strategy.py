import numpy as np
import pandas as pd

from alpaca_screener.strategy import ScreenConfig, analyze_symbol, screen_bars


def make_cross_bars(*, spike: float = 2.0) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230, tz="UTC")
    close = np.concatenate(
        [
            np.linspace(120, 80, 200),
            np.linspace(81, 160, 30),
        ]
    )
    volume = np.full(230, 1_000_000.0)
    volume[-1] *= spike
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def test_recent_golden_cross_with_volume_spike_matches():
    config = ScreenConfig(crossover_lookback=10)
    result = analyze_symbol("TEST", make_cross_bars(), config)

    assert result is not None
    assert result["symbol"] == "TEST"
    assert result["volume_ratio"] == 2.0
    assert result["sessions_since_cross"] <= 10


def test_golden_cross_without_volume_spike_is_rejected():
    config = ScreenConfig(crossover_lookback=10, volume_multiplier=1.5)
    result = analyze_symbol("QUIET", make_cross_bars(spike=1.1), config)

    assert result is None


def test_results_are_ranked_by_score():
    config = ScreenConfig(crossover_lookback=10)
    results = screen_bars(
        {
            "LOW": make_cross_bars(spike=1.6),
            "HIGH": make_cross_bars(spike=3.0),
        },
        config,
    )

    assert results["symbol"].tolist() == ["HIGH", "LOW"]

