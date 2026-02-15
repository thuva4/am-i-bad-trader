---
name: am-i-bad-trader
description: >
  Analyze a user's past portfolio actions (BUY, SELL, DIVIDEND, INTEREST, DEPOSIT, WITHDRAWAL, etc.)
  from uploaded CSV files against real market data. Fetches historical prices, dividend dates, and
  market context from Yahoo Finance public endpoints to evaluate timing quality, missed opportunities,
  and behavioral patterns. Produces a detailed HTML report with concrete examples, scores, and
  actionable advice. Use this skill whenever the user uploads brokerage CSV exports, trade logs,
  transaction histories, or mentions wanting to analyze their past trades, portfolio timing,
  investment mistakes, or trading patterns. Also trigger when the user says things like
  "how did my trades do", "analyze my portfolio", "review my transactions", "did I time the
  market well", or "what mistakes did I make in my investments".
---

# Portfolio Action Analyzer (am-i-bad-trader)

Analyze a user's historical portfolio actions against real market data to surface timing mistakes,
missed opportunities, and behavioral patterns — with concrete examples and actionable advice.

GitHub: https://github.com/thuva4/am-i-bad-trader

## Overview

This skill ingests CSV files containing the user's brokerage/portfolio transaction history,
fetches surrounding market data from Yahoo Finance's public API, and produces a comprehensive
analysis report showing exactly what happened around each action.

## Prerequisites

**IMPORTANT: Never install packages with system pip.** Always use a virtual environment.

```bash
# Create venv if it doesn't exist
python3 -m venv .venv
# Install dependencies inside venv
.venv/bin/pip install -r requirements.txt
```

All commands must use the venv:
- Install packages: `.venv/bin/pip install ...` (NEVER `pip install` or `python3 -m pip install`)
- Run scripts: `.venv/bin/python3 ...` (NEVER `python3` directly)

## Step-by-Step Workflow

### 1. Parse the User's CSV

Read `references/csv_formats.md` for all supported CSV column layouts and normalization rules.

Run the parser on whatever CSVs the user uploaded:
```bash
.venv/bin/python3 scripts/parse_csv.py /path/to/csv/dir/ --output parsed_actions.json
```

The parser is flexible and handles many brokerage formats including Trading 212.
If it fails, inspect the CSV manually and help the user identify columns.

The parser captures **currency**, **trade_currency**, **ISIN**, and **exchange_rate** fields
(when available) which are critical for multi-currency handling and Yahoo Finance ticker resolution.

**Key currency fields**:
- `currency` = account currency from "Currency (Total)" column (e.g., GBP)
- `trade_currency` = trade currency from "Currency (Price / share)" (e.g., USD, GBX, EUR)
- `exchange_rate` = divisor to convert trade currency → account currency
- `price` = share price in trade currency (full precision for fractional shares)
- `total` = transaction total in account currency (GBP)

**Trading 212 CSV specifics**:
- Column "Time" (not "Date") contains the timestamp
- Column "No. of shares" for quantity
- Column "Price / share" for price
- Actions are "Market buy" / "Market sell" (normalized to BUY/SELL)

### 2. Fetch Market Data

For every unique ticker, fetch historical price, dividend, and split data from Yahoo Finance
using the `yfinance` library (handles auth cookies, crumbs, and rate limiting automatically).

```bash
.venv/bin/python3 scripts/fetch_market_data.py parsed_actions.json --output market_data.json
```

**Ticker resolution** uses `trade_currency` (not account currency) and ISIN prefix:
- USD → no suffix (AAPL, AMZN)
- GBP/GBX → `.L` suffix (LLOY.L, VUSA.L)
- CAD → `.TO` suffix (CNQ.TO)
- CHF → `.SW` suffix (NESN.SW)
- EUR → ISIN prefix mapping (FR→`.PA`, DE→`.DE`, NL→`.AS`, ES→`.MC`, BE→`.BR`, IT→`.MI`)
- Special characters: `BT/A` → `BT-A.L`

**Multi-exchange splitting**: When the same ticker has trades in different currencies
(e.g., CNQ bought in both USD and CAD), the fetch script automatically splits them into
separate tickers (CNQ for USD, CNQ.TO for CAD) so they are treated as independent positions.
Uses majority voting across BUY/SELL actions when a single currency must be chosen.

**Date range**: Fetches from 150 days before the earliest action through today (not just
around each action). This ensures all stock splits are captured, even those that happened
long after the last trade.

