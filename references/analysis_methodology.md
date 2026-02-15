# Analysis Methodology

## Timing Score (-100 to +100)

Each BUY and SELL receives a timing score based on what the price did AFTER the action
within a 90-day forward window.

### For SELL actions:
```
score = ((sell_price - min_price_after) / sell_price) * 100
```
- Sold near a local high before a decline → positive score (good timing)
- Sold near a local low before a rally → negative score (bad timing)
- Capped at +100 / -100

### For BUY actions:
```
score = ((max_price_after - buy_price) / buy_price) * 100
```
- Bought near a local low before a rally → positive score (good timing)
- Bought near a local high before a decline → negative score (bad timing)

### Score Interpretation:
| Range | Label | Meaning |
|---|---|---|
| +80 to +100 | Excellent | Nearly optimal timing |
| +40 to +79 | Good | Solid timing, captured most of the move |
| +10 to +39 | Neutral | Modest move in favorable direction |
| -9 to +9 | Flat | No significant price movement either way |
| -39 to -10 | Poor | Meaningful move against the user |
| -79 to -40 | Bad | Significant adverse move |
| -100 to -80 | Terrible | Near worst-case timing |

## Dollar Impact Calculation (Multi-Currency)

For each action, estimate the GBP impact of the timing decision using the **percentage method**
to handle multi-currency portfolios correctly.

### SELL:
```
optimal_sell_price = max price within 30 days before and 30 days after (in trade currency)
pct_diff = (actual_price - optimal_sell_price) / actual_price
dollar_impact = pct_diff * total_account_currency_gbp
```
If negative, the user left money on the table (in £).

### BUY:
```
optimal_buy_price = min price within 30 days before and 30 days after (in trade currency)
pct_diff = (optimal_buy_price - actual_price) / actual_price
dollar_impact = pct_diff * total_account_currency_gbp
```
If negative, the user overpaid vs what was available nearby (in £).

### Why Percentage Method?
The portfolio has trades in USD, GBX, GBP, EUR, CAD, CHF. Using `(price_diff * quantity)`
would mix currencies (e.g., GBX pence vs GBP pounds). The percentage method computes the
price change as a percentage in trade currency, then applies it to the GBP total, producing
correct GBP-denominated impacts regardless of trade currency.

**Important**: This is hindsight analysis. Nobody can time perfectly. The purpose is
educational, not to make the user feel bad. Frame positively where possible.

## Portfolio Tracking (Chronological Pass)

Before per-action timing analysis, the analyzer runs a chronological pass through all actions
to build portfolio state.

### Average Cost Basis
- On BUY: `cost_basis_gbp += total_gbp`, `shares += quantity`
- Weighted avg cost per share (£): `cost_basis_gbp / shares`
- On SELL: realized P&L = `total_gbp - (shares_sold * avg_cost_per_share_gbp)`
- After SELL: `cost_basis_gbp -= (shares_sold * avg_cost_per_share_gbp)`, `shares -= shares_sold`

### Cash Flow Tracking
- Deposits, withdrawals, dividends, interest, fees are accumulated
- `net_invested = total_deposits - total_withdrawals`

### Current Holdings Valuation
For each held position:
```
latest_price = last available close from market data (in trade currency)
current_value_gbp = (latest_price * shares) / exchange_rate
```
Where `exchange_rate` is the **divisor** from the Trading 212 CSV (GBX=100, USD≈1.20, etc.)

### Overall Portfolio Return
```
unrealized_pnl = total_current_value - total_cost_basis
total_return = realized_pnl + unrealized_pnl + dividends + interest - fees
return_pct = total_return / net_invested * 100
```

## Pattern Detection Algorithms

### Panic Selling (Enhanced)
**Trigger**: SELL action where the stock dropped >5% in the 5 trading days BEFORE the sell.
**Additional signals**:
- High volume on the sell day (>2x average volume)
- Broader market (SPY) also declined >2%
- User sold at a loss relative to their avg cost basis (from portfolio tracker)

**Severity**: Higher if the stock recovered within 30 days of the sell.

