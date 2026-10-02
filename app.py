"""SecMetrics web app — ticker search -> live SEC metrics dashboard.

Deploy: Railway / Render / Fly.io (see README.md in this dir).
Local:  pip install -r requirements.txt && python app.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, Response

import edgar_client as ed
import metrics as mx
import narrative as nv
import dashboard as db

app = Flask(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
FACTS_TTL = 24 * 3600      # company XBRL facts change only when new filings land
SUBMISSIONS_TTL = 3600     # filing index polled hourly


def _cached(name, ttl, fetch):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as f:
            return json.load(f)
    data = fetch()
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def _resolve(ticker):
    t = (ticker or "").strip().upper()
    if not t.isalnum() or len(t) > 6:
        raise ValueError("invalid ticker")
    return ed.ticker_to_cik(t)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return Response(SEARCH_PAGE, mimetype="text/html")


@app.get("/t/<ticker>")
def ticker_page(ticker):
    try:
        cik, cik_pad, company = _resolve(ticker)
    except ValueError as e:
        return Response(f"<h1>Ticker not found</h1><p>{e}</p>", status=404, mimetype="text/html")
    facts = _cached(f"facts_{cik_pad}.json", FACTS_TTL, lambda: ed.get_company_facts(cik_pad))
    m = mx.build_metrics(facts)
    filings = _cached(f"subs_{cik_pad}.json", SUBMISSIONS_TTL,
                      lambda: ed.recent_filings(cik_pad, forms=("10-K", "10-Q", "8-K"), limit=10))
    # narrative diff loads async via /api/narrative/<ticker> (filing HTML is slow)
    page = db.render_dashboard(company, ticker.upper(), m, filings, {})
    # inject async narrative loader before </body>
    t_up = ticker.upper()
    loader = ('<script>fetch("/api/narrative/' + t_up + '").then(r=>r.json()).then(d=>{'
              'var el=document.getElementById("narr");if(!el)return;'
              'el.innerHTML=d.html;}).catch(()=>{'
              'document.getElementById("narr").innerHTML="<div class=\\"none\\">Narrative unavailable.</div>";});</script>')
    page = page.replace('<h2>What changed in the narrative</h2>',
                        '<h2>What changed in the narrative</h2><div id="narr"><div class="none">Analyzing filing text…</div></div>')
    page = page.replace("</body>", loader + "</body>")
    return Response(page, mimetype="text/html")


@app.get("/api/metrics/<ticker>")
def api_metrics(ticker):
    try:
        _, cik_pad, company = _resolve(ticker)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    facts = _cached(f"facts_{cik_pad}.json", FACTS_TTL, lambda: ed.get_company_facts(cik_pad))
    m = mx.build_metrics(facts)
    return jsonify({"company": company, "ticker": ticker.upper(), "metrics": m})


@app.get("/api/filings/<ticker>")
def api_filings(ticker):
    try:
        _, cik_pad, company = _resolve(ticker)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    filings = _cached(f"subs_{cik_pad}.json", SUBMISSIONS_TTL,
                      lambda: ed.recent_filings(cik_pad, forms=("10-K", "10-Q", "8-K"), limit=20))
    return jsonify({"company": company, "ticker": ticker.upper(), "filings": filings})


@app.get("/api/narrative/<ticker>")
def api_narrative(ticker):
    try:
        cik, cik_pad, _ = _resolve(ticker)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    filings = ed.recent_filings(cik_pad, forms=("10-K", "10-Q"), limit=2)
    if len(filings) < 2:
        return jsonify({"html": '<div class="none">Not enough filings to compare.</div>'})
    new_f, old_f = filings[0], filings[1]
    new_text = ed.get_filing_text(cik, new_f["accession"], new_f["primaryDoc"])
    old_text = ed.get_filing_text(cik, old_f["accession"], old_f["primaryDoc"])
    parts = [f'<div class="none">Comparing {new_f["form"]} ({new_f["filingDate"]}) vs '
             f'{old_f["form"]} ({old_f["filingDate"]})</div>']
    import html as _h
    for section in ("mda", "risk_factors"):
        title = "MD&A — Management's Discussion" if section == "mda" else "Risk Factors"
        new_sec = nv.extract_section(new_text, section)
        old_sec = nv.extract_section(old_text, section)
        parts.append(f"<h3>{title}</h3>")
        if not (new_sec and old_sec):
            parts.append('<div class="none">Section not found in one of the filings.</div>')
            continue
        added, removed = nv.diff_narratives(old_sec, new_sec)
        def lis(items, cls):
            if not items:
                return '<div class="none">No material changes detected.</div>'
            return "<ul>" + "".join(f'<li class="{cls}">{_h.escape(s[:380])}</li>' for s in items) + "</ul>"
        parts.append("<h4>New / changed language</h4>" + lis(added, "added"))
        parts.append("<h4>Removed language</h4>" + lis(removed, "removed"))
    return jsonify({"html": "".join(parts)})


SEARCH_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SecMetrics — SEC filings into analyst metrics</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0f14;color:#e6edf3;font-family:-apple-system,system-ui,sans-serif;
display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:24px}
h1{font-size:30px;margin-bottom:6px}h1 span{color:#58a6ff}
p{color:#8b949e;margin-bottom:24px;text-align:center;max-width:420px;line-height:1.5}
form{display:flex;width:100%;max-width:420px;gap:8px}
input{flex:1;background:#161b22;border:1px solid #30363d;border-radius:10px;color:#e6edf3;
font-size:18px;padding:12px 16px;text-transform:uppercase}
button{background:#1f6feb;border:none;border-radius:10px;color:#fff;font-size:16px;padding:0 22px;cursor:pointer}
.tickers{margin-top:28px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
.tickers a{color:#58a6ff;text-decoration:none;background:#161b22;border:1px solid #30363d;
border-radius:20px;padding:6px 14px;font-size:14px}
.foot{margin-top:40px;color:#6e7681;font-size:12px;text-align:center;max-width:420px;line-height:1.6}
</style></head><body>
<h1>Sec<span>Metrics</span></h1>
<p>Type any US stock ticker. We pull its SEC filings and compute analyst-grade financial metrics on the spot.</p>
<form onsubmit="event.preventDefault();const t=document.getElementById('t').value.trim();if(t)location.href='/t/'+encodeURIComponent(t)">
<input id="t" placeholder="AAPL" maxlength="6" autocomplete="off"><button>Go</button></form>
<div class="tickers">
<a href="/t/AAPL">AAPL</a><a href="/t/MSFT">MSFT</a><a href="/t/NVDA">NVDA</a>
<a href="/t/TSLA">TSLA</a><a href="/t/AMZN">AMZN</a><a href="/t/GOOGL">GOOGL</a>
<a href="/t/META">META</a><a href="/t/JPM">JPM</a>
</div>
<div class="foot">Data: SEC EDGAR (public filings). Metrics computed from filed XBRL.<br>Not investment advice.</div>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