**Market data structure**:
```
market_data["data"][ticker]["chart"]["prices"]   → list of {date, close, open, high, low, volume}
market_data["data"][ticker]["chart"]["dividends"] → list of {date, amount}
market_data["data"][ticker]["chart"]["splits"]    → list of {date, numerator, denominator}
market_data["data"][ticker]["chart"]["meta"]      → {currency, exchange_timezone, instrument_type}
market_data["ticker_symbol_map"]                  → {csv_ticker: yahoo_symbol}
```

Read `references/yahoo_finance_api.md` for full endpoint documentation.

**If network is unavailable**: Inform user, offer CSV-only structural analysis.

### 3. Run the Analysis

```bash
.venv/bin/python3 scripts/analyze_portfolio.py \
  parsed_actions.json \
  market_data.json \
  --output analysis_results.json
```

Read `references/analysis_methodology.md` for the full scoring and pattern-detection logic.

The analyzer runs these steps in order:

#### Pre-processing

1. **Multi-exchange splitting**: Same as fetch — splits tickers traded in multiple currencies
   into separate positions. This ensures the analysis matches the fetched data.

2. **Stock split adjustment**: Yahoo Finance retroactively adjusts all historical prices for
   splits. CSV data has pre-split prices/quantities. The analyzer extracts all splits from
   Yahoo's data and adjusts each action's quantity and price to match Yahoo's basis:
   - `adjusted_quantity = original_quantity * cumulative_split_factor`
   - `adjusted_price = original_price / cumulative_split_factor`
   - `total_gbp` is unchanged (you paid the same amount regardless of splits)
   - Forward splits (e.g., NVDA 10:1): yfinance ratio > 1, factor multiplies quantity
   - Reverse splits (e.g., TTOO 1:100): yfinance ratio < 1 (0.01), factor divides quantity

#### Portfolio Tracking (chronological pass)
- Tracks average cost basis per ticker using weighted average of GBP totals
- Computes realized P&L for each sell vs actual avg cost basis
- Tracks deposits, withdrawals, dividends, interest, fees
- Computes current holdings value using latest market data
- Produces overall portfolio return: `(realized + unrealized + dividends + interest - fees) / net_invested`

#### Per-Action Timing Analysis
**Timing Analysis** (per BUY/SELL):
- Price trajectory 1, 5, 10, 30, 60, 90 days after action
- Nearby peaks/troughs detection
- Timing score: -100 (catastrophic) to +100 (perfect)
- Dollar impact vs optimal timing (normalized to GBP via percentage method)

**Dividend Analysis** (per SELL):
- Proximity to ex-dividend dates (sold before collecting?)
- Missed dividend amounts converted to account currency (GBP) using exchange_rate as divisor

**DCA (Dollar-Cost Averaging) Detection**:
- Detects recurring buy sequences (same ticker, regular intervals, similar amounts)
- Classifies interval type (daily, weekly, biweekly, monthly)
- Minimum 4 consecutive buys to qualify
- Amount similarity: within 50% of median
- Gap tolerance: up to 2.5x detected median interval
- Computes consistency score, DCA vs lump sum return comparison
- DCA actions excluded from FOMO buy and worst-timed buy detection (unfair for automated buys)
- Still evaluates timing quality and detects well-timed buys (positive reinforcement)

**Benchmark Comparison (vs SPY)**:
- Portfolio time-weighted return (Modified Dietz method) vs SPY buy-and-hold
- Alpha (excess return vs benchmark), CAGR for both
- Monthly cumulative comparison series (last 12 months)

**Risk-Adjusted Return Metrics** (uses numpy):
- Daily portfolio value reconstruction from position data
- Annualized volatility: `std(daily_returns) * sqrt(252)`
- Sharpe ratio: `(annualized_return - 4.5%) / annualized_volatility`
- Sortino ratio: `(annualized_return - 4.5%) / downside_deviation`
- Maximum drawdown with peak/trough dates and recovery timeline
- Daily return statistics (best/worst day, win rate)

**Behavioral Pattern Detection** (with detailed reasoning):
- **Panic selling**: detects sells after >5% 5-day drops, shows price recovery trajectory,
  optimal sell date, and missed upside percentage
- **FOMO buying**: detects buys after >10% 10-day run-ups, shows max drawdown after entry,
  optimal buy date, and overpaid percentage (DCA buys excluded)
- **Worst-timed sells**: detects sells followed by >10% rally (sold at the bottom),
  shows missed rally %, max price after, optimal sell date, price trajectory
- **Worst-timed buys**: detects buys followed by >10% drop (bought at the top),
  shows max drawdown, bought-the-top flag, recovery date, price trajectory (DCA buys excluded)
- **Well-timed sells**: detects sells followed by >5% decline (good exit),
  shows loss avoided %, stayed-below-sell-price flag, price trajectory
