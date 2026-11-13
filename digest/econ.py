"""'Economy this week': the latest official US economic numbers and the next data releases, from FRED.

FRED (Federal Reserve Bank of St. Louis) republishes government statistics. Only public-domain series from US
agencies (BLS, the Fed, Treasury, EIA) are used: some FRED series belong to private companies and can't be shown.
Needs FRED_API_KEY (free); without it this step is skipped. Credit "Source: FRED, Federal Reserve Bank of St. Louis".
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

API = "https://api.stlouisfed.org/fred/"

# id, label, how to read the latest value, plain-English explanation. (The 10-year yield is already in the market card.)
SERIES = [
    ("CPIAUCSL", "Inflation", "yoy",
     "How much prices rose over the past 12 months (consumer price index). The Fed aims for about 2%."),
    ("UNRATE", "Unemployment", "level",
     "Share of people who want a job but don't have one. Low means a strong job market."),
    ("PAYEMS", "Jobs added", "diff",
     "How many jobs US employers added last month (nonfarm payrolls), in thousands."),
    ("DFEDTARU", "Fed interest rate", "level",
     "The top of the Federal Reserve's target rate. Higher rates make borrowing costlier and can cool prices."),
    ("GASREGW", "Gas price", "dollars",
     "Average US price of a gallon of regular gas, weekly. A quick read on energy costs for households."),
]

# FRED release id → friendly name, for the "coming up" list. Government releases only.
RELEASES = {
    10: "Inflation report (CPI)", 50: "Jobs report", 53: "GDP (economic growth)",
    54: "PCE inflation and consumer spending", 46: "Wholesale prices (PPI)", 9: "Retail sales",
    180: "Weekly jobless claims", 13: "Factory output", 192: "Job openings (JOLTS)",
}


def _get(path: str, **params) -> dict:
    params.update(api_key=os.environ["FRED_API_KEY"], file_type="json")
    with urllib.request.urlopen(API + path + "?" + urllib.parse.urlencode(params), timeout=20) as r:
        return json.load(r)


def _obs(series: str, n: int = 14) -> list[tuple[str, float]]:
    rows = _get("series/observations", series_id=series, sort_order="desc", limit=n)["observations"]
    return [(o["date"], float(o["value"])) for o in rows if o["value"] not in (".", "")]


FREQ = {"CPIAUCSL": "M", "UNRATE": "M", "PAYEMS": "M", "DFEDTARU": "D", "GASREGW": "W"}


def _freq(sid: str) -> str:
    return FREQ.get(sid, "")


def indicators() -> list[dict]:
    out = []
    for sid, label, kind, explain in SERIES:
        try:
            obs = _obs(sid, 26)
        except Exception as e:
            print(f"! FRED {sid}: {e}")
            continue
        if len(obs) < 2:
            continue
        (d0, v0), (d1, v1) = obs[0], obs[1]
        if kind == "yoy":  # monthly index → % change vs the same month a year earlier (matched by date: months can be missing)
            by_date = dict(obs)
            ago = lambda d: f"{int(d[:4]) - 1}{d[4:]}"
            if ago(d0) in by_date and ago(d1) in by_date:
                value, prev = (v0 / by_date[ago(d0)] - 1) * 100, (v1 / by_date[ago(d1)] - 1) * 100
                text, unit = f"{value:.1f}%", "%"
            else:  # a year-ago month was never published (e.g. Oct 2025, government shutdown): show the monthly change
                value, prev = (v0 / v1 - 1) * 100, (v1 / obs[2][1] - 1) * 100
                text, unit = f"{value:+.1f}%", "%"
                label = "Inflation (this month)"
                explain = ("How much prices rose in the latest month (consumer price index). The yearly rate can't be "
                           "calculated because the government didn't publish data for the same month last year.")
        elif kind == "diff":  # total employment → change from the month before
            value, prev = v0 - v1, v1 - obs[2][1]
            text, unit = f"{value:+,.0f}K", "K"
        elif kind == "dollars":
            value, prev = v0, v1
            text, unit = f"${value:.2f}", "$"
        else:
            value, prev = v0, v1
            text, unit = (f"{value:.1f}%" if sid == "UNRATE" else f"{value:.2f}%"), "%"
        vs = {"M": "last month", "W": "last week"}.get(_freq(sid), "")
        fmt = {"K": lambda x: f"{x:+,.0f}K", "$": lambda x: f"${x:.2f}"}.get(unit, lambda x: f"{x:.1f}%" if kind != "level" or sid == "UNRATE" else f"{x:.2f}%")
        if kind == "yoy" and text.startswith(("+", "-")):
            fmt = lambda x: f"{x:+.1f}%"
        change = "" if not vs else (f"same as {vs}" if fmt(prev) == text else f"{'up' if value > prev else 'down'} from {fmt(prev)} {vs}")
        out.append({"id": sid, "label": label, "vs": vs, "change": change, "value": round(value, 3), "prev": round(prev, 3), "text": text,
                    "unit": unit, "date": d0, "explain": explain, "url": f"https://fred.stlouisfed.org/series/{sid}"})
    return out


def upcoming(today: str, days: int = 14) -> list[dict]:
    end = (dt.date.fromisoformat(today) + dt.timedelta(days=days)).isoformat()
    rows = _get("releases/dates", realtime_start=today, realtime_end=end, include_release_dates_with_no_data="true",
                sort_order="asc", limit=1000)["release_dates"]
    seen, out = set(), []
    for r in rows:
        rid = int(r["release_id"])
        if rid in RELEASES and (rid, r["date"]) not in seen and r["date"] >= today:
            seen.add((rid, r["date"]))
            out.append({"date": r["date"], "name": RELEASES[rid], "release_id": rid})
    out.sort(key=lambda x: x["date"])
    # weekly jobless claims appear every week; keep only the next one so the bigger reports stay visible
    claims = [x for x in out if x["release_id"] == 180]
    return [x for x in out if x["release_id"] != 180 or x is (claims[0] if claims else None)][:8]


def snapshot(today: str) -> dict | None:
    if not os.environ.get("FRED_API_KEY"):
        print("  (no FRED_API_KEY, skipping the economy card)")
        return None
    ind = indicators()
    try:
        cal = upcoming(today)
    except Exception as e:
        print(f"! FRED release calendar: {e}")
        cal = []
    return {"date": today, "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "indicators": ind, "upcoming": cal} if ind else None
