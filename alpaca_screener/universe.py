from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


CAP_BUCKETS = {
    "small": (0, 2_000_000_000),
    "mid": (2_000_000_000, 10_000_000_000),
    "large": (10_000_000_000, float("inf")),
}
CAP_ALIASES = {"medium": "mid"}
PERFORMANCE_WINDOWS = {"1m": 21, "3m": 63, "6m": 126}


def is_common_stock_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    if any(token in normalized for token in (".PR", "-P", ".WS", ".WT", ".U")):
        return False
    return True


@dataclass(frozen=True)
class UniverseFilterConfig:
    fundamentals_file: str | None = None
    pe_min: float | None = None
    pe_max: float | None = None
    industries: tuple[str, ...] = field(default_factory=tuple)
    market_caps: tuple[str, ...] = field(default_factory=tuple)
    cap_mix: dict[str, float] = field(default_factory=dict)
    min_30d_share_volume: float | None = None
    min_30d_dollar_volume: float | None = None
    performance_windows: tuple[str, ...] = field(default_factory=tuple)
    top_performance_pct: float | None = None
    min_performance: dict[str, float] = field(default_factory=dict)
    max_symbols: int | None = None

    @property
    def needs_fundamentals(self) -> bool:
        return any(
            [
                self.pe_min is not None,
                self.pe_max is not None,
                self.industries,
                self.market_caps,
                self.cap_mix,
            ]
        )

    @property
    def needs_volume(self) -> bool:
        return (
            self.min_30d_share_volume is not None
            or self.min_30d_dollar_volume is not None
            or bool(self.cap_mix)
        )

    @property
    def needs_performance(self) -> bool:
        return bool(self.performance_windows or self.min_performance)


