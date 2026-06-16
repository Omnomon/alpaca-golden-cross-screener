# Alpaca Golden Cross Stock Screener

This project adapts the indicator-dataframe approach from
[`jbpayton/langchain-stock-screener`](https://github.com/jbpayton/langchain-stock-screener)
into a focused, deterministic Alpaca Markets screener.

It finds stocks where:

1. The configurable fast moving average crossed above the configurable slow
   moving average within the last `N` completed bars.
2. The moving-average type can be simple (`SMA`) or exponential (`EMA`).
3. Volume spiked by at least the target percentage on one of the last 3 bars
   versus its trailing average volume.
4. The bullish fast/slow moving-average alignment is still intact.
5. Support can be calculated from pivot lows, recent lows, monthly lows, or a
   custom list of lookback windows.
6. Basic price and average-volume liquidity filters pass.

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
  --fast-window 21 `
  --slow-window 50 `
  --ma-type ema `
  --cross-lookback 3 `
  --volume-spike-pct 100 `
  --volume-spike-lookback 3 `
  --support-modes pivot,recent_low,1_month_low,3_month_low `
  --support-lookback 120 `
  --support-lookbacks 21,63,126 `
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

If you pull strategy updates while the notebook is already open, restart the
kernel or rerun the Setup cell before running the configuration cell. The Setup
cell forces Jupyter to load the local checkout instead of a stale imported copy.

## Output

Results are sorted by distance to support from closest to furthest. The screener
can compare multiple support candidates and choose the closest one below the
latest close:

- `pivot`: latest local pivot low in `--support-lookback`.
- `recent_low`: lowest low in `--support-lookback`.
- `1_month_low`, `3_month_low`, `6_month_low`, `1_year_low`: fixed trading-day
  low windows.
- `--support-lookbacks`: custom comma-separated low windows such as
  `21,63,126`.

The `score` column is still included as a secondary context field favoring
larger volume spikes, more recent crossovers, and stronger separation above the
slow moving average.

Important fields include `cross_date`, `sessions_since_cross`,
`ma_type`, `volume_spike_date`, `volume_spike_pct`, `support`,
`support_label`, `support_date`, `distance_to_support_pct`, and
`price_above_slow_ma_pct`.

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