- **Well-timed buys**: detects buys followed by >10% gain (good entry),
  shows max gain %, dip-buy detection, never-went-below-entry flag
- All patterns include price trajectory at 1 week, 1 month, 3 months after action
- Chasing losses / round-trip losses (FIFO matched buy-sell pairs)
- Wash sale candidates (sell at loss, rebuy within 30 days)
- Overtrading in same ticker (>3 trades in 60-day window)

### 4. Generate the Report

```bash
.venv/bin/python3 scripts/generate_report.py \
  analysis_results.json \
  --output portfolio_analysis_report.html
```

**Report features**:
- **Floating Table of Contents**: Fixed-position sidebar navigation with scroll-spy highlighting.
  Responsive: always visible on wide screens (>1400px), hamburger toggle on narrower screens.
  TOC items are dynamic — only sections with data appear.

Report sections (in order):
1. **The Roast** — Dynamic, data-driven humorous roast based on actual trading data
   (timing score, dollar impact, panic sells, FOMO buys, worst buys/sells, wash sales,
   round-trip losses, DCA compliment, benchmark burn, Sharpe roast, overall return)
2. **Executive Summary** — Overall timing score, total impact (£ GBP), patterns
3. **Portfolio Overview** — Net invested, current value, total return %, cash flows,
   realized/unrealized P&L, dividends, interest, fees
4. **Current Holdings** — Per-ticker: shares, avg cost (£), cost basis, current value,
   unrealized P&L with %, realized P&L
5. **DCA Strategies** — Detected sequences, total invested, beat-period-avg count,
   consistency scores, DCA vs lump sum comparison table
6. **Benchmark vs SPY** — Portfolio TWR, SPY return, alpha, CAGR, monthly comparison
7. **Risk-Adjusted Returns** — Volatility, Sharpe, Sortino, max drawdown detail,
   daily return statistics
8. **Best & Worst Timed Actions** — Top 3 each direction
9. **Best Timed Sells (detailed)** — Green-bordered cards, top 15 by loss_avoided_pct,
   price trajectory, stayed-below-sell-price flag, realized P&L
10. **Best Timed Buys (detailed)** — Green-bordered cards, top 15 by max_gain_after_pct,
    dip-buy detection, never-went-below-entry flag
11. **Worst Timed Sells (detailed)** — Red-bordered cards, top 15 by missed_rally_pct,
    optimal sell date/price, realized P&L, price trajectory
12. **Worst Timed Buys (detailed)** — Red-bordered cards, top 15 by max_drop_after_pct,
    bought-the-top flag, recovery info, price trajectory
13. **Panic Sells (detailed)** — Per-sell cards with: why flagged, avg cost basis,
    realized P&L, price trajectory after, recovery info, optimal sell date
14. **FOMO Buys (detailed)** — Per-buy cards with: why flagged, drawdown after entry,
    price trajectory, optimal buy date, overpaid %
15. **All Scored Actions** — Full table with trade currency and flags
    (DCA, Great Sell, Great Buy, Worst Sell, Worst Buy, Panic, FOMO, Div Miss)
16. **Round-Trip Trades** — FIFO matched buy-sell pairs with returns
17. **Dividend Timing Issues** — Missed dividends with amounts in £
18. **Wash Sales** — Tax-relevant sell-rebuy pairs
19. **Actionable Recommendations** — Concrete rules tied to specific mistakes

All monetary values in the report use £ (GBP) as the account currency.

### 5. Verify Data Quality

Run the ticker mismatch detector to verify CSV trade prices match Yahoo Finance prices:
```bash
.venv/bin/python3 scripts/detect_ticker_mismatches.py
```

This compares each trade's price against Yahoo Finance's close price on the same date.
Flags any ticker with >30% median price divergence. Common causes:
- **Stock splits** (most common): Yahoo retroactively adjusts prices but CSV has pre-split values.
  The analyze script handles this automatically, but mismatches help identify unhandled splits.
- **Wrong Yahoo symbol**: The ticker resolves to a different stock on Yahoo Finance.
- **Delisted/reorganized**: The company changed its ticker or was acquired.

### 6. Present Results

Open the HTML report in the user's browser:
```bash
open portfolio_analysis_report.html
```

Give a concise summary of key findings in the chat.

## Multi-Currency Handling

**Critical**: The portfolio has trades in multiple currencies (USD, GBP, GBX, EUR, CAD, CHF).

