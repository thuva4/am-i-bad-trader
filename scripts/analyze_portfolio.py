#!/usr/bin/env python3
"""
Analyze portfolio actions against market data.
Evaluates timing, detects patterns, scores decisions, and generates actionable insights.
"""

import json
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict


def load_data(parsed_path, market_path):
    """Load parsed actions and market data."""
    with open(parsed_path, 'r') as f:
        parsed = json.load(f)
    with open(market_path, 'r') as f:
        market = json.load(f)
    return parsed, market


# Currency/ISIN → Yahoo suffix mappings (must match fetch_market_data.py)
_CURRENCY_SUFFIX = {"USD": "", "GBP": ".L", "GBX": ".L", "CAD": ".TO", "CHF": ".SW"}
_ISIN_SUFFIX = {"FR": ".PA", "DE": ".DE", "NL": ".AS", "ES": ".MC", "BE": ".BR",
                "IT": ".MI", "CH": ".SW", "IE": ".L", "GB": ".L"}


def _resolve_yahoo_symbol(ticker, currency, isin):
    """Resolve Yahoo Finance symbol (lightweight copy for analysis script)."""
    if not ticker:
        return ticker
    if currency == "USD":
        return ticker
    yahoo_ticker = ticker.replace("/", "-")
    if isin and len(isin) >= 2:
        suffix = _ISIN_SUFFIX.get(isin[:2])
        if suffix:
            return f"{yahoo_ticker}{suffix}"
    suffix = _CURRENCY_SUFFIX.get(currency, "")
    if suffix:
        return f"{yahoo_ticker}{suffix}"
    return yahoo_ticker


def split_multi_exchange_tickers(actions):
    """Split tickers traded on multiple exchanges into separate tickers.

    When the same ticker (e.g., CNQ) has trades in different currencies
    (USD on NYSE, CAD on TSX), rename each action's ticker to the resolved
    Yahoo symbol so they are treated as separate positions.
    """
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
        yahoo_sym = _resolve_yahoo_symbol(ticker, tc, isin)
        if yahoo_sym != ticker:
            a["ticker_original"] = ticker
            a["ticker"] = yahoo_sym
            renamed += 1

    return renamed


# ---------------------------------------------------------------------------
# Portfolio Tracker: tracks avg cost basis, realized P&L, current holdings
# ---------------------------------------------------------------------------

class PortfolioTracker:
    """Process actions chronologically to build portfolio state."""

    def __init__(self):
        # Per-ticker state: {ticker: {shares, cost_basis_gbp, total_invested_gbp, total_sold_gbp}}
        self.positions = {}
        # Cash-flow tracking (all in GBP)
        self.total_deposits = 0.0
        self.total_withdrawals = 0.0
        self.total_dividends = 0.0
        self.total_interest = 0.0
        self.total_fees = 0.0
        self.total_bought_gbp = 0.0
        self.total_sold_gbp = 0.0
        self.realized_pnl = 0.0
        # Per-ticker realized P&L
        self.ticker_realized = defaultdict(float)
        # Sell details with avg cost context
        self.sell_details = []

    def process(self, action):
        """Process a single action. Must be called in chronological order."""
        ticker = action.get("ticker", "")
        total_gbp = abs(action.get("total", 0))
        quantity = action.get("quantity", 0)
        fees = action.get("fees", 0)
        self.total_fees += fees
        act = action["action"]

        if act == "BUY" and ticker and quantity > 0:
            if ticker not in self.positions:
                self.positions[ticker] = {
                    "shares": 0.0,
                    "cost_basis_gbp": 0.0,
                    "trade_currency": action.get("trade_currency", ""),
                    "exchange_rate": action.get("exchange_rate", 1.0),
                    "isin": action.get("isin", ""),
                }
            pos = self.positions[ticker]
            pos["shares"] += quantity
            pos["cost_basis_gbp"] += total_gbp
            # Keep latest exchange rate and trade currency for current valuation
            pos["trade_currency"] = action.get("trade_currency", pos["trade_currency"])
            pos["exchange_rate"] = action.get("exchange_rate", pos["exchange_rate"]) or pos["exchange_rate"]
            self.total_bought_gbp += total_gbp

        elif act == "SELL" and ticker and quantity > 0:
            if ticker in self.positions and self.positions[ticker]["shares"] > 0:
                pos = self.positions[ticker]
                avg_cost_per_share_gbp = pos["cost_basis_gbp"] / pos["shares"] if pos["shares"] > 0 else 0
                sell_qty = min(quantity, pos["shares"])
                cost_of_sold_gbp = avg_cost_per_share_gbp * sell_qty
                realized = total_gbp - cost_of_sold_gbp
                self.realized_pnl += realized
                self.ticker_realized[ticker] += realized
                self.total_sold_gbp += total_gbp

                self.sell_details.append({
                    "ticker": ticker,
                    "date": action["date"],
                    "quantity": sell_qty,
                    "sell_total_gbp": total_gbp,
                    "avg_cost_per_share_gbp": avg_cost_per_share_gbp,
                    "cost_of_sold_gbp": cost_of_sold_gbp,
                    "realized_pnl_gbp": realized,
                })

                pos["shares"] -= sell_qty
                pos["cost_basis_gbp"] -= cost_of_sold_gbp
                if pos["shares"] < 1e-9:
                    pos["shares"] = 0.0
                    pos["cost_basis_gbp"] = 0.0
            else:
                self.total_sold_gbp += total_gbp

        elif act == "DIVIDEND":
            self.total_dividends += total_gbp
        elif act == "INTEREST":
            self.total_interest += total_gbp
        elif act == "DEPOSIT":
            self.total_deposits += total_gbp
        elif act == "WITHDRAWAL":
            self.total_withdrawals += total_gbp

    def get_current_holdings(self, market_data):
        """Compute current value of all held positions using latest market prices."""
        holdings = []
        total_current_value = 0.0
        total_cost_basis = 0.0

        for ticker, pos in self.positions.items():
            if pos["shares"] < 1e-9:
                continue

            # Get latest price from market data
            price_dict, prices_list = get_prices_for_ticker(market_data, ticker)
            current_price = None
            current_date = None
            if prices_list:
                last_bar = prices_list[-1]
                current_price = last_bar.get("adjclose")
                current_date = last_bar.get("date")

            # Convert trade-currency price to GBP
            current_value_gbp = None
            if current_price is not None:
                exchange_rate = pos.get("exchange_rate", 1.0) or 1.0
                current_value_gbp = (current_price * pos["shares"]) / exchange_rate

            cost_basis = pos["cost_basis_gbp"]
            avg_cost_gbp = cost_basis / pos["shares"] if pos["shares"] > 0 else 0
            unrealized_pnl = (current_value_gbp - cost_basis) if current_value_gbp is not None else None
            unrealized_pct = ((current_value_gbp / cost_basis - 1) * 100) if current_value_gbp and cost_basis > 0 else None

            holding = {
                "ticker": ticker,
                "shares": pos["shares"],
                "cost_basis_gbp": round(cost_basis, 2),
                "avg_cost_gbp": round(avg_cost_gbp, 4),
                "current_price_trade": current_price,
                "current_price_date": current_date,
                "trade_currency": pos.get("trade_currency", ""),
                "exchange_rate": pos.get("exchange_rate", 1.0),
                "current_value_gbp": round(current_value_gbp, 2) if current_value_gbp is not None else None,
                "unrealized_pnl_gbp": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                "unrealized_pct": round(unrealized_pct, 2) if unrealized_pct is not None else None,
                "realized_pnl_gbp": round(self.ticker_realized.get(ticker, 0), 2),
            }
            holdings.append(holding)
            if current_value_gbp is not None:
                total_current_value += current_value_gbp
            total_cost_basis += cost_basis

        holdings.sort(key=lambda h: h.get("current_value_gbp") or 0, reverse=True)
        return holdings, round(total_current_value, 2), round(total_cost_basis, 2)

    def get_portfolio_summary(self, market_data):
        """Compute overall portfolio return metrics."""
        holdings, total_current_value, total_cost_basis = self.get_current_holdings(market_data)

        net_invested = self.total_deposits - self.total_withdrawals
        # Total return = current value + cash withdrawn + dividends + interest - total deposited
        # But simpler: total return = unrealized + realized + dividends + interest - fees
        total_unrealized = total_current_value - total_cost_basis
        total_return_gbp = self.realized_pnl + total_unrealized + self.total_dividends + self.total_interest - self.total_fees
        total_return_pct = (total_return_gbp / net_invested * 100) if net_invested > 0 else 0

        return {
            "net_invested_gbp": round(net_invested, 2),
            "total_deposits_gbp": round(self.total_deposits, 2),
            "total_withdrawals_gbp": round(self.total_withdrawals, 2),
            "total_bought_gbp": round(self.total_bought_gbp, 2),
            "total_sold_gbp": round(self.total_sold_gbp, 2),
            "total_dividends_gbp": round(self.total_dividends, 2),
            "total_interest_gbp": round(self.total_interest, 2),
            "total_fees_gbp": round(self.total_fees, 2),
            "realized_pnl_gbp": round(self.realized_pnl, 2),
            "total_unrealized_pnl_gbp": round(total_unrealized, 2),
            "current_portfolio_value_gbp": total_current_value,
            "total_cost_basis_gbp": total_cost_basis,
            "total_return_gbp": round(total_return_gbp, 2),
            "total_return_pct": round(total_return_pct, 2),
            "num_holdings": len(holdings),
            "holdings": holdings,
            "sell_details": self.sell_details,
        }


