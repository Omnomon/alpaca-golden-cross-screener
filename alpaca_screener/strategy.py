from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


SUPPORT_MODE_LOOKBACKS = {
    "1_month_low": 21,
    "3_month_low": 63,
    "6_month_low": 126,
    "1_year_low": 252,
}


@dataclass(frozen=True)
class ScreenConfig:
    fast_window: int = 50
    slow_window: int = 200
    ma_type: str = "sma"
    crossover_lookback: int = 5
    volume_window: int = 20
    volume_spike_lookback: int = 3
    volume_spike_pct: float = 50.0
    support_lookback: int = 90
    support_pivot_span: int = 3
    support_modes: tuple[str, ...] = ("pivot", "recent_low", "1_month_low")
    support_lookbacks: tuple[int, ...] = field(default_factory=tuple)
    min_price: float = 5.0
    min_average_volume: float = 100_000.0

    @property
    def minimum_bars(self) -> int:
        support_windows = [self.support_lookback, *self.support_lookbacks]
        support_windows.extend(
            SUPPORT_MODE_LOOKBACKS[mode]
            for mode in self.support_modes
            if mode in SUPPORT_MODE_LOOKBACKS
        )
        return max(
            self.slow_window + self.crossover_lookback,
            max(support_windows, default=self.support_lookback)
            + self.support_pivot_span,
            self.volume_window + self.volume_spike_lookback,
        )

    @property
    def volume_multiplier(self) -> float:
        return 1.0 + self.volume_spike_pct / 100.0


RESULT_COLUMNS = [
    "symbol",
    "as_of",
    "close",
    "ma_type",
    "ma_fast",
    "ma_slow",
    "cross_date",
    "sessions_since_cross",
    "volume",
    "average_volume",
    "volume_ratio",
    "volume_spike_date",
    "volume_spike_pct",
    "support",
    "support_date",
    "support_label",
    "distance_to_support_pct",
    "price_above_slow_ma_pct",
    "score",
]


def analyze_symbol(
    symbol: str,
    bars: pd.DataFrame,
    config: ScreenConfig,
) -> dict[str, object] | None:
    required = {"close", "low", "volume"}
    if not required.issubset(bars.columns):
        missing = ", ".join(sorted(required - set(bars.columns)))
        raise ValueError(f"{symbol}: missing required columns: {missing}")

    frame = bars.sort_index().copy()
    frame = frame.loc[:, ["close", "low", "volume"]].dropna()
    if len(frame) < config.minimum_bars:
        return None

    frame["ma_fast"] = _moving_average(frame["close"], config.fast_window, config.ma_type)
    frame["ma_slow"] = _moving_average(frame["close"], config.slow_window, config.ma_type)
    frame["average_volume"] = (
        frame["volume"].shift(1).rolling(config.volume_window).mean()
    )
    frame["golden_cross"] = (
        (frame["ma_fast"] > frame["ma_slow"])
        & (frame["ma_fast"].shift(1) <= frame["ma_slow"].shift(1))
    )

    recent = frame.tail(config.crossover_lookback + 1)
    crosses = recent.index[recent["golden_cross"].fillna(False)]
    if len(crosses) == 0:
        return None

    spike = _best_recent_volume_spike(frame, config)
    if spike is None:
        return None
    volume_ratio, volume_spike_date, spike_volume, spike_average_volume = spike
    latest = frame.iloc[-1]
    if (
        latest["ma_fast"] <= latest["ma_slow"]
        or latest["close"] < config.min_price
        or spike_average_volume < config.min_average_volume
        or volume_ratio < config.volume_multiplier
    ):
        return None

    cross_date = crosses[-1]
    cross_position = frame.index.get_loc(cross_date)
    sessions_since_cross = len(frame) - 1 - int(cross_position)
    support, support_date, support_label = _closest_support(frame, config)
    distance_to_support_pct = float((latest["close"] / support - 1.0) * 100.0)
    price_above_slow_ma_pct = float(
        (latest["close"] / latest["ma_slow"] - 1.0) * 100.0
    )
    score = (
        volume_ratio * 10.0
        + max(0, config.crossover_lookback - sessions_since_cross)
        + max(0.0, price_above_slow_ma_pct)
    )

    return {
        "symbol": symbol,
        "as_of": _date_string(frame.index[-1]),
        "close": round(float(latest["close"]), 2),
        "ma_type": config.ma_type.upper(),
        "ma_fast": round(float(latest["ma_fast"]), 2),
        "ma_slow": round(float(latest["ma_slow"]), 2),
        "cross_date": _date_string(cross_date),
        "sessions_since_cross": sessions_since_cross,
        "volume": int(spike_volume),
        "average_volume": round(float(spike_average_volume), 0),
        "volume_ratio": round(volume_ratio, 2),
        "volume_spike_date": _date_string(volume_spike_date),
        "volume_spike_pct": round((volume_ratio - 1.0) * 100.0, 2),
        "support": round(float(support), 2),
        "support_date": _date_string(support_date),
        "support_label": support_label,
        "distance_to_support_pct": round(distance_to_support_pct, 2),
        "price_above_slow_ma_pct": round(price_above_slow_ma_pct, 2),
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
        .sort_values(
            ["distance_to_support_pct", "sessions_since_cross", "volume_ratio"],
            ascending=[True, True, False],
        )
        .reset_index(drop=True)
    )


