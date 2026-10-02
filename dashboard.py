"""Dashboard generator: metrics + narrative -> single mobile-first HTML file."""
import html
from metrics import fmt_money, fmt_pct, fmt_ratio


def sparkline(values, w=220, h=48):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1
    pts = []
    for i, v in enumerate(vals):
        x = i / (len(vals) - 1) * w
        y = h - 4 - (v - mn) / rng * (h - 10)
        pts.append(f"{x:.1f},{y:.1f}")
    # green if up, red if down (first -> last)
    color = "#34d399" if vals[-1] >= vals[0] else "#f87171"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="2.5" stroke-linecap="round"/></svg>')


def card(title, value, sub="", chart=""):
    return f"""<div class="card"><div class="label">{html.escape(title)}</div>
<div class="value">{value}</div><div class="sub">{sub}</div>{chart}</div>"""


def arrow(v):
    if v is None:
        return ""
    return "▲" if v >= 0 else "▼"


def arrow_cls(v):
    if v is None:
        return ""
    return "up" if v >= 0 else "down"


def render_dashboard(company, ticker, metrics, filings, narrative_changes):
    """Return the dashboard HTML string (web app uses this directly)."""
    m = metrics
    rev_vals = [q["value"] for q in m["revenue_quarters"]][::-1]
    ni_vals = [q["value"] for q in m["net_income_quarters"]][::-1]

    cards = [
        card("Revenue (TTM)", fmt_money(m["revenue_ttm"]),
             f'<span class="{arrow_cls(m["revenue_yoy"])}">{arrow(m["revenue_yoy"])} {fmt_pct(m["revenue_yoy"])}</span> YoY (quarter)',
             sparkline(rev_vals)),
        card("Net Income (TTM)", fmt_money(m["net_income_ttm"]),
             f'<span class="{arrow_cls(m["net_income_yoy"])}">{arrow(m["net_income_yoy"])} {fmt_pct(m["net_income_yoy"])}</span> YoY (quarter)',
             sparkline(ni_vals)),
        card("Gross Margin", fmt_pct(m["gross_margin"]), "TTM"),
        card("Net Margin", fmt_pct(m["net_margin"]), "TTM"),
        card("Free Cash Flow (TTM)", fmt_money(m["fcf_ttm"]), "Operating cash − capex"),
        card("ROE", fmt_pct(m["roe"]), "TTM net income / equity"),
        card("Current Ratio", fmt_ratio(m["current_ratio"]), "Current assets / liabilities"),
        card("Debt / Equity", fmt_ratio(m["debt_to_equity"]), "Total liabilities / equity"),
        card("Cash on Hand", fmt_money(m["cash"]), "Latest quarter"),
        card("R&D Intensity", fmt_pct(m["rd_intensity"]), "R&D / revenue (TTM)"),
    ]

    filing_rows = "".join(
        f'<div class="filing"><span class="fform">{f["form"]}</span>'
        f'<span class="fdate">{f["filingDate"]}</span></div>' for f in filings[:8])

    def sent_list(items, cls):
        if not items:
            return '<div class="none">No material changes detected.</div>'
        lis = "".join(f'<li class="{cls}">{html.escape(s[:380])}</li>' for s in items)
        return f"<ul>{lis}</ul>"

    narr_html = ""
    for section, (added, removed) in narrative_changes.items():
        title = "MD&A — Management's Discussion" if section == "mda" else "Risk Factors"
        narr_html += f"""<h3>{title}</h3>
<h4>New / changed language</h4>{sent_list(added, "added")}
<h4>Removed language</h4>{sent_list(removed, "removed")}"""

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(company)} — SEC Metrics</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0b0f14;color:#e6edf3;font-family:-apple-system,system-ui,sans-serif;padding:16px;max-width:640px;margin:0 auto}}
h1{{font-size:22px;margin-bottom:2px}}h2{{font-size:15px;color:#8b949e;margin:18px 0 10px;text-transform:uppercase;letter-spacing:.5px}}
h3{{font-size:16px;margin:14px 0 6px}}h4{{font-size:13px;color:#8b949e;margin:10px 0 4px}}
.meta{{color:#8b949e;font-size:13px;margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:12px}}
.label{{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.4px}}
.value{{font-size:21px;font-weight:700;margin:4px 0}}
.sub{{font-size:12px;color:#8b949e}}.up{{color:#34d399}}.down{{color:#f87171}}
.card svg{{width:100%;height:40px;margin-top:6px}}
.filing{{display:flex;justify-content:space-between;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 12px;margin-bottom:6px;font-size:14px}}
.fform{{font-weight:700;color:#58a6ff}}.fdate{{color:#8b949e}}
ul{{list-style:none}}li{{font-size:13px;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;margin-bottom:6px;line-height:1.45}}
li.added{{border-left:3px solid #34d399}}li.removed{{border-left:3px solid #f87171;opacity:.75}}
.none{{font-size:13px;color:#8b949e}}
.foot{{color:#6e7681;font-size:11px;margin-top:20px;line-height:1.5}}
</style></head><body>
<h1>{html.escape(company)}</h1>
<div class="meta">{html.escape(ticker)} · SEC EDGAR · as of {html.escape(m["as_of_frame"] or "")} · generated from filed XBRL</div>
<h2>Key metrics</h2><div class="grid">{"".join(cards)}</div>
<h2>Latest filings</h2>{filing_rows}
<h2>What changed in the narrative</h2>{narr_html}
<div class="foot">Prototype: metrics computed deterministically from XBRL company facts filed with the SEC.
Narrative diffs are sentence-level comparisons of the latest 10-Q/10-K vs the prior period.
Not investment advice.</div>
</body></html>"""
    return page


def build_dashboard(company, ticker, metrics, filings, narrative_changes, out_path):
    """Render and write the dashboard to a file (CLI use)."""
    page = render_dashboard(company, ticker, metrics, filings, narrative_changes)
    with open(out_path, "w") as f:
        f.write(page)
    return out_path