**Detailed reasoning output** (per flagged sell):
- `stock_decline_5d`: the 5-day decline that triggered the flag (%)
- `sell_price`: price at which the user sold (trade currency)
- `avg_cost_basis_gbp`: user's weighted avg cost per share (£)
- `realized_pnl_gbp`: realized P&L on this sell vs avg cost (£)
- `max_price_after`: highest price in 90 days after the sell
- `max_price_date`: date of that high
- `recovery_pct`: how much the stock recovered from sell price (%)
- `recovered_sell_price_date`: when the stock recovered back to the sell price (if it did)
- `price_trajectory`: price at 1 week, 1 month, 3 months after sell
- `optimal_sell_date`: the date within 90 days when selling would have been best
- `optimal_sell_price`: price on that optimal date
- `missed_gain_pct`: how much more the user could have gained (%)

### FOMO Buying (Enhanced)
**Trigger**: BUY action where the stock rose >10% in the 10 trading days BEFORE the buy.
**Additional signals**:
- Stock was near or at all-time high
- Volume spike indicating retail pile-in
- Stock subsequently declined within 30 days

**Severity**: Higher if the stock declined significantly post-purchase.

**Detailed reasoning output** (per flagged buy):
- `stock_gain_10d`: the 10-day run-up that triggered the flag (%)
- `buy_price`: price at which the user bought (trade currency)
- `min_price_after`: lowest price in 90 days after the buy
- `min_price_date`: date of that low
- `max_drawdown_pct`: maximum drawdown from buy price (%)
- `price_trajectory`: price at 1 week, 1 month, 3 months after buy
- `optimal_buy_date`: the date within 90 days when buying would have been cheapest
- `optimal_buy_price`: price on that optimal date
- `overpaid_pct`: how much more the user paid vs optimal (%)

### Selling Before Ex-Dividend
**Trigger**: SELL action that occurs within 14 calendar days BEFORE an ex-dividend date.
**Impact** (multi-currency):
```
missed_in_trade_currency = dividend_per_share * shares_sold
missed_gbp = missed_in_trade_currency / exchange_rate
```
Where `exchange_rate` is the divisor from the CSV (GBX=100, USD≈1.20, etc.)
**Context**: More impactful for high-yield stocks (>3% yield).

### Round-Trip Losses
**Detection**: Match BUY → SELL pairs for the same ticker.
```
round_trip_return = (sell_total - buy_total - fees) / buy_total
```
Flag any round trip with negative return.

### Wash Sales
**Detection**: SELL at a loss followed by BUY of the same ticker within 30 calendar days
(before or after the sell).
**Note**: This is a tax concern, not necessarily a timing issue. Flag for awareness.

### Overtrading
**Detection**: More than 3 BUY+SELL actions in the same ticker within 60 days.
**Impact**: Sum up all transaction fees plus bid/ask spread costs (estimate 0.05% per trade).

### Concentration Risk
**Detection**: Any single position exceeding 25% of total invested capital (sum of all buys).
**Note**: Estimate, since we may not know the full portfolio.

## Positive Pattern Recognition (Well-Timed Actions)

### Well-Timed Sells
**Trigger**: SELL action where the price dropped >5% within 90 days after selling.

**Detailed reasoning output** (per flagged sell):
- `sell_price`: price at which the user sold (trade currency)
- `min_price_after`: lowest price in 90 days after the sell
- `min_price_date`: date of that low
- `max_decline_after_pct`: how much the price dropped after selling (%)
- `loss_avoided_pct`: absolute value of the decline — how much loss the user avoided
- `price_trajectory`: price at 1 week, 1 month, 3 months after sell
- `stayed_below_sell_price`: whether price never recovered to sell price in 90 days
- `recovered_date`: when the price recovered to sell price (if it did)

### Well-Timed Buys
**Trigger**: BUY action where the price rose >10% within 90 days after buying.

**Detailed reasoning output** (per flagged buy):
- `buy_price`: price at which the user bought (trade currency)
- `max_price_after`: highest price in 90 days after the buy
- `max_price_date`: date of that high
- `max_gain_after_pct`: how much the price rose after buying (%)
- `price_trajectory`: price at 1 week, 1 month, 3 months after buy
- `bought_the_dip`: whether the stock had fallen >5% before the buy (boolean)
- `dip_detail.decline_before_buy_pct`: the pre-buy decline (%)
- `never_went_below_entry`: whether price stayed within 2% of buy price (clean entry)
- `min_price_after`: lowest price in 90 days after buy

