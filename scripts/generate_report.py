#!/usr/bin/env python3
"""
Generate a comprehensive HTML report from portfolio analysis results.
Produces a self-contained, styled HTML file with all findings.
"""

import json
import sys
import argparse
from datetime import datetime


def score_color(score):
    """Return a CSS color based on timing score."""
    if score >= 40:
        return "#16a34a"  # green
    elif score >= 10:
        return "#65a30d"  # lime
    elif score >= -10:
        return "#9ca3af"  # gray
    elif score >= -40:
        return "#ea580c"  # orange
    else:
        return "#dc2626"  # red


def score_label(score):
    if score >= 80:
        return "Excellent"
    elif score >= 40:
        return "Good"
    elif score >= 10:
        return "Neutral+"
    elif score >= -10:
        return "Flat"
    elif score >= -40:
        return "Poor"
    elif score >= -80:
        return "Bad"
    else:
        return "Terrible"


def score_emoji(score):
    if score >= 40:
        return "✅"
    elif score >= -10:
        return "➖"
    elif score >= -40:
        return "⚠️"
    else:
        return "🔴"


def severity_badge(severity):
    colors = {
        "high": ("bg: #fef2f2; color: #dc2626; border: 1px solid #fecaca",),
        "medium": ("bg: #fffbeb; color: #d97706; border: 1px solid #fde68a",),
        "low": ("bg: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0",),
        "positive": ("bg: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0",),
    }
    style_str = {
        "high": "background:#fef2f2;color:#dc2626;border:1px solid #fecaca",
        "medium": "background:#fffbeb;color:#d97706;border:1px solid #fde68a",
        "low": "background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0",
        "positive": "background:#ecfdf5;color:#059669;border:1px solid #a7f3d0",
    }
    style = style_str.get(severity, style_str["medium"])
    label = severity.upper() if severity != "positive" else "👍 GOOD"
    return f'<span class="badge" style="{style}">{label}</span>'


def format_dollar(val):
    if val >= 0:
        return f'<span style="color:#16a34a">+£{val:,.2f}</span>'
    else:
        return f'<span style="color:#dc2626">-£{abs(val):,.2f}</span>'


