"""Turn an episode/video into a learner-focused summary, and a set of summaries into a daily brief."""
from typing import Literal
import json
import re
import os
import threading
import time
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

# Gemini (free tier): each job goes to the model that did it best in our benchmark (2026-11-11, real episodes scored
# with checks.py / claims.py), then falls back on 404 (gone), 429 (daily quota used), 5xx (overloaded) or timeouts.
# Every free model has its OWN daily quota, so spreading jobs across models multiplies capacity.
#   3.6-flash        best writing (top stories, summaries) but a tiny quota  -> the two once-a-day jobs only
#   3-flash-preview  best at finding forecasts with real quotes, fast        -> forecasts, quiz
#   3.1-flash-lite   fastest, most reliable, clean summaries                 -> per-episode summaries, audio script
#   3.5-flash-lite   best transcription match vs Whisper                     -> transcripts
#   3.5-flash        good when it answers, but often overloaded (503)        -> fallback only
# Override any job with GEMINI_MODELS_<JOB>=model1,model2 (e.g. GEMINI_MODELS_SUMMARY), or all with GEMINI_MODEL.
_TASKS = {
    "summary":    "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.5-flash",
    "repair":     "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.5-flash",
    "forecasts":  "gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-3.5-flash",
    "top_stories": "gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.1-flash-lite",
    "brief":      "gemini-3.6-flash,gemini-3-flash-preview,gemini-3.5-flash,gemini-3.1-flash-lite",
    "quiz":       "gemini-3-flash-preview,gemini-3.5-flash,gemini-3.1-flash-lite",
    "audio_script": "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3-flash-preview",
}
# Which job an answer belongs to, from the shape we ask for.
_SCHEMA_TASK = {"ItemSummary": "summary", "Repair": "repair", "Claims": "forecasts", "HotTopics": "top_stories",
                "DailyBrief": "brief", "Quiz": "quiz", "Briefing": "audio_script", "GlossaryTags": "quiz"}
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")  # set to force one model first for every job
GEMINI_FALLBACKS = os.environ.get("GEMINI_FALLBACKS", "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.5-flash")
# Transcribing is long and mechanical: the lite models match Whisper ~86% at ~10 s per 8-minute episode.
GEMINI_TRANSCRIBE_MODELS = os.environ.get("GEMINI_TRANSCRIBE_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-lite-latest")
GEMINI_RPM = float(os.environ.get("GEMINI_RPM", "8"))  # pace requests under the free tier's per-minute limits
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
    # Field order matters: the model writes fields in this order, so listing segments first makes it read the whole
    # episode before summarizing, and the judgement fields come last.
    segments: list[str] = Field(description="FIRST, list every distinct story/segment of the source in order, max 8 words each "
                                            "(skip ads). E.g. 'Nvidia CEO affair probe', 'Mortgage rates at 7.18%', 'China consumer brands'.")
    headline: str = Field(description="A specific, informative headline naming the main subject, e.g. 'Nvidia falls 6% as spy scandal widens'. "
                                      "Never generic ('Key market updates', 'Market dynamics', '... and market dynamics'), no show name or date, "
                                      "no question. If the source covers several stories, name the top two concretely, e.g. "
                                      "'Anthropic sets $70-78 IPO range; Fed's Waller floats 50bp hike'.")
    tldr: str = Field(description="2-3 sentences: what this was about and the main takeaway.")
    key_points: list[KeyPoint] = Field(description="3-6 most important points, in order of importance. Cover the whole source: draw from every "
                                                   "substantive segment listed in segments, not just the first one. Use exact numbers and say "
                                                   "who said it when it is a guest's view.")
    numbers: list[Figure] = Field(description="The 3-5 MOST important market/economic/company figures, copied exactly as stated in the source "
                                              "(never more than 5). Include the comparison if given (vs expected, vs last year). Never add a "
                                              "date or year the source didn't say ('last year' stays 'last year'). Empty if none.")
    lesson: str = Field(description="A general investing/economics principle this teaches that still applies next year to OTHER companies. "
                                    "It must name a mechanism (cause → effect) a learner can reuse, and must not mention this episode, "
                                    "'investors' or 'should'. Bad: 'This episode highlights the importance of corporate governance.' "
                                    "Good: 'When a company's value is tied to one leader, the stock reacts to that person's risks (key-person "
                                    "risk); boards reduce it with succession plans.' Bad: 'Investing should be simple.' Good: 'Most active "
                                    "funds trail their index after fees, so low-cost index funds tend to win over long periods.'")
    opinions_and_predictions: list[str] = Field(description="Only forecasts and judgements, never reported facts. Attribute each to the person "
                                                            "who actually said it, with their role as introduced (e.g. 'Robert Armstrong (FT) "
                                                            "thinks...'); if unsure who said it, write 'a guest'. If the speaker has a stake "
                                                            "(e.g. invested in the company), say so. Empty if none.")
    tickers: list[str] = Field(description="Publicly traded companies discussed substantively, as 'Name (TICKER)', e.g. 'Nvidia (NVDA)', "
                                           "'Take-Two (TTWO)'. Use a ticker only if stated in the source or you are certain of it; otherwise "
                                           "give the name alone. Companies not yet listed (pre-IPO) get no ticker. Empty if none.")
    glossary: list[Term] = Field(description="3-6 jargon terms actually used in the source that a beginner would not know. Always include any "
                                             "jargon you used in key_points or lesson. Skip everyday words (bipartisan, semiconductors, "
                                             "valuations). The definition must be the correct general meaning, not this episode's spin.")
    level: str = Field(description="beginner | intermediate | advanced")
    topics: list[str] = Field(description="2-4 short lowercase topic tags, e.g. 'interest rates', 'ai stocks'.")
    quality_note: str = Field(description="One line about the SOURCE, not this summary (never write 'this digest'): who speaks (reporter, "
                                          "analyst, executive, investor with a stake) and whether claims are backed by data or are speculation.")
    worth_reading: bool = Field(description="False if the content is mostly ads, hype, filler or has no real substance.")