## Negative Pattern Recognition (Worst-Timed Actions)

### Worst-Timed Sells
**Trigger**: SELL action where the price rallied >10% within 90 days after selling (sold at the bottom).

**Detailed reasoning output** (per flagged sell):
- `sell_price`: price at which the user sold (trade currency)
- `max_price_after`: highest price in 90 days after the sell
- `max_price_date`: date of that high
- `missed_rally_pct`: how much the price rallied after selling (%)
- `price_trajectory`: price at 1 week, 1 month, 3 months after sell
- `optimal_sell_price`: the max price in the 90-day window
- `optimal_sell_date`: when that optimal price occurred

### Worst-Timed Buys
**Trigger**: BUY action where the price dropped >10% within 90 days after buying (bought at the top).

**Detailed reasoning output** (per flagged buy):
- `buy_price`: price at which the user bought (trade currency)
- `min_price_after`: lowest price in 90 days after the buy
- `min_price_date`: date of that low
- `max_drop_after_pct`: how much the price dropped after buying (%)
- `price_trajectory`: price at 1 week, 1 month, 3 months after buy
- `bought_the_top`: whether the stock had risen >5% before the buy (boolean)
- `recovered_date`: when price recovered to within 2% of buy price (if it did)

## Report Framing Guidelines

The analysis should be:
1. **Balanced**: Lead with a mix of good and bad — don't pile on
2. **Specific**: Every point references a real action with real numbers
3. **Educational**: Explain WHY the pattern is harmful and HOW to avoid it
4. **Empathetic**: "Hindsight is 20/20" — timing the market is genuinely hard
5. **Actionable**: Every mistake should come with a concrete prevention strategy
6. **Quantified**: Dollar impacts make abstract patterns tangible

### The Roast Section
The report includes a dynamic, data-driven roast section that generates humorous commentary
based on actual trading data. Roast lines are generated for each category with multiple
severity levels:

| Category | Metric | Thresholds |
|---|---|---|
| Overall score | `avg_score` | <-30 (harsh), <-10 (medium), <10 (mild), >=10 (backhanded compliment) |
| Dollar impact | `total_impact` | <-£1000 (with scaled comparisons: holiday/car/house deposit) |
| Panic sells | `n_panic` | >=5 (harsh), >=2 (medium) |
| FOMO buys | `n_fomo` | >=5 (harsh), >=2 (medium) |
| Worst buys | `n_worst_buys` | >=20 (harsh), >=5 (medium) |
| Worst sells | `n_worst_sells` | >=20 (harsh), >=5 (medium) |
| Wash sales | `n_wash` | >=10 |
| Losing round trips | `n_losing_trips` | >=10 |
| Overall return | `total_return_pct` | >15% (backhanded), >0% (mild burn), <=0% (harsh) |

All roast lines reference real numbers from the user's data. The section includes a disclaimer
that the roast is based entirely on actual trading data.

### Floating Table of Contents
The report includes a floating TOC sidebar with:
- Fixed position on the left side of the viewport
- Scroll-spy JavaScript that highlights the active section
- Responsive design: always visible on screens >1400px, hamburger toggle on narrower screens
- Dynamic items: only sections with data are included in the TOC
- Section IDs on all `<h2>` headings for anchor navigation

## DCA (Dollar-Cost Averaging) Detection

### Algorithm
1. Group all BUY actions by ticker, sort chronologically
2. Sliding window scans for clusters of recurring buys:
   - **Amount similarity**: each buy within 50% of the sequence's median GBP amount
   - **Regular intervals**: gap between consecutive buys must match a detected pattern
   - **Minimum 4 buys** to qualify as a DCA sequence
   - Sequence ends if gap > 2.5x the detected interval or amount shifts >50%

### Interval Classification
| Label | Gap Range (days) |
|---|---|
| Daily | 1-2 |
| Weekly | 5-9 |
| Biweekly | 12-16 |
| Monthly | 25-35 |
| Irregular | Outside above ranges |

