# CSV Formats Reference

## Supported Brokerage Formats

The parser auto-detects the brokerage format by inspecting column headers. Below are the
known column mappings for major brokerages.

## Column Normalization Map

The parser maps all of these to a standard schema:

| Standard Field | Possible Column Names |
|---|---|
| `date` | Date, Time, Trade Date, Transaction Date, Settlement Date, Run Date, Process Date, Activity Date |
| `action` | Action, Type, Transaction Type, Activity Type, Trans Type, Description, Transaction Description |
| `ticker` | Symbol, Ticker, Stock, Instrument, Security, CUSIP, Name |
| `quantity` | Quantity, Shares, Qty, Units, Amount, Number of Shares, No. of shares |
| `price` | Price, Trade Price, Execution Price, Price ($), Unit Price, Cost Basis Per Share, Price / share |
| `total` | Amount, Total, Net Amount, Principal, Cost, Proceeds, Value, Net Proceeds |
| `fees` | Commission, Fee, Fees, Transaction Fee, Commission ($), SEC Fee |
| `notes` | Description, Notes, Memo, Comment, Details |
| `account` | Account, Account Number, Account Name, Account # |
| `currency` | Currency (Total), Currency, Currency Code |
| `trade_currency` | Currency (Price / share) |
| `isin` | ISIN |
| `exchange_rate` | Exchange rate |

## Action Normalization Map

| Standard Action | Recognized Inputs |
|---|---|
| `BUY` | Buy, BUY, PURCHASE, Bought, Buy to Open, BTO, Reinvestment, REINVEST, Automatic Investment, Market buy |
| `SELL` | Sell, SELL, SOLD, Sell to Close, STC, Redemption, Market sell, Limit sell |
| `DIVIDEND` | Dividend, DIV, DIVIDEND, Div, Cash Dividend, Qualified Dividend, Non-Qualified Dividend, Ordinary Dividend, LTCG Distribution, STCG Distribution, Capital Gain, Return of Capital, Dividend (Ordinary), Dividend (Bonus), Dividend (Property income), Dividend adjustment |
| `INTEREST` | Interest, INT, INTEREST, Interest Earned, Interest Income, Bond Interest, Interest on cash |
| `DEPOSIT` | Deposit, DEPOSIT, Transfer In, Wire In, ACH In, Electronic Transfer, Contribution |
| `WITHDRAWAL` | Withdrawal, WITHDRAW, Transfer Out, Wire Out, ACH Out, Distribution |
| `FEE` | Fee, FEE, Advisory Fee, Management Fee, Service Fee, Account Fee |
| `SPLIT` | Split, STOCK SPLIT, Forward Split, Reverse Split |
| `TRANSFER` | Transfer, TRANSFER, Journal, Internal Transfer, ACAT |
| `OTHER` | Any unrecognized action type |

## Known Brokerage Formats

### Schwab
Columns: `Date, Action, Symbol, Description, Quantity, Price, Fees & Comm, Amount`
- Date format: `MM/DD/YYYY`
- Actions: "Buy", "Sell", "Qualified Dividend", "Cash Dividend", "Bank Interest"

### Fidelity
Columns: `Run Date, Account, Action, Symbol, Description, Type, Quantity, Price ($), Commission ($), Fees ($), Amount ($)`
- Date format: `MM/DD/YYYY`
- Actions: "YOU BOUGHT", "YOU SOLD", "DIVIDEND RECEIVED", "INTEREST EARNED"

### Vanguard
Columns: `Account Number, Trade Date, Settlement Date, Transaction Type, Transaction Description, Investment Name, Symbol, Shares, Share Price, Principal Amount, Commission Fees, Net Amount`
- Date format: `MM/DD/YYYY`
- Actions: "Buy", "Sell", "Dividend", "Capital gain"

### E*TRADE
Columns: `TransactionDate, TransactionType, SecurityType, Symbol, Quantity, Amount, Price, Commission, Description`
- Date format: `MM/DD/YYYY`
- Actions: "Bought", "Sold", "Dividend", "Interest"

### Robinhood
Columns: `Activity Date, Process Date, Settle Date, Instrument, Description, Trans Code, Quantity, Price, Amount`
- Date format: `MM/DD/YYYY`
- Trans Codes: "Buy", "Sell", "CDIV" (cash dividend), "INT"

### Interactive Brokers
Columns: `Date/Time, Symbol, Action, Quantity, Price, Commission, Net Cash, Description`
- Date format: `YYYY-MM-DD, HH:MM:SS` or `YYYYMMDD`
- Actions: "BOT" (bought), "SLD" (sold), "DIV" (dividend)

### Trading 212
Columns: `Action, Time, ISIN, Ticker, Name, Notes, ID, No. of shares, Price / share, Currency (Price / share), Exchange rate, Result, Currency (Result), Total, Currency (Total), Withholding tax, Currency (Withholding tax), Stamp duty reserve tax, Currency (Stamp duty reserve tax), Currency conversion fee, Currency (Currency conversion fee), French transaction tax, Currency (French transaction tax)`
- Date column: `Time` (format: `YYYY-MM-DD HH:MM:SS`)
- Actions: "Market buy", "Market sell", "Limit sell", "Deposit", "Withdrawal", "Interest on cash", "Dividend (Ordinary)", "Dividend (Bonus)", "Dividend (Property income)", "Dividend (Interest)", "Dividend adjustment", "Equity rights", "Result adjustment"
- Multi-currency: USD, GBP, GBX, EUR, CAD, CHF tracked per trade
- **Key fields**:
  - `ISIN` — for Yahoo Finance ticker resolution (ISIN prefix → exchange suffix)
  - `Currency (Price / share)` — trade currency for exchange suffix mapping (USD, GBX, GBP, EUR, CAD, CHF)
  - `Currency (Total)` — account currency (always GBP for this portfolio)
  - `Exchange rate` — **divisor** to convert trade currency → account currency: `GBP = trade_amount / exchange_rate`
    - GBX: rate=100 (1 GBX = £0.01)
    - USD: rate≈1.20 (1 USD ≈ £0.83)
    - EUR: rate≈1.14 (1 EUR ≈ £0.88)
    - GBP: rate=1.0
- `Price / share` is in trade currency (e.g., GBX pence, USD dollars)
- `Total` is in account currency (GBP)
- Filename pattern: `from_YYYY-MM-DD_to_YYYY-MM-DD_<hash>.csv`

### Generic / Custom
Any CSV with at least a date column, an action/type column, and either a ticker/symbol or description
column can be parsed. The parser will attempt best-effort mapping.

## Parsing Rules

1. **Skip header rows** that contain metadata (account summaries, disclaimers)
2. **Skip empty rows** and rows where all key fields are empty
3. **Handle multi-line descriptions** by joining with the prior row if no date is present
4. **Currency symbols** ($, £, €) are stripped from numeric fields
5. **Negative amounts**: Some brokerages use negative values for sells/withdrawals — normalize
6. **Commas in numbers**: Strip commas from amounts (e.g., "1,250.00" → 1250.00)
7. **Dates**: Try multiple formats; prefer the first valid parse
