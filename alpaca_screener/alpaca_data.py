from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pandas as pd

from .universe import is_common_stock_symbol

if TYPE_CHECKING:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

DEFAULT_EXCHANGES = ("NASDAQ", "NYSE")


def clients_from_environment() -> tuple["StockHistoricalDataClient", "TradingClient"]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_KEY")
    secret = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment or .env."
        )
    return StockHistoricalDataClient(key, secret), TradingClient(key, secret)


def get_tradable_symbols(
    trading_client: "TradingClient",
    limit: int | None = None,
    common_only: bool = True,
    exchanges: tuple[str, ...] = DEFAULT_EXCHANGES,
) -> list[str]:
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest

    request = GetAssetsRequest(
        status=AssetStatus.ACTIVE,
        asset_class=AssetClass.US_EQUITY,
    )
    symbols = sorted(
        asset.symbol
        for asset in trading_client.get_all_assets(request)
        if _include_asset(asset, common_only=common_only, exchanges=exchanges)
    )
    return symbols[:limit] if limit else symbols


def _include_asset(
    asset: object,
    *,
    common_only: bool,
    exchanges: tuple[str, ...],
) -> bool:
    symbol = getattr(asset, "symbol", "")
    exchange = _normalize_exchange(getattr(asset, "exchange", ""))
    allowed_exchanges = {_normalize_exchange(item) for item in exchanges}
    return (
        bool(getattr(asset, "tradable", False))
        and bool(exchange)
        and symbol.isascii()
        and (not allowed_exchanges or exchange in allowed_exchanges)
        and (not common_only or is_common_stock_symbol(symbol))
    )


def _normalize_exchange(value: object) -> str:
    raw = getattr(value, "value", value)
    normalized = str(raw or "").upper()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized


def fetch_daily_bars(
    data_client: StockHistoricalDataClient,
    symbols: Iterable[str],
    *,
    calendar_days: int = 420,
    batch_size: int = 200,
    feed: "DataFeed | None" = None,
    incomplete_session_date: date | None = None,
) -> dict[str, pd.DataFrame]:
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    if feed is None:
        feed = DataFeed.IEX
    symbol_list = list(dict.fromkeys(symbol.upper() for symbol in symbols))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=calendar_days)
    output: dict[str, pd.DataFrame] = {}

    for offset in range(0, len(symbol_list), batch_size):
        batch = symbol_list[offset : offset + batch_size]
        request = StockBarsRequest(
            symbol_or_symbols=batch,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=feed,
        )
        frame = data_client.get_stock_bars(request).df
        if frame.empty:
            continue
        if isinstance(frame.index, pd.MultiIndex):
            for symbol, symbol_frame in frame.groupby(level="symbol"):
                output[str(symbol)] = _drop_incomplete_session(
                    symbol_frame.droplevel("symbol"), incomplete_session_date
                )
        elif len(batch) == 1:
            output[batch[0]] = _drop_incomplete_session(
                frame, incomplete_session_date
            )

    return output


def _drop_incomplete_session(
    frame: pd.DataFrame,
    incomplete_session_date: date | None,
) -> pd.DataFrame:
    if incomplete_session_date is None or frame.empty:
        return frame
    session_dates = pd.DatetimeIndex(frame.index).date
    return frame.loc[session_dates != incomplete_session_date]
