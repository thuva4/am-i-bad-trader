# am-i-bad-trader

Analyze your brokerage transaction history against real market data to find out exactly how bad your trading decisions were — with timing scores, behavioral pattern detection, and a personalized roast.

## What It Does

Drop in your CSV exports from Trading 212 (or other brokerages), and the tool will:

- **Score every trade** from -100 (catastrophic) to +100 (perfect) based on what the price did next
- **Detect behavioral patterns**: panic sells, FOMO buys, wash sales, missed dividends
- **Track your portfolio**: cost basis, realized/unrealized P&L, dividends, current holdings
- **Detect DCA sequences**: identifies automated recurring buys and evaluates them separately
- **Benchmark against SPY**: how you would have done just buying an index fund
- **Calculate risk metrics**: Sharpe ratio, Sortino ratio, max drawdown, volatility
- **Generate an HTML report** with a floating table of contents, color-coded scores, and a roast section

## Usage

Install as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill and let Claude run the entire pipeline for you conversationally.

```bash
# Clone into your Claude Code project's skills directory
mkdir -p .claude/skills
git clone https://github.com/thuva4/am-i-bad-trader.git .claude/skills/am-i-bad-trader
```

Then drop your CSV exports into the project directory and tell Claude:

> /am-i-bad-trader "Analyze my portfolio actions"

Claude will read the skill instructions, run all four pipeline stages, and present the HTML report — handling ticker resolution, stock splits, multi-currency math, and edge cases automatically.

The skill file (`SKILL.md`) contains the full methodology, known issues, and fix patterns so Claude can debug problems autonomously across sessions.


## Pipeline

```
CSV Exports (Trading 212, Schwab, Fidelity, etc.)
  -> parse_csv.py       -> parsed_actions.json    (normalized actions)
  -> fetch_market_data.py -> market_data.json      (historical prices & dividends)
  -> analyze_portfolio.py -> analysis_results.json (timing scores, patterns, metrics)
  -> generate_report.py  -> report.html           (self-contained HTML report)
```

### Stage 1: Parse

Reads CSV files from any supported brokerage and normalizes them into a standard format with fields for date, action type, ticker, quantity, price, total, currency, exchange rate, and ISIN.

**Supported brokerages**: Trading 212, Schwab, Fidelity, Vanguard, E\*TRADE, Robinhood, Interactive Brokers, and any CSV with recognizable column headers.

### Stage 2: Fetch Market Data

For every unique ticker, fetches historical prices, dividends, and stock splits from Yahoo Finance using the `yfinance` library.

Handles multi-currency ticker resolution automatically:
- USD tickers work as-is (AAPL, AMZN)
- GBP/GBX tickers get `.L` suffix (LLOY.L, VUSA.L)
- CAD tickers get `.TO` suffix (CNQ.TO)
- EUR tickers use ISIN prefix mapping (FR->.PA, DE->.DE, NL->.AS)
- Same ticker traded on multiple exchanges is split into separate positions

### Stage 3: Analyze

Two-pass analysis:

**Pass 1 — Portfolio Tracking**: Processes every action chronologically to build portfolio state. Tracks average cost basis per ticker, realized P&L on each sell, deposits, withdrawals, dividends, interest, and current holdings valued at latest prices.

**Pass 2 — Per-Action Scoring**: Each BUY and SELL gets:
- A timing score (-100 to +100) based on the 90-day post-action price trajectory
- A dollar impact estimate in your account currency
- Behavioral pattern flags (panic sell, FOMO buy, well-timed, worst-timed)
- Dividend proximity checks for sells

Also runs:
- **DCA detection** — finds recurring automated buy sequences, excludes them from emotional trading flags
- **Benchmark comparison** — portfolio time-weighted return vs SPY buy-and-hold
- **Risk metrics** — Sharpe ratio, Sortino ratio, max drawdown, annualized volatility
- **Stock split adjustment** — adjusts CSV quantities/prices to match Yahoo Finance's split-adjusted basis
- **Round-trip matching** — FIFO buy-sell pairs with per-trade returns
- **Wash sale detection** — sell at loss + rebuy within 30 days

### Stage 4: Report

Generates a self-contained HTML file with 19 sections:

1. **The Roast** — data-driven humorous summary of your trading decisions
2. **Executive Summary** — overall score, total dollar impact, pattern counts
3. **Portfolio Overview** — net invested, current value, total return, cash flows
4. **Current Holdings** — per-ticker detail with unrealized P&L
5. **DCA Strategies** — detected sequences with consistency scores and DCA vs lump sum comparison
6. **Benchmark vs SPY** — portfolio TWR, alpha, CAGR, monthly comparison
7. **Risk-Adjusted Returns** — volatility, Sharpe, Sortino, max drawdown
8. **Best & Worst Timed Actions** — top 3 each direction
9. **Best Timed Sells** — detailed cards with price trajectory
10. **Best Timed Buys** — detailed cards with dip-buy detection
11. **Worst Timed Sells** — detailed cards with missed rally analysis
12. **Worst Timed Buys** — detailed cards with drawdown analysis
13. **Panic Sells** — sells during sharp declines with recovery info
14. **FOMO Buys** — buys after run-ups with drawdown after entry
15. **All Scored Actions** — full table with flags
16. **Round-Trip Trades** — FIFO matched pairs with returns
17. **Dividend Timing Issues** — missed dividends with amounts
18. **Wash Sales** — tax-relevant sell-rebuy pairs
19. **Actionable Recommendations** — concrete rules tied to your specific mistakes

## Multi-Currency Support

The tool handles portfolios with trades in multiple currencies (USD, GBP, GBX, EUR, CAD, CHF).

- Trade prices stay in their original currency for comparison with Yahoo Finance
- All portfolio-level values are converted to your account currency (GBP by default)
- Exchange rates from Trading 212 CSVs are used as divisors: `account_amount = trade_amount / exchange_rate`
- Dollar impacts use a percentage method that's currency-agnostic

## Stock Split Handling

Yahoo Finance retroactively adjusts historical prices for stock splits. The tool detects all splits from Yahoo's data and adjusts CSV quantities and prices to match, so a pre-split buy of 0.1 shares at $424 becomes 1 share at $42.40 (same total cost, different units).

A mismatch detector (`detect_ticker_mismatches.py`) is included to verify that trade prices in your CSV match Yahoo Finance prices on the same date.

## Privacy

Only ticker symbols and date ranges are sent to Yahoo Finance. Your quantities, prices, and portfolio values never leave your machine.

## Disclaimer

This tool is for educational purposes only. It is not financial advice. Past performance does not indicate future results.

## License

MIT