def _moving_average(prices: pd.Series, window: int, ma_type: str) -> pd.Series:
    normalized = ma_type.lower()
    if normalized == "sma":
        return prices.rolling(window).mean()
    if normalized == "ema":
        return prices.ewm(span=window, adjust=False, min_periods=window).mean()
    raise ValueError("ma_type must be 'sma' or 'ema'")


def _best_recent_volume_spike(
    frame: pd.DataFrame,
    config: ScreenConfig,
) -> tuple[float, object, float, float] | None:
    recent = frame.tail(config.volume_spike_lookback)
    candidates = recent[recent["average_volume"].notna() & (recent["average_volume"] > 0)]
    if candidates.empty:
        return None
    ratios = candidates["volume"] / candidates["average_volume"]
    spike_date = ratios.idxmax()
    return (
        float(ratios.loc[spike_date]),
        spike_date,
        float(candidates.loc[spike_date, "volume"]),
        float(candidates.loc[spike_date, "average_volume"]),
    )


def _closest_support(
    frame: pd.DataFrame,
    config: ScreenConfig,
) -> tuple[float, object, str]:
    latest_close = float(frame["close"].iloc[-1])
    supports = _support_candidates(frame, config)
    valid_supports = [
        support
        for support in supports
        if support[0] > 0 and support[0] <= latest_close
    ]
    if not valid_supports:
        support_date = frame["low"].idxmin()
        return float(frame.loc[support_date, "low"]), support_date, "all_time_low"

    return min(valid_supports, key=lambda item: latest_close / item[0] - 1.0)


def _support_candidates(
    frame: pd.DataFrame,
    config: ScreenConfig,
) -> list[tuple[float, object, str]]:
    candidates: list[tuple[float, object, str]] = []
    modes = tuple(mode.lower() for mode in config.support_modes)

    if "pivot" in modes:
        candidates.append(_pivot_support(frame, config))
    if "recent_low" in modes:
        candidates.append(_period_low_support(frame, config.support_lookback, "recent_low"))

    for mode in modes:
        if mode in SUPPORT_MODE_LOOKBACKS:
            candidates.append(
                _period_low_support(frame, SUPPORT_MODE_LOOKBACKS[mode], mode)
            )

    for lookback in config.support_lookbacks:
        candidates.append(
            _period_low_support(frame, lookback, f"{lookback}_bar_low")
        )

    return candidates


def _pivot_support(
    frame: pd.DataFrame,
    config: ScreenConfig,
) -> tuple[float, object, str]:
    recent = frame.tail(config.support_lookback)
    pivot_lows = _pivot_lows(recent["low"], config.support_pivot_span)
    latest_close = float(frame["close"].iloc[-1])
    valid_supports = pivot_lows[pivot_lows <= latest_close]

    if not valid_supports.empty:
        support_date = valid_supports.index[-1]
        return float(valid_supports.iloc[-1]), support_date, "pivot"

    return _period_low_support(frame, config.support_lookback, "pivot_fallback_low")


def _period_low_support(
    frame: pd.DataFrame,
    lookback: int,
    label: str,
) -> tuple[float, object, str]:
    recent = frame.tail(lookback)
    latest_close = float(frame["close"].iloc[-1])
    below_close = recent["low"][recent["low"] <= latest_close]
    support_series = below_close if not below_close.empty else recent["low"]
    support_date = support_series.idxmin()
    return float(support_series.loc[support_date]), support_date, label


def _pivot_lows(lows: pd.Series, span: int) -> pd.Series:
    if span < 1:
        return lows
    rolling_window = span * 2 + 1
    centered_min = lows.rolling(rolling_window, center=True).min()
    return lows[(lows == centered_min) & centered_min.notna()]


def _date_string(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()
