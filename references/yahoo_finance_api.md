# Yahoo Finance Market Data Reference

## Overview

All market data is fetched via the **`yfinance` Python library**, which wraps Yahoo Finance's
internal endpoints. We do NOT call the Yahoo Finance API directly.

**Why `yfinance`** (do NOT use raw `urllib`/`requests`):
1. **SSL certificate errors** on macOS (Python can't find system certs)
2. **Cookie/crumb authentication** — Yahoo endpoints require session cookies + crumb tokens,
   which `yfinance` handles automatically
3. **Rate limiting** (HTTP 429) — `yfinance` manages backoff and retries

```bash
# Install in venv
.venv/bin/pip install yfinance
```

## yfinance Usage

### Historical Prices
```python
import yfinance as yf
ticker = yf.Ticker("AAPL")
hist = ticker.history(start="2024-01-01", end="2024-12-31", auto_adjust=False)
# Returns DataFrame with: Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits
```

### Dividends
```python
ticker = yf.Ticker("AAPL")
divs = ticker.dividends  # Series of dividend amounts by date
```

### Quick Quote (Multiple Tickers)
```python
tickers = yf.Tickers("AAPL MSFT GOOGL")
for t in tickers.tickers.values():
    print(t.info.get("regularMarketPrice"))
```

### Ticker Info
```python
ticker = yf.Ticker("AAPL")
info = ticker.info  # dict with: marketCap, dividendYield, exDividendDate, 52-week range, etc.
```

## Ticker Symbol Resolution (Non-US Stocks)

Trading 212 and other brokerages use plain tickers (e.g., "LLOY") but Yahoo Finance
requires exchange suffixes for non-US stocks. Map using **trade_currency** and **ISIN prefix**:

| Currency | Suffix | Example |
|----------|--------|---------|
| USD | *(none)* | `AAPL`, `AMZN` |
| GBP/GBX | `.L` | `LLOY.L`, `VUSA.L` |
| CAD | `.TO` | `CNQ.TO`, `RY.TO` |
| CHF | `.SW` | `NESN.SW` |
| EUR (FR ISIN) | `.PA` | `TTE.PA`, `OR.PA` |
| EUR (DE ISIN) | `.DE` | `BMW.DE`, `O2D.DE` |
| EUR (NL ISIN) | `.AS` | `ASML.AS` |
| EUR (ES ISIN) | `.MC` | `ITX.MC` |
| EUR (BE ISIN) | `.BR` | `PROX.BR` |
| EUR (IE ISIN) | `.L` | Irish-domiciled ETFs on LSE |

Special character handling: `BT/A` → `BT-A.L` (replace `/` with `-`).

## Usage Guidelines

### Price Adjustment
- Always use `adjclose` (adjusted close) for analysis — accounts for splits and dividends
- The raw `close` field is unadjusted — do not use for timing analysis

### Dividend Date Logic
- Historical ex-dividend dates come from `ticker.dividends`
- A sell **before** the ex-date = seller MISSES the dividend
- A sell **on or after** the ex-date = seller GETS the dividend

### Date Handling
- Fetch a window: 60 trading days before + 90 trading days after each action cluster
- For each ticker, merge overlapping windows into a single request

### Error Handling
- Ticker not found: may be delisted or mistyped — `yfinance` returns empty DataFrame
- Empty data: ticker exists but no data for the requested range
- `NaN` values in OHLCV: trading halt or holiday — skip those bars
- ~3% of tickers may fail (delisted, OTC) — pipeline gracefully degrades

### Common Ticker Issues
- Mutual funds (e.g., `VFIAX`) may not have full OHLCV data
- International stocks need exchange suffix (see resolution table above)
- Crypto uses format like `BTC-USD`
- Delisted stocks may have limited historical data
