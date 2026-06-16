# Alpaca Golden Cross Stock Screener

This project adapts the indicator-dataframe approach from
[`jbpayton/langchain-stock-screener`](https://github.com/jbpayton/langchain-stock-screener)
into a focused, deterministic Alpaca Markets screener.

It finds stocks where:

1. The 50-session simple moving average crossed above the 200-session SMA
   within the last `N` completed bars.
2. The latest volume is at least `1.5x` the average of the previous 20 bars.
3. The bullish 50/200 alignment is still intact.
4. The most recent support level is calculated from recent pivot lows.
5. Basic price and average-volume liquidity filters pass.

The volume baseline excludes the current bar so the spike does not inflate its
own comparison. When Alpaca reports that the market is open, the current
in-progress daily bar is excluded entirely.

## Setup

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add your Alpaca credentials to `.env`:

```dotenv
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
```

## Run

Screen a watchlist using Alpaca's free IEX feed:

```powershell
alpaca-golden-cross --symbols AAPL,MSFT,NVDA,AMD,AMZN
```

Screen all active, tradable US equities:

```powershell
alpaca-golden-cross --top 25 --output outputs/screen-results.csv
```

Use a symbol file and stricter confirmation:

```powershell
alpaca-golden-cross `
  --symbols-file symbols.txt `
  --cross-lookback 3 `
  --volume-multiplier 2.0 `
  --support-lookback 120 `
  --min-average-volume 500000 `
  --output outputs/screen-results.json
```

Use `--feed sip` only when the Alpaca account has SIP data access.

## Notebook

You can also run the full screener from Jupyter:

```powershell
pip install -e ".[notebook]"
jupyter notebook notebooks/alpaca_golden_cross_screener.ipynb
```

The notebook loads `.env`, lets you configure the watchlist or full universe,
runs the same package code as the CLI, saves CSV/JSON output to `outputs/`, and
includes an optional chart for the closest-to-support match.

## Output

Results are sorted by distance to support from closest to furthest. Support is
defined as the latest local pivot low in the configured lookback window. If no
pivot low is available, the screener falls back to the lowest low in that
window.

The `score` column is still included as a secondary context field favoring
larger volume spikes, more recent crossovers, and stronger separation above the
200-day SMA.

Important fields include `cross_date`, `sessions_since_cross`,
`volume_ratio`, `support`, `support_date`, `distance_to_support_pct`, and
`price_above_slow_pct`.

## Notes

- The default universe can be several thousand symbols and may take time.
  Use `--symbols`, `--symbols-file`, or `--limit-universe` while testing.
- Daily data requires enough history for the 200-day moving average.
- This program screens market data only. It does not place orders.
- A golden cross is a lagging technical signal, not a guarantee of future
  performance. This software is for research and education, not financial
  advice.

## Test

```powershell
pytest
```