def get_prices_for_ticker(market_data, ticker):
    """Get price bars as a dict keyed by date string."""
    td = market_data.get("data", {}).get(ticker, {})
    chart = td.get("chart")
    if not chart:
        return {}, []
    prices = chart.get("prices", [])
    price_dict = {p["date"]: p for p in prices}
    return price_dict, prices


def get_dividends_for_ticker(market_data, ticker):
    """Get dividend events as a list."""
    td = market_data.get("data", {}).get(ticker, {})
    chart = td.get("chart")
    if not chart:
        return []
    return chart.get("dividends", [])


def get_spy_prices(market_data):
    """Get SPY price dict for market context."""
    return get_prices_for_ticker(market_data, "SPY")


# ---------------------------------------------------------------------------
# Stock Split Adjustment
# ---------------------------------------------------------------------------

def build_split_adjustments(market_data):
    """Extract all stock splits from market data.

    Returns {ticker: [(date_str, ratio), ...]} sorted by date.
    ratio is the yfinance numerator: 10.0 for a 10:1 forward split,
    0.01 for a 1:100 reverse split.
    """
    splits = {}
    data = market_data.get("data", {})
    for ticker, td in data.items():
        chart = (td or {}).get("chart") or {}
        split_list = chart.get("splits") or []
        if split_list:
            ticker_splits = []
            for s in split_list:
                ratio = s.get("numerator", 1.0)
                if ratio and ratio != 1.0:
                    ticker_splits.append((s["date"], float(ratio)))
            if ticker_splits:
                ticker_splits.sort(key=lambda x: x[0])
                splits[ticker] = ticker_splits
    return splits


def get_cumulative_split_factor(ticker_splits, action_date):
    """Compute cumulative split factor for all splits AFTER action_date.

    Converts pre-split values to Yahoo's split-adjusted basis:
      adjusted_quantity = original_quantity * factor
      adjusted_price    = original_price   / factor

    Examples:
      10:1 forward split (ratio=10): factor=10 → qty*10, price/10
      1:100 reverse split (ratio=0.01): factor=0.01 → qty*0.01, price/0.01
    """
    factor = 1.0
    for split_date, ratio in ticker_splits:
        if split_date > action_date:
            factor *= ratio
    return factor


def apply_split_adjustments(actions, market_data):
    """Adjust action quantities and prices for stock splits.

    Yahoo Finance returns split-adjusted historical prices. CSV data has
    pre-split quantities and prices. This adjusts CSV values to match
    Yahoo's adjusted basis so comparisons are correct.

    The GBP total is unchanged (you paid the same amount regardless of splits).
    """
    splits = build_split_adjustments(market_data)
    if not splits:
        return 0

    adjusted_count = 0
    for action in actions:
        ticker = action.get("ticker", "")
        if not ticker or ticker not in splits:
            continue
        if action["action"] not in ("BUY", "SELL"):
            continue

        factor = get_cumulative_split_factor(splits[ticker], action["date"])
        if abs(factor - 1.0) > 1e-9:
            # Preserve originals for display
            action["quantity_original"] = action["quantity"]
            action["price_original"] = action["price"]
            action["split_factor"] = factor
            # Adjust to match Yahoo's split-adjusted prices
            action["quantity"] = action["quantity"] * factor
            action["price"] = action["price"] / factor
            # total_gbp stays the same
            adjusted_count += 1

    return adjusted_count


def find_price_at_date(price_dict, date_str, direction="forward", max_days=5):
    """Find the price on or near a date. Look forward or backward for nearest trading day."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    step = 1 if direction == "forward" else -1
    for offset in range(max_days + 1):
        check = (dt + timedelta(days=offset * step)).strftime("%Y-%m-%d")
        if check in price_dict:
            return price_dict[check]
    return None


def get_price_window(prices_list, date_str, days_before, days_after):
    """Get price bars in a window around a date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = dt - timedelta(days=days_before)
    end = dt + timedelta(days=days_after)
    window = [p for p in prices_list if start <= datetime.strptime(p["date"], "%Y-%m-%d") <= end]
    return window


def compute_timing_score(action_type, action_price, prices_after):
    """
    Compute a timing score from -100 to +100.
    For SELL: positive = sold before a decline (good), negative = sold before a rally (bad)
    For BUY: positive = bought before a rally (good), negative = bought before a decline (bad)
    """
    if not prices_after or action_price <= 0:
        return 0, {}

    adjcloses = [p["adjclose"] for p in prices_after if p.get("adjclose") is not None]
    if not adjcloses:
        return 0, {}

    max_after = max(adjcloses)
    min_after = min(adjcloses)

    # Price at various intervals
    intervals = {}
    for days in [1, 5, 10, 30, 60, 90]:
        if len(adjcloses) > days:
            intervals[f"day_{days}"] = adjcloses[days - 1] if days <= len(adjcloses) else adjcloses[-1]
        elif adjcloses:
            intervals[f"day_{days}"] = adjcloses[-1]

    details = {
        "max_price_after": max_after,
        "min_price_after": min_after,
        "price_intervals": intervals,
    }

    if action_type == "SELL":
        if max_after > action_price:
            # Price went up after selling — bad timing
            pct_missed = ((max_after - action_price) / action_price) * 100
            score = -min(pct_missed * 2, 100)
        else:
            # Price went down after selling — good timing
            pct_avoided = ((action_price - min_after) / action_price) * 100
            score = min(pct_avoided * 2, 100)
    elif action_type == "BUY":
        if min_after < action_price:
            # Price went down after buying — bad timing
            pct_loss = ((action_price - min_after) / action_price) * 100
            score = -min(pct_loss * 2, 100)
        else:
            # Price went up after buying — good timing
            pct_gain = ((max_after - action_price) / action_price) * 100
            score = min(pct_gain * 2, 100)
    else:
        score = 0

    details["score"] = round(score, 1)
    return round(score, 1), details


def compute_dollar_impact(action_type, action_price, total_account_currency, prices_window):
    """Estimate dollar impact vs optimal timing in window.

    Uses percentage-based calculation applied to total_account_currency (GBP)
    so that all impacts are in the same currency regardless of trade currency.
    """
    if not prices_window or action_price <= 0 or total_account_currency <= 0:
        return 0, {}

    adjcloses = [p["adjclose"] for p in prices_window if p.get("adjclose") is not None]
    if not adjcloses:
        return 0, {}

    if action_type == "SELL":
        optimal = max(adjcloses)
        pct_diff = (action_price - optimal) / action_price  # negative = sold below optimal
        impact = pct_diff * total_account_currency
        return round(impact, 2), {"optimal_price": optimal, "action": "sell"}
    elif action_type == "BUY":
        optimal = min(adjcloses)
        pct_diff = (optimal - action_price) / action_price  # negative = bought above optimal
        impact = pct_diff * total_account_currency
        return round(impact, 2), {"optimal_price": optimal, "action": "buy"}
    return 0, {}


def check_dividend_proximity(sell_date, dividends, ticker):
    """Check if a sell happened near an ex-dividend date."""
    if not dividends:
        return None
    sell_dt = datetime.strptime(sell_date, "%Y-%m-%d")
    nearest = None
    nearest_days = None
    for div in dividends:
        div_dt = datetime.strptime(div["date"], "%Y-%m-%d")
        days_diff = (div_dt - sell_dt).days
        # Only care about ex-dates within 30 days AFTER the sell
        if 0 < days_diff <= 30:
            if nearest_days is None or days_diff < nearest_days:
                nearest = div
                nearest_days = days_diff
    if nearest:
        return {
            "ex_dividend_date": nearest["date"],
            "days_before_ex_date": nearest_days,
            "dividend_per_share": nearest["amount"],
            "missed": True,
        }
    return None


