// Play page: the daily 90% range game and "Your stats" (beat the market, Sharpe, max drawdown). All scoring happens in
// the database (supabase/migrations/017_quant_games.sql); this file only draws the controls and results.
(() => {
  const $ = (s) => document.querySelector(s);
  if (!$("#range")) return;
  const money = (v) => "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (v) => Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
  const dayName = (d) => {
    const ny = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
    if (d === ny) return "today";
    return new Date(d + "T12:00:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  };
  let q = null, mine = null;

  // Same formula as settle_ranges(): S = width + 20 × miss; points = 100 × max(0, 1 − S / 5% of the close).
  const points = (lo, hi, x) => Math.max(0, Math.round(100 * (1 - ((hi - lo) + 20 * Math.max(lo - x, 0) + 20 * Math.max(x - hi, 0)) / (0.05 * x))));

  function range() {
    const p = Number(q.price), c = Number($("#rg-center").value), w = Number($("#rg-width").value);
    const mid = p * (1 + c / 100);
    return { lo: mid * (1 - w / 100), hi: mid * (1 + w / 100), mid, c, w, p };
  }

  function draw() {
    if (!q) return;
    const r = range(), span = r.p * 0.08, left = r.p - span / 2;  // the bar shows ±4% around now
    const at = (v) => Math.min(100, Math.max(0, ((v - left) / span) * 100));
    $("#rg-band").style.left = at(r.lo) + "%";
    $("#rg-band").style.width = (at(r.hi) - at(r.lo)) + "%";
    $("#rg-now").style.left = at(r.p) + "%";
    $("#rg-low").textContent = num(r.lo);
    $("#rg-high").textContent = num(r.hi);
    $("#rg-mid").textContent = `now ${num(r.p)}`;
    $("#rg-center-v").textContent = (r.c >= 0 ? "+" : "−") + Math.abs(r.c).toFixed(2) + "%";
    $("#rg-width-v").textContent = "±" + r.w.toFixed(2) + "%";
    const best = points(r.lo, r.hi, r.mid);
    $("#rg-est").innerHTML = best > 0
      ? `If it closes inside: about <b>${best} points</b> (+$${best * 2}). Narrower = more points, but a miss costs 20× the distance.`
      : `This range is too wide to score: shrink it until you're about 90% sure.`;
  }

  function showMine() {
    const box = $("#rg-mine");
    if (!mine) { box.hidden = true; $("#rg-go").textContent = "Lock in my range"; return; }
    box.hidden = false;
    box.innerHTML = `✅ <b>Your range for ${dayName(mine.day)}:</b> ${num(mine.low)} – ${num(mine.high)}. Scored after the 4 pm ET close.` +
      (q && q.day === mine.day ? ` <span class="muted">You can change it until 3:30 pm ET.</span>` : "");
    $("#rg-go").textContent = "Update my range";
  }

  // Until the database has the game functions (migration 017), keep the new cards and boards out of sight.
  const setReady = (ok) => {
    ["#range", "#stats", "[data-board=skill]", "[data-board=range]"].forEach((sel) => { const el = $(sel); if (el) el.hidden = !ok; });
    return ok;
  };

  async function loadRange() {
    const { data, error } = await MD.sb.rpc("range_question");
    if (!setReady(!error)) return;
    q = data && data[0];
    if (!q || !q.price) { $("#rg-q").textContent = "Prices aren't available right now. Try again soon."; return; }
    const move = q.prev_close ? (q.price / q.prev_close - 1) * 100 : null;
    $("#rg-q").innerHTML = `Where will the <b>S&amp;P 500</b> close <b>${dayName(q.day)}</b>? Set a range you're <b>90% sure</b> of.` +
      ` <span class="muted small">Now ${num(q.price)}${move != null ? ` (${pct(move)} today)` : ""}</span>`;
    draw();
    if (!MD.user) { $("#rg-go").textContent = "Sign in to play"; return; }
    const [{ data: hist }, { data: st }] = await Promise.all([MD.sb.rpc("my_ranges", { p_limit: 6 }), MD.sb.rpc("my_range_stats")]);
    mine = (hist || []).find((r) => r.day === q.day && r.close == null) || null;
    if (mine) {  // start the sliders at the saved range
      const mid = (Number(mine.low) + Number(mine.high)) / 2;
      $("#rg-center").value = ((mid / Number(q.price) - 1) * 100).toFixed(2);
      $("#rg-width").value = (((Number(mine.high) - Number(mine.low)) / 2 / mid) * 100).toFixed(2);
      draw();
    }
    showMine();
    const s = st && st[0];
    const scored = (hist || []).filter((r) => r.close != null);
    $("#rg-hist").innerHTML = (s && s.scored > 0 ? `<li class="rg-sum"><span>Your ranges caught the close <b>${s.hit_rate}%</b> of the time` +
        `${s.scored >= 5 ? (s.hit_rate < 80 ? " (aim for 90%: try wider)" : s.hit_rate > 97 ? " (aim for 90%: you can go tighter)" : " 👌") : ""}</span>` +
        `<b>avg ${s.avg_points} pts</b></li>` : "") +
      scored.map((r) => `<li><span>${dayName(r.day)}: ${num(r.low)}–${num(r.high)} · closed ${num(r.close)} ${r.hit ? "✅" : "❌"}</span><b>${r.points} pts</b></li>`).join("");
  }

  async function lockIn() {
    if (!MD.user) return document.querySelector("[data-signin]")?.click();
    const r = range();
    const btn = $("#rg-go"); btn.disabled = true;
    const { data, error } = await MD.sb.rpc("make_range", { p_low: r.lo.toFixed(2), p_high: r.hi.toFixed(2) });
    btn.disabled = false;
    if (error) return MD.toast(error.message);
    mine = data; showMine();
    MD.track && MD.track("range_call", { w: r.w });
    MD.toast(`🎯 Locked in: ${num(data.low)} – ${num(data.high)}. Scored after the close.`);
  }

  async function loadStats() {
    const grid = $("#qs-grid");
    if ($("#stats").hidden) return;
    if (!MD.user) { grid.innerHTML = `<p class="muted">Sign in and make a trade to see how you stack up against the market.</p>`; return; }
    const [{ data: m }, { data: k }] = await Promise.all([MD.sb.rpc("my_market_compare"), MD.sb.rpc("my_skill")]);
    const mc = m && m[0], sk = k && k[0];
    if (!mc || !Number(mc.trades)) {
      grid.innerHTML = `<p class="muted">Make your first trade and this shows whether you're beating the S&amp;P 500: every trade is compared with putting the same money in the index at the same moment.</p>`;
      return;
    }
    const a = mc.alpha_pct == null ? null : Number(mc.alpha_pct);
    const tile = (label, value, sub, cls = "") => `<div class="qs"><span>${label}</span><b class="${cls}">${value}</b><small>${sub}</small></div>`;
    grid.innerHTML =
      tile("Your trades", (mc.my_pnl >= 0 ? "+" : "−") + money(Math.abs(mc.my_pnl)), `on ${money(mc.invested)} invested`, mc.my_pnl >= 0 ? "pos" : "neg") +
      tile("Same money in S&amp;P 500", (mc.spy_pnl >= 0 ? "+" : "−") + money(Math.abs(mc.spy_pnl)), "bought and sold at the same moments", mc.spy_pnl >= 0 ? "pos" : "neg") +
      tile("Alpha", a == null ? "–" : pct(a), a == null ? "" : a >= 0 ? "you're beating the market 🎉" : "the market is beating you (for now)", a == null ? "" : a >= 0 ? "pos" : "neg") +
      tile("Sharpe", sk && sk.sharpe != null ? sk.sharpe : "–", sk && sk.sharpe != null ? "return per unit of risk, yearly (1+ is good)" : `after 5 trading days (${(sk && sk.days) || 0} so far)`) +
      tile("Max drawdown", sk && Number(sk.days) ? pct(sk.max_drawdown_pct) : "–", "biggest drop from a high point", sk && sk.max_drawdown_pct < -10 ? "neg" : "");
  }

  ["#rg-center", "#rg-width"].forEach((s) => $(s).addEventListener("input", draw));
  $("#rg-go").addEventListener("click", lockIn);
  setReady(false);
  const go = async () => { await loadRange(); loadStats(); };
  document.addEventListener("md:auth", go);
  if (MD.authReady) go();
  setInterval(() => { if (!document.hidden) loadStats(); }, 60000);
})();
