#!/usr/bin/env python3
"""
Parse portfolio CSV files from various brokerages into a normalized JSON format.
Handles: Schwab, Fidelity, Vanguard, E*TRADE, Robinhood, Interactive Brokers, and generic CSVs.
"""

import csv
import json
import os
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Column name mappings (lowercase for matching)
COLUMN_MAP = {
    "date": ["date", "time", "trade date", "transaction date", "settlement date", "run date",
             "process date", "activity date", "transactiondate", "date/time", "datetime"],
    "action": ["action", "type", "transaction type", "activity type", "trans type",
               "trans code", "transaction description", "description", "transactiontype"],
    "ticker": ["symbol", "ticker", "stock", "instrument", "security", "cusip", "name",
               "investment name"],
    "quantity": ["quantity", "shares", "qty", "units", "number of shares", "no. of shares"],
    "price": ["price", "trade price", "execution price", "price ($)", "unit price",
              "cost basis per share", "share price", "price / share"],
    "total": ["amount", "total", "net amount", "principal", "cost", "proceeds", "value",
              "net proceeds", "amount ($)", "principal amount", "net cash"],
    "fees": ["commission", "fee", "fees", "transaction fee", "commission ($)", "sec fee",
             "fees & comm", "commission fees", "fees ($)"],
    "notes": ["description", "notes", "memo", "comment", "details",
              "transaction description"],
    "account": ["account", "account number", "account name", "account #"],
    "currency": ["currency (total)", "currency", "currency code"],
    "trade_currency": ["currency (price / share)"],
    "isin": ["isin"],
    "exchange_rate": ["exchange rate"],
}

# Action normalization
ACTION_MAP = {
    "BUY": ["buy", "bought", "purchase", "buy to open", "bto", "reinvestment", "reinvest",
            "automatic investment", "you bought", "bot", "buy to cover", "market buy"],
    "SELL": ["sell", "sold", "sell to close", "stc", "redemption", "you sold", "sld",
             "market sell"],
    "DIVIDEND": ["dividend", "div", "cash dividend", "qualified dividend",
                 "non-qualified dividend", "ordinary dividend", "ltcg distribution",
                 "stcg distribution", "capital gain", "return of capital", "cdiv",
                 "reinvested dividend", "dividend received"],
    "INTEREST": ["interest", "int", "interest earned", "interest income", "bond interest",
                 "bank interest", "credit interest", "interest on cash"],
    "DEPOSIT": ["deposit", "transfer in", "wire in", "ach in", "electronic transfer",
                "contribution", "client requested electronic funding receipt",
                "electronic funds transfer received", "moneylink transfer"],
    "WITHDRAWAL": ["withdrawal", "withdraw", "transfer out", "wire out", "ach out",
                   "distribution", "electronic funds transfer paid"],
    "FEE": ["fee", "advisory fee", "management fee", "service fee", "account fee",
            "margin interest"],
    "SPLIT": ["split", "stock split", "forward split", "reverse split"],
    "TRANSFER": ["transfer", "journal", "internal transfer", "acat"],
}

DATE_FORMATS = [
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y%m%d",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d, %H:%M:%S",
]


def clean_numeric(val):
    """Strip currency symbols, commas, parens (negative), and convert to float."""
    if val is None or str(val).strip() == "" or str(val).strip() == "--":
        return 0.0
    s = str(val).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = re.sub(r'[£€$,]', '', s)
    s = s.strip()
    if not s:
        return 0.0
    try:
        result = float(s)
        return -result if negative else result
    except ValueError:
        return 0.0


