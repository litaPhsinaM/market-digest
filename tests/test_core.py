"""Core safety tests: the NYSE calendar, the fact checks, and forecast parsing.
Run: .venv/bin/python -m pytest -q"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from digest import checks, claims, hours

NY = ZoneInfo("America/New_York")


# ---------- market hours (prices fill trades only when the market is really open) ----------

@pytest.mark.parametrize("when, open_", [
    ("2026-11-12 10:00", True),    # Thursday, regular session
    ("2026-11-12 09:29", False),   # one minute before the open
    ("2026-11-12 16:01", False),   # after the close
    ("2026-11-14 12:00", False),   # Saturday
    ("2026-11-26 12:00", False),   # Thanksgiving
    ("2026-11-27 12:30", True),    # day after Thanksgiving, early close at 1 pm
    ("2026-11-27 13:30", False),   # ...so closed by 1:30 pm
    ("2026-12-25 12:00", False),   # Christmas
])
def test_market_open(when, open_):
    assert hours.is_open(dt.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=NY)) is open_


def test_session_times():
    assert hours.session(dt.date(2026, 11, 14)) is None                      # weekend
    o, c = hours.session(dt.date(2026, 11, 27))
    assert (o.hour, o.minute, c.hour) == (9, 30, 13)                         # early close
    assert hours.session(dt.date(2026, 11, 12))[1].hour == 16                # normal close


# ---------- fact checks (numbers, dates, advice must come from / respect the source) ----------

def summary(**over):
    s = {"headline": "Nvidia shares fall after CEO scandal", "tldr": "Nvidia fell 30% after the scandal.",
         "key_points": [{"point": "Shares fell 30%.", "why_it_matters": "Leadership risk."}],
         "numbers": [{"figure": "30%", "context": "drop since October"}],
         "opinions_and_predictions": [], "segments": [], "tickers": [],
         "lesson": "When a company depends on one leader, doubts about that person move the stock.",
         "quality_note": "An analyst speaking; the figures are data-backed."}
    s.update(over)
    return s


TRANSCRIPT = "Nvidia is off more than 30% since the scandal broke in October."


def test_clean_summary_passes():
    assert checks.check_item(summary(), TRANSCRIPT) == []


def test_invented_figure_is_dropped():
    s = summary(numbers=[{"figure": "45%", "context": "made-up drop"}, {"figure": "30%", "context": "real"}])
    checks.check_item(s, TRANSCRIPT)
    assert [n["figure"] for n in s["numbers"]] == ["30%"]


def test_invented_number_in_prose_is_flagged():
    problems = checks.check_item(summary(tldr="Nvidia fell 42% after the scandal."), TRANSCRIPT)
    assert any("42" in p for p in problems)


def test_invented_date_is_flagged():
    problems = checks.check_item(summary(tldr="Nvidia fell 30% on November 3rd."), TRANSCRIPT)
    assert any("November 3rd" in p for p in problems)


def test_advice_is_flagged():
    problems = checks.check_item(summary(tldr="Investors should buy the dip: Nvidia fell 30%."), TRANSCRIPT)
    assert any("advice" in p for p in problems)


def test_recap_lesson_is_flagged():
    problems = checks.check_item(summary(lesson="This episode covers Nvidia's scandal."), TRANSCRIPT)
    assert any("lesson" in p for p in problems)


# ---------- forecasts (Scorecard): deadlines, kinds, quotes ----------

SAID = dt.date(2026, 11, 10)


@pytest.mark.parametrize("iso, said, expected", [
    ("2026-12-17", "", dt.date(2026, 12, 17)),
    ("none", "by year end", dt.date(2026, 12, 31)),
    ("none", "next year", dt.date(2027, 12, 31)),
    ("none", "at the December meeting", dt.date(2026, 12, 31)),
    ("none", "early 2028", dt.date(2028, 3, 31)),
    ("none", "not specified", None),
])
def test_deadlines(iso, said, expected):
    assert claims.resolve_deadline(iso, said, SAID) == expected


@pytest.mark.parametrize("text, kind", [
    ("The Fed will hike rates in December", "rate_hike"),
    ("The Fed will ease policy next year", "rate_cut"),
    ("M&A activity will increase next year", "other"),   # 'increase' must not read as a Fed 'ease'
    ("Stocks will rally into year end", "up"),
])
def test_infer_kind(text, kind):
    assert claims.infer_kind("other", text) == kind


def test_quote_must_be_in_transcript():
    flat = claims._norm("I think the Fed will raise rates by fifty basis points at the December meeting, honestly.")
    assert claims.quote_in("the Fed will raise rates by fifty basis points at the December meeting", flat)
    assert claims.quote_in("the Fed will raise rates by 50 basis points at the December meeting", flat)  # one word off
    assert not claims.quote_in("the Fed will cut rates sharply in the spring because inflation is falling", flat)


# ---------- model routing (each morning job goes to the model that's best at it, with fallbacks) ----------

def test_each_job_has_its_own_first_choice_and_fallbacks():
    from digest import summarize
    firsts = {t: summarize.task_models(t)[0] for t in ("summary", "forecasts", "top_stories", "brief", "quiz", "audio_script")}
    assert firsts["forecasts"] == "gemini-3-flash-preview"
    assert firsts["brief"] == "gemini-3.6-flash"
    for t in firsts:
        assert len(summarize.task_models(t)) >= 4          # never a single point of failure
        assert "gemini-3.1-flash-lite" in summarize.task_models(t)


def test_every_answer_shape_maps_to_a_job():
    from digest import summarize
    for schema in (summarize.ItemSummary, summarize.Quiz, summarize.Briefing, summarize.DailyBrief, summarize.HotTopics):
        assert schema.__name__ in summarize._SCHEMA_TASK


def test_forecast_prompt_rejects_facts_and_moods():
    for phrase in ("already happened", "descriptions of the present", "vague moods", "List each forecast once"):
        assert phrase in claims.PROMPT