class Theme(BaseModel):
    title: str = Field(description="Concrete and specific, e.g. 'Streaming broke the sitcom business model', never abstract like 'The power of long-term thinking'.")
    explanation: str = Field(description="2-4 sentences on what the source(s) said and why it matters.")
    item_ids: list[str]


class Concept(BaseModel):
    concept: str = Field(description="A named finance/economics concept, e.g. 'Convertible debt', 'Syndication', 'Home-country bias'. Not a life lesson. "
                                     "Prefer a concept with a mechanism that appeared in a story today (e.g. adjusted vs GAAP earnings, dilution, "
                                     "amortization, key-person risk), not a generic one like diversification.")
    explanation: str = Field(description="A clear 4-6 sentence lesson: what it is, how it works, and how it showed up in today's sources.")


class DailyBrief(BaseModel):
    big_picture: str = Field(description="2-3 short sentences naming the most important things today. Plain, concrete, no grand unifying message.")
    themes: list[Theme] = Field(description="One theme per distinct topic. Merge stories ONLY when they are about the same subject (e.g. two episodes on the Fed).")
    concept_of_the_day: Concept
    watch_for: list[str] = Field(description="Dated or scheduled future events named in the summaries, each with its timing, e.g. 'Anthropic IPO "
                                             "prices Wed Nov 18, trades Nov 19', 'December Fed meeting: 25 vs 50bp hike'. Risks, analysis or "
                                             "restatements are NOT events. Empty if none.")


