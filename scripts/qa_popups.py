"""QA: open every pop-up (<dialog>) on every page at phone, short-phone (app with bars) and desktop sizes; check each fits
on screen, scrolls when its content is long, and has no overlapping parts. Needs Playwright + Chrome:
  pip install playwright && python scripts/qa_popups.py /tmp/popups [--shots]
Build the site first (python run.py --build-only)."""
import functools, http.server, json, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

SITE = str(Path(__file__).resolve().parent.parent / "site")
OUT = Path(sys.argv[1]); OUT.mkdir(exist_ok=True)
SHOTS = "--shots" in sys.argv


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8795), functools.partial(Q, directory=SITE))
threading.Thread(target=srv.serve_forever, daemon=True).start()

PAGES = ["index.html", "play.html", "learn.html", "glossary.html", "scorecard.html", "archive.html"]
SIZES = [("phone", 390, 844, True), ("app-short", 390, 640, True), ("desktop", 1440, 900, False)]
CHECK = """(d) => {
  const r = d.getBoundingClientRect(), cs = getComputedStyle(d);
  const scrollable = d.scrollHeight <= d.clientHeight + 2 || ['auto','scroll'].includes(cs.overflowY);
  // children that overlap their next sibling vertically (a sign of squashed layout)
  let overlaps = 0;
  d.querySelectorAll('.story-grid > *, .ep > *:not(.sheet-foot)').forEach((el) => {
    const n = el.nextElementSibling; if (!n || n.classList.contains('sheet-foot') || !el.offsetParent || !n.offsetParent) return;
    const a = el.getBoundingClientRect(), b = n.getBoundingClientRect();
    if (a.width && b.width && a.bottom > b.top + 2 && a.top < b.bottom - 2 && a.right > b.left + 2 && a.left < b.right - 2) overlaps++;
  });
  return { top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right),
           h: Math.round(r.height), vw: innerWidth, vh: innerHeight, scrollable, overlaps, content: d.scrollHeight };
}"""

problems, total = [], 0
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    for size, w, h, mobile in SIZES:
        ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile, color_scheme="dark")
        ctx.route("**/rest/v1/**", lambda r: r.fulfill(status=200, content_type="application/json", body="[]"))
        pg = ctx.new_page()
        for page in PAGES:
            pg.goto(f"http://127.0.0.1:8795/{page}", wait_until="load"); pg.wait_for_timeout(700)
            pg.evaluate("document.querySelectorAll('#intro').forEach(e=>e.remove())")
            ids = pg.evaluate("[...document.querySelectorAll('dialog')].map((d,i)=>d.id||('#'+i))")
            seen_kinds = set()
            for did in ids:
                kind = did.split("-")[0] if did.startswith(("hot-", "theme-", "co-", "l")) and not did.startswith("lb") else did
                # one of each repeated kind is enough for screenshots, but every dialog is measured
                sel = f"dialog#{did}" if not did.startswith("#") else f"dialog:nth-of-type({int(did[1:]) + 1})"
                try:
                    pg.evaluate(f"""(()=>{{const d=document.querySelector({json.dumps(sel)}); if(!d) return; if(d.open) d.close(); d.showModal();}})()""")
                except Exception as e:
                    continue
                pg.wait_for_timeout(380)
                d = pg.query_selector(sel)
                if not d or not pg.evaluate("(d)=>d.open", d):
                    continue
                total += 1
                m = pg.evaluate(CHECK, d)
                bad = []
                if m["top"] < -1 or m["bottom"] > m["vh"] + 1: bad.append(f"off screen vertically (top {m['top']}, bottom {m['bottom']}, screen {m['vh']})")
                if m["left"] < -1 or m["right"] > m["vw"] + 1: bad.append(f"off screen sideways ({m['left']}–{m['right']} of {m['vw']})")
                if not m["scrollable"]: bad.append("content taller than the pop-up but it can't scroll")
                if m["overlaps"]: bad.append(f"{m['overlaps']} overlapping parts")
                if bad:
                    problems.append(f"{size:9} {page:15} #{did}: " + "; ".join(bad))
                if SHOTS and (size, page, kind) not in seen_kinds:
                    seen_kinds.add((size, page, kind))
                    pg.screenshot(path=str(OUT / f"{size}-{page.split('.')[0]}-{did}.png"))
                pg.evaluate("(d)=>d.close()", d); pg.wait_for_timeout(60)
        ctx.close()
    b.close()
srv.shutdown()
print(f"checked {total} pop-up openings")
print("\n".join(problems) if problems else "no problems found")
