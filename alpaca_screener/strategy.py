from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ScreenConfig:
    fast_window: int = 50
    slow_window: int = 200
    crossover_lookback: int = 5
    volume_window: int = 20
    volume_multiplier: float = 1.5
    min_price: float = 5.0
    min_average_volume: float = 100_000.0

    @property
    def minimum_bars(self) -> int:
        return self.slow_window + self.crossover_lookback


RESULT_COLUMNS = [
    "symbol",
    "as_of",
    "close",
    "sma_fast",
    "sma_slow",
    "cross_date",
    "sessions_since_cross",
    "volume",
    "average_volume",
    "volume_ratio",
    "price_above_slow_pct",
    "score",
]


def analyze_symbol(
    symbol: str,
    bars: pd.DataFrame,
    config: ScreenConfig,
) -> dict[str, object] | None:
    required = {"close", "volume"}
    if not required.issubset(bars.columns):
        missing = ", ".join(sorted(required - set(bars.columns)))
        raise ValueError(f"{symbol}: missing required columns: {missing}")

    frame = bars.sort_index().copy()
    frame = frame.loc[:, ["close", "volume"]].dropna()
    if len(frame) < config.minimum_bars:
        return None

    frame["sma_fast"] = frame["close"].rolling(config.fast_window).mean()
    frame["sma_slow"] = frame["close"].rolling(config.slow_window).mean()
    frame["average_volume"] = (
        frame["volume"].shift(1).rolling(config.volume_window).mean()
    )
    frame["golden_cross"] = (
        (frame["sma_fast"] > frame["sma_slow"])
        & (frame["sma_fast"].shift(1) <= frame["sma_slow"].shift(1))
    )

    recent = frame.tail(config.crossover_lookback + 1)
    crosses = recent.index[recent["golden_cross"].fillna(False)]
    if len(crosses) == 0:
        return None

    latest = frame.iloc[-1]
    if pd.isna(latest["average_volume"]) or latest["average_volume"] <= 0:
        return None

    volume_ratio = float(latest["volume"] / latest["average_volume"])
    if (
        latest["sma_fast"] <= latest["sma_slow"]
        or latest["close"] < config.min_price
        or latest["average_volume"] < config.min_average_volume
        or volume_ratio < config.volume_multiplier
    ):
        return None

    cross_date = crosses[-1]
    cross_position = frame.index.get_loc(cross_date)
    sessions_since_cross = len(frame) - 1 - int(cross_position)
    price_above_slow_pct = float(
        (latest["close"] / latest["sma_slow"] - 1.0) * 100.0
    )
    score = (
        volume_ratio * 10.0
        + max(0, config.crossover_lookback - sessions_since_cross)
        + max(0.0, price_above_slow_pct)
    )

    return {
        "symbol": symbol,
        "as_of": _date_string(frame.index[-1]),
        "close": round(float(latest["close"]), 2),
        "sma_fast": round(float(latest["sma_fast"]), 2),
        "sma_slow": round(float(latest["sma_slow"]), 2),
        "cross_date": _date_string(cross_date),
        "sessions_since_cross": sessions_since_cross,
        "volume": int(latest["volume"]),
        "average_volume": round(float(latest["average_volume"]), 0),
        "volume_ratio": round(volume_ratio, 2),
        "price_above_slow_pct": round(price_above_slow_pct, 2),
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
        .sort_values(["score", "volume_ratio"], ascending=False)
        .reset_index(drop=True)
    )


def _date_string(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()

