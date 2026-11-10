"""Turn an episode/video into a learner-focused summary, and a set of summaries into a daily brief."""
import json
import os
import time
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
BACKEND = os.environ.get("DIGEST_BACKEND", "gemini")  # gemini | ollama


class KeyPoint(BaseModel):
    point: str = Field(description="One concrete idea or fact from the source, in plain English.")
    why_it_matters: str = Field(description="Why a learner/investor should care, in one or two sentences.")


class Figure(BaseModel):
    figure: str = Field(description="ONLY the number with its unit, as stated in the source, keeping its sign. Max ~12 characters, e.g. '-4.3%', '$3.2T', '1.8x'.")
    context: str = Field(description="One short sentence: what the number measures and how to read it.")


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
    numbers: list[Figure] = Field(description="The 3-5 MOST important figures stated in the source (never more than 5). Empty if none.")
    lesson: str = Field(description="A general investing/economics principle this teaches that still applies next year to OTHER companies, "
                                    "e.g. 'Adjusted earnings exclude costs management calls one-off; always compare them with GAAP earnings.' "
                                    "Do not just restate the news.")
    opinions_and_predictions: list[str] = Field(description="Claims that are opinion or forecast, attributed (e.g. 'Guest X expects...'). Empty if none.")
    tickers: list[str] = Field(description="Companies/tickers discussed substantively, e.g. 'Nvidia (NVDA)'. Empty if none.")
    glossary: list[Term] = Field(description="3-6 jargon terms used in the source that a beginner would not know.")
    level: str = Field(description="beginner | intermediate | advanced")
    topics: list[str] = Field(description="2-4 short lowercase topic tags, e.g. 'interest rates', 'ai stocks'.")


class Theme(BaseModel):
    title: str = Field(description="Concrete and specific, e.g. 'Streaming broke the sitcom business model', never abstract like 'The power of long-term thinking'.")
    explanation: str = Field(description="2-4 sentences on what the source(s) said and why it matters.")
    item_ids: list[str]


class Concept(BaseModel):
    concept: str = Field(description="A named finance/economics concept, e.g. 'Convertible debt', 'Syndication', 'Home-country bias'. Not a life lesson.")
    explanation: str = Field(description="A clear 4-6 sentence lesson: what it is, how it works, and how it showed up in today's sources.")


class DailyBrief(BaseModel):
    big_picture: str = Field(description="2-3 short sentences naming the most important things today. Plain, concrete, no grand unifying message.")
    themes: list[Theme] = Field(description="One theme per distinct topic. Merge stories ONLY when they are about the same subject (e.g. two episodes on the Fed).")
    concept_of_the_day: Concept
    watch_for: list[str] = Field(description="Specific upcoming events the sources named (an earnings date, a Fed meeting, a data release, an IPO). Empty if none were named.")


class HotTopic(BaseModel):
    title: str = Field(description="Specific, factual headline for ONE story, e.g. 'October inflation came in hotter than expected'. "
                                   "Never a category like 'AI and tech innovation' or 'Market volatility'.")
    explanation: str = Field(description="2-3 plain-English sentences on what is being reported, using only the headlines/blurbs given.")
    why_it_matters: str = Field(description="One sentence on why a learner/investor should care, with any jargon explained.")
    tickers: list[str] = Field(description="US stock tickers of listed companies central to this story, e.g. ['NVDA']. Only real, "
                                           "currently traded company tickers; no indexes, agencies or private companies. Empty if none.")
    headline_ids: list[str] = Field(description="ids of the 2-5 headlines this topic is built from.")


class HotTopics(BaseModel):
    topics: list[HotTopic] = Field(description="The 3-7 biggest specific business, market, economy and tech stories, most important first. "
                                               "Fewer is better than padding with vague topics.")


HOT_PROMPT = """You are a finance editor picking today's hottest stories for a beginner investor, from the newsroom
headlines below (JSON: id, source, title, blurb).
- Each topic is ONE specific news story (an event, a company, a data release), never a broad category.
  Group headlines about that same story together. Prefer stories reported by several outlets.
- Focus on markets, the economy, companies, deals, central banks and technology. Skip celebrity, sport and
  politics unless it clearly moves markets.
- You only have headlines and short blurbs: describe what is *reported*, and don't add facts or numbers
  that aren't in them.
- Describe, don't prescribe: never say what investors should do.

Headlines:
{headlines}"""

class QuizQuestion(BaseModel):
    question: str = Field(description="Tests understanding of a concept, term or number from today, not trivia like dates or names.")
    options: list[str] = Field(description="Exactly 4 short answer options; wrong ones must be plausible.")
    answer: int = Field(description="0-based index of the correct option.")
    explanation: str = Field(description="2 sentences: why the answer is right, teaching the idea. Reference today's story.")
    item_id: str = Field(description="id of the story or hot topic the question comes from.")


class Quiz(BaseModel):
    questions: list[QuizQuestion] = Field(description="Exactly 3 questions: one on a jargon term, one on what a number means, one on why a story matters.")


class Briefing(BaseModel):
    script: str = Field(description="The spoken script, 380-480 words.")


QUIZ_PROMPT = """You write a quick daily quiz for a beginner learning about markets, like Duolingo for finance.
From today's stories and hot topics below (JSON), write 3 multiple-choice questions.
- Test understanding ("What does a P/E of 20 mean?"), never memory of trivia ("On what date…").
- Every question must be answerable from the material; the explanation teaches the idea.
- Vary which option is correct.

Material:
{material}"""

