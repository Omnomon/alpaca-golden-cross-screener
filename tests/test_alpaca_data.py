from types import SimpleNamespace

from alpaca_screener.alpaca_data import _include_asset


def asset(symbol: str, exchange: str, tradable: bool = True) -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, exchange=exchange, tradable=tradable)


def test_include_asset_allows_nasdaq_and_nyse_common_stocks():
    assert _include_asset(
        asset("AAPL", "NASDAQ"),
        common_only=True,
        exchanges=("NASDAQ", "NYSE"),
    )
    assert _include_asset(
        asset("IBM", "NYSE"),
        common_only=True,
        exchanges=("NASDAQ", "NYSE"),
    )


def test_include_asset_excludes_other_exchanges_by_default():
    assert not _include_asset(
        asset("OTCM", "OTC"),
        common_only=True,
        exchanges=("NASDAQ", "NYSE"),
    )


def test_include_asset_still_excludes_non_common_on_allowed_exchange():
    assert not _include_asset(
        asset("ABR.PRD", "NYSE"),
        common_only=True,
        exchanges=("NASDAQ", "NYSE"),
    )


def test_include_asset_can_accept_custom_exchange_and_non_common():
    assert _include_asset(
        asset("ABR.PRD", "NYSE"),
        common_only=False,
        exchanges=("NYSE",),
    )