def parse_date(val):
    """Try multiple date formats and return YYYY-MM-DD string."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Strip "as of MM/DD/YYYY" suffixes
    s = re.sub(r'\s+as of.*$', '', s, flags=re.IGNORECASE)
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_action(raw_action, description=""):
    """Map a raw action string to a standard action type."""
    if not raw_action:
        raw_action = ""
    combined = f"{raw_action} {description}".lower().strip()
    for standard, variants in ACTION_MAP.items():
        for v in variants:
            if v in combined:
                return standard
    return "OTHER"


def map_columns(headers):
    """Map CSV headers to standard field names."""
    mapping = {}
    headers_lower = [h.lower().strip() for h in headers]
    for standard_field, aliases in COLUMN_MAP.items():
        for alias in aliases:
            for i, h in enumerate(headers_lower):
                if h == alias and i not in mapping.values():
                    # Avoid mapping 'description' to action if we already have action
                    if standard_field == "action" and alias == "description":
                        if any(headers_lower[j] in COLUMN_MAP["action"][:6]
                               for j in range(len(headers_lower))
                               if j not in mapping.values()):
                            continue
                    mapping[standard_field] = i
                    break
            if standard_field in mapping:
                break
    return mapping


def find_header_row(rows):
    """Find the row that looks like a header (most string-like non-empty cells)."""
    best_idx = 0
    best_score = 0
    for i, row in enumerate(rows[:20]):  # Check first 20 rows
        if not row:
            continue
        non_empty = [c for c in row if str(c).strip()]
        if len(non_empty) < 2:
            continue
        # Score: more non-numeric, non-empty cells = more likely a header
        score = sum(1 for c in non_empty if not re.match(r'^[\d$€£,.\-()]+$', str(c).strip()))
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def parse_single_csv(filepath):
    """Parse a single CSV file and return normalized actions."""
    actions = []
    with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
        # Read all rows
        content = f.read()

    # Handle potential TSV
    if '\t' in content and ',' not in content.split('\n')[0]:
        delimiter = '\t'
    else:
        delimiter = ','

    rows = list(csv.reader(content.splitlines(), delimiter=delimiter))
    if not rows:
        return actions

    # Find header row
    header_idx = find_header_row(rows)
    headers = rows[header_idx]
    col_map = map_columns(headers)

    if "date" not in col_map:
        print(f"  Warning: No date column found in {filepath}, skipping.")
        return actions

    for row_idx, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not row or all(not str(c).strip() for c in row):
            continue

        # Extract fields using column mapping
        def get_field(name):
            if name in col_map and col_map[name] < len(row):
                return row[col_map[name]]
            return None

        date_str = parse_date(get_field("date"))
        if not date_str:
            continue

        raw_action = get_field("action") or ""
        description = get_field("notes") or ""
        action = normalize_action(raw_action, description)

        ticker = get_field("ticker") or ""
        ticker = ticker.strip().upper()
        # Clean ticker (remove exchange suffixes sometimes present)
        ticker = re.sub(r'\s+.*$', '', ticker)

        quantity = clean_numeric(get_field("quantity"))  # keep full precision for fractional shares
        price = clean_numeric(get_field("price"))          # share price in trade currency
        total = clean_numeric(get_field("total"))          # total in account currency (GBP)
        fees = abs(clean_numeric(get_field("fees")))

        # Skip rows that seem like summaries or notes
        if not ticker and action == "OTHER" and not total:
            continue

        # Currency (Total) = account currency (e.g. GBP)
        currency = (get_field("currency") or "").strip().upper()
        # Currency (Price / share) = trade currency (for Yahoo Finance ticker resolution)
        trade_currency = (get_field("trade_currency") or currency or "").strip().upper()
        isin = (get_field("isin") or "").strip().upper()
        exchange_rate = clean_numeric(get_field("exchange_rate")) or 1.0

        actions.append({
            "date": date_str,
            "action": action,
            "ticker": ticker,
            "quantity": abs(quantity),
            "price": abs(price),
            "total": abs(total) if action in ("BUY", "SELL") else total,
            "fees": fees,
            "currency": currency,
            "trade_currency": trade_currency,
            "exchange_rate": exchange_rate,
            "isin": isin,
            "notes": f"{raw_action} - {description}".strip(" -"),
            "source_file": os.path.basename(filepath),
            "source_row": row_idx,
        })

    return actions


def parse_csvs(input_path, output_path):
    """Parse all CSVs in a directory or a single CSV file."""
    input_path = Path(input_path)
    all_actions = []

    if input_path.is_file():
        csv_files = [input_path]
    elif input_path.is_dir():
        csv_files = sorted(
            list(input_path.glob("*.csv")) +
            list(input_path.glob("*.CSV")) +
            list(input_path.glob("*.tsv")) +
            list(input_path.glob("*.TSV"))
        )
    else:
        print(f"Error: {input_path} not found")
        sys.exit(1)

    if not csv_files:
        print(f"No CSV/TSV files found in {input_path}")
        sys.exit(1)

    for csv_file in csv_files:
        print(f"Parsing: {csv_file.name}")
        try:
            actions = parse_single_csv(str(csv_file))
            print(f"  Found {len(actions)} actions")
            all_actions.extend(actions)
        except Exception as e:
            print(f"  Error parsing {csv_file.name}: {e}")

    # Sort by date
    all_actions.sort(key=lambda a: a["date"])

    # Summary
    action_counts = {}
    tickers = set()
    for a in all_actions:
        action_counts[a["action"]] = action_counts.get(a["action"], 0) + 1
        if a["ticker"]:
            tickers.add(a["ticker"])

    summary = {
        "total_actions": len(all_actions),
        "date_range": {
            "start": all_actions[0]["date"] if all_actions else None,
            "end": all_actions[-1]["date"] if all_actions else None,
        },
        "action_counts": action_counts,
        "unique_tickers": sorted(list(tickers)),
        "ticker_count": len(tickers),
    }

    output = {
        "summary": summary,
        "actions": all_actions,
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nSummary:")
    print(f"  Total actions: {summary['total_actions']}")
    print(f"  Date range: {summary['date_range']['start']} to {summary['date_range']['end']}")
    print(f"  Unique tickers: {summary['ticker_count']}")
    print(f"  Action breakdown: {json.dumps(action_counts, indent=4)}")
    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse portfolio CSV files")
    parser.add_argument("input", help="Path to CSV file or directory of CSVs")
    parser.add_argument("--output", "-o", default="./parsed_actions.json",
                        help="Output JSON path")
    args = parser.parse_args()
    parse_csvs(args.input, args.output)