def generate_report(analysis_path, output_path):
    """Generate the HTML report."""
    with open(analysis_path, 'r') as f:
        data = json.load(f)

    summary = data.get("summary", {})
    portfolio = data.get("portfolio", {})
    analyzed = data.get("analyzed_actions", [])
    round_trips = data.get("round_trips", [])
    wash_sales = data.get("wash_sales", [])
    overtrading = data.get("overtrading", [])
    recommendations = data.get("recommendations", [])

    dca_sequences = data.get("dca_sequences", [])
    benchmark = data.get("benchmark")
    risk_metrics = data.get("risk_metrics")

    scored_actions = [a for a in analyzed
                      if a.get("analysis") and "timing_score" in a.get("analysis", {})]
    scored_actions.sort(key=lambda a: a["analysis"]["timing_score"])

    # Determine which sections exist for TOC
    panic_sells = [a for a in analyzed
                   if (a.get("analysis") or {}).get("panic_sell")]
    fomo_buys = [a for a in analyzed
                 if (a.get("analysis") or {}).get("fomo_buy")]
    well_sells = [a for a in analyzed
                  if (a.get("analysis") or {}).get("well_timed_sell")]
    well_buys = [a for a in analyzed
                 if (a.get("analysis") or {}).get("well_timed_buy")]
    worst_sells = [a for a in analyzed
                   if (a.get("analysis") or {}).get("worst_timed_sell")]
    worst_buys = [a for a in analyzed
                  if (a.get("analysis") or {}).get("worst_timed_buy")]
    missed_divs = [a for a in analyzed
                   if (a.get("analysis") or {}).get("dividend_proximity")]

    toc_items = []
    toc_items.append(("roast", "The Roast"))
    toc_items.append(("executive-summary", "Executive Summary"))
    if portfolio:
        toc_items.append(("portfolio-overview", "Portfolio Overview"))
    if dca_sequences:
        toc_items.append(("dca-strategies", f"DCA Strategies ({len(dca_sequences)})"))
    if benchmark:
        toc_items.append(("benchmark", "Benchmark vs SPY"))
    if risk_metrics:
        toc_items.append(("risk-metrics", "Risk-Adjusted Returns"))
    toc_items.append(("best-worst-timing", "Best & Worst Timing"))
    if well_sells:
        toc_items.append(("best-sells", f"Best Timed Sells ({len(well_sells)})"))
    if well_buys:
        toc_items.append(("best-buys", f"Best Timed Buys ({len(well_buys)})"))
    if worst_sells:
        toc_items.append(("worst-sells", f"Worst Timed Sells ({len(worst_sells)})"))
    if worst_buys:
        toc_items.append(("worst-buys", f"Worst Timed Buys ({len(worst_buys)})"))
    if panic_sells:
        toc_items.append(("panic-sells", f"Panic Sells ({len(panic_sells)})"))
    if fomo_buys:
        toc_items.append(("fomo-buys", f"FOMO Buys ({len(fomo_buys)})"))
    toc_items.append(("all-actions", "All Scored Actions"))
    if round_trips:
        toc_items.append(("round-trips", f"Round-Trip Trades ({len(round_trips)})"))
    if missed_divs:
        toc_items.append(("dividend-timing", f"Dividend Timing ({len(missed_divs)})"))
    if wash_sales:
        toc_items.append(("wash-sales", f"Wash Sales ({len(wash_sales)})"))
    if recommendations:
        toc_items.append(("recommendations", "Recommendations"))

    toc_links = "\n".join(
        f'    <a href="#{sid}" class="toc-link" data-section="{sid}">{label}</a>'
        for sid, label in toc_items
    )

    # Build HTML
    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Action Analysis Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; scroll-padding-top: 1rem; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8fafc; color: #1e293b; line-height: 1.6;
    padding: 2rem; padding-left: 2rem; max-width: 1100px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.8rem; color: #0f172a; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.4rem; color: #1e293b; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid #e2e8f0; }}
  h3 {{ font-size: 1.1rem; color: #334155; margin: 1.5rem 0 0.75rem; }}
  .subtitle {{ color: #64748b; font-size: 0.95rem; margin-bottom: 2rem; }}
  .disclaimer {{
    background: #fefce8; border: 1px solid #fde047; border-radius: 8px;
    padding: 0.75rem 1rem; margin-bottom: 2rem; font-size: 0.85rem; color: #854d0e;
  }}

  /* Floating TOC */
  .toc {{
    position: fixed; top: 1rem; left: 1rem;
    width: 210px; max-height: calc(100vh - 2rem);
    overflow-y: auto; background: #fff;
    border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 0.75rem 0; box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    z-index: 1000; font-size: 0.8rem;
    transition: transform 0.2s ease, opacity 0.2s ease;
  }}
  .toc-header {{
    padding: 0.25rem 1rem 0.5rem; font-weight: 700; color: #0f172a;
    font-size: 0.85rem; border-bottom: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .toc-toggle {{
    display: none; position: fixed; top: 1rem; left: 1rem;
    z-index: 1001; background: #fff; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 0.4rem 0.7rem; cursor: pointer;
    font-size: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }}
  .toc-close {{
    cursor: pointer; font-size: 1.1rem; color: #94a3b8;
    display: none; line-height: 1;
  }}
  .toc-close:hover {{ color: #475569; }}
  .toc-link {{
    display: block; padding: 0.3rem 1rem; color: #475569;
    text-decoration: none; border-left: 3px solid transparent;
    transition: all 0.15s ease;
  }}
  .toc-link:hover {{ background: #f1f5f9; color: #1e293b; }}
  .toc-link.active {{
    border-left-color: #3b82f6; color: #1e40af;
    background: #eff6ff; font-weight: 600;
  }}
  .toc::-webkit-scrollbar {{ width: 4px; }}
  .toc::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 4px; }}

  /* Shift main content when TOC is visible */
  @media (min-width: 1400px) {{
    body {{ margin-left: 240px; }}
  }}
  @media (max-width: 1399px) {{
    .toc {{ transform: translateX(-120%); opacity: 0; }}
    .toc.open {{ transform: translateX(0); opacity: 1; }}
    .toc-toggle {{ display: block; }}
    .toc-close {{ display: block; }}
  }}

  /* Cards */
  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 1.25rem 1.5rem; margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }}
  .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }}
  .stat-card {{ text-align: center; }}
  .stat-value {{ font-size: 2rem; font-weight: 700; }}
  .stat-label {{ font-size: 0.85rem; color: #64748b; }}

  /* Score bar */
  .score-bar {{
    display: inline-flex; align-items: center; gap: 0.5rem;
    padding: 0.25rem 0.75rem; border-radius: 999px; font-weight: 600;
    font-size: 0.9rem; color: #fff;
  }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
  th {{ background: #f1f5f9; text-align: left; padding: 0.6rem 0.75rem; font-weight: 600; color: #475569; border-bottom: 2px solid #e2e8f0; }}
  td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid #f1f5f9; }}
  tr:hover {{ background: #f8fafc; }}

  /* Badge */
  .badge {{
    display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
    font-size: 0.75rem; font-weight: 600;
  }}

  /* Recommendation */
  .rec-card {{
    background: #fff; border-left: 4px solid #3b82f6; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }}
  .rec-card.high {{ border-left-color: #dc2626; }}
  .rec-card.medium {{ border-left-color: #f59e0b; }}
  .rec-card.positive {{ border-left-color: #16a34a; }}
  .rec-example {{ color: #475569; margin: 0.5rem 0; font-size: 0.9rem; }}
  .rec-advice {{
    background: #f0f9ff; border-radius: 6px; padding: 0.75rem;
    margin-top: 0.5rem; font-size: 0.9rem; color: #1e40af;
  }}

  /* Footer */
  .footer {{ margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 0.8rem; text-align: center; }}
</style>
</head>
<body>

<!-- Floating TOC toggle (visible on smaller screens) -->
<button class="toc-toggle" onclick="document.querySelector('.toc').classList.toggle('open')" title="Table of Contents">☰</button>

<!-- Floating Table of Contents -->
<nav class="toc" id="toc">
  <div class="toc-header">
    Contents
    <span class="toc-close" onclick="this.closest('.toc').classList.remove('open')">✕</span>
  </div>
{toc_links}
</nav>

<h1>📊 Portfolio Action Analysis Report</h1>
<p class="subtitle">Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')} &middot;
Covering {summary.get('total_actions_scored', 0)} scored actions</p>
<div class="disclaimer">
⚠️ <strong>Disclaimer:</strong> This is an educational analysis based on historical data, not investment advice.
Hindsight analysis is inherently biased — nobody can perfectly time the market. Past performance does not
indicate future results. Consult a licensed financial advisor for investment decisions.
</div>
""")

    # === THE ROAST ===
    avg_score = summary.get("overall_timing_score", 0)
    total_impact = summary.get("total_dollar_impact", 0)
    patterns = summary.get("patterns", {})
    total_return_pct = portfolio.get("total_return_pct", 0) if portfolio else 0
    n_panic = patterns.get("panic_sells", 0)
    n_fomo = patterns.get("fomo_buys", 0)
    n_worst_sells = len(worst_sells)
    n_worst_buys = len(worst_buys)
    n_wash = patterns.get("wash_sale_candidates", 0)
    n_losing_trips = patterns.get("round_trips_losing", 0)

    roast_lines = []
    roast_lines.append("Let's be honest about what happened here.")

    # Overall score roast
    if avg_score < -30:
        roast_lines.append(f"Your overall timing score is <strong>{avg_score:+.1f}</strong>. A literal coin flip would have done better. Actually, a coin flip would have scored around 0 — you somehow managed to consistently pick the wrong moments.")
    elif avg_score < -10:
        roast_lines.append(f"Your timing score of <strong>{avg_score:+.1f}</strong> suggests you have a remarkable talent for buying high and selling low. Most people do this accidentally — you seem to have made it a strategy.")
    elif avg_score < 10:
        roast_lines.append(f"Your timing score of <strong>{avg_score:+.1f}</strong> is aggressively mediocre. Not bad enough to be impressive, not good enough to brag about. You're the human equivalent of a market-hours random number generator.")
    else:
        roast_lines.append(f"Your timing score of <strong>{avg_score:+.1f}</strong> is... actually decent? This is awkward. The roast section was supposed to be mean. Fine — let's find what you messed up.")

    # Impact roast
    if total_impact < -1000:
        roast_lines.append(f"Your timing decisions cost you approximately <strong>£{abs(total_impact):,.0f}</strong> vs optimal timing. That's real money you left on the table — enough for {'a nice holiday' if abs(total_impact) < 5000 else 'a very nice car' if abs(total_impact) < 50000 else 'a house deposit'}.")

    # Panic sell roast
    if n_panic >= 5:
        roast_lines.append(f"You panic-sold <strong>{n_panic} times</strong>. Every time your stocks had a bad week, you apparently screamed 'SELL EVERYTHING' at your phone like it personally betrayed you. Spoiler: most of them recovered.")
    elif n_panic >= 2:
        roast_lines.append(f"You panic-sold <strong>{n_panic} times</strong>. The market dipped, you panicked, and your portfolio suffered for it. Have you considered putting your phone in a drawer when stocks go red?")

    # FOMO roast
    if n_fomo >= 5:
        roast_lines.append(f"You FOMO-bought <strong>{n_fomo} times</strong> — chasing stocks that had already run up 10%+. You basically showed up to the party after everyone left and wondered why the music stopped.")
    elif n_fomo >= 2:
        roast_lines.append(f"You chased momentum <strong>{n_fomo} times</strong>. Buying after a 10%+ rally is like paying full price for something that was on sale last week — except the 'sale' is still coming.")

    # Worst buys roast
    if n_worst_buys >= 20:
        roast_lines.append(f"You made <strong>{n_worst_buys} buys</strong> that immediately dropped 10%+ afterward. At this point, hedge funds should pay you to tell them what you're buying — so they can short it.")
    elif n_worst_buys >= 5:
        roast_lines.append(f"<strong>{n_worst_buys} of your buys</strong> were followed by a 10%+ drop. Your buy button seems to double as a 'crash incoming' signal for the market.")

    # Worst sells roast
    if n_worst_sells >= 20:
        roast_lines.append(f"You sold <strong>{n_worst_sells} times</strong> right before the stock rallied 10%+. You don't just sell low — you sell at surgically precise bottoms. It's almost a talent.")
    elif n_worst_sells >= 5:
        roast_lines.append(f"<strong>{n_worst_sells} of your sells</strong> were immediately followed by a 10%+ rally. The stocks literally waited for you to leave before going up. Coincidence? The data says no.")

    # Wash sales roast
    if n_wash >= 10:
        roast_lines.append(f"You have <strong>{n_wash} potential wash sales</strong>. That's selling at a loss and buying the same thing back within 30 days — {n_wash} times. You're basically paying transaction fees to do nothing.")

    # Losing round trips
    if n_losing_trips >= 10:
        roast_lines.append(f"You had <strong>{n_losing_trips} losing round-trip trades</strong>. Buy, lose money, sell. Rinse and repeat. You turned trading into a very inefficient way to make your broker rich.")

    # DCA compliment (positive — disciplined investing)
    n_dca = patterns.get("dca_actions", 0)
    if n_dca >= 20:
        roast_lines.append(f"OK, credit where it's due: <strong>{n_dca} of your buys</strong> were part of disciplined DCA sequences. Automated investing is the one thing you're doing right. The machines are better at this than you — and you were smart enough to let them.")
    elif n_dca >= 5:
        roast_lines.append(f"At least <strong>{n_dca} of your buys</strong> were automated DCA. Good — the less you touch the buy button manually, the better your returns seem to get. Coincidence? Absolutely not.")

    # Benchmark roast
    if benchmark:
        alpha = benchmark.get("alpha_pct", 0)
        if alpha < -10:
            roast_lines.append(f"Your portfolio underperformed SPY by <strong>{abs(alpha):.1f}%</strong>. You spent all that time researching stocks, stressing about earnings, and panic-selling during dips... and you would have done better buying one ETF and forgetting your password.")
        elif alpha < 0:
            roast_lines.append(f"You trailed SPY by <strong>{abs(alpha):.1f}%</strong>. Not catastrophic, but every hedge fund manager who underperforms the S&P 500 gets fired. Just saying.")
        elif alpha > 10:
            roast_lines.append(f"You beat SPY by <strong>{alpha:.1f}%</strong>. Either you're genuinely skilled, or you're about to learn about survivorship bias and mean reversion the hard way.")

    # Sharpe roast
    if risk_metrics:
        sharpe = risk_metrics.get("sharpe_ratio", 0)
        if sharpe < 0:
            roast_lines.append(f"Your Sharpe ratio is <strong>{sharpe:.2f}</strong>. That's negative. You literally took on risk to LOSE money. A savings account at 4.5% would have been less stressful and more profitable.")
        elif sharpe < 0.5:
            roast_lines.append(f"Your Sharpe ratio is <strong>{sharpe:.2f}</strong>. For context, anything below 1.0 means you're not being adequately compensated for the risk you're taking. You're essentially volunteering for stress.")

    # Overall return
    if total_return_pct > 15:
        roast_lines.append(f"Despite all of this chaos, you somehow made <strong>{total_return_pct:+.1f}%</strong> overall. Imagine what you'd have if you just bought an index fund and touched grass instead.")
    elif total_return_pct > 0:
        roast_lines.append(f"Your total return is <strong>{total_return_pct:+.1f}%</strong>. Positive, technically. A savings account would be jealous. Actually no, a savings account at 5% might not be.")
    else:
        roast_lines.append(f"Your total return is <strong>{total_return_pct:+.1f}%</strong>. You would have literally made more money hiding cash under your mattress. At least the mattress doesn't charge transaction fees.")

    roast_html = "</p><p>".join(roast_lines)
    html_parts.append(f"""
<h2 id="roast">The Roast</h2>
<div class="card" style="border-left:4px solid #f97316; background:linear-gradient(135deg, #fff7ed 0%, #fff 100%)">
  <p style="font-size:1.5rem;margin-bottom:0.75rem">You asked for this.</p>
  <p>{roast_html}</p>
  <p style="margin-top:1rem;font-size:0.85rem;color:#9ca3af;font-style:italic">This roast is based entirely on your actual trading data. Every number is real. We're not making this up — you did this to yourself.</p>
</div>
""")

    # === EXECUTIVE SUMMARY ===

    html_parts.append(f"""
<h2 id="executive-summary">Executive Summary</h2>
<div class="card-grid">
  <div class="card stat-card">
    <div class="stat-value" style="color:{score_color(avg_score)}">{avg_score:+.1f}</div>
    <div class="stat-label">Overall Timing Score<br>({score_label(avg_score)})</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{format_dollar(total_impact)}</div>
    <div class="stat-label">Estimated Dollar Impact<br>(vs optimal timing)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{summary.get('total_actions_scored', 0)}</div>
    <div class="stat-label">Actions Analyzed</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{len(round_trips)}</div>
    <div class="stat-label">Round-Trip Trades<br>({patterns.get('round_trips_winning', 0)} won, {patterns.get('round_trips_losing', 0)} lost)</div>
  </div>
</div>

<div class="card-grid" style="margin-top:1rem">
  <div class="card stat-card">
    <div class="stat-value" style="color:#dc2626">{patterns.get('panic_sells', 0)}</div>
    <div class="stat-label">Panic Sells Detected</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#ea580c">{patterns.get('fomo_buys', 0)}</div>
    <div class="stat-label">FOMO Buys Detected</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#dc2626">{patterns.get('missed_dividends', 0)}</div>
    <div class="stat-label">Missed Dividends<br>(£{patterns.get('total_missed_dividend_income', 0):.2f} total)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#f59e0b">{patterns.get('wash_sale_candidates', 0)}</div>
    <div class="stat-label">Wash Sale Candidates</div>
  </div>
</div>
""")

    # === PORTFOLIO OVERVIEW ===
    if portfolio:
        total_return = portfolio.get("total_return_gbp", 0)
        total_return_pct = portfolio.get("total_return_pct", 0)
        ret_color = "#16a34a" if total_return >= 0 else "#dc2626"
        html_parts.append(f"""
<h2 id="portfolio-overview">Portfolio Overview</h2>
<div class="card-grid">
  <div class="card stat-card">
    <div class="stat-value">£{portfolio.get('net_invested_gbp', 0):,.2f}</div>
    <div class="stat-label">Net Invested<br>(deposits - withdrawals)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">£{portfolio.get('current_portfolio_value_gbp', 0):,.2f}</div>
    <div class="stat-label">Current Portfolio Value</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:{ret_color}">£{total_return:,.2f}</div>
    <div class="stat-label">Total Return<br>(<span style="color:{ret_color}">{total_return_pct:+.2f}%</span>)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{portfolio.get('num_holdings', 0)}</div>
    <div class="stat-label">Current Holdings</div>
  </div>
</div>
<div class="card" style="margin-top:1rem">
  <h3 style="margin-top:0">Account Cash Flows (£ GBP)</h3>
  <table>
    <tr><td>Total Deposits</td><td style="text-align:right;font-weight:600">£{portfolio.get('total_deposits_gbp', 0):,.2f}</td></tr>
    <tr><td>Total Withdrawals</td><td style="text-align:right;font-weight:600">-£{portfolio.get('total_withdrawals_gbp', 0):,.2f}</td></tr>
    <tr><td>Total Bought</td><td style="text-align:right;font-weight:600">£{portfolio.get('total_bought_gbp', 0):,.2f}</td></tr>
    <tr><td>Total Sold</td><td style="text-align:right;font-weight:600">£{portfolio.get('total_sold_gbp', 0):,.2f}</td></tr>
    <tr><td>Dividends Received</td><td style="text-align:right;font-weight:600;color:#16a34a">+£{portfolio.get('total_dividends_gbp', 0):,.2f}</td></tr>
    <tr><td>Interest Earned</td><td style="text-align:right;font-weight:600;color:#16a34a">+£{portfolio.get('total_interest_gbp', 0):,.2f}</td></tr>
    <tr><td>Total Fees</td><td style="text-align:right;font-weight:600;color:#dc2626">-£{portfolio.get('total_fees_gbp', 0):,.2f}</td></tr>
    <tr style="border-top:2px solid #1e293b"><td><strong>Realized P&L</strong></td>
        <td style="text-align:right;font-weight:700;color:{'#16a34a' if portfolio.get('realized_pnl_gbp', 0) >= 0 else '#dc2626'}">
        £{portfolio.get('realized_pnl_gbp', 0):,.2f}</td></tr>
    <tr><td><strong>Unrealized P&L</strong></td>
        <td style="text-align:right;font-weight:700;color:{'#16a34a' if portfolio.get('total_unrealized_pnl_gbp', 0) >= 0 else '#dc2626'}">
        £{portfolio.get('total_unrealized_pnl_gbp', 0):,.2f}</td></tr>
  </table>
</div>
""")

        # Holdings table
        holdings = portfolio.get("holdings", [])
        if holdings:
            html_parts.append("""<h3>Current Holdings</h3>
<table>
<tr><th>Ticker</th><th>Shares</th><th>Avg Cost (£)</th><th>Cost Basis (£)</th>
<th>Current Value (£)</th><th>Unrealized P&L</th><th>Return</th><th>Realized P&L</th></tr>""")
            for h in holdings:
                upl = h.get("unrealized_pnl_gbp")
                upl_str = f"£{upl:,.2f}" if upl is not None else "N/A"
                upl_color = "#16a34a" if upl and upl >= 0 else "#dc2626" if upl else "#9ca3af"
                cv = h.get("current_value_gbp")
                cv_str = f"£{cv:,.2f}" if cv is not None else "N/A"
                pct = h.get("unrealized_pct")
                pct_str = f"{pct:+.1f}%" if pct is not None else "N/A"
                rpl = h.get("realized_pnl_gbp", 0)
                rpl_color = "#16a34a" if rpl >= 0 else "#dc2626"
                html_parts.append(f"""<tr>
<td><strong>{h['ticker']}</strong></td>
<td>{h['shares']:.6g}</td>
<td>£{h['avg_cost_gbp']:.4f}</td>
<td>£{h['cost_basis_gbp']:,.2f}</td>
<td>{cv_str}</td>
<td style="color:{upl_color};font-weight:600">{upl_str}</td>
<td style="color:{upl_color};font-weight:600">{pct_str}</td>
<td style="color:{rpl_color}">{format_dollar(rpl)}</td>
</tr>""")
            html_parts.append("</table>")

    # === DCA STRATEGIES ===
    if dca_sequences:
        n_dca_seqs = len(dca_sequences)
        total_dca_invested = sum(s.get("total_invested_gbp", 0) for s in dca_sequences)
        n_beat_avg = sum(1 for s in dca_sequences if (s.get("vs_period_avg_pct") or 0) < 0)
        avg_consistency = sum(s.get("consistency_score", 0) for s in dca_sequences) / n_dca_seqs if n_dca_seqs else 0
        n_dca_won = sum(1 for s in dca_sequences if s.get("dca_won"))

        html_parts.append(f"""
<h2 id="dca-strategies">DCA Strategies Detected</h2>
<p>These are sequences of recurring buys at regular intervals with similar amounts — automated or disciplined dollar-cost averaging.</p>
<div class="card-grid">
  <div class="card stat-card">
    <div class="stat-value" style="color:#3b82f6">{n_dca_seqs}</div>
    <div class="stat-label">DCA Sequences Found</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">£{total_dca_invested:,.0f}</div>
    <div class="stat-label">Total DCA Invested</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#16a34a">{n_beat_avg}/{n_dca_seqs}</div>
    <div class="stat-label">Beat Period Average Price</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{avg_consistency:.0f}/100</div>
    <div class="stat-label">Avg Consistency Score</div>
  </div>
</div>
<table style="margin-top:1rem">
<tr><th>Ticker</th><th>Interval</th><th># Buys</th><th>Avg Amount</th><th>Total Invested</th>
<th>Avg Cost vs Period Avg</th><th>DCA Return</th><th>Lump Sum Return</th><th>Winner</th><th>Consistency</th></tr>""")
        for s in dca_sequences:
            vs_avg = s.get("vs_period_avg_pct")
            vs_avg_str = f"{vs_avg:+.1f}%" if vs_avg is not None else "N/A"
            vs_avg_clr = "#16a34a" if vs_avg is not None and vs_avg < 0 else "#dc2626" if vs_avg is not None else "#9ca3af"
            dca_ret = s.get("dca_return_pct", 0)
            ls_ret = s.get("lump_sum_return_pct", 0)
            dca_clr = "#16a34a" if dca_ret >= 0 else "#dc2626"
            ls_clr = "#16a34a" if ls_ret >= 0 else "#dc2626"
            winner = "🔄 DCA" if s.get("dca_won") else "💰 Lump Sum"
            winner_clr = "#3b82f6" if s.get("dca_won") else "#f59e0b"
            html_parts.append(f"""<tr>
<td><strong>{s['ticker']}</strong></td>
<td>{s['interval_type'].title()}</td>
<td>{s['num_buys']}</td>
<td>£{s['avg_amount_gbp']:,.2f}</td>
<td>£{s['total_invested_gbp']:,.2f}</td>
<td style="color:{vs_avg_clr};font-weight:600">{vs_avg_str}</td>
<td style="color:{dca_clr};font-weight:600">{dca_ret:+.1f}%</td>
<td style="color:{ls_clr};font-weight:600">{ls_ret:+.1f}%</td>
<td style="color:{winner_clr};font-weight:600">{winner}</td>
<td>{s['consistency_score']:.0f}</td>
</tr>""")
        html_parts.append("</table>")

    # === BENCHMARK VS SPY ===
    if benchmark:
        alpha = benchmark.get("alpha_pct", 0)
        alpha_clr = "#16a34a" if alpha >= 0 else "#dc2626"
        ptwr = benchmark.get("portfolio_twr_pct", 0)
        ptwr_clr = "#16a34a" if ptwr >= 0 else "#dc2626"
        spy_ret = benchmark.get("spy_buy_hold_return_pct", 0)
        html_parts.append(f"""
<h2 id="benchmark">Benchmark Comparison: Your Portfolio vs SPY</h2>
<p>How did your active portfolio management compare to simply buying and holding an S&P 500 index fund?
Period: {benchmark['period_start']} to {benchmark['period_end']} ({benchmark['period_years']} years)</p>
<div class="card-grid">
  <div class="card stat-card">
    <div class="stat-value" style="color:{ptwr_clr}">{ptwr:+.1f}%</div>
    <div class="stat-label">Portfolio Return</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#3b82f6">{spy_ret:+.1f}%</div>
    <div class="stat-label">SPY Buy &amp; Hold</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:{alpha_clr}">{alpha:+.1f}%</div>
    <div class="stat-label">Alpha<br>(portfolio - SPY)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{benchmark.get('portfolio_cagr_pct', 0):+.1f}%</div>
    <div class="stat-label">Portfolio CAGR<br>(SPY: {benchmark.get('spy_cagr_pct', 0):+.1f}%)</div>
  </div>
</div>""")

        # Monthly comparison table (last 12 months)
        monthly = benchmark.get("monthly_comparison", [])
        if monthly:
            html_parts.append("""<div class="card" style="margin-top:1rem">
<h3 style="margin-top:0">SPY Cumulative Return by Month</h3>
<table style="max-width:500px">
<tr><th>Month</th><th>SPY Cumulative</th></tr>""")
            for m in monthly:
                spy_cum = m.get("spy_cumulative_pct", 0)
                clr = "#16a34a" if spy_cum >= 0 else "#dc2626"
                html_parts.append(f"""<tr>
<td>{m['month']}</td>
<td style="color:{clr};font-weight:600">{spy_cum:+.1f}%</td>
</tr>""")
            html_parts.append("</table></div>")

    # === RISK-ADJUSTED RETURNS ===
    if risk_metrics:
        sharpe = risk_metrics.get("sharpe_ratio", 0)
        sortino = risk_metrics.get("sortino_ratio", 0)
        vol = risk_metrics.get("annualized_volatility_pct", 0)
        max_dd = risk_metrics.get("max_drawdown_pct", 0)

        # Color coding for Sharpe
        if sharpe >= 1.0:
            sharpe_clr = "#16a34a"
        elif sharpe >= 0.5:
            sharpe_clr = "#65a30d"
        elif sharpe >= 0:
            sharpe_clr = "#f59e0b"
        else:
            sharpe_clr = "#dc2626"

        html_parts.append(f"""
<h2 id="risk-metrics">Risk-Adjusted Returns</h2>
<p>How much return did you earn per unit of risk? Higher Sharpe/Sortino ratios mean better risk-adjusted performance.</p>
<div class="card-grid">
  <div class="card stat-card">
    <div class="stat-value">{vol:.1f}%</div>
    <div class="stat-label">Annualized Volatility</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:{sharpe_clr}">{sharpe:.2f}</div>
    <div class="stat-label">Sharpe Ratio<br>(rf={risk_metrics.get('risk_free_rate_pct', 4.5)}%)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:{sharpe_clr}">{sortino:.2f}</div>
    <div class="stat-label">Sortino Ratio</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value" style="color:#dc2626">{max_dd:.1f}%</div>
    <div class="stat-label">Max Drawdown</div>
  </div>
</div>""")

        # Drawdown detail card
        dd_start = risk_metrics.get("max_drawdown_start_date", "N/A")
        dd_end = risk_metrics.get("max_drawdown_end_date", "N/A")
        dd_recovery = risk_metrics.get("max_drawdown_recovery_date")
        dd_duration = risk_metrics.get("max_drawdown_duration_days", 0)
        recovery_str = dd_recovery if dd_recovery else "Not yet recovered"

        html_parts.append(f"""
<div class="card" style="margin-top:1rem; border-left: 4px solid #dc2626">
  <h3 style="margin-top:0">Maximum Drawdown Detail</h3>
  <table style="max-width:500px">
    <tr><td>Peak Date</td><td style="font-weight:600">{dd_start}</td></tr>
    <tr><td>Trough Date</td><td style="font-weight:600">{dd_end}</td></tr>
    <tr><td>Duration</td><td style="font-weight:600">{dd_duration} days</td></tr>
    <tr><td>Max Decline</td><td style="font-weight:600;color:#dc2626">{max_dd:.1f}%</td></tr>
    <tr><td>Recovery Date</td><td style="font-weight:600;color:{'#16a34a' if dd_recovery else '#dc2626'}">{recovery_str}</td></tr>
  </table>
</div>""")

        # Daily return stats
        html_parts.append(f"""
<div class="card" style="margin-top:1rem">
  <h3 style="margin-top:0">Daily Return Statistics</h3>
  <table style="max-width:500px">
    <tr><td>Total Trading Days</td><td style="font-weight:600">{risk_metrics.get('total_trading_days', 0)}</td></tr>
    <tr><td>Positive Days</td><td style="font-weight:600;color:#16a34a">{risk_metrics.get('positive_days', 0)}</td></tr>
    <tr><td>Negative Days</td><td style="font-weight:600;color:#dc2626">{risk_metrics.get('negative_days', 0)}</td></tr>
    <tr><td>Win Rate</td><td style="font-weight:600">{risk_metrics.get('win_rate_pct', 0):.1f}%</td></tr>
    <tr><td>Best Day</td><td style="font-weight:600;color:#16a34a">{risk_metrics.get('best_day_return_pct', 0):+.2f}% ({risk_metrics.get('best_day_date', 'N/A')})</td></tr>
    <tr><td>Worst Day</td><td style="font-weight:600;color:#dc2626">{risk_metrics.get('worst_day_return_pct', 0):+.2f}% ({risk_metrics.get('worst_day_date', 'N/A')})</td></tr>
    <tr><td>Annualized Return</td><td style="font-weight:600">{risk_metrics.get('annualized_return_pct', 0):+.1f}%</td></tr>
  </table>
</div>""")

    # === TOP 3 BEST / WORST ===
    html_parts.append("""<h2 id="best-worst-timing">Top Actions: Best &amp; Worst Timing</h2>""")

    best_3 = summary.get("best_3_actions", [])
    worst_3 = summary.get("worst_3_actions", [])

    html_parts.append("""<h3>🏆 Best Timed Actions</h3><table>
<tr><th>Ticker</th><th>Action</th><th>Date</th><th>Score</th><th>Dollar Impact</th></tr>""")
    for a in reversed(best_3):
        html_parts.append(f"""<tr>
<td><strong>{a['ticker']}</strong></td>
<td>{a['action']}</td>
<td>{a['date']}</td>
<td><span class="score-bar" style="background:{score_color(a['score'])}">{a['score']:+.0f}</span></td>
<td>{format_dollar(a.get('impact', 0))}</td>
</tr>""")
    html_parts.append("</table>")

    html_parts.append("""<h3>💸 Worst Timed Actions</h3><table>
<tr><th>Ticker</th><th>Action</th><th>Date</th><th>Score</th><th>Dollar Impact</th></tr>""")
    for a in worst_3:
        html_parts.append(f"""<tr>
<td><strong>{a['ticker']}</strong></td>
<td>{a['action']}</td>
<td>{a['date']}</td>
<td><span class="score-bar" style="background:{score_color(a['score'])}">{a['score']:+.0f}</span></td>
<td>{format_dollar(a.get('impact', 0))}</td>
</tr>""")
    html_parts.append("</table>")

    # === WELL TIMED SELLS (detailed) ===
    well_sells.sort(key=lambda a: a["analysis"]["well_timed_sell"].get("loss_avoided_pct", 0), reverse=True)
    if well_sells:
        html_parts.append("""<h2 id="best-sells">Best Timed Sells — Detailed Breakdown</h2>
<p>These sells were followed by a significant price drop — great timing that avoided losses.</p>""")
        for a in well_sells[:15]:
            ws = a["analysis"]["well_timed_sell"]
            action = a["action"]
            analysis = a["analysis"]
            total_gbp = action.get("total", 0)

            traj = ws.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_sell", 0)
                clr = "#16a34a" if pct <= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            stayed_str = ""
            if ws.get("stayed_below_sell_price"):
                stayed_str = '<p style="color:#16a34a;font-weight:600">The price never recovered to your sell price in the 90 days after — excellent exit.</p>'
            elif ws.get("recovered_date"):
                stayed_str = f'<p>Price recovered to your sell price by {ws["recovered_date"]}, but dropped <strong>{ws["max_decline_after_pct"]:.1f}%</strong> in between.</p>'

            # Realized P&L from avg cost
            realized_str = ""
            rpnl = analysis.get("realized_pnl_gbp")
            avg_cost = analysis.get("avg_cost_gbp")
            if rpnl is not None and avg_cost is not None:
                rpnl_clr = "#16a34a" if rpnl >= 0 else "#dc2626"
                realized_str = f'<p>Your avg cost basis was <strong>£{avg_cost:.4f}/share</strong>. Realized P&L: <span style="color:{rpnl_clr};font-weight:600">£{rpnl:,.2f}</span></p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #16a34a; margin-bottom:1.5rem">
  <h3 style="margin-top:0">✅ {action['ticker']} — Sold {action['date']}</h3>
  <p><strong>Why this was great:</strong> After you sold, the price dropped as low as <span style="color:#dc2626;font-weight:600">{ws['max_decline_after_pct']:.1f}%</span> (to {ws['min_price_after']:,.2f} on {ws['min_price_date']}). You avoided <strong>{ws['loss_avoided_pct']:.1f}%</strong> in losses.</p>
  <p>You sold at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {realized_str}
  {stayed_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you sold:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Sell</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === WELL TIMED BUYS (detailed) ===
    well_buys.sort(key=lambda a: a["analysis"]["well_timed_buy"].get("max_gain_after_pct", 0), reverse=True)
    if well_buys:
        html_parts.append("""<h2 id="best-buys">Best Timed Buys — Detailed Breakdown</h2>
<p>These buys were followed by a significant price increase — great entries that captured gains.</p>""")
        for a in well_buys[:15]:
            wb = a["analysis"]["well_timed_buy"]
            action = a["action"]
            total_gbp = action.get("total", 0)

            traj = wb.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_buy", 0)
                clr = "#16a34a" if pct >= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            dip_str = ""
            if wb.get("bought_the_dip") and wb.get("dip_detail"):
                dip_str = f'<p style="color:#16a34a;font-weight:600">🎯 You bought the dip! The stock had fallen {wb["dip_detail"]["decline_before_buy_pct"]:.1f}% before your purchase.</p>'

            never_below_str = ""
            if wb.get("never_went_below_entry"):
                never_below_str = '<p style="color:#16a34a">The price never meaningfully dipped below your entry — clean entry point.</p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #16a34a; margin-bottom:1.5rem">
  <h3 style="margin-top:0">✅ {action['ticker']} — Bought {action['date']}</h3>
  <p><strong>Why this was great:</strong> After you bought, the price rose as high as <span style="color:#16a34a;font-weight:600">+{wb['max_gain_after_pct']:.1f}%</span> (to {wb['max_price_after']:,.2f} on {wb['max_price_date']}). Excellent entry.</p>
  <p>You bought at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {dip_str}
  {never_below_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you bought:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Buy</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === WORST TIMED SELLS (detailed) ===
    worst_sells.sort(key=lambda a: a["analysis"]["worst_timed_sell"].get("missed_rally_pct", 0), reverse=True)
    if worst_sells:
        html_parts.append("""<h2 id="worst-sells">Worst Timed Sells — Detailed Breakdown</h2>
<p>These sells were followed by a massive rally. You sold at the bottom. Ouch.</p>""")
        for a in worst_sells[:15]:
            wts = a["analysis"]["worst_timed_sell"]
            action = a["action"]
            analysis = a["analysis"]
            total_gbp = action.get("total", 0)

            traj = wts.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_sell", 0)
                clr = "#16a34a" if pct <= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            # Realized P&L from avg cost
            realized_str = ""
            rpnl = analysis.get("realized_pnl_gbp")
            avg_cost = analysis.get("avg_cost_gbp")
            if rpnl is not None and avg_cost is not None:
                rpnl_clr = "#16a34a" if rpnl >= 0 else "#dc2626"
                realized_str = f'<p>Your avg cost basis was <strong>£{avg_cost:.4f}/share</strong>. Realized P&L: <span style="color:{rpnl_clr};font-weight:600">£{rpnl:,.2f}</span></p>'

            optimal_str = ""
            if wts.get("optimal_sell_date"):
                optimal_str = f'<p>If you had waited until <strong>{wts["optimal_sell_date"]}</strong>, you could have sold at <strong>{wts["optimal_sell_price"]:,.2f}</strong> — that\'s <strong>{wts["missed_rally_pct"]:.1f}%</strong> more. Let that sink in.</p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #dc2626; margin-bottom:1.5rem">
  <h3 style="margin-top:0">💀 {action['ticker']} — Sold {action['date']}</h3>
  <p><strong>Why this was terrible:</strong> After you sold, the price rallied <span style="color:#dc2626;font-weight:600">+{wts['missed_rally_pct']:.1f}%</span> reaching {wts['max_price_after']:,.2f} on {wts['max_price_date']}. You sold at the bottom.</p>
  <p>You sold at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {realized_str}
  {optimal_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you sold:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Sell</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === WORST TIMED BUYS (detailed) ===
    worst_buys.sort(key=lambda a: a["analysis"]["worst_timed_buy"].get("max_drop_after_pct", 0))
    if worst_buys:
        html_parts.append("""<h2 id="worst-buys">Worst Timed Buys — Detailed Breakdown</h2>
<p>These buys were followed by a massive drop. You bought at the top. Classic.</p>""")
        for a in worst_buys[:15]:
            wtb = a["analysis"]["worst_timed_buy"]
            action = a["action"]
            total_gbp = action.get("total", 0)

            traj = wtb.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_buy", 0)
                clr = "#16a34a" if pct >= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            top_str = ""
            if wtb.get("bought_the_top"):
                top_str = '<p style="color:#dc2626;font-weight:600">You bought after the stock was already climbing — textbook buying the top.</p>'

            recovered_str = ""
            if wtb.get("recovered_date"):
                recovered_str = f'<p>The price eventually recovered to your entry by <strong>{wtb["recovered_date"]}</strong>. Cold comfort.</p>'
            else:
                recovered_str = '<p style="color:#dc2626">The price <strong>never recovered</strong> to your entry in the 90 days after. Pain.</p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #dc2626; margin-bottom:1.5rem">
  <h3 style="margin-top:0">💀 {action['ticker']} — Bought {action['date']}</h3>
  <p><strong>Why this was terrible:</strong> After you bought, the price cratered <span style="color:#dc2626;font-weight:600">{wtb['max_drop_after_pct']:.1f}%</span> hitting {wtb['min_price_after']:,.2f} on {wtb['min_price_date']}.</p>
  <p>You bought at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {top_str}
  {recovered_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you bought:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Buy</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === FULL ACTION BREAKDOWN ===
    html_parts.append("""<h2 id="all-actions">All Scored Actions</h2>
<table>
<tr><th>Date</th><th>Action</th><th>Ticker</th><th>Price</th><th>Qty</th>
<th>Score</th><th>Impact</th><th>Flags</th></tr>""")

    for a in scored_actions:
        action = a["action"]
        analysis = a["analysis"]
        flags = []
        if analysis.get("is_dca"):
            flags.append("🔄 DCA")
        if analysis.get("panic_sell"):
            flags.append("🔴 Panic")
        if analysis.get("fomo_buy"):
            flags.append("🟡 FOMO")
        if analysis.get("dividend_proximity"):
            flags.append("💰 Div Miss")
        if analysis.get("well_timed_sell"):
            flags.append("✅ Great Sell")
        if analysis.get("well_timed_buy"):
            flags.append("✅ Great Buy")
        if analysis.get("worst_timed_sell"):
            flags.append("💀 Worst Sell")
        if analysis.get("worst_timed_buy"):
            flags.append("💀 Worst Buy")
        score = analysis["timing_score"]
        html_parts.append(f"""<tr>
<td>{action['date']}</td>
<td>{action['action']}</td>
<td><strong>{action['ticker']}</strong></td>
<td>{action['price']:,.2f} {action.get('trade_currency', '')}</td>
<td>{action['quantity']:.6g}</td>
<td>{score_emoji(score)} <span style="color:{score_color(score)};font-weight:600">{score:+.0f}</span></td>
<td>{format_dollar(analysis.get('dollar_impact', 0))}</td>
<td>{'  '.join(flags) if flags else '—'}</td>
</tr>""")

    html_parts.append("</table>")

    # === PANIC SELLS (detailed) ===
    panic_sells = [a for a in analyzed
                   if (a.get("analysis") or {}).get("panic_sell")]
    if panic_sells:
        html_parts.append("""<h2 id="panic-sells">Panic Sells — Detailed Breakdown</h2>
<p>These sells were triggered after a sharp price decline. For each one, here's what happened and what the optimal timing would have been.</p>""")
        for a in panic_sells:
            ps = a["analysis"]["panic_sell"]
            action = a["action"]
            analysis = a["analysis"]
            total_gbp = action.get("total", 0)

            # Build trajectory table
            traj = ps.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_sell", 0)
                clr = "#16a34a" if pct >= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            recovered_str = ""
            if ps.get("recovered_sell_price_date"):
                recovered_str = f'<p style="color:#16a34a;font-weight:600">Price recovered to your sell price by {ps["recovered_sell_price_date"]}.</p>'
            elif ps.get("recovery_pct", 0) > 0:
                recovered_str = f'<p style="color:#ea580c">Price partially recovered: peak was {ps.get("recovery_pct",0):+.1f}% above your sell price on {ps.get("max_price_date","")}.</p>'

            optimal_str = ""
            if ps.get("optimal_sell_date") and ps.get("missed_gain_pct", 0) > 1:
                optimal_str = f'<p>Optimal sell would have been <strong>{ps["optimal_sell_date"]}</strong> at {ps["optimal_sell_price"]:,.2f} — you missed <strong>{ps["missed_gain_pct"]:+.1f}%</strong> upside.</p>'

            # Realized P&L from avg cost
            realized_str = ""
            rpnl = analysis.get("realized_pnl_gbp")
            avg_cost = analysis.get("avg_cost_gbp")
            if rpnl is not None and avg_cost is not None:
                rpnl_clr = "#16a34a" if rpnl >= 0 else "#dc2626"
                realized_str = f'<p>Your avg cost basis was <strong>£{avg_cost:.4f}/share</strong>. Realized P&L: <span style="color:{rpnl_clr};font-weight:600">£{rpnl:,.2f}</span></p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #dc2626; margin-bottom:1.5rem">
  <h3 style="margin-top:0">🔴 {action['ticker']} — Sold {action['date']}</h3>
  <p><strong>Why flagged:</strong> Stock dropped <span style="color:#dc2626;font-weight:600">{ps['stock_decline_5d']:.1f}%</span> in the 5 days before you sold. This pattern suggests a reactive/emotional sell rather than a planned exit.</p>
  <p>You sold at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {realized_str}
  {recovered_str}
  {optimal_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you sold:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Sell</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === FOMO BUYS (detailed) ===
    fomo_buys = [a for a in analyzed
                 if (a.get("analysis") or {}).get("fomo_buy")]
    if fomo_buys:
        html_parts.append("""<h2 id="fomo-buys">FOMO Buys — Detailed Breakdown</h2>
<p>These buys happened after a strong price run-up, suggesting you may have chased momentum. Here's what happened next.</p>""")
        for a in fomo_buys:
            fb = a["analysis"]["fomo_buy"]
            action = a["action"]
            total_gbp = action.get("total", 0)

            traj = fb.get("price_trajectory", {})
            traj_rows = ""
            for period, info in traj.items():
                pct = info.get("pct_vs_buy", 0)
                clr = "#16a34a" if pct >= 0 else "#dc2626"
                traj_rows += f'<tr><td>{period} later</td><td>{info.get("date","")}</td><td>{info.get("price",0):,.2f}</td><td style="color:{clr};font-weight:600">{pct:+.1f}%</td></tr>'

            drawdown_str = ""
            if fb.get("max_drawdown_pct", 0) < -3:
                drawdown_str = f'<p style="color:#dc2626">After buying, the price dropped as low as <strong>{fb["min_price_after"]:,.2f}</strong> on {fb["min_price_date"]} — a <strong>{fb["max_drawdown_pct"]:.1f}%</strong> drawdown from your entry.</p>'

            optimal_str = ""
            if fb.get("optimal_buy_date") and fb.get("overpaid_pct", 0) > 1:
                optimal_str = f'<p>Optimal entry would have been <strong>{fb["optimal_buy_date"]}</strong> at {fb["optimal_buy_price"]:,.2f} — you overpaid by <strong>{fb["overpaid_pct"]:.1f}%</strong>.</p>'

            html_parts.append(f"""
<div class="card" style="border-left:4px solid #f59e0b; margin-bottom:1.5rem">
  <h3 style="margin-top:0">🟡 {action['ticker']} — Bought {action['date']}</h3>
  <p><strong>Why flagged:</strong> Stock had already rallied <span style="color:#ea580c;font-weight:600">{fb['stock_gain_10d']:.1f}%</span> in the 10 days before you bought. Buying after a strong run-up often means buying near a short-term top.</p>
  <p>You bought at <strong>{action['price']:,.2f} {action.get('trade_currency','')}</strong> ({action['quantity']:.6g} shares, £{total_gbp:,.2f} total).</p>
  {drawdown_str}
  {optimal_str}
  <h4 style="margin:0.75rem 0 0.25rem">What happened after you bought:</h4>
  <table style="max-width:500px">
    <tr><th>Period</th><th>Date</th><th>Price</th><th>vs Your Buy</th></tr>
    {traj_rows}
  </table>
</div>""")

    # === ROUND TRIPS ===
    if round_trips:
        html_parts.append("""<h2 id="round-trips">Round-Trip Trades</h2>
<table>
<tr><th>Ticker</th><th>Buy Date</th><th>Buy Price</th><th>Sell Date</th><th>Sell Price</th>
<th>Days Held</th><th>Return</th><th>P/L</th></tr>""")
        for t in sorted(round_trips, key=lambda x: x["dollar_return"]):
            ret_color = "#16a34a" if t["return_pct"] >= 0 else "#dc2626"
            html_parts.append(f"""<tr>
<td><strong>{t['ticker']}</strong></td>
<td>{t['buy_date']}</td>
<td>{t['buy_price']:,.2f}</td>
<td>{t['sell_date']}</td>
<td>{t['sell_price']:,.2f}</td>
<td>{t['holding_days']}</td>
<td style="color:{ret_color};font-weight:600">{t['return_pct']:+.1f}%</td>
<td>{format_dollar(t['dollar_return'])}</td>
</tr>""")
        html_parts.append("</table>")

    # === DIVIDEND ANALYSIS ===
    missed_divs = [a for a in analyzed
                   if (a.get("analysis") or {}).get("dividend_proximity")]
    if missed_divs:
        html_parts.append("""<h2 id="dividend-timing">Dividend Timing Issues</h2>
<p>These sells happened shortly before ex-dividend dates, causing you to miss dividend payments.</p>
<table>
<tr><th>Ticker</th><th>Sell Date</th><th>Ex-Div Date</th><th>Days Before</th>
<th>Div/Share</th><th>Shares</th><th>Missed (£)</th></tr>""")
        for a in missed_divs:
            dp = a["analysis"]["dividend_proximity"]
            html_parts.append(f"""<tr>
<td><strong>{a['action']['ticker']}</strong></td>
<td>{a['action']['date']}</td>
<td>{dp['ex_dividend_date']}</td>
<td style="color:#dc2626;font-weight:600">{dp['days_before_ex_date']}</td>
<td>{dp['dividend_per_share']:.4f}</td>
<td>{a['action']['quantity']:.6g}</td>
<td style="color:#dc2626;font-weight:600">£{dp.get('missed_amount', 0):.2f}</td>
</tr>""")
        html_parts.append("</table>")

    # === WASH SALES ===
    if wash_sales:
        html_parts.append("""<h2 id="wash-sales">Potential Wash Sales</h2>
<p>These are sells at a loss followed by a repurchase within 30 days. This may affect tax deductibility of the loss.
Consult a tax professional.</p>
<table>
<tr><th>Ticker</th><th>Sell Date</th><th>Sell Price</th><th>Rebuy Date</th><th>Rebuy Price</th><th>Days Between</th></tr>""")
        for w in wash_sales:
            html_parts.append(f"""<tr>
<td><strong>{w['ticker']}</strong></td>
<td>{w['sell_date']}</td>
<td>{w['sell_price']:,.2f}</td>
<td>{w['rebuy_date']}</td>
<td>{w['rebuy_price']:,.2f}</td>
<td>{w['days_between']}</td>
</tr>""")
        html_parts.append("</table>")

    # === RECOMMENDATIONS ===
    if recommendations:
        html_parts.append("""<h2 id="recommendations">Actionable Recommendations</h2>
<p>Based on your specific trading patterns, here are concrete steps to improve your timing:</p>""")
        for rec in recommendations:
            cat_labels = {
                "dividend_timing": "💰 Dividend Timing",
                "panic_selling": "🔴 Panic Selling",
                "fomo_buying": "🟡 FOMO Buying",
                "round_trip_losses": "📉 Round-Trip Losses",
                "positive_reinforcement": "✅ Keep Doing This",
            }
            label = cat_labels.get(rec["category"], rec["category"])
            html_parts.append(f"""
<div class="rec-card {rec['severity']}">
  <strong>{label}</strong> {severity_badge(rec['severity'])}
  <p class="rec-example">{rec['example']}</p>
  <div class="rec-advice">💡 <strong>Action:</strong> {rec['advice']}</div>
</div>""")

    # === FOOTER ===
    html_parts.append(f"""
<div class="footer">
  <p>Portfolio Analysis Report &middot; Generated {datetime.now().strftime('%Y-%m-%d')} &middot;
  Market data from Yahoo Finance</p>
  <p>This report is for educational purposes only and does not constitute investment advice.</p>
</div>

<script>
// Scroll-spy: highlight active TOC link based on scroll position
(function() {{
  const links = document.querySelectorAll('.toc-link');
  const sections = [];
  links.forEach(function(link) {{
    const id = link.getAttribute('data-section');
    const el = document.getElementById(id);
    if (el) sections.push({{ id: id, el: el, link: link }});
  }});

  function updateActive() {{
    let current = sections[0];
    for (let i = 0; i < sections.length; i++) {{
      if (sections[i].el.getBoundingClientRect().top <= 80) {{
        current = sections[i];
      }}
    }}
    links.forEach(function(l) {{ l.classList.remove('active'); }});
    if (current) current.link.classList.add('active');
  }}

  window.addEventListener('scroll', updateActive, {{ passive: true }});
  updateActive();

  // Close mobile TOC when a link is clicked
  links.forEach(function(link) {{
    link.addEventListener('click', function() {{
      document.querySelector('.toc').classList.remove('open');
    }});
  }});
}})();
</script>
</body>
</html>""")

    html = "\n".join(html_parts)
    with open(output_path, 'w') as f:
        f.write(html)

    print(f"Report generated: {output_path}")
    print(f"  Sections: Summary, {len(scored_actions)} actions, "
          f"{len(round_trips)} round-trips, {len(recommendations)} recommendations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HTML portfolio analysis report")
    parser.add_argument("input", help="Path to analysis_results.json")
    parser.add_argument("--output", "-o",
                        default="./portfolio_analysis_report.html",
                        help="Output HTML path")
    args = parser.parse_args()
    generate_report(args.input, args.output)