### Consistency Score (0-100)
Average of:
- **Amount consistency**: `100 - mean(|amount - median| / median) * 100`
- **Gap consistency**: `100 - mean(|gap - median_gap| / median_gap) * 100`

### DCA vs Lump Sum Comparison
- **DCA return**: `(last_price - weighted_avg_cost) / weighted_avg_cost * 100`
- **Lump sum return**: `(last_price - first_buy_price) / first_buy_price * 100`
  (Simulates investing the full amount at the first buy date)
- **Winner**: whichever had higher return

### Impact on Pattern Detection
Actions identified as DCA are excluded from:
- FOMO buy detection (automated buys shouldn't be flagged as emotional)
- Worst-timed buy detection (unfair for scheduled recurring investments)

DCA actions **still receive**:
- Timing scores (useful for evaluating DCA effectiveness)
- Well-timed buy detection (positive reinforcement)
- `is_dca: true` flag in analysis output

## Benchmark Comparison (SPY)

### Portfolio Return: Modified Dietz Approximation
```
portfolio_twr_pct = total_return_gbp / net_invested * 100
```
Where `total_return = realized + unrealized + dividends + interest - fees`.

### SPY Buy-and-Hold Return
```
spy_return = (spy_end_price - spy_start_price) / spy_start_price * 100
```
Over the portfolio's active period (first action to last action).

### Alpha
```
alpha = portfolio_twr - spy_return
```

### CAGR (Compound Annual Growth Rate)
```
portfolio_cagr = (total_value / total_deposits)^(1/years) - 1
spy_cagr = (spy_end / spy_start)^(1/years) - 1
```

### Monthly Comparison Series
SPY cumulative return computed month-by-month for the last 12 months of the active period.

## Risk-Adjusted Return Metrics

### Daily Portfolio Value Reconstruction
1. For each trading day, value all held positions at that day's closing price
2. Use carry-forward for missing prices (standard practice)
3. Track cash flows (deposits/withdrawals) per day
4. Compute daily returns adjusted for cash flows:
   ```
   return_i = (V_i - V_{i-1} - CF_i) / (V_{i-1} + CF_i)
   ```

### Annualized Volatility
```
volatility = std(daily_returns) * sqrt(252)
```

### Sharpe Ratio
```
sharpe = (annualized_return - risk_free_rate) / annualized_volatility
```
Risk-free rate = 4.5% (approximate current UK gilt rate).

| Range | Interpretation |
|---|---|
| > 1.0 | Excellent risk-adjusted returns |
| 0.5-1.0 | Good |
| 0-0.5 | Suboptimal — taking on risk without adequate compensation |
| < 0 | Losing money on a risk-adjusted basis |

### Sortino Ratio
```
downside_deviation = sqrt(mean(min(return, 0)^2)) * sqrt(252)
sortino = (annualized_return - risk_free_rate) / downside_deviation
```
Higher than Sharpe when the portfolio has positive skew (fewer large losses).

### Maximum Drawdown
Largest peak-to-trough decline in portfolio value.
```
drawdown_i = (value_i - peak_i) / peak_i
max_drawdown = min(drawdown_i)
```
Includes: start date (peak), end date (trough), recovery date, duration in days.

### Daily Return Statistics
- Best/worst single-day return with dates
- Positive vs negative day counts
- Win rate (% of positive days)

## Recommendation Categories

Each detected pattern should generate recommendations from these categories:

### Calendar-Based Rules
"Check the ex-dividend calendar before any sell order"
"Don't trade within 48 hours of earnings announcements"

### Behavioral Rules
"Implement a 48-hour cooling-off period before selling during >3% drops"
"Set limit orders instead of market orders to avoid FOMO entries"

### Portfolio Rules
"Cap any single position at 20% of portfolio"
"Rebalance quarterly instead of reactively"

### Information Sources
Point to specific free tools:
- Dividend calendars: dividend.com, nasdaq.com/market-activity/dividends
- Earnings dates: earnings.com, earningswhispers.com
- SEC filings: sec.gov/cgi-bin/browse-edgar
