#!/usr/bin/env python3
"""
Fetch historical market data from Yahoo Finance for all tickers in parsed actions.
Uses yfinance library which handles cookies, crumbs, rate-limiting automatically.
"""

import json
import sys
import time
import argparse
from datetime import datetime, timedelta

import yfinance as yf


TRADING_DAYS_BEFORE = 60
TRADING_DAYS_AFTER = 90
CALENDAR_BUFFER_DAYS = 150  # ~90 trading days ≈ 130 calendar days + buffer

# Currency → Yahoo Finance exchange suffix mapping
CURRENCY_SUFFIX = {
    "USD": "",
    "GBP": ".L",
    "GBX": ".L",
    "CAD": ".TO",
    "CHF": ".SW",
}

# ISIN prefix → Yahoo suffix for EUR and other non-USD tickers
ISIN_PREFIX_TO_SUFFIX = {
    "FR": ".PA",
    "DE": ".DE",
    "NL": ".AS",
    "ES": ".MC",
    "BE": ".BR",
    "IT": ".MI",
    "CH": ".SW",
    "IE": ".L",   # Irish-domiciled ETFs often trade on LSE
    "GB": ".L",
}


def resolve_yahoo_symbol(ticker, currency, isin):
    """Map a Trading 212 ticker to a Yahoo Finance symbol using currency and ISIN."""
    if not ticker:
        return ticker

    # USD tickers work as-is on Yahoo Finance
    if currency == "USD":
        return ticker

    # Handle special characters (BT/A → BT-A)
    yahoo_ticker = ticker.replace("/", "-")

    # Try ISIN prefix mapping first (most reliable for EUR tickers)
    if isin and len(isin) >= 2:
        prefix = isin[:2]
        suffix = ISIN_PREFIX_TO_SUFFIX.get(prefix)
        if suffix:
            return f"{yahoo_ticker}{suffix}"

    # Fall back to currency-based suffix
    suffix = CURRENCY_SUFFIX.get(currency, "")
    if suffix:
        return f"{yahoo_ticker}{suffix}"

    return yahoo_ticker