def detect_panic_sell(action, price_dict, prices_list, spy_price_dict):
    """Detect if a sell looks like panic selling. Returns detailed reasoning."""
    if action["action"] != "SELL":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    sell_price = action["price"]

    # Get prices 5 trading days before
    before = get_price_window(prices_list, date, days_before=10, days_after=0)
    if len(before) < 5:
        return None

    recent_5 = before[-6:-1] if len(before) >= 6 else before[:-1]
    if not recent_5:
        return None

    first_close = recent_5[0].get("adjclose")
    last_close = recent_5[-1].get("adjclose")
    if not first_close or not last_close or first_close <= 0:
        return None

    pct_decline = ((last_close - first_close) / first_close) * 100
    if pct_decline >= -5:
        return None

    # Get prices AFTER the sell to see what happened
    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    # Find recovery info
    recovery_info = {}
    if after_closes and sell_price > 0:
        max_bar = max(after_closes, key=lambda p: p.get("adjclose", 0))
        max_price = max_bar.get("adjclose", 0)
        max_date = max_bar["date"]
        recovery_pct = ((max_price - sell_price) / sell_price) * 100

        # Find when price first exceeded sell price
        recovered_date = None
        for p in after_closes:
            if p.get("adjclose", 0) > sell_price:
                recovered_date = p["date"]
                break

        # Price at key intervals after sell
        price_trajectory = {}
        for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
            if idx < len(after_closes):
                p = after_closes[idx].get("adjclose", 0)
                price_trajectory[label] = {
                    "price": round(p, 2),
                    "pct_vs_sell": round(((p - sell_price) / sell_price) * 100, 2) if sell_price > 0 else 0,
                    "date": after_closes[idx]["date"],
                }

        # Optimal sell date in the 90-day window (before + after)
        full_window = get_price_window(prices_list, date, days_before=5, days_after=90)
        if full_window:
            optimal_bar = max(full_window, key=lambda p: p.get("adjclose", 0))
            optimal_price = optimal_bar.get("adjclose", 0)
            optimal_date = optimal_bar["date"]
        else:
            optimal_price = sell_price
            optimal_date = date

        recovery_info = {
            "max_price_after": round(max_price, 2),
            "max_price_date": max_date,
            "recovery_pct": round(recovery_pct, 2),
            "recovered_sell_price_date": recovered_date,
            "price_trajectory": price_trajectory,
            "optimal_sell_price": round(optimal_price, 2),
            "optimal_sell_date": optimal_date,
            "missed_gain_pct": round(((optimal_price - sell_price) / sell_price) * 100, 2) if sell_price > 0 else 0,
        }

    return {
        "pattern": "panic_sell",
        "stock_decline_5d": round(pct_decline, 2),
        "date": date,
        "ticker": action["ticker"],
        "sell_price": sell_price,
        **recovery_info,
    }


def detect_fomo_buy(action, price_dict, prices_list):
    """Detect if a buy looks like FOMO buying. Returns detailed reasoning."""
    if action["action"] != "BUY":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    buy_price = action["price"]

    before = get_price_window(prices_list, date, days_before=20, days_after=0)
    if len(before) < 10:
        return None

    recent_10 = before[-11:-1] if len(before) >= 11 else before[:-1]
    if not recent_10:
        return None

    first_close = recent_10[0].get("adjclose")
    last_close = recent_10[-1].get("adjclose")
    if not first_close or not last_close or first_close <= 0:
        return None

    pct_runup = ((last_close - first_close) / first_close) * 100
    if pct_runup <= 10:
        return None

    # What happened AFTER the buy
    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    aftermath = {}
    if after_closes and buy_price > 0:
        min_bar = min(after_closes, key=lambda p: p.get("adjclose", 0))
        min_price = min_bar.get("adjclose", 0)
        min_date = min_bar["date"]
        max_drawdown = ((min_price - buy_price) / buy_price) * 100

        # Price at key intervals
        price_trajectory = {}
        for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
            if idx < len(after_closes):
                p = after_closes[idx].get("adjclose", 0)
                price_trajectory[label] = {
                    "price": round(p, 2),
                    "pct_vs_buy": round(((p - buy_price) / buy_price) * 100, 2) if buy_price > 0 else 0,
                    "date": after_closes[idx]["date"],
                }

        # Optimal buy in the 30-day window around the buy
        full_window = get_price_window(prices_list, date, days_before=5, days_after=30)
        if full_window:
            optimal_bar = min(full_window, key=lambda p: p.get("adjclose", 0))
            optimal_price = optimal_bar.get("adjclose", 0)
            optimal_date = optimal_bar["date"]
        else:
            optimal_price = buy_price
            optimal_date = date

        aftermath = {
            "min_price_after": round(min_price, 2),
            "min_price_date": min_date,
            "max_drawdown_pct": round(max_drawdown, 2),
            "price_trajectory": price_trajectory,
            "optimal_buy_price": round(optimal_price, 2),
            "optimal_buy_date": optimal_date,
            "overpaid_pct": round(((buy_price - optimal_price) / optimal_price) * 100, 2) if optimal_price > 0 else 0,
        }

    return {
        "pattern": "fomo_buy",
        "stock_gain_10d": round(pct_runup, 2),
        "date": date,
        "ticker": action["ticker"],
        "buy_price": buy_price,
        **aftermath,
    }


def detect_well_timed_sell(action, price_dict, prices_list):
    """Detect if a sell had excellent timing. Returns detailed reasoning."""
    if action["action"] != "SELL":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    sell_price = action["price"]
    if sell_price <= 0:
        return None

    # Get prices after the sell
    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    if len(after_closes) < 5:
        return None

    # Check if price dropped significantly after selling (>10% decline = well timed)
    min_bar = min(after_closes, key=lambda p: p.get("adjclose", float("inf")))
    min_price = min_bar.get("adjclose", 0)
    if min_price <= 0:
        return None

    decline_after = ((min_price - sell_price) / sell_price) * 100
    if decline_after >= -5:
        return None  # Price didn't drop enough to be noteworthy

    # Price trajectory after sell
    price_trajectory = {}
    for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
        if idx < len(after_closes):
            p = after_closes[idx].get("adjclose", 0)
            price_trajectory[label] = {
                "price": round(p, 2),
                "pct_vs_sell": round(((p - sell_price) / sell_price) * 100, 2) if sell_price > 0 else 0,
                "date": after_closes[idx]["date"],
            }

    # How much loss was avoided
    loss_avoided_pct = abs(decline_after)

    # When did the low occur
    min_date = min_bar["date"]

    # Did price ever recover back to sell price?
    recovered_date = None
    stayed_below = True
    for p in after_closes:
        if p.get("adjclose", 0) >= sell_price:
            recovered_date = p["date"]
            stayed_below = False
            break

    return {
        "pattern": "well_timed_sell",
        "date": date,
        "ticker": action["ticker"],
        "sell_price": sell_price,
        "min_price_after": round(min_price, 2),
        "min_price_date": min_date,
        "max_decline_after_pct": round(decline_after, 2),
        "loss_avoided_pct": round(loss_avoided_pct, 2),
        "price_trajectory": price_trajectory,
        "stayed_below_sell_price": stayed_below,
        "recovered_date": recovered_date,
    }


def detect_well_timed_buy(action, price_dict, prices_list):
    """Detect if a buy had excellent timing. Returns detailed reasoning."""
    if action["action"] != "BUY":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    buy_price = action["price"]
    if buy_price <= 0:
        return None

    # Get prices after the buy
    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    if len(after_closes) < 5:
        return None

    # Check if price rose significantly after buying (>10% gain = well timed)
    max_bar = max(after_closes, key=lambda p: p.get("adjclose", 0))
    max_price = max_bar.get("adjclose", 0)
    if max_price <= 0:
        return None

    gain_after = ((max_price - buy_price) / buy_price) * 100
    if gain_after <= 10:
        return None  # Not enough gain to be noteworthy

    # Price trajectory after buy
    price_trajectory = {}
    for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
        if idx < len(after_closes):
            p = after_closes[idx].get("adjclose", 0)
            price_trajectory[label] = {
                "price": round(p, 2),
                "pct_vs_buy": round(((p - buy_price) / buy_price) * 100, 2) if buy_price > 0 else 0,
                "date": after_closes[idx]["date"],
            }

    # Max price and date
    max_date = max_bar["date"]

    # Was this a dip buy? Check if price was down before the buy
    before = get_price_window(prices_list, date, days_before=20, days_after=0)
    bought_the_dip = False
    dip_detail = {}
    if len(before) >= 10:
        recent_10 = before[-11:-1] if len(before) >= 11 else before[:-1]
        if recent_10:
            first_close = recent_10[0].get("adjclose")
            last_close = recent_10[-1].get("adjclose")
            if first_close and last_close and first_close > 0:
                pre_move = ((last_close - first_close) / first_close) * 100
                if pre_move < -5:
                    bought_the_dip = True
                    dip_detail = {
                        "decline_before_buy_pct": round(pre_move, 2),
                    }

    # Did price stay above buy price?
    min_bar_after = min(after_closes, key=lambda p: p.get("adjclose", float("inf")))
    min_after = min_bar_after.get("adjclose", 0)
    never_went_below = min_after >= buy_price * 0.98  # within 2%

    return {
        "pattern": "well_timed_buy",
        "date": date,
        "ticker": action["ticker"],
        "buy_price": buy_price,
        "max_price_after": round(max_price, 2),
        "max_price_date": max_date,
        "max_gain_after_pct": round(gain_after, 2),
        "price_trajectory": price_trajectory,
        "bought_the_dip": bought_the_dip,
        "dip_detail": dip_detail,
        "never_went_below_entry": never_went_below,
        "min_price_after": round(min_after, 2),
    }


