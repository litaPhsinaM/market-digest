"""Glossary topics + duplicate merging for the dictionary page.

data/glossary_meta.json maps a term (lowercase) to {"topic": key, "same_as": "other term" (optional)}. New terms are
classified once by the AI (cheap, one call for the batch); existing entries are never changed by it, so a hand fix sticks.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# key, label, emoji, what belongs there (also the AI's instructions)
TOPICS = [
    ("stocks", "Stocks & investing", "📈", "shares, funds, ETFs, index funds, IPOs, market cap, dividends, portfolios, asset classes"),
    ("trading", "Trading & charts", "📊", "chart indicators, trends, volume, volatility, corrections, short selling, how traders and hedge funds trade"),
    ("companies", "Companies & earnings", "🏢", "revenue, profit, margins, EPS, guidance, M&A, management, governance, business models"),
    ("banking", "Banking & loans", "🏦", "banks, deposits, credit, mortgages, loans, debt a person or company owes, credit scores"),
    ("economy", "Economy & the Fed", "🏛", "inflation, CPI, jobs, GDP, recessions, central banks, the Fed, interest-rate policy"),
    ("bonds", "Bonds & interest rates", "💵", "bonds, Treasuries, yields, basis points, duration, coupons, the yield curve"),
    ("policy", "Taxes, laws & policy", "🧾", "taxes, regulation, tariffs, export controls, government programs, elections' economic effects"),
    ("personal", "Personal finance", "👛", "budgeting, saving, emergency funds, retirement accounts, fees, compound growth, scams"),
    ("crypto", "Crypto", "🪙", "cryptocurrencies, wallets, exchanges, blockchain, stablecoins"),
    ("tech", "Tech & AI", "🤖", "AI, chips, GPUs, cloud, data centers, software and the tech industry's terms"),
    ("energy", "Energy & commodities", "⚡", "oil, gas, power, refining, metals, mining, farm goods, shipping"),
    ("other", "Everyday words", "📖", "words that aren't about money or markets (education, culture, science)"),
]
TOPIC_KEYS = [t[0] for t in TOPICS]
META = Path(__file__).resolve().parent.parent / "data" / "glossary_meta.json"


class Tag(BaseModel):
    term: str = Field(description="The term exactly as given.")
    topic: Literal[tuple(TOPIC_KEYS)] = Field(description="The one topic it belongs to.")
    same_as: str = Field(description="If this is the same idea as ANOTHER term in the list (a plural, abbreviation, or spelled-out "
                                     "version, e.g. 'CPI' vs 'Consumer Price Index (CPI)', 'Market cap' vs 'Market capitalization'), "
                                     "that other term exactly as listed; otherwise an empty string. Different ideas that are only "
                                     "related (inflation vs core inflation) are NOT the same.")


class GlossaryTags(BaseModel):
    tags: list[Tag]


PROMPT = """Sort these glossary terms from a beginner investing app into topics, and spot duplicates.
Topics:
{topics}
For each term give exactly one topic: where a beginner would look for it. Mark same_as only for true duplicates
(the same idea written differently); for each duplicate group, point every other spelling at the clearest one.

Terms (one per line):
{terms}"""


def load() -> dict:
    return json.loads(META.read_text()) if META.exists() else {}


def classify(terms: list[str]) -> dict:
    """Add topics for terms not in the meta file yet. Returns the full meta."""
    meta = load()
    new = sorted({t.strip() for t in terms if t.strip() and t.strip().lower() not in meta}, key=str.lower)
    if not new:
        return meta
    from digest import summarize
    topics = "\n".join(f"- {k}: {label} ({what})" for k, label, _, what in TOPICS)
    known = {t.lower(): t for t in new} | {k: k for k in meta}
    out = summarize._generate(PROMPT.format(topics=topics, terms="\n".join(new + [m for m in meta])), GlossaryTags)
    for tag in out.tags:
        key = tag.term.strip().lower()
        if key not in {t.lower() for t in new}:
            continue  # only fill in new terms; existing ones keep their (possibly hand-fixed) topic
        entry = {"topic": tag.topic}
        same = tag.same_as.strip().lower()
        if same and same != key and same in known:
            entry["same_as"] = same
        meta[key] = entry
    for t in new:  # anything the model skipped
        meta.setdefault(t.lower(), {"topic": "other"})
    META.write_text(json.dumps(dict(sorted(meta.items())), indent=1, ensure_ascii=False))
    print(f"Glossary: sorted {len(new)} new term(s) into topics")
    return meta