def fetch_ticker_data(yahoo_sym, start_date, end_date):
    """Fetch historical data for a single ticker using yfinance."""
    try:
        ticker = yf.Ticker(yahoo_sym)

        # Fetch historical OHLCV with dividends and splits
        hist = ticker.history(start=start_date, end=end_date, auto_adjust=False)

        if hist.empty:
            return None

        # Build price bars
        prices = []
        for date, row in hist.iterrows():
            date_str = date.strftime("%Y-%m-%d")
            close = row.get("Close")
            if close is not None and not (isinstance(close, float) and close != close):  # skip NaN
                prices.append({
                    "date": date_str,
                    "timestamp": int(date.timestamp()),
                    "open": float(row["Open"]) if row.get("Open") == row.get("Open") else None,
                    "high": float(row["High"]) if row.get("High") == row.get("High") else None,
                    "low": float(row["Low"]) if row.get("Low") == row.get("Low") else None,
                    "close": float(close),
                    "adjclose": float(row["Adj Close"]) if row.get("Adj Close") == row.get("Adj Close") else float(close),
                    "volume": int(row["Volume"]) if row.get("Volume") == row.get("Volume") else None,
                })

        # Fetch dividends
        dividends = []
        try:
            divs = ticker.dividends
            if divs is not None and not divs.empty:
                for date, amount in divs.items():
                    date_str = date.strftime("%Y-%m-%d")
                    if start_date <= date_str <= end_date:
                        dividends.append({
                            "date": date_str,
                            "timestamp": int(date.timestamp()),
                            "amount": float(amount),
                        })
        except Exception:
            pass

        # Fetch splits
        splits = []
        try:
            sp = ticker.splits
            if sp is not None and not sp.empty:
                for date, ratio in sp.items():
                    date_str = date.strftime("%Y-%m-%d")
                    if start_date <= date_str <= end_date:
                        splits.append({
                            "date": date_str,
                            "timestamp": int(date.timestamp()),
                            "numerator": float(ratio),
                            "denominator": 1,
                            "ratio": f"{float(ratio)}:1",
                        })
        except Exception:
            pass

        # Get basic info for meta
        meta_info = {}
        try:
            info = ticker.info
            meta_info = {
                "currency": info.get("currency", "USD"),
                "exchange_timezone": info.get("exchangeTimezoneName", "America/New_York"),
                "instrument_type": info.get("quoteType", "EQUITY"),
            }
        except Exception:
            meta_info = {"currency": "USD", "exchange_timezone": "America/New_York", "instrument_type": "EQUITY"}

        chart = {
            "prices": prices,
            "dividends": dividends,
            "splits": splits,
            "meta": meta_info,
        }

        # Get summary info
        summary = None
        try:
            info = ticker.info
            summary = {
                "dividend_yield": info.get("dividendYield"),
                "trailing_annual_dividend_rate": info.get("trailingAnnualDividendRate"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "beta": info.get("beta"),
                "next_ex_dividend_date": info.get("exDividendDate"),
                "short_percent_of_float": info.get("shortPercentOfFloat"),
                "shares_outstanding": info.get("sharesOutstanding"),
            }
        except Exception:
            pass

        return chart, summary

    except Exception as e:
        print(f"    Error: {e}")
        return None


def split_multi_exchange_tickers(actions):
    """Split tickers traded on multiple exchanges into separate tickers.

    When the same ticker (e.g., CNQ) has trades in different currencies
    (USD on NYSE, CAD on TSX), rename each action's ticker to the resolved
    Yahoo symbol so they are treated as separate positions.

    Returns the number of renamed actions.
    """
    # Find tickers with multiple trade currencies
    ticker_currencies = {}
    for a in actions:
        ticker = a.get("ticker", "")
        if not ticker:
            continue
        tc = a.get("trade_currency", "") or a.get("currency", "")
        if tc and a["action"] in ("BUY", "SELL"):
            if ticker not in ticker_currencies:
                ticker_currencies[ticker] = set()
            ticker_currencies[ticker].add(tc)

    multi = {t for t, cs in ticker_currencies.items() if len(cs) > 1}
    if not multi:
        return 0

    renamed = 0
    for a in actions:
        ticker = a.get("ticker", "")
        if ticker not in multi:
            continue
        tc = a.get("trade_currency", "") or a.get("currency", "")
        isin = a.get("isin", "")
        yahoo_sym = resolve_yahoo_symbol(ticker, tc, isin)
        if yahoo_sym != ticker:
            a["ticker_original"] = ticker
            a["ticker"] = yahoo_sym
            renamed += 1

    return renamed


def compute_date_ranges_and_symbols(actions):
    """For each ticker, compute the date range and resolve Yahoo Finance symbol."""
    ticker_ranges = {}
    ticker_currencies = {}  # {ticker: {currency: count}}
    ticker_isin = {}
    already_resolved = set()  # tickers already renamed by split_multi_exchange_tickers

    for action in actions:
        ticker = action.get("ticker", "")
        if not ticker:
            continue
        action_date = action["date"]
        dt = datetime.strptime(action_date, "%Y-%m-%d")
        start = (dt - timedelta(days=CALENDAR_BUFFER_DAYS)).strftime("%Y-%m-%d")
        # Always extend to today so we capture all stock splits and current prices
        end = datetime.now().strftime("%Y-%m-%d")

        if ticker not in ticker_ranges:
            ticker_ranges[ticker] = {"start": start, "end": end}
        else:
            if start < ticker_ranges[ticker]["start"]:
                ticker_ranges[ticker]["start"] = start
            if end > ticker_ranges[ticker]["end"]:
                ticker_ranges[ticker]["end"] = end

        # Count trade currencies per ticker (BUY/SELL only) for majority voting
        if action["action"] in ("BUY", "SELL"):
            trade_currency = action.get("trade_currency", "") or action.get("currency", "")
            if trade_currency:
                if ticker not in ticker_currencies:
                    ticker_currencies[ticker] = {}
                ticker_currencies[ticker][trade_currency] = ticker_currencies[ticker].get(trade_currency, 0) + 1

        # Store ISIN (first seen)
        if ticker not in ticker_isin:
            isin = action.get("isin", "")
            if isin:
                ticker_isin[ticker] = isin

        # Track tickers already renamed by split_multi_exchange_tickers
        if action.get("ticker_original"):
            already_resolved.add(ticker)

    # Resolve Yahoo symbols using majority trade currency
    ticker_to_yahoo = {}
    for ticker in ticker_ranges:
        # Skip resolution for tickers already renamed to Yahoo symbols
        if ticker in already_resolved:
            ticker_to_yahoo[ticker] = ticker
            continue
        currencies = ticker_currencies.get(ticker, {})
        if currencies:
            currency = max(currencies, key=currencies.get)
        else:
            currency = ""
        isin = ticker_isin.get(ticker, "")
        yahoo_sym = resolve_yahoo_symbol(ticker, currency, isin)
        ticker_to_yahoo[ticker] = yahoo_sym

    return ticker_ranges, ticker_to_yahoo


def fetch_market_data(parsed_path, output_path):
    """Main function: fetch market data for all tickers in parsed actions."""
    with open(parsed_path, 'r') as f:
        parsed = json.load(f)

    actions = parsed["actions"]

    # Split tickers traded on multiple exchanges into separate tickers
    n_renamed = split_multi_exchange_tickers(actions)
    if n_renamed:
        print(f"Split {n_renamed} actions across multiple exchanges")

    print(f"Fetching market data for {len(parsed['summary']['unique_tickers'])} tickers...")

    # Compute date ranges and resolve Yahoo symbols
    ticker_ranges, ticker_to_yahoo = compute_date_ranges_and_symbols(actions)

    market_data = {}
    success_count = 0
    fail_count = 0

    # Also fetch SPY for market context
    all_tickers = list(ticker_ranges.keys())
    if "SPY" not in all_tickers:
        if ticker_ranges:
            all_starts = [v["start"] for v in ticker_ranges.values()]
            all_ends = [v["end"] for v in ticker_ranges.values()]
            ticker_ranges["SPY"] = {"start": min(all_starts), "end": max(all_ends)}
            ticker_to_yahoo["SPY"] = "SPY"
            all_tickers.append("SPY")

    for i, ticker in enumerate(all_tickers):
        yahoo_sym = ticker_to_yahoo.get(ticker, ticker)
        suffix_info = f" -> {yahoo_sym}" if yahoo_sym != ticker else ""
        print(f"\n[{i+1}/{len(all_tickers)}] {ticker}{suffix_info}")

        date_range = ticker_ranges.get(ticker, {})
        if not date_range:
            continue

        ticker_data = {
            "ticker": ticker,
            "yahoo_symbol": yahoo_sym,
            "chart": None,
            "summary": None,
            "error": None,
        }

        result = fetch_ticker_data(yahoo_sym, date_range["start"], date_range["end"])
        if result:
            chart, summary = result
            ticker_data["chart"] = chart
            ticker_data["summary"] = summary
            print(f"  Got {len(chart['prices'])} price bars, "
                  f"{len(chart['dividends'])} dividends, "
                  f"{len(chart['splits'])} splits")
            success_count += 1
        else:
            ticker_data["error"] = "Failed to fetch data"
            print(f"  FAILED to fetch data")
            fail_count += 1

        market_data[ticker] = ticker_data
        time.sleep(0.3)  # Gentle rate limiting

    output = {
        "fetch_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tickers_requested": len(all_tickers),
        "tickers_success": success_count,
        "tickers_failed": fail_count,
        "ticker_symbol_map": ticker_to_yahoo,
        "data": market_data,
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nFetch complete: {success_count} succeeded, {fail_count} failed")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch market data from Yahoo Finance")
    parser.add_argument("input", help="Path to parsed_actions.json")
    parser.add_argument("--output", "-o", default="./market_data.json",
                        help="Output JSON path")
    args = parser.parse_args()
    fetch_market_data(args.input, args.output)