- `price` field = share price in **trade currency** (matches Yahoo Finance prices)
- `total` field = transaction total in **account currency** (GBP)
- `exchange_rate` = **divisor** to convert trade → account: `GBP = trade_amount / exchange_rate`
  - GBX: rate=100 (1 GBX = £0.01)
  - USD: rate≈1.20 (1 USD ≈ £0.83)
  - EUR: rate≈1.14 (1 EUR ≈ £0.88)
- Dollar impacts use **percentage method** on GBP total: `pct_change * total_gbp`
- Dividend missed amounts: `(div_per_share * quantity) / exchange_rate` (divide, NOT multiply)
- Timing scores are percentage-based, so currency-agnostic
- Portfolio tracker uses GBP totals for cost basis and P&L

## Stock Split Handling

Yahoo Finance retroactively adjusts all historical prices for stock splits. CSV data has
pre-split prices and quantities. Without adjustment, timing scores and portfolio values
are wildly incorrect for any ticker that has split.

**How it works**:
1. `build_split_adjustments()` extracts all splits from Yahoo's market data
2. `get_cumulative_split_factor()` computes the product of all split ratios AFTER each action date
3. `apply_split_adjustments()` adjusts each action's quantity and price, preserving total_gbp

**Split types from yfinance**:
- Forward splits (NVDA 10:1, NFLX 10:1, AVGO 10:1, WMT 3:1): ratio > 1
- Reverse splits (TTOO 1:100, BETR 1:50, NKLAQ 1:30, NIXX 1:15): ratio < 1

**Key lesson**: Always fetch data up to today (not just around action dates) to capture
splits that happened after the last trade in a ticker.

## Multi-Exchange Tickers

When the same ticker is traded on multiple exchanges in different currencies (e.g., CNQ
on NYSE in USD and on TSX in CAD), both `fetch_market_data.py` and `analyze_portfolio.py`
detect this and rename actions to their resolved Yahoo symbols (CNQ stays CNQ for USD trades,
becomes CNQ.TO for CAD trades). This ensures they are tracked as separate positions.

**Important**: Tickers already renamed by the multi-exchange splitter must NOT be re-resolved
in `compute_date_ranges_and_symbols()` — they are tracked via `already_resolved` set to
prevent double-suffixing (e.g., CNQ.TO → CNQ.TO.TO).

## Important Notes

- **Privacy**: Only ticker symbols and date ranges go to Yahoo Finance — never user quantities or values.
- **Not financial advice**: Always include disclaimer. This is educational analysis only.
- **Adjusted prices**: Always use adjusted close to account for splits and dividends.
- **Timezone**: Normalize to US Eastern for US equities. Handle weekends/holidays.
- **Graceful degradation**: If API fails for some tickers, analyze what's available and note gaps.
  Typically ~3% of tickers fail (delisted, OTC, etc.).

## Known Issues & Fixes

- **macOS SSL errors**: Python on macOS often fails with `CERTIFICATE_VERIFY_FAILED`. The `yfinance`
  library handles this. Never use raw `urllib` for Yahoo Finance calls.
- **Yahoo Finance auth (401/429)**: Raw API calls require cookie/crumb authentication. Use `yfinance`
  which manages this automatically via session cookies.
- **NoneType analysis field**: Non-BUY/SELL actions (DEPOSIT, INTEREST, etc.) have `analysis: None`.
  Always use `(a.get("analysis") or {}).get(...)` — NOT `a.get("analysis", {}).get(...)` — because
  the key exists but its value is `None`. This pattern applies to any dict where a key may have
  a `None` value.
- **NoneType chart field**: Some tickers have `chart: None` in market data. Always use
  `(ticker_data.get("chart") or {}).get("prices", [])` not `ticker_data.get("chart", {}).get(...)`.
- **GBX vs GBP**: GBX (pence) is 1/100 of GBP. Exchange rate from Trading 212 CSV is 100 for GBX.
  Always divide by exchange_rate (it's a divisor, not a multiplier).
- **Fractional shares**: Quantities preserve full float precision (no rounding). Use `:.6g` format
  in reports to avoid unnecessary trailing zeros.
- **Majority voting for currency**: When resolving a ticker's Yahoo symbol, use the most common
  trade_currency across all BUY/SELL actions for that ticker — not just the first action's currency.
  This prevents rare edge cases where the first trade was in a minority currency.
- **Double-suffix prevention**: Tickers renamed by `split_multi_exchange_tickers()` already have
  their Yahoo suffix. The `already_resolved` set in `compute_date_ranges_and_symbols()` prevents
  appending a second suffix.
- **Stock split timing scores**: Before split adjustment was added, tickers like NVDA showed
  score=-100 because the CSV price ($424) didn't match Yahoo's split-adjusted price ($42.40).
  The split adjustment fixed NVDA's score from -100 to -5.6.
