from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ScreenConfig:
    ema_fast_window: int = 50
    ema_slow_window: int = 200
    sma_fast_window: int = 50
    sma_slow_window: int = 200
    ao_fast_window: int = 5
    ao_slow_window: int = 34
    ao_min: float = 0.5
    volume_change_pct: float = 5.0
    low_near_short_weeks: int = 13
    low_near_long_weeks: int = 26
    low_near_min_pct: float = 0.0
    low_near_max_pct: float = 3.0
    uo_short_window: int = 7
    uo_medium_window: int = 14
    uo_long_window: int = 28
    uo_cross_level: float = 50.0
    require_uo_cross_up: bool = True
    min_price: float = 5.0
    min_weekly_volume: float = 100_000.0

    @property
    def minimum_bars(self) -> int:
        return max(
            self.ema_slow_window,
            self.sma_slow_window,
            self.ao_slow_window,
            self.uo_long_window + 1,
            self.low_near_long_weeks,
        ) + 2


RESULT_COLUMNS = [
    "symbol",
    "as_of",
    "close",
    "ema_fast",
    "ema_slow",
    "sma_fast",
    "sma_slow",
    "ao",
    "volume",
    "previous_volume",
    "volume_change_pct",
    "low_3m",
    "low_6m",
    "low_3m_above_6m_pct",
    "uo",
    "previous_uo",
    "score",
]


def analyze_symbol(
    symbol: str,
    bars: pd.DataFrame,
    config: ScreenConfig,
) -> dict[str, object] | None:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(bars.columns):
        missing = ", ".join(sorted(required - set(bars.columns)))
        raise ValueError(f"{symbol}: missing required columns: {missing}")

    weekly = _to_weekly_bars(bars)
    if len(weekly) < config.minimum_bars:
        return None

    weekly["ema_fast"] = weekly["close"].ewm(
        span=config.ema_fast_window,
        adjust=False,
        min_periods=config.ema_fast_window,
    ).mean()
    weekly["ema_slow"] = weekly["close"].ewm(
        span=config.ema_slow_window,
        adjust=False,
        min_periods=config.ema_slow_window,
    ).mean()
    weekly["sma_fast"] = weekly["close"].rolling(config.sma_fast_window).mean()
    weekly["sma_slow"] = weekly["close"].rolling(config.sma_slow_window).mean()
    weekly["ao"] = _awesome_oscillator(
        weekly,
        config.ao_fast_window,
        config.ao_slow_window,
    )
    weekly["uo"] = _ultimate_oscillator(
        weekly,
        config.uo_short_window,
        config.uo_medium_window,
        config.uo_long_window,
    )

    latest = weekly.iloc[-1]
    previous = weekly.iloc[-2]
    low_3m = float(weekly["low"].tail(config.low_near_short_weeks).min())
    low_6m = float(weekly["low"].tail(config.low_near_long_weeks).min())
    low_3m_above_6m_pct = (low_3m / low_6m - 1.0) * 100.0 if low_6m > 0 else None
    volume_change_pct = (
        (latest["volume"] / previous["volume"] - 1.0) * 100.0
        if previous["volume"] > 0
        else None
    )

    values = [
        latest["ema_fast"],
        latest["ema_slow"],
        latest["sma_fast"],
        latest["sma_slow"],
        latest["ao"],
        latest["uo"],
        previous["uo"],
        volume_change_pct,
        low_3m_above_6m_pct,
    ]
    if any(pd.isna(value) for value in values):
        return None

    uo_passes = latest["uo"] >= config.uo_cross_level
    if config.require_uo_cross_up:
        uo_passes = uo_passes and previous["uo"] < config.uo_cross_level

    if not (
        latest["ema_fast"] > latest["ema_slow"]
        and latest["sma_fast"] > latest["sma_slow"]
        and latest["ao"] > config.ao_min
        and volume_change_pct > config.volume_change_pct
        and config.low_near_min_pct <= low_3m_above_6m_pct <= config.low_near_max_pct
        and uo_passes
        and latest["close"] >= config.min_price
        and latest["volume"] >= config.min_weekly_volume
    ):
        return None

    score = (
        float(latest["ao"])
        + float(volume_change_pct)
        + max(0.0, float(latest["uo"]) - config.uo_cross_level)
        - float(low_3m_above_6m_pct)
    )

    return {
        "symbol": symbol,
        "as_of": _date_string(weekly.index[-1]),
        "close": round(float(latest["close"]), 2),
        "ema_fast": round(float(latest["ema_fast"]), 2),
        "ema_slow": round(float(latest["ema_slow"]), 2),
        "sma_fast": round(float(latest["sma_fast"]), 2),
        "sma_slow": round(float(latest["sma_slow"]), 2),
        "ao": round(float(latest["ao"]), 2),
        "volume": int(latest["volume"]),
        "previous_volume": int(previous["volume"]),
        "volume_change_pct": round(float(volume_change_pct), 2),
        "low_3m": round(low_3m, 2),
        "low_6m": round(low_6m, 2),
        "low_3m_above_6m_pct": round(float(low_3m_above_6m_pct), 2),
        "uo": round(float(latest["uo"]), 2),
        "previous_uo": round(float(previous["uo"]), 2),
        "score": round(score, 2),
    }


def screen_bars(
    bars_by_symbol: dict[str, pd.DataFrame],
    config: ScreenConfig | None = None,
) -> pd.DataFrame:
    config = config or ScreenConfig()
    matches = [
        result
        for symbol, bars in bars_by_symbol.items()
        if (result := analyze_symbol(symbol, bars, config)) is not None
    ]
    if not matches:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    return (
        pd.DataFrame(matches, columns=RESULT_COLUMNS)
        .sort_values(["score", "volume_change_pct", "ao"], ascending=False)
        .reset_index(drop=True)
    )


def _to_weekly_bars(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index)
    weekly = frame.resample("W-FRI").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return weekly.dropna()


def _awesome_oscillator(
    frame: pd.DataFrame,
    fast_window: int,
    slow_window: int,
) -> pd.Series:
    median_price = (frame["high"] + frame["low"]) / 2.0
    return median_price.rolling(fast_window).mean() - median_price.rolling(
        slow_window
    ).mean()


def _ultimate_oscillator(
    frame: pd.DataFrame,
    short_window: int,
    medium_window: int,
    long_window: int,
) -> pd.Series:
    previous_close = frame["close"].shift(1)
    low_or_previous_close = pd.concat(
        [frame["low"], previous_close], axis=1
    ).min(axis=1)
    high_or_previous_close = pd.concat(
        [frame["high"], previous_close], axis=1
    ).max(axis=1)
    buying_pressure = frame["close"] - low_or_previous_close
    true_range = high_or_previous_close - low_or_previous_close

    average_short = buying_pressure.rolling(short_window).sum() / true_range.rolling(
        short_window
    ).sum()
    average_medium = buying_pressure.rolling(medium_window).sum() / true_range.rolling(
        medium_window
    ).sum()
    average_long = buying_pressure.rolling(long_window).sum() / true_range.rolling(
        long_window
    ).sum()
    return 100.0 * (4.0 * average_short + 2.0 * average_medium + average_long) / 7.0


def _date_string(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()
