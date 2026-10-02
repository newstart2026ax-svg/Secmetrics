"""EDGAR client: ticker -> CIK -> filings + XBRL company facts.

Uses only the SEC's free public JSON APIs. No key required, but the SEC
asks for a descriptive User-Agent header (we send one on every request).
"""
import json
import re
import time
import urllib.request

UA = "SHAETHON-SecMetrics/0.1 (research prototype; contact: hello@shaethon.ai)"
BASE_DATA = "https://data.sec.gov"
BASE_WWW = "https://www.sec.gov"

_ticker_map = None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def ticker_to_cik(ticker):
    """Return (cik_int, cik_padded, company_name) for a ticker symbol."""
    global _ticker_map
    if _ticker_map is None:
        raw = _get(f"{BASE_WWW}/files/company_tickers.json")
        _ticker_map = {v["ticker"].upper(): v for v in json.loads(raw).values()}
    t = ticker.strip().upper()
    if t not in _ticker_map:
        raise ValueError(f"Ticker {ticker!r} not found in EDGAR")
    v = _ticker_map[t]
    cik = int(v["cik_str"])
    return cik, str(cik).zfill(10), v["title"]


def get_submissions(cik_padded):
    """Recent filing index for a company (forms, dates, accession numbers)."""
    raw = _get(f"{BASE_DATA}/submissions/CIK{cik_padded}.json")
    return json.loads(raw)


def recent_filings(cik_padded, forms=("10-K", "10-Q", "8-K"), limit=12):
    """List of recent filings filtered to the given forms, newest first."""
    subs = get_submissions(cik_padded)
    r = subs["filings"]["recent"]
    out = []
    for i in range(len(r["form"])):
        if r["form"][i] in forms:
            out.append({
                "form": r["form"][i],
                "filingDate": r["filingDate"][i],
                "reportDate": r["reportDate"][i],
                "accession": r["accessionNumber"][i],
                "primaryDoc": r["primaryDocument"][i],
                "isXBRL": bool(r["isXBRL"][i]),
            })
        if len(out) >= limit:
            break
    return out


def check_new_filings(cik_padded, since_date, forms=("10-K", "10-Q", "8-K")):
    """Filings newer than since_date (YYYY-MM-DD). The 'real-time' poll."""
    return [f for f in recent_filings(cik_padded, forms, limit=40)
            if f["filingDate"] > since_date]


def get_company_facts(cik_padded):
    """All XBRL facts for a company (us-gaap + dei). Large payload; cached by caller."""
    raw = _get(f"{BASE_DATA}/api/xbrl/companyfacts/CIK{cik_padded}.json")
    return json.loads(raw)


def filing_document_url(cik_int, accession, primary_doc):
    acc = accession.replace("-", "")
    return f"{BASE_WWW}/Archives/edgar/data/{cik_int}/{acc}/{primary_doc}"


def get_filing_text(cik_int, accession, primary_doc):
    """Raw text of a filing's primary document (HTML stripped lightly)."""
    import html as _html
    url = filing_document_url(cik_int, accession, primary_doc)
    raw = _get(url).decode("utf-8", errors="replace")
    raw = _html.unescape(raw)  # &#8217; -> ' etc., before stripping tags
    # light HTML strip; keep it fast and dependency-free
    raw = re.sub(r"(?is)<script.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    time.sleep(0.2)  # be polite to EDGAR
    return raw
