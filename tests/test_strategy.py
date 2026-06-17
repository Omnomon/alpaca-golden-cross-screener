import numpy as np
import pandas as pd

from alpaca_screener.strategy import (
    ScreenConfig,
    _awesome_oscillator,
    _ultimate_oscillator,
    analyze_symbol,
    screen_bars,
)


def make_weekly_rule_bars(
    *,
    volume_change: float = 0.10,
    low_3m_gap: float = 0.02,
    final_close: float = 330.0,
) -> pd.DataFrame:
    dates = pd.date_range("2021-01-01", periods=230, freq="W-FRI", tz="UTC")
    close = np.linspace(80, 260, 230)
    close[-30:-1] = np.linspace(260, 210, 29)
    close[-1] = final_close
    open_ = close * 0.995
    high = close * 1.01
    low = close * 0.99
    low[-26] = 200.0
    close[-13:-1] = 205.0
    open_[-13:-1] = 206.0
    high[-13:-1] = 270.0
    low[-13:] = 200.0 * (1.0 + low_3m_gap)
    close[-4:-1] = 268.0
    high[-1] = final_close * 1.01
    volume = np.full(230, 1_000_000.0)
    volume[-2] = 1_000_000.0
    volume[-1] = 1_000_000.0 * (1.0 + volume_change)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_weekly_rule_strategy_matches():
    config = ScreenConfig()
    result = analyze_symbol("TEST", make_weekly_rule_bars(), config)

    assert result is not None
    assert result["symbol"] == "TEST"
    assert result["ema_fast"] > result["ema_slow"]
    assert result["sma_fast"] > result["sma_slow"]
    assert result["ao"] > 0.5
    assert result["volume_change_pct"] > 5
    assert 0 <= result["low_3m_above_6m_pct"] <= 3
    assert result["previous_uo"] < 50 <= result["uo"]


def test_volume_change_rule_rejects_quiet_week():
    result = analyze_symbol(
        "QUIET",
        make_weekly_rule_bars(volume_change=0.01),
        ScreenConfig(),
    )

    assert result is None


def test_low_proximity_rule_rejects_far_3m_low():
    result = analyze_symbol(
        "FAR",
        make_weekly_rule_bars(low_3m_gap=0.08),
        ScreenConfig(),
    )

    assert result is None


def test_screen_bars_orders_by_score():
    results = screen_bars(
        {
            "LOW": make_weekly_rule_bars(volume_change=0.06, final_close=320),
            "HIGH": make_weekly_rule_bars(volume_change=0.20, final_close=350),
        },
        ScreenConfig(),
    )

    assert results["symbol"].tolist() == ["HIGH", "LOW"]


def test_awesome_and_ultimate_oscillator_calculate():
    bars = make_weekly_rule_bars()
    ao = _awesome_oscillator(bars, 5, 34)
    uo = _ultimate_oscillator(bars, 7, 14, 28)

    assert pd.notna(ao.iloc[-1])
    assert pd.notna(uo.iloc[-1])


def test_missing_ohlc_column_is_rejected():
    bars = make_weekly_rule_bars().drop(columns=["high"])

    try:
        analyze_symbol("BAD", bars, ScreenConfig())
    except ValueError as exc:
        assert "high" in str(exc)
    else:
        raise AssertionError("Expected missing high column to raise ValueError")