def detect_worst_timed_sell(action, price_dict, prices_list):
    """Detect if a sell had terrible timing (sold before a big rally)."""
    if action["action"] != "SELL":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    sell_price = action["price"]
    if sell_price <= 0:
        return None

    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    if len(after_closes) < 5:
        return None

    max_bar = max(after_closes, key=lambda p: p.get("adjclose", 0))
    max_price = max_bar.get("adjclose", 0)
    if max_price <= 0:
        return None

    rally_after = ((max_price - sell_price) / sell_price) * 100
    if rally_after <= 10:
        return None

    price_trajectory = {}
    for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
        if idx < len(after_closes):
            p = after_closes[idx].get("adjclose", 0)
            price_trajectory[label] = {
                "price": round(p, 2),
                "pct_vs_sell": round(((p - sell_price) / sell_price) * 100, 2) if sell_price > 0 else 0,
                "date": after_closes[idx]["date"],
            }

    max_date = max_bar["date"]

    # Optimal sell date (within 90 days after)
    optimal_price = max_price
    optimal_date = max_date

    return {
        "pattern": "worst_timed_sell",
        "date": date,
        "ticker": action["ticker"],
        "sell_price": sell_price,
        "max_price_after": round(max_price, 2),
        "max_price_date": max_date,
        "missed_rally_pct": round(rally_after, 2),
        "price_trajectory": price_trajectory,
        "optimal_sell_price": round(optimal_price, 2),
        "optimal_sell_date": optimal_date,
    }


