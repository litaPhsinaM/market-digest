"""US stock market (NYSE/Nasdaq) trading hours in New York time: weekends, holidays and 1 pm early closes.
No dependencies, so the price workflow can ask "is the market open?" before installing anything:
  python3 digest/hours.py        # prints open|closed and exits 0 if a price update should run now
Keep CLOSED / EARLY in sync with templates/features.js (MD.market) and supabase/migrations/014_*.
Source: NYSE holiday calendar (nyse.com/markets/hours-calendars). Add the next year before it starts.
"""
import datetime as dt
import sys
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CLOSED = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
}
EARLY = {"2026-11-27", "2026-12-24", "2027-11-26"}  # close at 1:00 pm ET


def session(day: dt.date):
    """(open, close) as New York datetimes for a trading day, or None if the market is closed all day."""
    if day.weekday() >= 5 or day.isoformat() in CLOSED:
        return None
    close = dt.time(13, 0) if day.isoformat() in EARLY else dt.time(16, 0)
    return dt.datetime.combine(day, dt.time(9, 30), NY), dt.datetime.combine(day, close, NY)


def is_open(now: dt.datetime | None = None) -> bool:
    now = (now or dt.datetime.now(NY)).astimezone(NY)
    s = session(now.date())
    return bool(s) and s[0] <= now <= s[1]


if __name__ == "__main__":
    # The price job runs from the open until 15 minutes after the close, so the closing price is captured.
    now = dt.datetime.now(NY)
    s = session(now.date())
    ok = bool(s) and s[0] <= now <= s[1] + dt.timedelta(minutes=15)
    print(("open" if ok else "closed") + f" ({now:%a %Y-%m-%d %H:%M} ET)")
    sys.exit(0 if ok else 1)