class HotTopic(BaseModel):
    title: str = Field(description="Specific, factual headline for ONE story, e.g. 'October inflation came in hotter than expected'. "
                                   "Never a category like 'AI and tech innovation' or 'Market volatility'.")
    explanation: str = Field(description="2-3 plain-English sentences on what is being reported, using only the headlines/blurbs given.")
    why_it_matters: str = Field(description="One sentence on why a learner/investor should care, with any jargon explained.")
    tickers: list[str] = Field(description="US stock tickers of listed companies central to this story, e.g. ['NVDA']. Only real, "
                                           "currently traded company tickers; no indexes, agencies or private companies. No crypto coins "
                                           "(BTC, ETH), ETFs (TLT), or not-yet-listed companies (Binance, Anthropic before trading). Empty if none.")
    beat: Literal["markets", "economy", "tech", "energy", "policy", "world"] = Field(
        description="The topic area: markets (companies, deals, earnings), economy (inflation, jobs, rates, central banks), "
                    "tech, energy (oil, gas, power, metals, mining, farm goods), policy (laws, regulation, elections, trade, "
                    "taxes), or world (other countries' economies and markets).")
    headline_ids: list[str] = Field(description="ids of the 2-5 headlines whose title or blurb is about THIS exact story (names the same "
                                                "company/event). Never repeat an id. Most headlines will not belong to any topic; leaving "
                                                "them unused is expected.")


class HotTopics(BaseModel):
    topics: list[HotTopic] = Field(description="The 4-8 biggest specific stories that matter to markets, most important first, spread "
                                               "across topic areas. Fewer is better than padding with vague topics.")


HOT_PROMPT = """You are a finance editor picking today's hottest stories for a beginner investor, from the newsroom
headlines below (JSON: id, source, beat, title, blurb).
- Each topic is ONE specific news story (an event, a company, a data release), never a broad category.
  Group headlines about that same story together. Prefer stories reported by several outlets.
- Cover the whole picture that moves markets, not just one story: companies and deals, the economy (inflation,
  jobs, interest rates, central banks), technology, energy and commodities (oil, gas, metals, mining, food),
  policy and politics (laws, regulation, trade, taxes, elections) and world economies. Each headline's "beat" says
  which desk it came from. When there is real news in them, include stories from at least 4 different areas.
- ONE topic per company or event: if a big story has several angles (a CEO quits, the stock falls, lawmakers
  react), fold them into that single topic instead of listing each angle separately.
- Skip celebrity, sport, crime and politics that doesn't affect markets or the economy.
- You only have headlines and short blurbs: describe what is *reported*, and don't add facts or numbers
  that aren't in them.
- Describe, don't prescribe: never say what investors should do.
- Never build a topic from a headline that doesn't mention it. A topic needs at least 2 headlines unless it's a
  major market-moving single report.

Headlines:
{headlines}"""

class Repair(BaseModel):
    headline: str = Field(description="Rewritten headline (or the original if it had no problem).")
    tldr: str = Field(description="Rewritten tldr (or the original if it had no problem).")
    lesson: str = Field(description="Rewritten lesson (or the original if it had no problem).")
    key_points: list[KeyPoint] = Field(description="Key points with any flagged date/number removed (otherwise unchanged).")
    opinions_and_predictions: list[str] = Field(description="Opinions with any flagged date/number removed (otherwise unchanged).")
    segments: list[str] = Field(description="Segments with any flagged date/number removed (otherwise unchanged).")
    quality_note: str = Field(description="Rewritten quality note (or the original if it had no problem).")


REPAIR_PROMPT = """An editor flagged problems in this summary of "{title}" ({source}). Fix ONLY the flagged fields and
return the others unchanged. Use only facts already in the summary.

Problems:
{problems}

Rules for the lesson: a reusable cause → effect principle that applies to other companies or situations; don't
mention the episode, "investors" or "should". Good example: "When a company's value is tied to one leader, the
stock reacts to that person's risks (key-person risk); boards reduce it with succession plans."

Summary (JSON):
{summary}"""


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
- Open with "Good morning, this is Stocksplain for {date}." then the biggest story.
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
- Episodes often have several unrelated segments. Cover all substantive segments, not just the first.
- Copy names and numbers exactly as spoken; do not convert "last year" into a year.
- Never write "investors should", "be cautious", or "cautionary tale"; describe what happened and why.
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


def _models(spec: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in spec.split(",") if m.strip()))


MODELS = _models(f"{GEMINI_MODEL},{GEMINI_FALLBACKS}")


