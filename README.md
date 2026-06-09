# Alpaca Golden Cross Stock Screener

This project adapts the indicator-dataframe approach from
[`jbpayton/langchain-stock-screener`](https://github.com/jbpayton/langchain-stock-screener)
into a focused, deterministic Alpaca Markets screener.

It finds stocks where:

1. The 50-session simple moving average crossed above the 200-session SMA
   within the last `N` completed bars.
2. The latest volume is at least `1.5x` the average of the previous 20 bars.
3. The bullish 50/200 alignment is still intact.
4. Basic price and average-volume liquidity filters pass.

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
  --min-average-volume 500000 `
  --output outputs/screen-results.json
```

Use `--feed sip` only when the Alpaca account has SIP data access.

## Output

Results are ranked by a transparent score favoring:

- Larger volume spikes.
- More recent crossovers.
- A close farther above the 200-day SMA.

Important fields include `cross_date`, `sessions_since_cross`,
`volume_ratio`, and `price_above_slow_pct`.

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
