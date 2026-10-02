"""Narrative analyzer: extract MD&A + Risk Factors from a filing and diff
against the prior period's filing.

This is the 'AI' layer of the prototype in its honest form: deterministic
NLP (section extraction + sentence-level change detection) that surfaces
*what changed* in management's own words. A production version would add an
LLM summarizer on top of these diffs.
"""
import difflib
import re

SECTION_PATTERNS = {
    "mda": [
        r"management.s discussion and analysis of financial condition and results of operations",
    ],
    "risk_factors": [
        r"risk factors",
    ],
}

# where each section typically ends (next item header)
END_HINTS = [
    r"quantitative and qualitative disclosures about market risk",
    r"unresolved staff comments",
    r"properties",
    r"legal proceedings",
    r"mine safety disclosures",
    r"controls and procedures",
    r"financial statements and supplementary data",
    r"changes in and disagreements with accountants",
]


def _normalize(text):
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text


def extract_section(full_text, section):
    """Pull a named section out of filing text. Returns '' if not found."""
    low = _normalize(full_text)
    starts = []
    for pat in SECTION_PATTERNS[section]:
        starts.extend(m.start() for m in re.finditer(pat, low))
    if not starts:
        return ""
    # last match: skips the Table of Contents entry near the front
    start = max(starts)
    # find the earliest end-hint after start
    end = len(low)
    for hint in END_HINTS:
        m = re.search(hint, low[start + 200:])
        if m and start + 200 + m.start() < end:
            end = start + 200 + m.start()
    # map back to original text approximately via length ratio
    ratio = len(full_text) / max(len(low), 1)
    snippet = full_text[int(start * ratio):int(end * ratio)]
    # cap length to keep diffs sane
    return snippet[:60000]


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) > 40:  # skip fragments / table debris
            out.append(p)
    return out


def diff_narratives(old_text, new_text, max_items=8):
    """Sentence-level diff. Returns (added, removed) sentence lists."""
    old_s = sentences(old_text)
    new_s = sentences(new_text)
    sm = difflib.SequenceMatcher(a=old_s, b=new_s, autojunk=False)
    added, removed = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added.extend(new_s[j1:j2])
        elif tag == "delete":
            removed.extend(old_s[i1:i2])
        elif tag == "replace":
            added.extend(new_s[j1:j2])
            removed.extend(old_s[i1:i2])
    # prefer longer, meatier sentences
    added.sort(key=len, reverse=True)
    removed.sort(key=len, reverse=True)
    return added[:max_items], removed[:max_items]


def keyword_hits(text, keywords):
    """Count analyst-relevant keyword mentions (risk radar)."""
    low = text.lower()
    return {k: len(re.findall(r"\b" + re.escape(k.lower()) + r"\b", low)) for k in keywords}


RISK_KEYWORDS = ["litigation", "regulatory", "tariff", "supply chain", "cybersecurity",
                 "impairment", "restructuring", "going concern", "inflation",
                 "foreign exchange", "antitrust", "data breach"]
