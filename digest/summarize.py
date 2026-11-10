"""Turn an episode/video into a learner-focused summary, and a set of summaries into a daily brief."""
import json
import os
import time
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
BACKEND = os.environ.get("DIGEST_BACKEND", "gemini")  # gemini | ollama


class KeyPoint(BaseModel):
    point: str = Field(description="One concrete idea or fact from the source, in plain English.")
    why_it_matters: str = Field(description="Why a learner/investor should care, in one or two sentences.")


class Figure(BaseModel):
    figure: str = Field(description="A number exactly as stated in the source, e.g. '4.25%', '$3.2 trillion'.")
    context: str = Field(description="What the number measures and how to read it.")


class Term(BaseModel):
    term: str
    definition: str = Field(description="Plain-English definition a smart 16-year-old would understand.")
    example: str = Field(description="A short concrete example, ideally from this source.")


class ItemSummary(BaseModel):
    worth_reading: bool = Field(description="False if the content is mostly ads, hype, filler or has no real substance.")
    quality_note: str = Field(description="One line on the source's evidence quality, e.g. 'interviews a Fed economist; data-backed' or 'mostly host speculation'.")
    headline: str = Field(description="A specific, informative headline. No clickbait.")
    tldr: str = Field(description="2-3 sentences: what this was about and the main takeaway.")
    key_points: list[KeyPoint] = Field(description="3-6 most important points, in order of importance.")
    numbers: list[Figure] = Field(description="Up to 5 key figures stated in the source. Empty if none.")
    lesson: str = Field(description="The evergreen concept a learner should take away, beyond today's news.")
    opinions_and_predictions: list[str] = Field(description="Claims that are opinion or forecast, attributed (e.g. 'Guest X expects...'). Empty if none.")
    tickers: list[str] = Field(description="Companies/tickers discussed substantively, e.g. 'Nvidia (NVDA)'. Empty if none.")
    glossary: list[Term] = Field(description="3-6 jargon terms used in the source that a beginner would not know.")
    level: str = Field(description="beginner | intermediate | advanced")
    topics: list[str] = Field(description="2-4 short lowercase topic tags, e.g. 'interest rates', 'ai stocks'.")


class Theme(BaseModel):
    title: str
    explanation: str = Field(description="3-5 sentences connecting what the sources said on this theme.")
    item_ids: list[str]


class Concept(BaseModel):
    concept: str
    explanation: str = Field(description="A clear 4-6 sentence lesson, with an example drawn from today's sources.")


class DailyBrief(BaseModel):
    big_picture: str = Field(description="3-4 sentences: what mattered today and how it connects.")
    themes: list[Theme] = Field(description="2-4 themes across the sources. Only themes with real substance.")
    concept_of_the_day: Concept
    watch_for: list[str] = Field(description="Upcoming events/data the sources flagged as worth watching. Empty if none.")


ITEM_PROMPT = """You are a patient finance teacher writing a daily study digest for a motivated beginner
who wants to understand markets, companies and the economy.

Summarize the {kind} below: "{title}" from {source}.

Rules:
- Use ONLY what is said in the source. Never invent numbers, names or facts. If unsure, leave it out.
- Skip sponsor reads, ads and housekeeping completely.
- Separate fact from opinion: put forecasts and personal views in opinions_and_predictions, attributed to who said them.
- Write in plain English. When a jargon word is unavoidable, explain it briefly in parentheses the first time.
- Be specific: "the Fed held rates at 4.25-4.5%" beats "the Fed made a decision".
- This is education, not advice. Never tell the reader to buy or sell anything.
- Set worth_reading to false if the content is mostly hype, ads or filler; be honest."""

BRIEF_PROMPT = """You are a finance teacher writing today's 3-minute overview for a beginner, based ONLY on the
summaries below (JSON). Connect the dots between sources where they genuinely overlap; don't force links.
Pick the single most useful concept from today as concept_of_the_day and teach it well.
No investment advice. Refer to items by their id in item_ids.

Summaries:
{summaries}"""


# ---------- Gemini ----------

_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _gemini_generate(contents, schema):
    from google.genai import types, errors
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=0.3,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
    )
    for attempt in range(4):
        try:
            resp = _gemini().models.generate_content(model=GEMINI_MODEL, contents=contents, config=cfg)
            return schema.model_validate_json(resp.text)
        except errors.APIError as e:
            if e.code in (429, 500, 503) and attempt < 3:
                wait = 30 * (attempt + 1)
                print(f"    Gemini {e.code}, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise


def _upload(path: Path):
    client = _gemini()
    f = client.files.upload(file=str(path))
    while f.state.name == "PROCESSING":
        time.sleep(3)
        f = client.files.get(name=f.name)
    if f.state.name != "ACTIVE":
        raise RuntimeError(f"upload failed: {f.state.name}")
    return f


# ---------- Ollama (text only) ----------

def _ollama_generate(prompt: str, schema):
    body = json.dumps({
        "model": OLLAMA_MODEL, "stream": False, "think": False, "format": schema.model_json_schema(),
        "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0.3, "num_ctx": 32768},
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return schema.model_validate_json(json.loads(r.read())["message"]["content"])


# ---------- public API ----------

def summarize_item(item, transcript: str | None = None, audio: Path | None = None) -> ItemSummary:
    prompt = ITEM_PROMPT.format(kind="video" if item.kind == "youtube" else "podcast episode",
                                title=item.title, source=item.source_name)
    if BACKEND == "ollama":
        if not transcript:
            raise RuntimeError("ollama backend needs a text transcript")
        return _ollama_generate(f"{prompt}\n\nTranscript:\n{transcript}", ItemSummary)

    from google.genai import types
    if transcript:
        return _gemini_generate([prompt, f"Transcript:\n{transcript}"], ItemSummary)
    if audio:
        f = _upload(audio)
        try:
            return _gemini_generate([f, prompt], ItemSummary)
        finally:
            _gemini().files.delete(name=f.name)
    # No captions: let Gemini watch the YouTube video directly.
    video = types.Part(file_data=types.FileData(file_uri=item.media_url))
    return _gemini_generate([video, prompt], ItemSummary)


def daily_brief(items: list[dict]) -> DailyBrief:
    slim = [{"id": i["id"], "source": i["source_name"], **{k: i["summary"][k] for k in
             ("headline", "tldr", "key_points", "lesson", "opinions_and_predictions")}} for i in items]
    prompt = BRIEF_PROMPT.format(summaries=json.dumps(slim, indent=1))
    if BACKEND == "ollama":
        return _ollama_generate(prompt, DailyBrief)
    return _gemini_generate([prompt], DailyBrief)
