import numpy as np
import pandas as pd

from alpaca_screener.strategy import ScreenConfig, analyze_symbol, screen_bars


def make_cross_bars(*, spike: float = 2.0, support_gap: float = 0.02) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230, tz="UTC")
    close = np.concatenate(
        [
            np.linspace(120, 80, 200),
            np.linspace(81, 160, 30),
        ]
    )
    close[-8:] = 160
    low = close * 0.99
    low[-8:] = close[-8:] * 0.995
    low[-5] = close[-1] * (1 - support_gap)
    volume = np.full(230, 1_000_000.0)
    volume[-1] *= spike
    return pd.DataFrame({"close": close, "low": low, "volume": volume}, index=dates)


def test_recent_golden_cross_with_volume_spike_matches():
    config = ScreenConfig(crossover_lookback=10)
    result = analyze_symbol("TEST", make_cross_bars(), config)

    assert result is not None
    assert result["symbol"] == "TEST"
    assert result["ma_type"] == "SMA"
    assert result["volume_ratio"] == 2.0
    assert result["volume_spike_pct"] == 100.0
    assert result["sessions_since_cross"] <= 10
    assert result["distance_to_support_pct"] > 0
    assert result["support_date"] is not None


def test_golden_cross_without_volume_spike_is_rejected():
    config = ScreenConfig(crossover_lookback=10, volume_spike_pct=50.0)
    result = analyze_symbol("QUIET", make_cross_bars(spike=1.1), config)

    assert result is None


def test_results_are_ranked_by_distance_to_support():
    config = ScreenConfig(crossover_lookback=10)
    results = screen_bars(
        {
            "FAR": make_cross_bars(spike=3.0, support_gap=0.10),
            "CLOSE": make_cross_bars(spike=1.6, support_gap=0.01),
        },
        config,
    )

    assert results["symbol"].tolist() == ["CLOSE", "FAR"]


def test_ema_golden_cross_can_be_selected():
    config = ScreenConfig(
        ma_type="ema",
        fast_window=20,
        slow_window=50,
        crossover_lookback=40,
        support_modes=("recent_low",),
    )
    result = analyze_symbol("EMA", make_cross_bars(), config)

    assert result is not None
    assert result["ma_type"] == "EMA"


def test_volume_spike_can_occur_within_last_three_days():
    bars = make_cross_bars(spike=1.0)
    bars.iloc[-2, bars.columns.get_loc("volume")] = 1_800_000.0
    config = ScreenConfig(crossover_lookback=10, volume_spike_pct=50.0)
    result = analyze_symbol("SPIKE", bars, config)

    assert result is not None
    assert result["volume_spike_date"] == "2025-11-18"
    assert result["volume_spike_pct"] == 80.0


def test_custom_support_lookback_can_be_used():
    config = ScreenConfig(
        crossover_lookback=10,
        support_modes=(),
        support_lookbacks=(10,),
    )
    result = analyze_symbol("SUPPORT", make_cross_bars(support_gap=0.03), config)

    assert result is not None
    assert result["support_label"] == "10_bar_low"


def test_missing_low_column_is_rejected():
    config = ScreenConfig(crossover_lookback=10)
    bars = make_cross_bars().drop(columns=["low"])

    try:
        analyze_symbol("BAD", bars, config)
    except ValueError as exc:
        assert "low" in str(exc)
    else:
        raise AssertionError("Expected missing low column to raise ValueError")
