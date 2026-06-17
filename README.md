# Alpaca Weekly Technical Stock Screener

This project adapts the indicator-dataframe approach from
[`jbpayton/langchain-stock-screener`](https://github.com/jbpayton/langchain-stock-screener)
into a focused, deterministic Alpaca Markets screener.

It screens weekly setups where:

1. Weekly `EMA(50) > EMA(200)`.
2. Weekly `SMA(50) > SMA(200)`.
3. Weekly Awesome Oscillator is above `0.5`.
4. Latest weekly volume is more than `5%` above the prior week.
5. The 3-month low is above the 6-month low by `0%` to `3%`.
6. Ultimate Oscillator `(7, 14, 28)` crosses upward through `50`.

All strategy thresholds are configurable from the CLI, notebook, or Python API.
When Alpaca reports that the market is open, the current in-progress daily bar is
excluded before weekly bars are built.

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

Screen all active, tradable NASDAQ and NYSE common stocks:

```powershell
alpaca-golden-cross --top 25 --output outputs/screen-results.csv
```

Use a symbol file and stricter universe filters:

```powershell
alpaca-golden-cross `
  --symbols-file symbols.txt `
  --fundamentals-file data/fundamentals.csv `
  --pe-max 35 `
  --industries Semiconductors,Technology `
  --market-caps mid,large `
  --performance-windows 1m,3m,6m `
  --top-performance-pct 2 `
  --min-performance 3m:25 `
  --cap-mix mid:40,large:60 `
  --min-30d-dollar-volume 500000000 `
  --max-filtered-symbols 100 `
  --ema-fast-window 50 `
  --ema-slow-window 200 `
  --sma-fast-window 50 `
  --sma-slow-window 200 `
  --ao-min 0.5 `
  --volume-change-pct 5 `
  --low-near-min-pct 0 `
  --low-near-max-pct 3 `
  --uo-cross-level 50 `
  --min-weekly-volume 500000 `
  --output outputs/screen-results.json
```

Use `--feed sip` only when the Alpaca account has SIP data access.

## Universe Filters

By default, generated universes are limited to active tradable NASDAQ and NYSE
common stocks. Preferred shares, warrants, and units are excluded to avoid noisy
symbols such as `ABR.PRD` and `ACHR.WS`.

Alpaca bars/assets data does not include P/E, market cap, or industry, and this
project intentionally avoids per-symbol `yfinance` calls because they rate limit
quickly and return noisy blanks. Fundamental filters use a local CSV supplied
with `--fundamentals-file`; 30-day traded volume and recent performance are
calculated from Alpaca daily bars before the full strategy fetch.

Fundamentals CSV columns:

- Required: `symbol`.
- Optional: `pe`, `market_cap`, `industry`, `sector`, `market_cap_bucket`.
- Accepted aliases include `ticker`, `pe_ratio`, `trailing_pe`, `forward_pe`,
  `marketCap`, `market_capitalization`, and `cap_bucket`.

Universe options:

- `--pe-min`, `--pe-max`: trailing P/E range.
- `--industries`: comma-separated industry or sector names.
- `--market-caps`: include cap buckets: `small`, `mid`/`medium`, `large`.
- `--cap-mix`: select a target filtered-universe mix, for example
  `small:20,mid:30,large:50`.
- `--min-30d-share-volume`: minimum shares traded over the last 30 bars.
- `--min-30d-dollar-volume`: minimum dollar volume over the last 30 bars.
- `--performance-windows`: rank by recent performance windows: `1m`, `3m`,
  `6m`.
- `--top-performance-pct`: keep stocks in the top N percent of selected
  performance windows, for example `2` for top 2%.
- `--min-performance`: require a minimum return by window, for example
  `3m:25` keeps stocks up more than 25% over roughly 3 months.
- `--max-filtered-symbols`: cap the filtered universe before full screening.
- `--include-non-common`: include preferred shares, warrants, and units.
- `--exchanges`: Alpaca exchange list for generated universes. Defaults to
  `NASDAQ,NYSE`.

## Strategy Options

- `--ema-fast-window`, `--ema-slow-window`: weekly EMA alignment windows.
- `--sma-fast-window`, `--sma-slow-window`: weekly SMA alignment windows.
- `--ao-fast-window`, `--ao-slow-window`, `--ao-min`: Awesome Oscillator
  settings.
- `--volume-change-pct`: required latest-week volume increase versus the prior
  week.
- `--low-near-short-weeks`, `--low-near-long-weeks`: low comparison windows.
  Defaults to 13 and 26 weeks, roughly 3 and 6 months.
- `--low-near-min-pct`, `--low-near-max-pct`: allowed distance between the
  short-window low and long-window low.
- `--uo-short-window`, `--uo-medium-window`, `--uo-long-window`,
  `--uo-cross-level`: Ultimate Oscillator settings.
- `--no-require-uo-cross-up`: accept UO already above the level instead of
  requiring a fresh upward cross.
- `--min-price`, `--min-weekly-volume`: liquidity filters.

## Notebook

You can also run the full screener from Jupyter:

```powershell
pip install -e ".[notebook]"
jupyter notebook notebooks/alpaca_golden_cross_screener.ipynb
```

The notebook loads `.env`, lets you configure the watchlist or full universe,
runs the same package code as the CLI, saves CSV/JSON output to `outputs/`, and
includes optional weekly charts for the top match.

If you pull strategy updates while the notebook is already open, restart the
kernel or rerun the Setup cell before running the configuration cell. The Setup
cell forces Jupyter to load the local checkout instead of a stale imported copy.

## Output

Results are sorted by `score` from strongest to weakest. The score favors
stronger AO, higher weekly volume change, UO strength above the trigger level,
and lows that are closer to the 6-month low.

Important fields include `ema_fast`, `ema_slow`, `sma_fast`, `sma_slow`, `ao`,
`volume_change_pct`, `low_3m`, `low_6m`, `low_3m_above_6m_pct`, `uo`,
`previous_uo`, and `score`.

## Notes

- The default universe can be several thousand symbols and may take time. Use
  `--symbols`, `--symbols-file`, or `--limit-universe` while testing.
- The weekly strategy needs enough daily history for 200-week averages, so the
  default full strategy fetch requests about 2,000 calendar days.
- This program screens market data only. It does not place orders.
- Technical signals are lagging research filters, not guarantees of future
  performance. This software is for research and education, not financial
  advice.

## Test

```powershell
pytest
```