def detect_worst_timed_buy(action, price_dict, prices_list):
    """Detect if a buy had terrible timing (bought before a big drop)."""
    if action["action"] != "BUY":
        return None
    date = action["date"]
    dt = datetime.strptime(date, "%Y-%m-%d")
    buy_price = action["price"]
    if buy_price <= 0:
        return None

    after = get_price_window(prices_list, date, days_before=0, days_after=90)
    after_closes = [p for p in after if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
    after_closes.sort(key=lambda p: p["date"])

    if len(after_closes) < 5:
        return None

    min_bar = min(after_closes, key=lambda p: p.get("adjclose", float("inf")))
    min_price = min_bar.get("adjclose", 0)
    if min_price <= 0:
        return None

    drop_after = ((min_price - buy_price) / buy_price) * 100
    if drop_after >= -10:
        return None

    price_trajectory = {}
    for label, idx in [("1 week", 4), ("1 month", 21), ("3 months", 63)]:
        if idx < len(after_closes):
            p = after_closes[idx].get("adjclose", 0)
            price_trajectory[label] = {
                "price": round(p, 2),
                "pct_vs_buy": round(((p - buy_price) / buy_price) * 100, 2) if buy_price > 0 else 0,
                "date": after_closes[idx]["date"],
            }

    min_date = min_bar["date"]

    # Did it ever recover?
    recovered_date = None
    for p in after_closes:
        if p.get("adjclose", 0) >= buy_price * 0.98:
            recovered_date = p["date"]
            break

    # Was this buying at a peak? Check if price was up before
    before = get_price_window(prices_list, date, days_before=20, days_after=0)
    bought_the_top = False
    if len(before) >= 10:
        recent_10 = before[-11:-1] if len(before) >= 11 else before[:-1]
        if recent_10:
            first_close = recent_10[0].get("adjclose")
            last_close = recent_10[-1].get("adjclose")
            if first_close and last_close and first_close > 0:
                pre_move = ((last_close - first_close) / first_close) * 100
                if pre_move > 5:
                    bought_the_top = True

    return {
        "pattern": "worst_timed_buy",
        "date": date,
        "ticker": action["ticker"],
        "buy_price": buy_price,
        "min_price_after": round(min_price, 2),
        "min_price_date": min_date,
        "max_drop_after_pct": round(drop_after, 2),
        "price_trajectory": price_trajectory,
        "bought_the_top": bought_the_top,
        "recovered_date": recovered_date,
    }


def detect_round_trips(actions):
    """Find buy-sell pairs for the same ticker and compute returns."""
    ticker_actions = defaultdict(list)
    for a in actions:
        if a["action"] in ("BUY", "SELL") and a["ticker"]:
            ticker_actions[a["ticker"]].append(a)

    round_trips = []
    for ticker, acts in ticker_actions.items():
        buys = [a for a in acts if a["action"] == "BUY"]
        sells = [a for a in acts if a["action"] == "SELL"]

        # Simple FIFO matching
        buy_queue = list(buys)
        for sell in sells:
            if not buy_queue:
                break
            buy = buy_queue[0]
            if buy["date"] < sell["date"]:
                buy_total = buy["total"] if buy["total"] > 0 else buy["price"] * buy["quantity"]
                sell_total = sell["total"] if sell["total"] > 0 else sell["price"] * sell["quantity"]
                if buy_total > 0:
                    ret = ((sell_total - buy_total) / buy_total) * 100
                    fees = buy.get("fees", 0) + sell.get("fees", 0)
                    round_trips.append({
                        "ticker": ticker,
                        "buy_date": buy["date"],
                        "buy_price": buy["price"],
                        "sell_date": sell["date"],
                        "sell_price": sell["price"],
                        "quantity": min(buy["quantity"], sell["quantity"]),
                        "return_pct": round(ret, 2),
                        "dollar_return": round(sell_total - buy_total - fees, 2),
                        "holding_days": (datetime.strptime(sell["date"], "%Y-%m-%d") -
                                         datetime.strptime(buy["date"], "%Y-%m-%d")).days,
                        "fees": fees,
                    })
                buy_queue.pop(0)

    return round_trips


def detect_wash_sales(actions):
    """Detect potential wash sales: sell at loss, rebuy within 30 days."""
    ticker_actions = defaultdict(list)
    for a in actions:
        if a["action"] in ("BUY", "SELL") and a["ticker"]:
            ticker_actions[a["ticker"]].append(a)

    wash_sales = []
    for ticker, acts in ticker_actions.items():
        sells = [a for a in acts if a["action"] == "SELL"]
        buys = [a for a in acts if a["action"] == "BUY"]

        for sell in sells:
            sell_dt = datetime.strptime(sell["date"], "%Y-%m-%d")
            for buy in buys:
                buy_dt = datetime.strptime(buy["date"], "%Y-%m-%d")
                days_diff = abs((buy_dt - sell_dt).days)
                if 0 < days_diff <= 30 and buy_dt > sell_dt:
                    wash_sales.append({
                        "ticker": ticker,
                        "sell_date": sell["date"],
                        "sell_price": sell["price"],
                        "rebuy_date": buy["date"],
                        "rebuy_price": buy["price"],
                        "days_between": days_diff,
                    })
    return wash_sales


def detect_overtrading(actions):
    """Detect excessive trading in the same ticker."""
    ticker_actions = defaultdict(list)
    for a in actions:
        if a["action"] in ("BUY", "SELL") and a["ticker"]:
            ticker_actions[a["ticker"]].append(a)

    overtrading = []
    for ticker, acts in ticker_actions.items():
        acts.sort(key=lambda a: a["date"])
        # Check 60-day windows
        for i, a in enumerate(acts):
            dt = datetime.strptime(a["date"], "%Y-%m-%d")
            window_end = dt + timedelta(days=60)
            count = sum(1 for b in acts
                        if dt <= datetime.strptime(b["date"], "%Y-%m-%d") <= window_end)
            if count > 3:
                overtrading.append({
                    "ticker": ticker,
                    "window_start": a["date"],
                    "window_end": window_end.strftime("%Y-%m-%d"),
                    "trade_count": count,
                })
                break  # One flag per ticker is enough
    return overtrading


def detect_dca_sequences(actions, market_data):
    """Detect dollar-cost averaging sequences — recurring buys of similar amounts at regular intervals.

    Returns {sequences: [...], dca_action_keys: set of (ticker, date)}.
    """
    from statistics import median

    # Group BUY actions by ticker, chronological
    ticker_buys = defaultdict(list)
    for a in actions:
        if a["action"] == "BUY" and a.get("ticker"):
            ticker_buys[a["ticker"]].append(a)

    for buys in ticker_buys.values():
        buys.sort(key=lambda a: a["date"])

    sequences = []
    dca_action_keys = set()

    interval_labels = {
        "daily": (1, 2),
        "weekly": (5, 9),
        "biweekly": (12, 16),
        "monthly": (25, 35),
    }

    for ticker, buys in ticker_buys.items():
        if len(buys) < 4:
            continue

        # Sliding window: try to build sequences of recurring buys
        i = 0
        while i < len(buys) - 3:
            seq = [buys[i]]
            for j in range(i + 1, len(buys)):
                candidate = buys[j]
                # Check amount similarity: within 50% of median of current seq
                amounts = [abs(a.get("total", 0)) for a in seq]
                med = median(amounts) if amounts else 0
                cand_amt = abs(candidate.get("total", 0))
                if med > 0 and abs(cand_amt - med) / med > 0.5:
                    break  # Amount shifted too much

                # Check interval regularity
                prev_dt = datetime.strptime(seq[-1]["date"], "%Y-%m-%d")
                cand_dt = datetime.strptime(candidate["date"], "%Y-%m-%d")
                gap = (cand_dt - prev_dt).days

                # Detect interval type from existing gaps
                if len(seq) >= 2:
                    gaps = []
                    for k in range(1, len(seq)):
                        d1 = datetime.strptime(seq[k-1]["date"], "%Y-%m-%d")
                        d2 = datetime.strptime(seq[k]["date"], "%Y-%m-%d")
                        gaps.append((d2 - d1).days)
                    med_gap = median(gaps)
                    # Allow gap up to 2x detected interval
                    if gap > med_gap * 2.5:
                        break
                else:
                    # First pair: accept any reasonable gap (1-35 days)
                    if gap > 35 or gap < 1:
                        break

                seq.append(candidate)

            if len(seq) >= 4:
                # Classify interval type
                gaps = []
                for k in range(1, len(seq)):
                    d1 = datetime.strptime(seq[k-1]["date"], "%Y-%m-%d")
                    d2 = datetime.strptime(seq[k]["date"], "%Y-%m-%d")
                    gaps.append((d2 - d1).days)
                med_gap = median(gaps)

                interval_type = "irregular"
                for label, (lo, hi) in interval_labels.items():
                    if lo <= med_gap <= hi:
                        interval_type = label
                        break

                # Consistency score: how uniform are the gaps and amounts?
                amounts = [abs(a.get("total", 0)) for a in seq]
                med_amt = median(amounts)
                amt_deviations = [abs(a - med_amt) / med_amt for a in amounts if med_amt > 0]
                amt_consistency = max(0, 100 - sum(amt_deviations) / len(amt_deviations) * 100) if amt_deviations else 100

                gap_deviations = [abs(g - med_gap) / med_gap for g in gaps if med_gap > 0]
                gap_consistency = max(0, 100 - sum(gap_deviations) / len(gap_deviations) * 100) if gap_deviations else 100

                consistency_score = round((amt_consistency + gap_consistency) / 2, 1)

                # DCA vs lump sum comparison
                total_invested_gbp = sum(abs(a.get("total", 0)) for a in seq)
                total_shares = sum(a.get("quantity", 0) for a in seq)
                avg_cost_trade = sum(a["price"] * a["quantity"] for a in seq) / total_shares if total_shares > 0 else 0

                # Get period average price from market data
                price_dict, prices_list = get_prices_for_ticker(market_data, ticker)
                start_date = seq[0]["date"]
                end_date = seq[-1]["date"]
                period_prices = [p["adjclose"] for p in prices_list
                                 if start_date <= p["date"] <= end_date and p.get("adjclose")]
                period_avg_price = sum(period_prices) / len(period_prices) if period_prices else 0

                # Lump sum: if invested all on first buy date
                first_price_bar = find_price_at_date(price_dict, start_date)
                last_price_bar = find_price_at_date(price_dict, end_date)
                lump_sum_price = first_price_bar["adjclose"] if first_price_bar else 0

                # DCA return: avg cost vs last price
                dca_return_pct = 0
                lump_sum_return_pct = 0
                if last_price_bar and last_price_bar.get("adjclose") and avg_cost_trade > 0:
                    last_price = last_price_bar["adjclose"]
                    dca_return_pct = ((last_price - avg_cost_trade) / avg_cost_trade) * 100
                if last_price_bar and last_price_bar.get("adjclose") and lump_sum_price > 0:
                    last_price = last_price_bar["adjclose"]
                    lump_sum_return_pct = ((last_price - lump_sum_price) / lump_sum_price) * 100

                dca_won = dca_return_pct > lump_sum_return_pct

                seq_data = {
                    "ticker": ticker,
                    "interval_type": interval_type,
                    "median_gap_days": round(med_gap, 1),
                    "num_buys": len(seq),
                    "start_date": start_date,
                    "end_date": end_date,
                    "total_invested_gbp": round(total_invested_gbp, 2),
                    "avg_amount_gbp": round(med_amt, 2),
                    "total_shares": round(total_shares, 6),
                    "avg_cost_trade_currency": round(avg_cost_trade, 4),
                    "period_avg_price": round(period_avg_price, 4) if period_avg_price else None,
                    "vs_period_avg_pct": round(((avg_cost_trade - period_avg_price) / period_avg_price) * 100, 2) if period_avg_price > 0 else None,
                    "consistency_score": consistency_score,
                    "dca_return_pct": round(dca_return_pct, 2),
                    "lump_sum_return_pct": round(lump_sum_return_pct, 2),
                    "dca_won": dca_won,
                    "trade_currency": seq[0].get("trade_currency", ""),
                }
                sequences.append(seq_data)

                # Mark all actions in this sequence as DCA
                for a in seq:
                    dca_action_keys.add((a["ticker"], a["date"]))

                # Skip past this sequence
                i += len(seq)
            else:
                i += 1

    sequences.sort(key=lambda s: s["total_invested_gbp"], reverse=True)
    return {"sequences": sequences, "dca_action_keys": dca_action_keys}


def compute_benchmark_comparison(tracker, actions, market_data):
    """Compare portfolio return vs SPY buy-and-hold using Modified Dietz method."""
    import math

    # Find portfolio active period
    dated_actions = [a for a in actions if a.get("date")]
    if not dated_actions:
        return None
    dates = sorted(a["date"] for a in dated_actions)
    start_date = dates[0]
    end_date = dates[-1]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end_dt - start_dt).days
    if total_days < 30:
        return None

    # SPY buy-and-hold return
    spy_price_dict, spy_prices_list = get_spy_prices(market_data)
    if not spy_prices_list:
        return None

    spy_start_bar = find_price_at_date(spy_price_dict, start_date, direction="forward")
    spy_end_bar = find_price_at_date(spy_price_dict, end_date, direction="backward")
    if not spy_start_bar or not spy_end_bar:
        return None

    spy_start_price = spy_start_bar["adjclose"]
    spy_end_price = spy_end_bar["adjclose"]
    if spy_start_price <= 0:
        return None

    spy_return_pct = ((spy_end_price - spy_start_price) / spy_start_price) * 100

    # Modified Dietz for portfolio TWR
    # V_end = current portfolio value + total withdrawn + dividends + interest
    # V_start = 0 (starting from nothing)
    # Cash flows = deposits (positive), withdrawals (negative)
    portfolio_summary = tracker.get_portfolio_summary(market_data)
    v_end = portfolio_summary["current_portfolio_value_gbp"]
    total_return_gbp = portfolio_summary["total_return_gbp"]
    net_invested = portfolio_summary["net_invested_gbp"]

    # Simple TWR approximation: total return / net invested
    portfolio_twr_pct = portfolio_summary["total_return_pct"]

    # Alpha
    alpha_pct = portfolio_twr_pct - spy_return_pct

    # CAGR calculation
    years = total_days / 365.25
    if years > 0 and net_invested > 0:
        # Portfolio CAGR
        total_value = v_end + tracker.total_withdrawals + tracker.total_dividends + tracker.total_interest
        if tracker.total_deposits > 0 and total_value > 0:
            portfolio_cagr = (math.pow(total_value / tracker.total_deposits, 1 / years) - 1) * 100
        else:
            portfolio_cagr = 0
        # SPY CAGR
        spy_cagr = (math.pow(spy_end_price / spy_start_price, 1 / years) - 1) * 100
    else:
        portfolio_cagr = 0
        spy_cagr = 0

    # Monthly comparison series (last 12 months or full period, whichever is shorter)
    monthly_comparison = []
    # Walk month by month from start
    current_month = start_dt.replace(day=1)
    while current_month <= end_dt:
        month_end = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if month_end > end_dt:
            month_end = end_dt
        month_str = month_end.strftime("%Y-%m-%d")
        spy_bar = find_price_at_date(spy_price_dict, month_str, direction="backward")
        if spy_bar and spy_start_price > 0:
            spy_cum = ((spy_bar["adjclose"] - spy_start_price) / spy_start_price) * 100
            monthly_comparison.append({
                "month": current_month.strftime("%Y-%m"),
                "spy_cumulative_pct": round(spy_cum, 2),
            })
        # Next month
        current_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    return {
        "period_start": start_date,
        "period_end": end_date,
        "period_days": total_days,
        "period_years": round(years, 2),
        "portfolio_twr_pct": round(portfolio_twr_pct, 2),
        "spy_buy_hold_return_pct": round(spy_return_pct, 2),
        "alpha_pct": round(alpha_pct, 2),
        "portfolio_cagr_pct": round(portfolio_cagr, 2),
        "spy_cagr_pct": round(spy_cagr, 2),
        "spy_start_price": round(spy_start_price, 2),
        "spy_end_price": round(spy_end_price, 2),
        "monthly_comparison": monthly_comparison[-12:],  # Last 12 months
    }