def task_models(task: str | None) -> list[str]:
    """Models for a job, best first: forced GEMINI_MODEL, then GEMINI_MODELS_<JOB> or the benchmark's pick, then the
    general fallbacks so a job never fails just because its favourite models are busy."""
    pick = os.environ.get(f"GEMINI_MODELS_{(task or '').upper()}") or _TASKS.get(task or "", "")
    return _models(f"{GEMINI_MODEL},{pick},{GEMINI_FALLBACKS}")
last_model = None  # the model that wrote the most recent answer (recorded with each summary)
_dead: set[str] = set()  # models that are gone (404) or out of today's quota: not asked again this run
_last_call = 0.0


def _pace():
    global _last_call
    wait = _last_call + 60 / GEMINI_RPM - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _with_deadline(fn, seconds: float):
    """Run fn() but give up after `seconds`. The HTTP timeout alone isn't enough: a stalled Gemini request was seen
    holding the connection open for 10 minutes. The abandoned call finishes (or dies) in a daemon thread."""
    box = {}

    def run():
        try:
            box["ok"] = fn()
        except BaseException as e:
            box["err"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"no answer in {seconds:.0f}s")
    if "err" in box:
        raise box["err"]
    return box["ok"]


def _gemini_call(contents, cfg, parse, models=None, timeout=180, pauses=(0, 20, 60, 120)):
    """Ask each model in turn until one gives an answer `parse` accepts; if all fail, more rounds with backoff."""
    global last_model
    import httpx
    from google.genai import errors, types
    cfg = cfg.model_copy(update={"http_options": types.HttpOptions(timeout=timeout * 1000)})
    last = None
    for pause in pauses:
        live = [m for m in (models or MODELS) if m not in _dead]
        if not live:
            break
        if pause:
            print(f"    Gemini busy, retrying in {pause}s")
            time.sleep(pause)
        for model in live:
            _pace()
            try:
                resp = _with_deadline(lambda: _gemini().models.generate_content(model=model, contents=contents,
                                                                                config=cfg), timeout)
                out = parse(resp)
                last_model = model
                return out
            except errors.APIError as e:
                last = e
                if e.code == 404 or (e.code == 429 and "PerDay" in str(e)):
                    _dead.add(model)
                    print(f"    {model}: {'not available' if e.code == 404 else 'daily quota used up'}, skipping it")
                elif e.code in (429, 500, 502, 503, 504):
                    print(f"    {model}: {e.code}, trying the next model")
                else:
                    raise
            except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as e:
                last = e
                print(f"    {model}: {type(e).__name__}, trying the next model")
            except ValueError as e:  # empty/blocked answer, or JSON that doesn't fit the schema
                last = e
                print(f"    {model}: unusable answer ({' '.join(str(e).split())[:80]}), trying the next model")
    raise RuntimeError(f"no Gemini model answered: {last}") from last


def _gemini_generate(contents, schema):
    from google.genai import types
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=0.3,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
    )
    return _gemini_call(contents, cfg, lambda r: schema.model_validate_json(r.text or ""),
                        models=task_models(_SCHEMA_TASK.get(schema.__name__)))


TRANSCRIBE_PROMPT = """Transcribe this podcast episode word for word, in English, from start to finish.
- Everything that is said, including ads and intros. Do not summarize, shorten or skip anything.
- Plain text only: no timestamps, no speaker labels, no headings. Start a new paragraph when the speaker changes.
- Write numbers as digits, the way a newspaper would: 4.3%, $3.2 billion, 25 basis points, 2026."""