def load_fundamentals_file(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame = frame.rename(columns={column: _normalize_column(column) for column in frame})
    required = {"symbol"}
    if not required.issubset(frame.columns):
        raise ValueError("Fundamentals file must include a symbol column.")

    output = pd.DataFrame()
    output["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    output["pe"] = pd.to_numeric(_optional_column(frame, "pe"), errors="coerce")
    output["market_cap"] = pd.to_numeric(
        _optional_column(frame, "market_cap"), errors="coerce"
    )
    output["industry"] = _optional_column(frame, "industry").astype("string")
    output["sector"] = _optional_column(frame, "sector").astype("string")
    output["market_cap_bucket"] = output["market_cap"].apply(market_cap_bucket)

    if "market_cap_bucket" in frame.columns:
        output["market_cap_bucket"] = (
            frame["market_cap_bucket"]
            .astype("string")
            .str.lower()
            .map(lambda value: _normalize_cap_bucket(value) if pd.notna(value) else None)
            .fillna(output["market_cap_bucket"])
        )

    return output.drop_duplicates("symbol")


def filter_universe(
    symbols: list[str],
    config: UniverseFilterConfig,
    *,
    fundamentals: pd.DataFrame | None = None,
    volume_stats: pd.DataFrame | None = None,
) -> list[str]:
    frame = pd.DataFrame({"symbol": list(dict.fromkeys(symbols))})

    if fundamentals is not None and not fundamentals.empty:
        frame = frame.merge(fundamentals, on="symbol", how="left")
        frame = _filter_fundamentals(frame, config)

    if volume_stats is not None and not volume_stats.empty:
        frame = frame.merge(volume_stats, on="symbol", how="left")
        frame = _filter_volume(frame, config)
        frame = _filter_performance(frame, config)

    if config.cap_mix and "market_cap_bucket" in frame.columns:
        frame = _apply_cap_mix(frame, config.cap_mix, config.max_symbols)
    elif config.max_symbols:
        frame = frame.sort_values(
            _sort_column(frame), ascending=False, na_position="last"
        ).head(config.max_symbols)

    return frame["symbol"].dropna().astype(str).tolist()


def market_cap_bucket(market_cap: float | None) -> str | None:
    if market_cap is None or pd.isna(market_cap):
        return None
    for bucket, (lower, upper) in CAP_BUCKETS.items():
        if lower <= market_cap < upper:
            return bucket
    return None


def volume_stats_from_bars(
    bars_by_symbol: dict[str, pd.DataFrame],
    lookback: int = 30,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, bars in bars_by_symbol.items():
        if bars.empty or not {"close", "volume"}.issubset(bars.columns):
            continue
        recent = bars.sort_index().tail(lookback)
        share_volume = float(recent["volume"].sum())
        dollar_volume = float((recent["close"] * recent["volume"]).sum())
        performance = performance_from_bars(bars)
        rows.append(
            {
                "symbol": symbol,
                "share_volume_30d": share_volume,
                "dollar_volume_30d": dollar_volume,
                **performance,
            }
        )
    return pd.DataFrame(rows)


def performance_from_bars(bars: pd.DataFrame) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    closes = bars.sort_index()["close"].dropna()
    for label, sessions in PERFORMANCE_WINDOWS.items():
        column = f"performance_{label}_pct"
        if len(closes) <= sessions or closes.iloc[-sessions - 1] <= 0:
            output[column] = None
            continue
        output[column] = float((closes.iloc[-1] / closes.iloc[-sessions - 1] - 1) * 100)
    return output


def _filter_fundamentals(
    frame: pd.DataFrame,
    config: UniverseFilterConfig,
) -> pd.DataFrame:
    output = frame
    if config.pe_min is not None:
        output = output[output["pe"] >= config.pe_min]
    if config.pe_max is not None:
        output = output[output["pe"] <= config.pe_max]
    if config.industries:
        wanted = {item.lower() for item in config.industries}
        output = output[
            output["industry"].fillna("").str.lower().isin(wanted)
            | output["sector"].fillna("").str.lower().isin(wanted)
        ]
    if config.market_caps:
        wanted_caps = {_normalize_cap_bucket(item) for item in config.market_caps}
        output = output[output["market_cap_bucket"].isin(wanted_caps)]
    return output


def _filter_volume(
    frame: pd.DataFrame,
    config: UniverseFilterConfig,
) -> pd.DataFrame:
    output = frame
    if config.min_30d_share_volume is not None:
        output = output[output["share_volume_30d"] >= config.min_30d_share_volume]
    if config.min_30d_dollar_volume is not None:
        output = output[output["dollar_volume_30d"] >= config.min_30d_dollar_volume]
    return output


def _filter_performance(
    frame: pd.DataFrame,
    config: UniverseFilterConfig,
) -> pd.DataFrame:
    output = frame
    for window, threshold in config.min_performance.items():
        column = _performance_column(window)
        if column in output.columns:
            output = output[output[column] >= threshold]

    if config.performance_windows and config.top_performance_pct is not None:
        columns = [
            _performance_column(window)
            for window in config.performance_windows
            if _performance_column(window) in output.columns
        ]
        if not columns:
            return output.head(0)
        ranks = output[columns].rank(pct=True, ascending=False, method="min")
        output = output[ranks.min(axis=1) <= config.top_performance_pct / 100.0]
    return output


def _apply_cap_mix(
    frame: pd.DataFrame,
    cap_mix: dict[str, float],
    max_symbols: int | None,
) -> pd.DataFrame:
    total = max_symbols or len(frame)
    selected = []
    sort_column = _sort_column(frame)
    for raw_bucket, pct in cap_mix.items():
        bucket = _normalize_cap_bucket(raw_bucket)
        count = max(1, round(total * pct / 100.0))
        bucket_frame = frame[frame["market_cap_bucket"] == bucket]
        selected.append(
            bucket_frame.sort_values(
                sort_column, ascending=False, na_position="last"
            ).head(count)
        )
    if not selected:
        return frame.head(0)
    output = pd.concat(selected).drop_duplicates("symbol")
    return output.head(total) if max_symbols else output


def _sort_column(frame: pd.DataFrame) -> str:
    if "performance_3m_pct" in frame.columns:
        return "performance_3m_pct"
    if "performance_1m_pct" in frame.columns:
        return "performance_1m_pct"
    if "performance_6m_pct" in frame.columns:
        return "performance_6m_pct"
    if "dollar_volume_30d" in frame.columns:
        return "dollar_volume_30d"
    if "share_volume_30d" in frame.columns:
        return "share_volume_30d"
    if "market_cap" in frame.columns:
        return "market_cap"
    return "symbol"


def _first_number(*values: object) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_cap_bucket(value: str) -> str:
    normalized = value.strip().lower()
    return CAP_ALIASES.get(normalized, normalized)


def _normalize_column(column: str) -> str:
    normalized = column.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "ticker": "symbol",
        "pe_ratio": "pe",
        "trailing_pe": "pe",
        "forward_pe": "pe",
        "marketcap": "market_cap",
        "market_capitalization": "market_cap",
        "cap": "market_cap",
        "cap_bucket": "market_cap_bucket",
    }
    return aliases.get(normalized, normalized)


def _optional_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([None] * len(frame), index=frame.index)


def _performance_column(window: str) -> str:
    normalized = window.lower().replace("_", "").replace("-", "")
    aliases = {
        "1": "1m",
        "1m": "1m",
        "1month": "1m",
        "3": "3m",
        "3m": "3m",
        "3month": "3m",
        "6": "6m",
        "6m": "6m",
        "6month": "6m",
    }
    label = aliases.get(normalized, normalized)
    return f"performance_{label}_pct"