def compute_risk_metrics(tracker, actions, market_data):
    """Compute risk-adjusted return metrics: volatility, Sharpe, Sortino, max drawdown."""
    import numpy as np

    dated_actions = [a for a in actions if a.get("date")]
    if not dated_actions:
        return None
    dates = sorted(a["date"] for a in dated_actions)
    start_date = dates[0]
    end_date = dates[-1]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end_dt - start_dt).days
    if total_days < 60:
        return None

    # Build a set of all trading days from market data
    all_dates = set()
    for ticker_key, ticker_data in market_data.get("data", {}).items():
        chart = ticker_data.get("chart") if ticker_data else None
        if chart:
            for p in chart.get("prices", []):
                d = p.get("date", "")
                if start_date <= d <= end_date:
                    all_dates.add(d)
    trading_days = sorted(all_dates)
    if len(trading_days) < 30:
        return None

    # Index actions by date for fast lookup
    action_by_date = defaultdict(list)
    for a in actions:
        if a.get("date"):
            action_by_date[a["date"]].append(a)

    # Track positions day by day
    positions = {}  # ticker -> {shares, exchange_rate}

    # Process all actions up to start to get initial state
    for a in actions:
        if a["date"] > start_date:
            break
        ticker = a.get("ticker", "")
        qty = a.get("quantity", 0)
        act = a["action"]
        if act == "BUY" and ticker:
            if ticker not in positions:
                positions[ticker] = {"shares": 0.0, "exchange_rate": a.get("exchange_rate", 1.0) or 1.0}
            positions[ticker]["shares"] += qty
            positions[ticker]["exchange_rate"] = a.get("exchange_rate", 1.0) or positions[ticker]["exchange_rate"]
        elif act == "SELL" and ticker and ticker in positions:
            positions[ticker]["shares"] = max(0, positions[ticker]["shares"] - qty)

    # Cache price dicts
    price_caches = {}
    for ticker in market_data.get("data", {}):
        pd_dict, _ = get_prices_for_ticker(market_data, ticker)
        if pd_dict:
            price_caches[ticker] = pd_dict

    last_known_prices = {}  # ticker -> last known price in GBP per share

    # Build daily portfolio values and cash flows
    raw_values = []
    raw_cash_flows = []

    for day in trading_days:
        day_cf = 0.0
        for a in action_by_date.get(day, []):
            ticker = a.get("ticker", "")
            qty = a.get("quantity", 0)
            act = a["action"]
            if act == "BUY" and ticker:
                if ticker not in positions:
                    positions[ticker] = {"shares": 0.0, "exchange_rate": a.get("exchange_rate", 1.0) or 1.0}
                positions[ticker]["shares"] += qty
                positions[ticker]["exchange_rate"] = a.get("exchange_rate", 1.0) or positions[ticker]["exchange_rate"]
            elif act == "SELL" and ticker and ticker in positions:
                positions[ticker]["shares"] = max(0, positions[ticker]["shares"] - qty)
            elif act == "DEPOSIT":
                day_cf += abs(a.get("total", 0))
            elif act == "WITHDRAWAL":
                day_cf -= abs(a.get("total", 0))

        portfolio_value = 0.0
        for ticker, pos in positions.items():
            if pos["shares"] < 1e-9:
                continue
            pd_dict = price_caches.get(ticker, {})
            bar = pd_dict.get(day)
            if bar and bar.get("adjclose"):
                price_gbp = bar["adjclose"] / (pos["exchange_rate"] or 1.0)
                last_known_prices[ticker] = price_gbp
                portfolio_value += price_gbp * pos["shares"]
            elif ticker in last_known_prices:
                portfolio_value += last_known_prices[ticker] * pos["shares"]

        raw_values.append(portfolio_value)
        raw_cash_flows.append(day_cf)

    if len(raw_values) < 30:
        return None

    values = np.array(raw_values, dtype=np.float64)
    cash_flows_arr = np.array(raw_cash_flows, dtype=np.float64)

    # Daily returns adjusted for cash flows
    prev_vals = values[:-1]
    curr_vals = values[1:]
    cfs = cash_flows_arr[1:]
    denominators = prev_vals + cfs
    # Fall back to prev_vals where denominator is non-positive
    safe_denom = np.where(denominators > 0, denominators, np.where(prev_vals > 0, prev_vals, 1.0))
    daily_returns = (curr_vals - prev_vals - cfs) / safe_denom
    # Zero out returns where both denominators were invalid
    daily_returns = np.where((denominators <= 0) & (prev_vals <= 0), 0.0, daily_returns)

    n = len(daily_returns)
    if n == 0:
        return None

    # Annualized return via compounded daily returns
    cumulative = np.prod(1 + daily_returns)
    years = n / 252
    annualized_return = np.power(cumulative, 1 / years) - 1 if years > 0 else 0.0

    # Annualized volatility
    annualized_vol = np.std(daily_returns, ddof=0) * np.sqrt(252)

    # Sharpe Ratio (risk-free rate = 4.5% annualized)
    risk_free = 0.045
    sharpe = float((annualized_return - risk_free) / annualized_vol) if annualized_vol > 0 else 0.0

    # Sortino Ratio (downside deviation)
    downside = np.minimum(daily_returns, 0.0)
    downside_dev = np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)
    sortino = float((annualized_return - risk_free) / downside_dev) if downside_dev > 0 else 0.0

    # Max Drawdown using numpy cumulative max
    running_max = np.maximum.accumulate(values)
    drawdowns = np.where(running_max > 0, (values - running_max) / running_max, 0.0)
    dd_end_idx = int(np.argmin(drawdowns))
    max_dd = float(drawdowns[dd_end_idx])
    dd_peak_idx = int(np.argmax(values[:dd_end_idx + 1])) if dd_end_idx > 0 else 0

    # Find recovery date
    recovery_idx = None
    dd_peak_val = values[dd_peak_idx]
    recovery_candidates = np.where(values[dd_end_idx:] >= dd_peak_val)[0]
    if len(recovery_candidates) > 0:
        recovery_idx = int(dd_end_idx + recovery_candidates[0])

    dd_start_date = trading_days[dd_peak_idx] if dd_peak_idx < len(trading_days) else None
    dd_end_date = trading_days[dd_end_idx] if dd_end_idx < len(trading_days) else None
    dd_recovery_date = trading_days[recovery_idx] if recovery_idx is not None and recovery_idx < len(trading_days) else None
    dd_duration_days = (datetime.strptime(dd_end_date, "%Y-%m-%d") - datetime.strptime(dd_start_date, "%Y-%m-%d")).days if dd_start_date and dd_end_date else 0

    # Daily return stats via numpy
    positive_days = int(np.sum(daily_returns > 0))
    negative_days = int(np.sum(daily_returns < 0))
    flat_days = int(np.sum(daily_returns == 0))
    best_day_idx = int(np.argmax(daily_returns))
    worst_day_idx = int(np.argmin(daily_returns))
    best_day_return = float(daily_returns[best_day_idx]) * 100
    worst_day_return = float(daily_returns[worst_day_idx]) * 100
    best_day_date = trading_days[best_day_idx + 1] if best_day_idx + 1 < len(trading_days) else None
    worst_day_date = trading_days[worst_day_idx + 1] if worst_day_idx + 1 < len(trading_days) else None

    return {
        "annualized_return_pct": round(float(annualized_return * 100), 2),
        "annualized_volatility_pct": round(float(annualized_vol * 100), 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "risk_free_rate_pct": 4.5,
        "max_drawdown_pct": round(float(max_dd * 100), 2),
        "max_drawdown_start_date": dd_start_date,
        "max_drawdown_end_date": dd_end_date,
        "max_drawdown_recovery_date": dd_recovery_date,
        "max_drawdown_duration_days": dd_duration_days,
        "total_trading_days": n,
        "positive_days": positive_days,
        "negative_days": negative_days,
        "flat_days": flat_days,
        "win_rate_pct": round(positive_days / n * 100, 1) if n > 0 else 0,
        "best_day_return_pct": round(best_day_return, 2),
        "best_day_date": best_day_date,
        "worst_day_return_pct": round(worst_day_return, 2),
        "worst_day_date": worst_day_date,
    }


def analyze_action(action, market_data, spy_prices_dict, is_dca=False):
    """Analyze a single action against market data."""
    ticker = action["ticker"]
    if not ticker:
        return {"action": action, "analysis": None, "reason": "no_ticker"}

    price_dict, prices_list = get_prices_for_ticker(market_data, ticker)
    if not price_dict:
        return {"action": action, "analysis": None, "reason": "no_market_data"}

    result = {"action": action, "analysis": {}}

    # Find the actual market price on the action date
    market_bar = find_price_at_date(price_dict, action["date"])
    if market_bar:
        result["analysis"]["market_price_at_date"] = market_bar["adjclose"]
        result["analysis"]["market_date"] = market_bar["date"]

    action_price = action["price"] if action["price"] > 0 else (
        market_bar["adjclose"] if market_bar else 0
    )

    if action["action"] in ("BUY", "SELL"):
        # Get prices after the action for timing analysis
        dt = datetime.strptime(action["date"], "%Y-%m-%d")
        prices_after = [p for p in prices_list
                        if datetime.strptime(p["date"], "%Y-%m-%d") > dt]
        prices_after.sort(key=lambda p: p["date"])
        prices_after = prices_after[:90]  # ~90 trading days

        # Timing score
        score, details = compute_timing_score(action["action"], action_price, prices_after)
        result["analysis"]["timing_score"] = score
        result["analysis"]["timing_details"] = details

        # Dollar impact (normalized to account currency via percentage method)
        window = get_price_window(prices_list, action["date"],
                                  days_before=45, days_after=45)
        total_account = action.get("total", 0) or (action["price"] * action["quantity"])
        impact, impact_details = compute_dollar_impact(
            action["action"], action_price, total_account, window
        )
        result["analysis"]["dollar_impact"] = impact
        result["analysis"]["dollar_impact_details"] = impact_details

        # Price context
        if prices_after:
            closes_after = [p["adjclose"] for p in prices_after if p.get("adjclose")]
            if closes_after:
                result["analysis"]["price_7d_after"] = closes_after[min(4, len(closes_after)-1)]
                result["analysis"]["price_30d_after"] = closes_after[min(21, len(closes_after)-1)]
                result["analysis"]["price_90d_after"] = closes_after[-1]
                result["analysis"]["max_price_90d"] = max(closes_after)
                result["analysis"]["min_price_90d"] = min(closes_after)

    if action["action"] == "SELL":
        # Check dividend proximity
        dividends = get_dividends_for_ticker(market_data, ticker)
        div_check = check_dividend_proximity(action["date"], dividends, ticker)
        if div_check:
            # Dividend amount is in trade currency; convert to account currency
            # exchange_rate is a divisor: GBP = trade_amount / exchange_rate
            exchange_rate = action.get("exchange_rate", 1.0) or 1.0
            trade_currency = action.get("trade_currency", "")
            # GBX→GBP: divide by 100 (exchange_rate from CSV handles this,
            # but if missing, apply known conversion)
            if trade_currency == "GBX" and exchange_rate == 1.0:
                exchange_rate = 100.0
            missed_in_trade = div_check["dividend_per_share"] * action["quantity"]
            div_check["missed_amount"] = round(missed_in_trade / exchange_rate, 2)
            div_check["missed_amount_currency"] = action.get("currency", "GBP")
            result["analysis"]["dividend_proximity"] = div_check

    # Behavioral patterns
    if action["action"] == "SELL":
        panic = detect_panic_sell(action, price_dict, prices_list, spy_prices_dict)
        if panic:
            result["analysis"]["panic_sell"] = panic
        well_sell = detect_well_timed_sell(action, price_dict, prices_list)
        if well_sell:
            result["analysis"]["well_timed_sell"] = well_sell
        worst_sell = detect_worst_timed_sell(action, price_dict, prices_list)
        if worst_sell:
            result["analysis"]["worst_timed_sell"] = worst_sell

    if action["action"] == "BUY":
        if not is_dca:
            fomo = detect_fomo_buy(action, price_dict, prices_list)
            if fomo:
                result["analysis"]["fomo_buy"] = fomo
        well_buy = detect_well_timed_buy(action, price_dict, prices_list)
        if well_buy:
            result["analysis"]["well_timed_buy"] = well_buy
        if not is_dca:
            worst_buy = detect_worst_timed_buy(action, price_dict, prices_list)
            if worst_buy:
                result["analysis"]["worst_timed_buy"] = worst_buy

    if is_dca:
        result["analysis"]["is_dca"] = True

    return result


def generate_summary(analyzed_actions, round_trips, wash_sales, overtrading):
    """Generate the executive summary."""
    scored = [a for a in analyzed_actions
              if a.get("analysis") and "timing_score" in a.get("analysis", {})]
    if not scored:
        return {"message": "No scored actions available"}

    scores = [a["analysis"]["timing_score"] for a in scored]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    impacts = [a["analysis"].get("dollar_impact", 0) for a in scored]
    total_impact = round(sum(impacts), 2)

    sorted_by_score = sorted(scored, key=lambda a: a["analysis"]["timing_score"])
    worst_3 = sorted_by_score[:3]
    best_3 = sorted_by_score[-3:]

    # Count patterns
    panic_sells = sum(1 for a in analyzed_actions
                      if (a.get("analysis") or {}).get("panic_sell"))
    fomo_buys = sum(1 for a in analyzed_actions
                    if (a.get("analysis") or {}).get("fomo_buy"))
    missed_dividends = [a for a in analyzed_actions
                        if (a.get("analysis") or {}).get("dividend_proximity")]
    total_missed_div = sum(
        a["analysis"]["dividend_proximity"].get("missed_amount", 0)
        for a in missed_dividends
    )

    losing_trips = [t for t in round_trips if t["return_pct"] < 0]
    winning_trips = [t for t in round_trips if t["return_pct"] >= 0]

    # Count DCA actions
    dca_actions = sum(1 for a in analyzed_actions
                      if (a.get("analysis") or {}).get("is_dca"))

    return {
        "overall_timing_score": avg_score,
        "total_dollar_impact": total_impact,
        "total_actions_scored": len(scored),
        "best_3_actions": [{
            "ticker": a["action"]["ticker"],
            "date": a["action"]["date"],
            "action": a["action"]["action"],
            "score": a["analysis"]["timing_score"],
            "impact": a["analysis"].get("dollar_impact", 0),
        } for a in best_3],
        "worst_3_actions": [{
            "ticker": a["action"]["ticker"],
            "date": a["action"]["date"],
            "action": a["action"]["action"],
            "score": a["analysis"]["timing_score"],
            "impact": a["analysis"].get("dollar_impact", 0),
        } for a in worst_3],
        "patterns": {
            "panic_sells": panic_sells,
            "fomo_buys": fomo_buys,
            "missed_dividends": len(missed_dividends),
            "total_missed_dividend_income": round(total_missed_div, 2),
            "round_trips_total": len(round_trips),
            "round_trips_losing": len(losing_trips),
            "round_trips_winning": len(winning_trips),
            "wash_sale_candidates": len(wash_sales),
            "overtrading_tickers": len(overtrading),
            "dca_actions": dca_actions,
        },
    }


def generate_recommendations(summary, analyzed_actions, round_trips):
    """Generate actionable recommendations based on detected patterns."""
    recs = []

    # Missed dividends
    missed_divs = [a for a in analyzed_actions
                   if (a.get("analysis") or {}).get("dividend_proximity")]
    for a in missed_divs[:3]:
        dp = a["analysis"]["dividend_proximity"]
        recs.append({
            "category": "dividend_timing",
            "severity": "high" if dp["missed_amount"] > 50 else "medium",
            "example": (f"You sold {a['action']['ticker']} on {a['action']['date']}, "
                        f"just {dp['days_before_ex_date']} days before the ex-dividend date "
                        f"({dp['ex_dividend_date']}). This cost you approximately "
                        f"${dp['missed_amount']:.2f} in missed dividends."),
            "advice": ("Check ex-dividend calendars before placing sell orders. "
                       "Free resources: dividend.com, nasdaq.com/market-activity/dividends. "
                       "If you need to sell, consider waiting until after the ex-date."),
        })

    # Panic selling
    panic_actions = [a for a in analyzed_actions
                     if (a.get("analysis") or {}).get("panic_sell")]
    if panic_actions:
        recovered = [a for a in panic_actions
                     if (a.get("analysis") or {}).get("timing_score", 0) < -20]
        recs.append({
            "category": "panic_selling",
            "severity": "high" if len(panic_actions) >= 3 else "medium",
            "example": (f"You panic-sold {len(panic_actions)} time(s). "
                        f"For instance, {panic_actions[0]['action']['ticker']} on "
                        f"{panic_actions[0]['action']['date']} after a "
                        f"{panic_actions[0]['analysis']['panic_sell']['stock_decline_5d']:.1f}% "
                        f"drop in 5 days."),
            "advice": ("Implement a 48-hour cooling-off rule: when a stock drops >3% in a day, "
                       "wait 48 hours before making any sell decision. "
                       "Historically, selling into sharp drawdowns locks in losses that "
                       "would have recovered."),
        })

    # FOMO buying
    fomo_actions = [a for a in analyzed_actions
                    if (a.get("analysis") or {}).get("fomo_buy")]
    if fomo_actions:
        recs.append({
            "category": "fomo_buying",
            "severity": "high" if len(fomo_actions) >= 3 else "medium",
            "example": (f"You chased momentum {len(fomo_actions)} time(s). "
                        f"Example: bought {fomo_actions[0]['action']['ticker']} on "
                        f"{fomo_actions[0]['action']['date']} after a "
                        f"{fomo_actions[0]['analysis']['fomo_buy']['stock_gain_10d']:.1f}% "
                        f"run-up in 10 days."),
            "advice": ("Use limit orders instead of market orders after run-ups. "
                       "Set your limit price 3-5% below the current price — if the "
                       "stock comes back to you, great. If not, you avoided overpaying. "
                       "Consider dollar-cost averaging into positions over 2-4 weeks."),
        })

    # Round-trip losses
    losing_trips = [t for t in round_trips if t["return_pct"] < 0]
    if losing_trips:
        worst = min(losing_trips, key=lambda t: t["dollar_return"])
        total_loss = sum(t["dollar_return"] for t in losing_trips)
        recs.append({
            "category": "round_trip_losses",
            "severity": "high" if abs(total_loss) > 1000 else "medium",
            "example": (f"You had {len(losing_trips)} losing round-trips. "
                        f"Worst: {worst['ticker']} bought {worst['buy_date']} at "
                        f"${worst['buy_price']:.2f}, sold {worst['sell_date']} at "
                        f"${worst['sell_price']:.2f} "
                        f"({worst['return_pct']:.1f}%, ${worst['dollar_return']:.2f})."),
            "advice": ("Before selling at a loss, ask: 'Has the thesis changed, or am I "
                       "reacting to price?' If the thesis hasn't changed and the fundamentals "
                       "are intact, consider holding. Set stop-losses at purchase time, "
                       "not reactively."),
        })

    # Good patterns to reinforce
    good_actions = [a for a in analyzed_actions
                    if (a.get("analysis") or {}).get("timing_score", 0) > 40]
    if good_actions:
        best = max(good_actions, key=lambda a: a["analysis"]["timing_score"])
        recs.append({
            "category": "positive_reinforcement",
            "severity": "positive",
            "example": (f"Great timing on {best['action']['ticker']} "
                        f"({best['action']['action']} on {best['action']['date']}): "
                        f"timing score of {best['analysis']['timing_score']}."),
            "advice": "Keep doing what worked here. This shows good discipline and patience.",
        })

    return recs


def run_analysis(parsed_path, market_path, output_path):
    """Main analysis function."""
    parsed, market_data = load_data(parsed_path, market_path)
    actions = parsed["actions"]

    spy_price_dict, _ = get_spy_prices(market_data)

    print(f"Analyzing {len(actions)} actions...")

    # --- Split multi-exchange tickers ---
    # Same ticker traded in different currencies → separate positions
    n_multi = split_multi_exchange_tickers(actions)
    if n_multi:
        print(f"  Split {n_multi} actions across multiple exchanges")

    # --- Apply stock split adjustments ---
    # Yahoo Finance returns split-adjusted prices; CSV has pre-split values.
    # Adjust quantities and prices so they match Yahoo's basis.
    print("\nApplying stock split adjustments...")
    n_split_adjusted = apply_split_adjustments(actions, market_data)
    print(f"  Adjusted {n_split_adjusted} actions for stock splits")

    # --- Portfolio tracking pass (chronological) ---
    tracker = PortfolioTracker()
    for action in actions:
        tracker.process(action)

    portfolio = tracker.get_portfolio_summary(market_data)

    print(f"\n=== Portfolio Overview ===")
    print(f"  Net invested:      £{portfolio['net_invested_gbp']:,.2f}")
    print(f"  Current value:     £{portfolio['current_portfolio_value_gbp']:,.2f}")
    print(f"  Realized P&L:      £{portfolio['realized_pnl_gbp']:,.2f}")
    print(f"  Unrealized P&L:    £{portfolio['total_unrealized_pnl_gbp']:,.2f}")
    print(f"  Dividends:         £{portfolio['total_dividends_gbp']:,.2f}")
    print(f"  Interest:          £{portfolio['total_interest_gbp']:,.2f}")
    print(f"  Fees:              £{portfolio['total_fees_gbp']:,.2f}")
    print(f"  Total return:      £{portfolio['total_return_gbp']:,.2f} ({portfolio['total_return_pct']:+.2f}%)")
    print(f"  Holdings:          {portfolio['num_holdings']} tickers")

    # Build avg cost lookup for sell analysis
    # {ticker: avg_cost_per_share_gbp at time of each sell}
    sell_cost_lookup = {}
    for sd in tracker.sell_details:
        key = (sd["ticker"], sd["date"])
        sell_cost_lookup[key] = sd

    # --- DCA detection (before per-action loop) ---
    print("\nDetecting DCA sequences...")
    dca_result = detect_dca_sequences(actions, market_data)
    dca_action_keys = dca_result["dca_action_keys"]
    print(f"  Found {len(dca_result['sequences'])} DCA sequences, "
          f"{len(dca_action_keys)} actions flagged as DCA")

    # --- Benchmark comparison ---
    print("\nComputing benchmark comparison (vs SPY)...")
    benchmark = compute_benchmark_comparison(tracker, actions, market_data)
    if benchmark:
        print(f"  Portfolio TWR: {benchmark['portfolio_twr_pct']:+.2f}%")
        print(f"  SPY return:    {benchmark['spy_buy_hold_return_pct']:+.2f}%")
        print(f"  Alpha:         {benchmark['alpha_pct']:+.2f}%")

    # --- Risk metrics ---
    print("\nComputing risk-adjusted return metrics...")
    risk_metrics = compute_risk_metrics(tracker, actions, market_data)
    if risk_metrics:
        print(f"  Volatility:    {risk_metrics['annualized_volatility_pct']:.1f}%")
        print(f"  Sharpe Ratio:  {risk_metrics['sharpe_ratio']:.2f}")
        print(f"  Sortino Ratio: {risk_metrics['sortino_ratio']:.2f}")
        print(f"  Max Drawdown:  {risk_metrics['max_drawdown_pct']:.1f}%")

    # --- Per-action timing analysis ---
    analyzed = []
    for i, action in enumerate(actions):
        if action["action"] in ("BUY", "SELL", "DIVIDEND"):
            is_dca = (action.get("ticker"), action.get("date")) in dca_action_keys
            result = analyze_action(action, market_data, spy_price_dict, is_dca=is_dca)
            # Enrich sell analysis with avg cost basis data
            if action["action"] == "SELL" and result.get("analysis"):
                key = (action["ticker"], action["date"])
                sd = sell_cost_lookup.get(key)
                if sd:
                    result["analysis"]["avg_cost_gbp"] = sd["avg_cost_per_share_gbp"]
                    result["analysis"]["cost_of_sold_gbp"] = sd["cost_of_sold_gbp"]
                    result["analysis"]["realized_pnl_gbp"] = sd["realized_pnl_gbp"]
            analyzed.append(result)
            if result.get("analysis") and "timing_score" in result.get("analysis", {}):
                score = result["analysis"]["timing_score"]
                label = "good" if score > 20 else ("poor" if score < -20 else "neutral")
                print(f"  [{i+1}] {action['action']} {action['ticker']} "
                      f"{action['date']}: score={score} ({label})")
        else:
            analyzed.append({"action": action, "analysis": None, "reason": "non_trade_action"})

    # Cross-action pattern detection
    trade_actions = [a for a in actions if a["action"] in ("BUY", "SELL")]
    round_trips = detect_round_trips(trade_actions)
    wash_sales = detect_wash_sales(trade_actions)
    overtrading = detect_overtrading(trade_actions)

    print(f"\nRound trips found: {len(round_trips)}")
    print(f"Wash sale candidates: {len(wash_sales)}")
    print(f"Overtrading flags: {len(overtrading)}")

    # Generate summary and recommendations
    summary = generate_summary(analyzed, round_trips, wash_sales, overtrading)
    recommendations = generate_recommendations(summary, analyzed, round_trips)

    output = {
        "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "portfolio": portfolio,
        "summary": summary,
        "analyzed_actions": analyzed,
        "round_trips": round_trips,
        "wash_sales": wash_sales,
        "overtrading": overtrading,
        "recommendations": recommendations,
        "dca_sequences": dca_result["sequences"],
        "benchmark": benchmark,
        "risk_metrics": risk_metrics,
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nAnalysis complete. Output saved to: {output_path}")
    print(f"Overall timing score: {summary.get('overall_timing_score', 'N/A')}")
    print(f"Total impact: £{summary.get('total_dollar_impact', 0):.2f}")
    print(f"Recommendations generated: {len(recommendations)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze portfolio actions against market data")
    parser.add_argument("parsed", help="Path to parsed_actions.json")
    parser.add_argument("market", help="Path to market_data.json")
    parser.add_argument("--output", "-o", default="./analysis_results.json",
                        help="Output JSON path")
    args = parser.parse_args()
    run_analysis(args.parsed, args.market, args.output)