def transcribe(item, audio: Path) -> str | None:
    """Cloud stand-in for local Whisper: Gemini transcribes the audio, so the quality checks and the forecast quotes
    (claims.py) still have a transcript to verify against. None if it refused, failed or came back too short."""
    from google.genai import types
    cfg = types.GenerateContentConfig(response_mime_type="text/plain", temperature=0, max_output_tokens=65536)

    def parse(resp):
        text = (resp.text or "").strip()
        cand = resp.candidates[0] if resp.candidates else None
        reason = cand.finish_reason.name if cand and cand.finish_reason else "?"
        if not text:
            raise ValueError(f"no transcript (finish reason {reason})")
        return text + (" [transcript truncated]" if reason == "MAX_TOKENS" else "")

    try:
        f = _upload(audio)
    except Exception as e:
        print(f"    ! audio upload failed: {e}")
        return None
    try:
        text = _gemini_call([f, TRANSCRIBE_PROMPT], cfg, parse, models=_models(GEMINI_TRANSCRIBE_MODELS),
                            timeout=420, pauses=(0, 30))
    except Exception as e:
        print(f"    ! Gemini transcript failed: {e}")
        return None
    finally:
        try:
            _gemini().files.delete(name=f.name)
        except Exception:
            pass  # uploads expire on their own after 48 h
    minutes, words = (item.duration or 0) / 60, len(text.split())
    if minutes >= 3 and words < 60 * minutes:  # people speak ~150 words a minute
        print(f"    ! transcript too short ({words} words for {minutes:.0f} min)")
        return None
    return text


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

def _ctx_for(prompt: str) -> int:
    """Size the context to the input: a smaller KV cache is faster on short episodes."""
    return min(40960, max(8192, int(len(prompt.split()) * 1.4) + 4096))


def _ollama_generate(prompt: str, schema):
    body = json.dumps({
        "model": OLLAMA_MODEL, "stream": False, "think": False, "format": schema.model_json_schema(),
        "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0.3, "num_ctx": _ctx_for(prompt)},
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return schema.model_validate_json(json.loads(r.read())["message"]["content"])


# ---------- public API ----------

def summarize_item(item, transcript: str | None = None, audio: Path | None = None) -> ItemSummary:
    from digest import checks
    s = _summarize_item(item, transcript, audio)
    # Models don't always respect list lengths; keep the page skimmable.
    s.key_points, s.numbers, s.glossary = s.key_points[:6], s.numbers[:5], s.glossary[:6]
    # Segments are short tags ("Nvidia CEO affair probe"); models sometimes write whole paragraphs.
    s.segments = [" ".join(re.split(r"[.,;:]\s", g, maxsplit=1)[0].split()[:9]) for g in s.segments][:10]
    d = s.model_dump()
    problems = checks.check_item(d, transcript) if transcript else []
    if problems:
        print("    ↻ repairing: " + "; ".join(p.split(":")[0] for p in problems))
        keep = {k: d[k] for k in ("headline", "tldr", "lesson", "key_points", "opinions_and_predictions", "quality_note", "segments")}
        fix = _generate(REPAIR_PROMPT.format(title=item.title, source=item.source_name, problems="\n".join(f"- {p}" for p in problems),
                                             summary=json.dumps(keep, indent=1)), Repair)
        d.update(fix.model_dump())
        left = [p for p in checks.check_item(d, transcript)]
        if left:
            print("    ! still flagged after repair: " + "; ".join(p.split(":")[0] for p in left))
    return ItemSummary.model_validate(d)


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
    slim = [{k: h.get(k, "") for k in ("id", "source", "beat", "title", "blurb")} for h in headlines]
    prompt = HOT_PROMPT.format(headlines=json.dumps(slim, indent=0))
    gen = _ollama_generate if BACKEND == "ollama" else (lambda p, s: _gemini_generate([p], s))
    result = gen(prompt, HotTopics)
    valid = {h["id"] for h in headlines}
    for t in result.topics:  # drop hallucinated ids; a topic with no real headline behind it is dropped
        t.headline_ids = [i for i in t.headline_ids if i in valid]
    from digest import checks
    kept = checks.check_hot([t.model_dump() for t in result.topics], {h["id"]: h for h in headlines})
    return HotTopics(topics=[HotTopic(**t) for t in kept][:8])


def daily_brief(items: list[dict]) -> DailyBrief:
    slim = [{"id": i["id"], "source": i["source_name"], **{k: i["summary"][k] for k in
             ("headline", "tldr", "key_points", "numbers", "lesson", "opinions_and_predictions")}} for i in items]
    prompt = BRIEF_PROMPT.format(summaries=json.dumps(slim, indent=1))
    if BACKEND == "ollama":
        return _ollama_generate(prompt, DailyBrief)
    return _gemini_generate([prompt], DailyBrief)
