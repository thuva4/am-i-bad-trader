#!/usr/bin/env python3
"""
Detect ticker mismatches between Trading 212 trade prices and Yahoo Finance prices.

For each ticker, compares the user's actual trade price against Yahoo Finance's
close price on the same day. Flags tickers where prices diverge significantly,
indicating the Yahoo Finance symbol maps to a different stock.
"""

import json
from datetime import datetime


def load_json(path):
    with open(path) as f:
        return json.load(f)


def build_price_dict(prices_list):
    """Build date -> close price dict for fast lookup."""
    d = {}
    for p in prices_list:
        d[p["date"]] = p["close"]
    return d


def find_closest_price(price_dict, target_date, max_days=5):
    """Find the closest available price to target_date within max_days."""
    target = datetime.strptime(target_date, "%Y-%m-%d")
    for offset in range(max_days + 1):
        for sign in (0, -1, 1):
            if offset == 0 and sign != 0:
                continue
            from datetime import timedelta
            check = (target + timedelta(days=offset * (sign if sign else 1))).strftime("%Y-%m-%d")
            if offset == 0:
                check = target_date
            if check in price_dict:
                return price_dict[check], check, offset
        # Try both directions
        for delta in (offset, -offset):
            from datetime import timedelta
            check = (target + timedelta(days=delta)).strftime("%Y-%m-%d")
            if check in price_dict:
                return price_dict[check], check, abs(delta)
    return None, None, None


def main():
    actions_data = load_json("parsed_actions.json")
    market_data = load_json("market_data.json")

    actions = actions_data["actions"]
    symbol_map = market_data.get("ticker_symbol_map", {})
    market = market_data.get("data", {})

    # Group BUY/SELL actions by ticker
    ticker_trades = {}
    for a in actions:
        if a["action"] not in ("BUY", "SELL"):
            continue
        ticker = a["ticker"]
        if ticker not in ticker_trades:
            ticker_trades[ticker] = []
        ticker_trades[ticker].append(a)

    mismatches = []
    good_tickers = 0
    no_data_tickers = []

    for ticker in sorted(ticker_trades.keys()):
        trades = ticker_trades[ticker]
        yahoo_sym = symbol_map.get(ticker, "?")

        ticker_data = market.get(ticker)
        if not ticker_data:
            no_data_tickers.append(ticker)
            continue

        chart = ticker_data.get("chart") or {}
        prices_list = chart.get("prices") or []
        if not prices_list:
            no_data_tickers.append(ticker)
            continue

        price_dict = build_price_dict(prices_list)

        # Compare each trade against Yahoo Finance price on same day
        comparisons = []
        for trade in trades:
            trade_price = trade["price"]  # in trade currency
            trade_date = trade["date"]

            yf_close, yf_date, gap = find_closest_price(price_dict, trade_date)
            if yf_close is None:
                continue

            # Compute ratio of trade price to Yahoo Finance price
            if yf_close > 0 and trade_price > 0:
                ratio = trade_price / yf_close
                pct_diff = abs(1 - ratio) * 100

                comparisons.append({
                    "date": trade_date,
                    "action": trade["action"],
                    "trade_price": trade_price,
                    "yf_close": yf_close,
                    "yf_date": yf_date,
                    "gap_days": gap,
                    "ratio": ratio,
                    "pct_diff": pct_diff,
                    "total_gbp": trade["total"],
                    "trade_currency": trade.get("trade_currency", "?"),
                })

        if not comparisons:
            continue

        # Use median percentage difference to flag mismatches
        pct_diffs = sorted([c["pct_diff"] for c in comparisons])
        median_diff = pct_diffs[len(pct_diffs) // 2]

        # Flag if median diff > 30% (allows for normal intraday/spread variance)
        if median_diff > 30:
            examples = sorted(comparisons, key=lambda c: c["pct_diff"], reverse=True)[:5]
            mismatches.append({
                "ticker": ticker,
                "yahoo_symbol": yahoo_sym,
                "isin": trades[0].get("isin", "?"),
                "trade_currency": trades[0].get("trade_currency", "?"),
                "num_trades": len(trades),
                "median_pct_diff": round(median_diff, 1),
                "examples": examples,
            })
        else:
            good_tickers += 1

    # Print results
    print(f"\n{'='*80}")
    print(f"TICKER MISMATCH DETECTION")
    print(f"{'='*80}")
    print(f"Checked {len(ticker_trades)} tickers")
    print(f"  Matched OK (median diff <30%):  {good_tickers}")
    print(f"  MISMATCHED (median diff >30%):   {len(mismatches)}")
    print(f"  No market data:                  {len(no_data_tickers)}")

    if no_data_tickers:
        print(f"\n--- No Market Data (fetch failed) ---")
        for t in no_data_tickers:
            print(f"  {t} -> {symbol_map.get(t, '?')}")

    if mismatches:
        # Sort by worst mismatch first
        mismatches.sort(key=lambda m: m["median_pct_diff"], reverse=True)

        print(f"\n{'='*80}")
        print(f"MISMATCHED TICKERS — Please verify these")
        print(f"{'='*80}")

        for m in mismatches:
            print(f"\n{'─'*80}")
            print(f"TICKER: {m['ticker']}  →  Yahoo: {m['yahoo_symbol']}  |  ISIN: {m['isin']}  |  Currency: {m['trade_currency']}")
            print(f"  Trades: {m['num_trades']}  |  Median price diff: {m['median_pct_diff']}%")
            print(f"  Examples:")
            for ex in m["examples"]:
                print(f"    {ex['date']} {ex['action']:4s}  "
                      f"Trade: {ex['trade_currency']} {ex['trade_price']:<12.4f}  "
                      f"Yahoo: {ex['yf_close']:<12.4f} ({ex['yf_date']})  "
                      f"Diff: {ex['pct_diff']:.1f}%  "
                      f"Total: £{ex['total_gbp']:.2f}")

        print(f"\n{'='*80}")
        print("ACTION NEEDED: The Yahoo Finance symbol likely maps to a different stock")
        print("than what Trading 212 traded. Verify and provide correct tickers.")
        print(f"{'='*80}\n")
    else:
        print("\nNo mismatches detected!")


if __name__ == "__main__":
    main()