BRIEFING_PROMPT = """Write a 3-minute spoken morning briefing (380-480 words) for a beginner investor, read aloud by a warm,
clear radio host. Use ONLY the material below (JSON).
- Open with "Good morning, this is Market Digest for {date}." then the biggest story.
- Cover the 3-4 most important stories, then end with today's concept explained simply, and a one-line sign-off.
- Write for the ear: short sentences, no lists, no markdown, no URLs, no tickers (say "Nvidia", not "NVDA").
  Write numbers the way you'd say them ("about six and a half billion dollars", "five percent").
- No investment advice.

Material:
{material}"""


def _material(items: list[dict], hot: dict | None) -> str:
    stories = [{"id": i["id"], "source": i["source_name"], **{k: i["summary"][k] for k in
                ("headline", "tldr", "key_points", "numbers", "lesson", "glossary")}} for i in items]
    topics = [{"id": f"hot-{n}", **{k: t[k] for k in ("title", "explanation", "why_it_matters")}}
              for n, t in enumerate((hot or {}).get("topics", []))]
    return json.dumps({"stories": stories, "hot_topics": topics}, indent=0)


def _generate(prompt: str, schema):
    return _ollama_generate(prompt, schema) if BACKEND == "ollama" else _gemini_generate([prompt], schema)


def quiz(items: list[dict], hot: dict | None) -> Quiz:
    q = _generate(QUIZ_PROMPT.format(material=_material(items, hot)), Quiz)
    q.questions = [x for x in q.questions if len(x.options) == 4 and 0 <= x.answer < 4][:3]
    return q


def briefing(items: list[dict], hot: dict | None, brief: dict | None, date_words: str) -> Briefing:
    material = json.loads(_material(items, hot))
    if brief:
        material["concept_of_the_day"] = brief["concept_of_the_day"]
    return _generate(BRIEFING_PROMPT.format(material=json.dumps(material, indent=0), date=date_words), Briefing)


MAX_TRANSCRIPT_WORDS = 22000  # ~2 h of speech; keeps long shows inside the local model's context

ITEM_PROMPT = """You are a patient finance teacher writing a daily study digest for a motivated beginner
who wants to understand markets, companies and the economy.

Summarize the {kind} below: "{title}" from {source}.

Rules:
- Use ONLY what is said in the source. Never invent numbers, names or facts. If unsure, leave it out.
- Skip sponsor reads, ads and housekeeping completely.
- Separate fact from opinion: put forecasts and personal views in opinions_and_predictions, attributed to who said them.
- Write in plain English. When a jargon word is unavoidable, explain it briefly in parentheses the first time.
- Be specific: "the Fed held rates at 4.25-4.5%" beats "the Fed made a decision". Keep negative signs on numbers.
- Be selective: a learner has 3 minutes for this. Quality over quantity in every list.
- This is education, not advice. Describe, don't prescribe: never tell the reader to buy, sell or "be cautious",
  and never write "investors should…". Attribute recommendations to the person who made them.
- Set worth_reading to false if the content is mostly hype, ads or filler; be honest."""

BRIEF_PROMPT = """You are a finance teacher writing today's 3-minute overview for a beginner, based ONLY on the
summaries below (JSON).
- Stories on unrelated topics stay separate. Never invent a common thread or a moral that ties them together;
  "today covered three unrelated topics" is a perfectly good answer.
- No filler or platitudes ("decisions are shaped by many factors", "long-term thinking matters"). Every sentence
  must contain a specific fact, name or number from the summaries.
- concept_of_the_day is the single most useful named finance concept from today, taught well.
- No investment advice. Refer to items by their id in item_ids.

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
        "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0.3, "num_ctx": 40960},
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return schema.model_validate_json(json.loads(r.read())["message"]["content"])


# ---------- public API ----------

def summarize_item(item, transcript: str | None = None, audio: Path | None = None) -> ItemSummary:
    s = _summarize_item(item, transcript, audio)
    # Models don't always respect list lengths; keep the page skimmable.
    s.key_points, s.numbers, s.glossary = s.key_points[:6], s.numbers[:5], s.glossary[:6]
    return s


def _summarize_item(item, transcript, audio) -> ItemSummary:
    if transcript:
        words = transcript.split()
        if len(words) > MAX_TRANSCRIPT_WORDS:
            transcript = " ".join(words[:MAX_TRANSCRIPT_WORDS]) + " [transcript truncated]"
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


def hot_topics(headlines: list[dict]) -> HotTopics:
    slim = [{k: h[k] for k in ("id", "source", "title", "blurb")} for h in headlines]
    prompt = HOT_PROMPT.format(headlines=json.dumps(slim, indent=0))
    gen = _ollama_generate if BACKEND == "ollama" else (lambda p, s: _gemini_generate([p], s))
    result = gen(prompt, HotTopics)
    valid = {h["id"] for h in headlines}
    for t in result.topics:  # drop hallucinated ids; a topic with no real headline behind it is dropped
        t.headline_ids = [i for i in t.headline_ids if i in valid]
    result.topics = [t for t in result.topics if t.headline_ids][:7]
    return result


def daily_brief(items: list[dict]) -> DailyBrief:
    slim = [{"id": i["id"], "source": i["source_name"], **{k: i["summary"][k] for k in
             ("headline", "tldr", "key_points", "lesson", "opinions_and_predictions")}} for i in items]
    prompt = BRIEF_PROMPT.format(summaries=json.dumps(slim, indent=1))
    if BACKEND == "ollama":
        return _ollama_generate(prompt, DailyBrief)
    return _gemini_generate([prompt], DailyBrief)
