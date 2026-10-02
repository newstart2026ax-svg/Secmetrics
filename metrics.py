"""Metrics engine: XBRL facts -> analyst-grade financial metrics.

Design notes
- Companies tag the same concept differently (Apple uses
  RevenueFromContractWithCustomerExcludingAssessedTax, others use Revenues),
  so every metric has a fallback tag list, tried in order.
- Duration facts (income statement) carry frames like CY2026Q2.
  Instant facts (balance sheet) carry frames like CY2026Q2I.
- TTM = sum of the 4 most recent quarterly duration frames.
"""
import re

# metric -> ordered list of us-gaap tags to try
TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
                "RevenuesNetOfInterestExpense"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "op_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

Q_FRAME = re.compile(r"^CY(\d{4})Q([1-4])$")
QI_FRAME = re.compile(r"^CY(\d{4})Q([1-4])I$")
Y_FRAME = re.compile(r"^CY(\d{4})$")


def _frame_key(frame, instant):
    m = (QI_FRAME if instant else Q_FRAME).match(frame or "")
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = Y_FRAME.match(frame or "")
    if m:
        return (int(m.group(1)), 0)
    return None


def _get_points(facts_json, metric, instant=False):
    """All 10-K/10-Q points for a metric, newest first. Returns (frame, value, filed, form).

    Tries every fallback tag and keeps the one with the *newest* data --
    companies sometimes switch tags (NVIDIA used
    RevenueFromContractWithCustomerExcludingAssessedTax until 2022, then Revenues).
    """
    namespaces = facts_json.get("facts", {})
    best_result, best_key = None, None
    for tag in TAGS[metric]:
        for ns in ("us-gaap", "dei"):
            concept = namespaces.get(ns, {}).get(tag)
            if not concept:
                continue
            for unit, pts in concept.get("units", {}).items():
                if unit not in ("USD", "shares"):
                    continue
                out = []
                for p in pts:
                    if p.get("form") not in ("10-K", "10-Q"):
                        continue
                    key = _frame_key(p.get("frame"), instant)
                    if key is None:
                        continue
                    # Annual frames (CY####) are FY/YTD totals, never discrete
                    # quarters -- skip them in the quarterly flow entirely.
                    if not instant and Y_FRAME.match(p.get("frame") or ""):
                        continue
                    out.append((key, p["val"], p.get("filed", ""), p.get("form"), p.get("frame")))
                if out:
                    # dedupe by frame key, prefer 10-Q then newest filed
                    deduped = {}
                    for key, val, filed, form, frame in out:
                        cur = deduped.get(key)
                        if cur is None or (form == "10-Q" and cur[3] == "10-K") or \
                           (form == cur[3] and filed > cur[2]):
                            deduped[key] = (key, val, filed, form, frame)
                    result = sorted(deduped.values(), key=lambda r: r[0], reverse=True)
                    if best_key is None or result[0][0] > best_key:
                        best_key = result[0][0]
                        best_result = result
    return best_result or []


def quarterly_series(facts_json, metric, n=12, instant=False):
    pts = _get_points(facts_json, metric, instant=instant)
    return [{"frame": p[4], "value": p[1], "form": p[3], "filed": p[2]} for p in pts[:n]]


def ttm(facts_json, metric):
    pts = _get_points(facts_json, metric, instant=False)
    if len(pts) < 4:
        return None
    return sum(p[1] for p in pts[:4])


def latest_value(facts_json, metric, instant=True):
    pts = _get_points(facts_json, metric, instant=instant)
    return pts[0][1] if pts else None


def pct_change(new, old):
    if new is None or old in (None, 0):
        return None
    return (new - old) / abs(old)


def build_metrics(facts_json):
    """Compute the analyst dashboard dict."""
    rev_q = quarterly_series(facts_json, "revenue", n=9)
    ni_q = quarterly_series(facts_json, "net_income", n=9)

    rev_ttm = ttm(facts_json, "revenue")
    ni_ttm = ttm(facts_json, "net_income")
    gp_ttm = ttm(facts_json, "gross_profit")
    ocf_ttm = ttm(facts_json, "op_cash_flow")
    capex_ttm = ttm(facts_json, "capex")

    equity = latest_value(facts_json, "equity")
    liabilities = latest_value(facts_json, "liabilities")
    cur_a = latest_value(facts_json, "current_assets")
    cur_l = latest_value(facts_json, "current_liabilities")
    cash = latest_value(facts_json, "cash")
    rd_ttm = ttm(facts_json, "rd_expense")

    fcf_ttm = (ocf_ttm - capex_ttm) if ocf_ttm is not None and capex_ttm is not None else None

    # YoY: latest quarter vs 4 quarters ago
    rev_yoy = pct_change(rev_q[0]["value"], rev_q[4]["value"]) if len(rev_q) >= 5 else None
    ni_yoy = pct_change(ni_q[0]["value"], ni_q[4]["value"]) if len(ni_q) >= 5 else None

    def ratio(a, b):
        return (a / b) if a is not None and b not in (None, 0) else None

    return {
        "revenue_ttm": rev_ttm,
        "revenue_yoy": rev_yoy,
        "net_income_ttm": ni_ttm,
        "net_income_yoy": ni_yoy,
        "gross_margin": ratio(gp_ttm, rev_ttm),
        "net_margin": ratio(ni_ttm, rev_ttm),
        "roe": ratio(ni_ttm, equity),
        "current_ratio": ratio(cur_a, cur_l),
        "debt_to_equity": ratio(liabilities, equity),
        "fcf_ttm": fcf_ttm,
        "cash": cash,
        "rd_ttm": rd_ttm,
        "rd_intensity": ratio(rd_ttm, rev_ttm),
        "revenue_quarters": rev_q,
        "net_income_quarters": ni_q,
        "as_of_frame": rev_q[0]["frame"] if rev_q else None,
    }


def fmt_money(v):
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1e12:
        return f"${v/1e12:.2f}T"
    if a >= 1e9:
        return f"${v/1e9:.1f}B"
    if a >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"


def fmt_pct(v):
    return f"{v*100:.1f}%" if v is not None else "n/a"


def fmt_ratio(v):
    return f"{v:.2f}" if v is not None else "n/a"
