// Social: usernames, friends, leaderboards, prediction game and paper trading (Supabase).
// Prices, order fills and prediction results are decided by the database, never by this page.
(function () {
  const MD = window.MD;
  if (!MD) return;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = (v) => "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
  const errMsg = (e) => (e && (e.message || e.error_description)) || "Something went wrong";
  let profile = null, myDaily = [];

  const needAccount = (why) => {
    MD.toast(why || "Sign in to play");
    $("#acct-btn") && $("#acct-btn").click();
  };
  async function ready() {
    if (!MD.user) { needAccount("Sign in to play: it's free and takes 10 seconds"); return false; }
    if (!profile || !profile.username) { openUsername(); return false; }
    return true;
  }

  // ---------- profile + username ----------
  async function loadProfile() {
    if (!MD.user) { profile = null; return; }
    const { data } = await MD.sb.from("profiles").select("*").eq("id", MD.user.id).maybeSingle();
    profile = data;
    renderProfileBits();
  }
  function renderProfileBits() {
    $$("[data-me-username]").forEach((el) => (el.textContent = profile && profile.username ? "@" + profile.username : "not set"));
    const link = $("#invite-link");
    if (link) link.value = profile && profile.username ? `${location.origin}${location.pathname.replace(/[^/]*$/, "")}play.html?follow=${profile.username}` : "";
  }
  function openUsername() {
    const d = $("#uname");
    if (!d) return;
    // Never suggest the email's first part: usernames are public on the leaderboards. Keep the current one, or suggest a random handle.
    const words = ["bull", "bear", "alpha", "delta", "theta", "quant", "ticker", "candle", "dip", "rally", "index", "yield"];
    $("#uname-in").value = (profile && profile.username) || `${words[Math.floor(Math.random() * words.length)]}_${Math.floor(100 + Math.random() * 900)}`;
    $("#uname-msg").hidden = true;
    d.showModal();
  }
  $("#uname-form") && $("#uname-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = $("#uname-in").value.trim().toLowerCase();
    const display_name = $("#uname-name").value.trim() || null;
    if (!/^[a-z0-9_]{3,20}$/.test(username)) return showUnameErr("3–20 characters: letters, numbers or _");
    // Users may only change username/display name, so update the existing row (an upsert would also rewrite the id).
    const fields = { username, ...(display_name ? { display_name } : {}) };
    const { data: existing } = await MD.sb.from("profiles").select("id").eq("id", MD.user.id).maybeSingle();
    let { error } = existing
      ? await MD.sb.from("profiles").update(fields).eq("id", MD.user.id)
      : await MD.sb.from("profiles").insert({ id: MD.user.id, ...fields });
    if (error && /duplicate|unique/i.test(error.message)) return showUnameErr("That username is taken, try another");
    if (error) return showUnameErr(errMsg(error));
    await loadProfile();
    $("#uname").close();
    MD.toast(`Welcome, @${username}! 🎉`);
    MD.track("username_set");
    if (window.location.pathname.endsWith("play.html")) loadPlay();
  });
  function showUnameErr(t) { const m = $("#uname-msg"); m.textContent = t; m.hidden = false; }
  $("#uname") && $("#uname").addEventListener("click", (e) => { if (e.target.id === "uname" || e.target.closest("[data-uname-close]")) $("#uname").close(); });
  $$("[data-edit-username]").forEach((b) => b.addEventListener("click", () => (MD.user ? openUsername() : needAccount())));

  // ---------- company dialog: prediction + paper trade ----------
  document.addEventListener("click", async (e) => {
    const p = e.target.closest("[data-predict]");
    if (p) {
      if (!(await ready())) return;
      const [sym, dir] = p.dataset.predict.split(":");
      const conf = +(p.closest(".predict")?.querySelector(".conf-in")?.value || 60) / 100;
      const { error } = await MD.sb.rpc("predict", { p_symbol: sym, p_direction: dir, p_confidence: conf });
      if (error) return MD.toast(errMsg(error));
      MD.toast(`🔮 ${Math.round(conf * 100)}% sure ${sym} goes ${dir === "up" ? "▲ up" : "▼ down"}. Scored at tomorrow's price update.`);
      MD.track("predict", { sym, dir });
      return;
    }
    const t = e.target.closest("[data-trade]");
    if (t) {
      if (!(await ready())) return;
      const box = t.closest(".trade");
      const sym = box.dataset.sym, side = t.dataset.trade;
      const qty = parseFloat($(".trade-qty", box).value);
      if (!(qty > 0)) return MD.toast("Enter how many shares (fractions are fine, e.g. 0.5)");
      const { error } = await MD.sb.rpc("place_order", { p_symbol: sym, p_side: side, p_qty: qty });
      if (error) return MD.toast(errMsg(error));
      MD.toast(`🧾 ${side === "buy" ? "Buy" : "Sell"} order for ${qty} ${sym} placed. It fills at the next price update.`);
      MD.track("paper_order", { sym, side });
      if (window.location.pathname.endsWith("play.html")) loadPortfolio();
    }
  });
  document.addEventListener("input", (e) => {
    const c = e.target.closest(".conf-in");
    if (c) { c.closest(".conf").querySelector(".conf-v").textContent = c.value + "%"; return; }
    const q = e.target.closest(".trade-qty");
    if (!q) return;
    const box = q.closest(".trade"), est = $(".trade-est", box);
    const v = parseFloat(q.value) * parseFloat(box.dataset.price);
    est.textContent = v > 0 ? `≈ ${money(v)} at today's price` : "";
  });

  // ---------- Play page ----------
  const play = $("#play");
  let board = "portfolio", scope = "all", friendCount = null;
  async function loadBoard() {
    const tbody = $("#lb-body");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="4" class="muted">Loading…</td></tr>`;
    let rows = [], col = "", fmt = (r) => "";
    if (board === "streak" || board === "quiz") {
      const order = board === "streak" ? "streak" : "quiz_correct";
      const { data, error } = await MD.sb.from("leaderboard_learning").select("*").order(order, { ascending: false }).limit(100);
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      rows = data;
      col = board === "streak" ? "🔥 Streak" : "🧠 Correct answers";
      fmt = (r) => board === "streak" ? `${r.streak} day${r.streak === 1 ? "" : "s"}` : `${r.quiz_correct}`;
    } else if (board === "skill") {
      const { data, error } = await MD.sb.rpc("leaderboard_skill");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      // Beat-the-market first (alpha vs the same money in the S&P 500); Sharpe-style skill shows once there are 5 trading days.
      rows = data.sort((a, b) => (b.alpha_pct ?? -999) - (a.alpha_pct ?? -999));
      col = "⚖️ vs the S&P 500";
      fmt = (r) => `<span class="${(r.alpha_pct ?? 0) >= 0 ? "pos" : "neg"}">${r.alpha_pct == null ? "–" : pct(r.alpha_pct)}</span>` +
        ` <span class="muted">${r.sharpe != null ? `Sharpe ${r.sharpe}` : `${r.trades} trade${r.trades === 1 ? "" : "s"}`}</span>`;
    } else if (board === "range") {
      const { data, error } = await MD.sb.rpc("leaderboard_ranges");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      rows = data.sort((a, b) => b.avg_points - a.avg_points || b.scored - a.scored);
      col = "🎯 Avg range score";
      fmt = (r) => `<b>${r.avg_points}</b> <span class="muted">${r.hit_rate}% caught · ${r.scored} day${r.scored === 1 ? "" : "s"}</span>`;
    } else if (board === "calls") {
      const { data, error } = await MD.sb.rpc("leaderboard_predictions");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      // Rank by forecasting skill (Brier score vs. a 50/50 guess) once someone has 5+ scored calls; luck alone can't top this board.
      const scored = (r) => r.calls >= 5 && r.skill != null;
      rows = data.sort((a, b) => (scored(b) - scored(a)) || (b.skill ?? -999) - (a.skill ?? -999) || b.right_calls - a.right_calls);
      col = "🔮 Forecasting skill (60 days)";
      fmt = (r) => r.skill != null ? `<b>${r.skill > 0 ? "+" : ""}${r.skill}</b> <span class="muted">${r.right_calls} right of ${r.calls} calls</span>` : `<span class="muted">${r.calls} pending</span>`;
    } else {
      const { data, error } = await MD.sb.rpc("leaderboard_portfolios");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      rows = board === "networth" ? data.sort((a, b) => b.value - a.value) : data.sort((a, b) => b.return_pct - a.return_pct);
      col = board === "networth" ? "💰 Net worth" : "💼 Investment return";
      // deposits = the $10,000 start + money earned by learning, so "earned" is the part above the start.
      fmt = (r) => board === "networth" ? `<b>${money(r.value)}</b>${r.deposits > 10000 ? ` <span class="muted">${money(r.deposits - 10000)} earned</span>` : ""}`
        : `<span class="${r.return_pct > 0 ? "pos" : r.return_pct < 0 ? "neg" : ""}">${pct(r.return_pct)}</span> <span class="muted">${money(r.value)}</span>`;
    }
    friendCount = null;
    if (scope === "friends" && !MD.user) rows = [];  // signed out: no friends list, show the sign-in prompt instead of everyone
    if (scope === "friends" && MD.user) {
      const { data } = await MD.sb.from("follows").select("followee").eq("follower", MD.user.id);
      friendCount = (data || []).length;
      const ids = new Set((data || []).map((f) => f.followee).concat(MD.user.id));
      rows = rows.filter((r) => ids.has(r.id));
    }
    $("#lb-col").textContent = col;
    const compact = !!$("#lb-slot #lb");
    const ranked = rows.map((r, i) => ({ r, i }));
    let shown = ranked.slice(0, compact ? 10 : 50);
    const mine = MD.user && ranked.find((x) => x.r.id === MD.user.id);
    if (mine && !shown.includes(mine)) shown = shown.concat(mine);
    tbody.innerHTML = rows.length ? shown.map(({ r, i }) => `<tr class="${MD.user && r.id === MD.user.id ? "me" : ""}">
        <td class="rank">${i < 3 ? ["🥇", "🥈", "🥉"][i] : i + 1}</td>
        <td><b>${esc(r.display_name || r.username)}</b> <span class="muted lb-user">@${esc(r.username)}</span></td>
        <td class="num">${fmt(r)}</td>
        <td>${MD.user && r.id !== MD.user.id ? `<button class="mini" type="button" data-follow="${r.id}">Follow</button>` : ""}</td></tr>`).join("")
      : `<tr><td colspan="4">${emptyBoard()}</td></tr>`;
    markFollowing();
  }

  // Empty boards say exactly how to get on them, with a button that does it.
  function emptyBoard() {
    const base = location.pathname.replace(/[^/]*$/, "");
    if (!MD.user) return `<div class="lb-empty"><b>Be the first on the board 🏆</b><span>Sign in (free, no password) to start your streak, take quizzes, make calls and trade.</span><button class="btn" type="button" data-signin-now>Sign in</button></div>`;
    if (!profile || !profile.username) return `<div class="lb-empty"><b>You're not on the board yet</b><span>Leaderboards show usernames only. Pick one and you'll appear here.</span><button class="btn" type="button" data-edit-username>Pick a username</button></div>`;
    if (scope === "friends" && !friendCount) return `<div class="lb-empty"><b>No friends here yet 👥</b><span>Copy your invite link above and send it to a friend: they'll follow you as soon as they open it.</span></div>`;
    return {
      streak: `<div class="lb-empty"><b>No streaks yet 🔥</b><span>Read a story or take a quiz today to start yours.</span><a class="btn" href="${base}index.html">Go to today's stories</a></div>`,
      quiz: `<div class="lb-empty"><b>No quiz scores yet 🧠</b><span>Answer today's quiz or a practice round to get on this board.</span><a class="btn" href="${base}learn.html#practice">Try a practice round</a></div>`,
      calls: `<div class="lb-empty"><b>No calls scored yet 🔮</b><span>Make today's call on the home page. It's scored at tomorrow's price update; rankings start after 5 scored calls.</span><a class="btn" href="${base}index.html#call-h">Make today's call</a></div>`,
      skill: `<div class="lb-empty"><b>No one on this board yet ⚖️</b><span>Make a trade: every trade is compared with putting the same money in the S&P 500 at the same moment.</span><button class="btn" type="button" data-open-trade>Trade</button></div>`,
      range: `<div class="lb-empty"><b>No range calls scored yet 🎯</b><span>Set today's 90% range for the S&P 500 above. It's scored after the 4 pm close.</span></div>`,
      portfolio: `<div class="lb-empty"><b>No portfolios yet 💼</b><span>Place your first paper trade in the box above. Try SPY: the whole S&P 500 in one fund.</span></div>`,
    }[board];
  }
  document.addEventListener("click", (e) => { if (e.target.closest("[data-signin-now]")) needAccount("Sign in to join the game"); });

  async function markFollowing() {
    if (!MD.user) return;
    const { data } = await MD.sb.from("follows").select("followee").eq("follower", MD.user.id);
    const ids = new Set((data || []).map((f) => f.followee));
    $$("[data-follow]").forEach((b) => { const on = ids.has(b.dataset.follow); b.textContent = on ? "Following" : "Follow"; b.classList.toggle("on", on); });
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-follow]");
    if (!b) return;
    if (!(await ready())) return;
    const on = b.classList.contains("on");
    const q = on ? MD.sb.from("follows").delete().eq("follower", MD.user.id).eq("followee", b.dataset.follow)
                 : MD.sb.from("follows").insert({ follower: MD.user.id, followee: b.dataset.follow });
    const { error } = await q;
    if (error) return MD.toast(errMsg(error));
    MD.toast(on ? "Unfollowed" : "Following! 👋");
    if (!on) MD.track("follow");
    markFollowing(); loadFriends();
  });

  async function loadFriends() {
    const box = $("#friends-list");
    if (!box || !MD.user) return;
    const { data: f } = await MD.sb.from("follows").select("followee").eq("follower", MD.user.id);
    const ids = (f || []).map((x) => x.followee);
    if (!ids.length) { box.innerHTML = `<p class="muted">You're not following anyone yet. Share your link or find friends by username.</p>`; return; }
    const { data } = await MD.sb.from("leaderboard_learning").select("*").in("id", ids).order("last_active", { ascending: false });
    const today = MD.todayLocal();
    box.innerHTML = (data || []).map((p) => `<div class="friend">
        <span class="f-av">${esc((p.display_name || p.username)[0].toUpperCase())}</span>
        <div class="f-main"><b>${esc(p.display_name || p.username)}</b> <span class="muted">@${esc(p.username)}</span>
          <div class="f-act">${p.last_active === today ? "🟢 Active today" : p.last_active ? "Last active " + p.last_active : "New"} · 🔥 ${p.streak} · 📖 ${p.stories_read} stories · 🧠 ${p.quiz_correct}</div></div>
        <button class="mini on" type="button" data-follow="${p.id}">Following</button></div>`).join("");
  }
  async function loadFeed() {
    const box = $("#friend-feed");
    if (!box || !MD.user) return;
    const { data } = await MD.sb.rpc("friend_feed", { p_limit: 30 });
    if (!Object.keys(prices || {}).length) { try { await loadPrices(); } catch (e) {} }
    const ago = (t) => { const m = Math.round((Date.now() - new Date(t)) / 60000); return m < 1 ? "just now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : m < 10080 ? `${Math.round(m / 1440)}d` : new Date(t).toLocaleDateString([], { month: "short", day: "numeric" }); };
    const badge = { pending: "⏳ Pending", filled: "Filled", rejected: "Rejected", right: "✅ Right", wrong: "❌ Wrong", void: "No change" };
    const rows = data || [];
    $("#feed-note").textContent = rows.length ? `${new Set(rows.map((f) => f.username)).size} friend${new Set(rows.map((f) => f.username)).size === 1 ? "" : "s"}` : "";
    box.innerHTML = rows.map((f, n) => {
      const who = esc(f.display_name || f.username), q = prices[f.symbol];
      const at = /\$([\d,]+(?:\.\d+)?)/.exec(f.detail || ""), then = at ? Number(at[1].replace(/,/g, "")) : null;
      const since = q && then && f.kind !== "prediction" && f.status === "filled" ? (q.price / then - 1) * 100 : null;
      const sell = /\bsold\b/i.test(f.detail || "");
      return `<li class="post${n >= 8 ? " extra" : ""}">
        <span class="f-av" aria-hidden="true">${esc((f.display_name || f.username)[0].toUpperCase())}</span>
        <div class="post-main">
          <div class="post-head"><b>${who}</b> <span class="muted">@${esc(f.username)} · ${ago(f.at)}</span></div>
          <div class="post-body">${f.kind === "prediction" ? `🔮 made a call on <b>${esc(f.symbol)}</b>: ${esc(f.detail)}` : `💼 <b>${esc(f.symbol)}</b> · ${esc(f.detail)}`}
            <span class="st st-${esc(f.status)}">${badge[f.status] || esc(f.status)}</span></div>
          ${q ? `<div class="post-tick"><button type="button" class="tick-chip" data-trade-sym="${esc(f.symbol)}"><b>${esc(f.symbol)}</b> ${money(q.price)}
            <span class="${(q.price >= q.prev) ? "pos" : "neg"}">${pct((q.price / q.prev - 1) * 100)} today</span></button>
            ${since != null ? `<span class="since ${since >= 0 ? "pos" : "neg"}">${since >= 0 ? "▲" : "▼"} ${pct(since)} since ${sell ? "they sold" : "they bought"}</span>` : ""}</div>` : ""}
        </div></li>`;
    }).join("") || `<li class="muted post-empty">Nothing yet. When friends trade or make a call, it shows up here. Invite one with your link →</li>`;
    const more = $('[data-showall="#friend-feed"]');
    if (more) { more.hidden = rows.length <= 8; box.classList.remove("all"); more.textContent = "Show more"; }
  }
  setInterval(() => { if (play && MD.user && !document.hidden) loadFeed(); }, 30000);
  // Live while open: prices change every 15 min in market hours, so refresh the portfolio, race and boards each minute.
  setInterval(() => { if (play && MD.user && !document.hidden && profile) { loadPortfolio(); loadBoard(); } }, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && play && MD.user && profile) { loadPortfolio(); loadBoard(); } });

  $("#find-form") && $("#find-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!(await ready())) return;
    const u = $("#find-in").value.trim().replace(/^@/, "").toLowerCase();
    const { data } = await MD.sb.from("profiles").select("id, username").eq("username", u).maybeSingle();
    if (!data) return MD.toast(`No one called @${u} yet`);
    if (data.id === MD.user.id) return MD.toast("That's you 🙂");
    const { error } = await MD.sb.from("follows").insert({ follower: MD.user.id, followee: data.id });
    MD.toast(error && !/duplicate/.test(error.message) ? errMsg(error) : `Following @${u}! 👋`);
    $("#find-in").value = ""; loadFriends();
  });
  $("#invite-copy") && $("#invite-copy").addEventListener("click", async () => {
    const v = $("#invite-link").value;
    if (!v) return (MD.user ? openUsername() : needAccount());
    try { await navigator.clipboard.writeText(v); MD.toast("Invite link copied"); } catch (e) { $("#invite-link").select(); }
  });

  // ---------- portfolio (Robinhood-style) ----------
  let prices = {};      // symbol -> {price, name, prev, hist: [[iso, price], ...]}
  let myPortfolio = { cash: 10000, deposits: 10000, rows: [] };
  let myRewards = [];
  const NAMES = { SPY: "S&P 500 index fund", QQQ: "Nasdaq-100 index fund", VTI: "Total US market fund" };
  const shortName = (n) => String(n || "").replace(/,? (Inc|Corp|Corporation|Holdings|Ltd|plc)\.?$/i, "").replace(/ (Inc|Corporation)\.?,?/, "");

  async function loadPrices() {
    // Newest first: the API returns at most 1,000 rows per request and ~100 symbols are saved every 15 minutes, so an
    // oldest-first query would show prices frozen at launch. The latest 4,000 rows reach back past the previous close.
    const pages = await Promise.all([0, 1, 2, 3].map((i) => MD.sb.from("prices").select("symbol, as_of, price, name")
      .order("as_of", { ascending: false }).order("symbol").range(i * 1000, i * 1000 + 999)));
    const seen = new Set();
    const rows = pages.flatMap((r) => r.data || []).filter((r) => !seen.has(r.symbol + r.as_of) && seen.add(r.symbol + r.as_of)).reverse();
    const nyDay = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });
    prices = {};
    for (const r of rows) {
      const p = (prices[r.symbol] ||= { hist: [], name: r.name });
      p.hist.push([r.as_of, Number(r.price)]);
      p.name = r.name || p.name;
    }
    for (const p of Object.values(prices)) {
      p.price = p.hist[p.hist.length - 1][1];
      // "today" = change since the last price of an earlier (New York) day, i.e. the previous close
      const day = nyDay.format(new Date(p.hist[p.hist.length - 1][0]));
      const before = p.hist.filter((h) => nyDay.format(new Date(h[0])) < day).pop();
      p.prev = before ? before[1] : p.hist[0][1];
    }
  }

  // Portfolio value at each price update, rebuilt from your actual fills (cash + shares held × price at that time).
  function valueSeries(orders, startCash) {
    const fills = orders.filter((o) => o.status === "filled").sort((a, b) => new Date(a.filled_at) - new Date(b.filled_at));
    const times = [...new Set(Object.values(prices).flatMap((p) => p.hist.map((h) => h[0])))].sort();
    const start = fills.length ? fills[0].filled_at : null;
    const out = [];
    for (const t of times) {
      if (start && t < start) continue;
      let cash = startCash + myRewards.filter((r) => r.created_at <= t).reduce((s, r) => s + Number(r.amount), 0); const held = {};
      for (const f of fills) {
        if (f.filled_at > t) break;
        const amt = Number(f.qty) * Number(f.fill_price);
        if (f.side === "buy") { cash -= amt; held[f.symbol] = (held[f.symbol] || 0) + Number(f.qty); }
        else { cash += amt; held[f.symbol] = (held[f.symbol] || 0) - Number(f.qty); }
      }
      let v = cash, known = true;
      for (const [s, q] of Object.entries(held)) {
        if (!q) continue;
        const h = prices[s]?.hist.filter((x) => x[0] <= t).pop();
        if (h) v += q * h[1]; else known = false;
      }
      if (known) out.push([t, v, startCash + myRewards.filter((r) => r.created_at <= t).reduce((x, r) => x + Number(r.amount), 0)]);
    }
    return out;
  }

  // Portfolio chart, trading-app style: 1D from 15-minute prices, 1W/1M/ALL from daily snapshots (portfolio_daily),
  // coloured by the change over the chosen range. Drag or hover to read any point; the big number follows.
  let chartRange = "1D", chartData = null;
  // "trading" = profit/loss from trades only (learning rewards are money added, like a deposit); "account" = total value
  let chartMode = (MD.store && MD.store.get("chartmode", "trading")) || "trading";
  const nyDate = (t) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(t));
  const when = (t, intraday) => new Date(t).toLocaleString([], intraday
    ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" } : { month: "short", day: "numeric", year: "numeric" });
  function rangeSeries(range) {
    const { intra, daily, total } = chartData;
    if (range === "1D") {
      const last = intra.length ? nyDate(intra[intra.length - 1][0]) : null;
      const day = intra.filter((x) => nyDate(x[0]) === last);
      return { pts: day.length >= 2 ? day : intra, intraday: true };
    }
    const days = { "1W": 7, "1M": 31, ALL: 99999 }[range];
    const cut = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
    const pts = daily.filter((d) => d.day >= cut).map((d) => [d.day + "T21:00:00Z", Number(d.value), Number(d.deposits)]);
    if (!pts.length || pts[pts.length - 1][0].slice(0, 10) < nyDate(Date.now())) pts.push([new Date().toISOString(), total, chartData.deposits]);
    return pts.length >= 2 ? { pts, intraday: false } : { pts: intra, intraday: true };
  }
  const changeText = (v, base, label, of = base) => {
    const d = v - base, p = of ? (d / of) * 100 : 0, cls = d >= 0 ? "up" : "down";
    return `<span class="${cls}">${d >= 0 ? "▲" : "▼"} ${money(Math.abs(d))} (${pct(p)})</span> ${esc(label)}`;
  };
  function drawChart() {
    const el = $("#pf-chart"), lab = $("#pf-scrub"), big = $("#pf-total");
    if (!el || !chartData) return;
    $$("[data-range]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.range === chartRange)));
    $$("[data-chartmode]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.chartmode === chartMode)));
    const pl = $("#pf-title");
    if (pl) pl.textContent = chartMode === "trading" ? "Your trading profit/loss" : "Your account value";
    const { pts, intraday } = chartData.filled ? rangeSeries(chartRange) : { pts: [], intraday: true };
    if (pts.length < 2) { el.innerHTML = `<div class="pf-flat"><span></span></div>`; lab.textContent = ""; return; }
    const trading = chartMode === "trading";
    const W = el.clientWidth || 600, H = 140, vals = pts.map((x) => trading ? x[1] - x[2] : x[1]), base = vals[0], up = vals[vals.length - 1] >= base;
    // trading %: the gain divided by all the money you've been given (start + learning rewards), same as the leaderboard
    const baseMoney = trading ? pts[pts.length - 1][2] : vals[0];
    let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
    const X = (i) => (i / (pts.length - 1)) * W, Y = (v) => H - ((v - lo) / (hi - lo)) * H;
    const d = vals.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="${up ? "up" : "down"}" role="img" aria-label="Portfolio value, ${chartRange}">
      <line class="base" x1="0" x2="${W}" y1="${Y(base)}" y2="${Y(base)}"/><path class="fill" d="${d}L${W},${H}L0,${H}Z"/><path class="ln" d="${d}"/>
      <line class="cur" y1="0" y2="${H}" x1="0" x2="0" visibility="hidden"/><circle class="dot" r="4" cx="0" cy="0" visibility="hidden"/></svg>`;
    $("#portfolio").classList.toggle("down", !up);
    const label = { "1D": intraday ? "today" : "", "1W": "past week", "1M": "past month", ALL: "all time" }[chartRange] || "";
    const signed = (v) => (v >= 0 ? "+" : "−") + money(Math.abs(v));
    const head = (v) => trading ? signed(v) : money(v);
    const rest = () => { big.textContent = head(trading ? chartData.total - chartData.deposits : chartData.total);
      lab.innerHTML = changeText(vals[vals.length - 1], base, label, baseMoney); };
    rest();
    const svg = $("svg", el), cur = $(".cur", svg), dot = $(".dot", svg);
    const at = (e) => {
      const r = svg.getBoundingClientRect(), i = Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1))));
      cur.setAttribute("x1", X(i)); cur.setAttribute("x2", X(i)); dot.setAttribute("cx", X(i)); dot.setAttribute("cy", Y(vals[i]));
      cur.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
      big.textContent = head(vals[i]); lab.innerHTML = changeText(vals[i], base, when(pts[i][0], intraday), baseMoney);
    };
    el.onpointermove = at; el.onpointerdown = at;
    el.onpointerleave = () => { cur.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); rest(); };
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-range]");
    if (b) { chartRange = b.dataset.range; drawChart(); }
    const m = e.target.closest("[data-chartmode]");
    if (m) { chartMode = m.dataset.chartmode; if (MD.store) MD.store.set("chartmode", chartMode); drawChart(); }
  });
  addEventListener("resize", () => { clearTimeout(drawChart.t); drawChart.t = setTimeout(drawChart, 150); });

  const todayHist = (hist) => {
    if (!hist || !hist.length) return hist;
    const last = nyDate(hist[hist.length - 1][0]), day = hist.filter((h) => nyDate(h[0]) === last);
    return day.length >= 2 ? day : hist;
  };
  const sparkline = (hist, up) => {
    if (!hist || hist.length < 2) return "";
    const v = hist.map((h) => h[1]), lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
    const d = v.map((x, i) => `${i ? "L" : "M"}${(i / (v.length - 1) * 60).toFixed(1)},${(22 - (x - lo) / r * 20).toFixed(1)}`).join("");
    return `<svg class="h-spark ${(up ?? v[v.length - 1] >= v[0]) ? "up" : "down"}" viewBox="0 0 60 24" aria-hidden="true"><path d="${d}"/></svg>`;
  };
  const chip = (el, val, label, isPct = true) => {
    el.className = "pf-chip " + (val >= 0 ? "up" : "down");
    el.textContent = `${val >= 0 ? "▲" : "▼"} ${isPct ? pct(val) : money(Math.abs(val))} ${label}`;
  };

  async function loadPortfolio() {
    const box = $("#portfolio");
    if (!box || !MD.user) return;
    const [{ data: pf }, { data: pos }, { data: orders }, { data: rewards }] = await Promise.all([
      MD.sb.from("portfolios").select("cash, deposits").eq("user_id", MD.user.id).maybeSingle(),
      MD.sb.from("positions").select("*").eq("user_id", MD.user.id),
      MD.sb.from("orders").select("*").eq("user_id", MD.user.id).order("placed_at", { ascending: false }).limit(200),
      MD.sb.from("rewards").select("*").eq("user_id", MD.user.id).order("created_at", { ascending: false }).limit(100),
      loadPrices(),
      MD.sb.from("portfolio_daily").select("day, value, deposits").eq("user_id", MD.user.id).order("day").then((r) => { myDaily = r.data || []; }),
    ]);
    const cash = pf ? Number(pf.cash) : 10000, deposits = pf ? Number(pf.deposits) : 10000;
    myRewards = rewards || [];
    const rows = (pos || []).map((p) => {
      const q = prices[p.symbol] || {};
      const now = q.price ?? Number(p.avg_buy_price);
      return { ...p, qty: Number(p.qty), avg: Number(p.avg_buy_price), now, prev: q.prev ?? now, name: NAMES[p.symbol] || shortName(q.name) || p.symbol, hist: q.hist };
    }).sort((a, b) => b.qty * b.now - a.qty * a.now);
    myPortfolio = { cash, deposits, rows };
    const invested = rows.reduce((s, r) => s + r.qty * r.now, 0);
    const total = cash + invested, ret = (total / deposits - 1) * 100;   // return on everything you've been given
    const todayChange = rows.reduce((s, r) => s + r.qty * (r.now - r.prev), 0);
    $("#pf-total").textContent = money(total);
    chip($("#pf-today"), todayChange, "today", false);
    chip($("#pf-ret"), ret, "all time");
    $("#pf-cash").textContent = money(cash);
    $("#pf-inv").textContent = money(invested);
    // No fills yet: a flat dashed line instead of a chart of nothing.
    const filled = (orders || []).some((o) => o.status === "filled");
    const earned = myRewards.reduce((s, r) => s + Number(r.amount), 0), start = deposits - earned;
    chartData = { intra: filled ? valueSeries(orders || [], start) : [], daily: myDaily, total, deposits, filled };
    // where the money came from: the start, what learning earned, and what trading made or lost
    const trade = total - deposits;
    $("#pf-split").innerHTML = `<span>Started with <b>${money(start)}</b></span><span>Earned by learning <b class="pos">+${money(earned)}</b></span>
      <span>Trading <b class="${trade >= 0 ? "pos" : "neg"}">${trade >= 0 ? "+" : "−"}${money(Math.abs(trade))} (${pct((trade / deposits) * 100)})</b></span>`;
    drawChart();
    renderRewards(earned);

    const pending = (orders || []).filter((o) => o.status === "pending");
    const banner = $("#pf-pending");
    banner.hidden = !pending.length;
    if (pending.length) {
      banner.innerHTML = `⏳ <b>${pending.length} order${pending.length > 1 ? "s" : ""}</b> will fill at the next price update (${fillWhen()}): ` +
        pending.map((o) => `<span class="pend">${o.side === "buy" ? "Buy" : "Sell"} ${Number(o.qty)} ${esc(o.symbol)}</span>`).join(" ");
    }

    const stockRow = (sym, sub, now, prev, hist, extra = "") => {
      const day = prev ? (now / prev - 1) * 100 : 0;
      return `<li><button type="button" class="h-row" data-trade-sym="${esc(sym)}">
        <span class="co-logo">${esc(sym[0])}</span>
        <span class="h-id"><b>${esc(sym)}</b><span class="muted small h-sub">${sub}</span></span>
        ${sparkline(todayHist(hist), day >= 0)}
        <span class="h-val"><b>${money(now)}</b><span class="pf-chip ${day >= 0 ? "up" : "down"}">${day >= 0 ? "▲" : "▼"} ${pct(day)}</span>${extra}</span></button></li>`;
    };
    $("#pf-pos").innerHTML = rows.length ? rows.map((r) => {
      const g = (r.now / r.avg - 1) * 100, value = r.qty * r.now;
      const shares = Number(r.qty).toLocaleString(undefined, { maximumFractionDigits: 4 });
      return stockRow(r.symbol, `${shares} share${r.qty === 1 ? "" : "s"}`, r.now, r.prev, r.hist,
        `<span class="h-gain" title="Your ${shares} shares are worth ${money(value)}. Gain since you bought, at your average price of ${money(r.avg)}: ${pct(g)}">${money(value)} · <span class="${g >= 0 ? "up" : "down"}">${pct(g)}</span></span>`);
    }).join("") : `<li class="h-empty"><b>No holdings yet</b><span class="muted">Your ${money(cash)} is waiting. Most beginners start with an index fund like <b>SPY</b>.</span>
        <button class="btn" type="button" data-trade-sym="SPY">Buy SPY</button></li>`;

    // Watchlist: the stocks you starred on the Today page
    const owned = new Set(rows.map((r) => r.symbol));
    const stars = ((MD.store && MD.store.get("stars", [])) || []).filter((sym) => prices[sym] && !owned.has(sym));
    if ($("#watch-card")) {
      $("#watch-card").hidden = !stars.length;
      $("#pf-watch").innerHTML = stars.map((sym) => {
        const q = prices[sym];
        return stockRow(sym, esc(NAMES[sym] || shortName(q.name) || sym), q.price, q.prev, q.hist);
      }).join("");
    }

    const om = $('[data-showall="#pf-orders"]'); if (om) om.hidden = (orders || []).length <= 5;
    $("#pf-orders").innerHTML = (orders || []).slice(0, 30).map((o, n) => `<li class="${n >= 5 ? "extra" : ""}"><span class="st st-${o.status}">${o.status}</span>
        ${o.side === "buy" ? "Buy" : "Sell"} ${Number(o.qty).toLocaleString(undefined, { maximumFractionDigits: 4 })} <b>${esc(o.symbol)}</b>
        ${o.fill_price ? "at " + money(o.fill_price) : ""} <span class="muted small">${new Date(o.placed_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
        ${o.note ? `<span class="muted small">· ${esc(o.note)}</span>` : ""}
        ${o.status === "pending" ? `<button class="mini" type="button" data-cancel="${o.id}">Cancel</button>` : ""}</li>`).join("") || `<li class="muted">No orders yet.</li>`;
    loadRace(total);
  }
  function renderRewards(earned) {
    const box = $("#rewards");
    if (!box) return;
    $("#earn-total").textContent = earned ? `${earned >= 0 ? "+" : "−"}${money(Math.abs(earned))} earned so far` : "";
    const rm = $('[data-showall="#rewards"]'); if (rm) rm.hidden = myRewards.length <= 5;
    box.innerHTML = myRewards.slice(0, 40).map((r, n) => `<li class="${n >= 5 ? "extra" : ""}"><span class="pf-chip ${Number(r.amount) >= 0 ? "up" : "down"}">${Number(r.amount) >= 0 ? "+" : "−"}${money(Math.abs(Number(r.amount)))}</span>
        <span>${esc(r.reason)}</span><span class="muted small">${new Date(r.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}</span></li>`).join("")
      || `<li class="muted">Nothing yet. Finish lesson 1 on the Learn tab for your first $500.</li>`;
  }
  // When a new order will fill: honest about closed markets and about price updates that are running late.
  const fillWhen = () => {
    const m = MD.market();
    if (!m.open) return "when the market next opens at 9:30 am ET";
    const last = Math.max(0, ...Object.values(prices).map((p) => Date.parse(p.hist[p.hist.length - 1][0])));
    return last && m.sinceOpen > 45 && Date.now() - last > 45 * 60e3 ? "as soon as price updates resume (they're running late)" : "within 15 minutes";
  };

  // ---------- friends race ----------
  async function loadRace(myTotal) {
    const box = $("#race");
    if (!box) return;
    const [{ data: board }, { data: fol }] = await Promise.all([
      MD.sb.rpc("leaderboard_portfolios"),
      MD.sb.from("follows").select("followee").eq("follower", MD.user.id),
    ]);
    const ids = new Set((fol || []).map((f) => f.followee).concat(MD.user.id));
    let racers = (board || []).filter((r) => ids.has(r.id)).map((r) => ({ ...r, me: r.id === MD.user.id }));
    if (!racers.some((r) => r.me)) racers.push({ id: MD.user.id, me: true, username: (profile && profile.username) || "you", display_name: "You", return_pct: (myTotal / myPortfolio.deposits - 1) * 100, value: myTotal });
    racers.sort((a, b) => b.return_pct - a.return_pct);
    const maxAbs = Math.max(1, ...racers.map((r) => Math.abs(r.return_pct)));
    box.innerHTML = racers.map((r, i) => `<div class="racer ${r.me ? "me" : ""}">
        <span class="r-rank">${i === 0 && racers.length > 1 ? "👑" : i + 1}</span>
        <span class="r-name">${r.me ? "You" : esc(r.display_name || r.username)}</span>
        <span class="r-track"><span class="r-bar ${r.return_pct >= 0 ? "up" : "down"}" style="width:${Math.max(4, Math.abs(r.return_pct) / maxAbs * 100)}%"></span></span>
        <span class="r-val ${r.return_pct > 0 ? "pos" : r.return_pct < 0 ? "neg" : ""}">${pct(Number(r.return_pct))}</span></div>`).join("")
      + (racers.length < 2 ? `<p class="muted small">Invite a friend to race: whoever grows their money the most wins. <button class="mini" type="button" id="race-invite">Copy invite link</button></p>` : "");
    const me = racers.findIndex((r) => r.me);
    $("#race-note").textContent = racers.length < 2 ? "" : me === 0 ? "You're in the lead 👑" : `You're #${me + 1} · ${(racers[0].return_pct - racers[me].return_pct).toFixed(2)}% behind ${racers[0].display_name || racers[0].username}`;
  }
  const copyInvite = async () => {
    const v = $("#invite-link").value;
    if (!v) return (MD.user ? openUsername() : needAccount());
    try { await navigator.clipboard.writeText(v); MD.toast("Invite link copied: send it to a friend 🏁"); } catch (e) { $("#invite-link").select(); }
  };
  document.addEventListener("click", (e) => { if (e.target.closest("#race-invite, #invite-copy-2")) copyInvite(); });

  // ---------- trade ticket ----------
  const tk = { sym: null, side: "buy", unit: "usd" };
  const tradeDlg = $("#trade");
  const tradables = () => Object.entries(prices).filter(([s]) => !s.startsWith("^")).map(([s, p]) => ({ sym: s, ...p, name: NAMES[s] || shortName(p.name) || s }))
    .sort((a, b) => (["SPY", "QQQ", "VTI"].indexOf(b.sym) + 1 > 0) - (["SPY", "QQQ", "VTI"].indexOf(a.sym) + 1 > 0) || a.sym.localeCompare(b.sym));
  const ETFS = ["SPY", "VOO", "QQQ", "VTI", "IWM", "DIA", "SCHD", "VXUS", "BND", "TLT", "GLD", "XLK", "XLF", "XLE", "XLV"];
  const POPULAR = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B", "AVGO", "JPM", "V", "MA", "NFLX", "AMD", "COST", "WMT",
    "DIS", "NKE", "KO", "PEP", "MCD", "SBUX", "UNH", "LLY", "JNJ", "PFE", "MRK", "ABBV", "XOM", "CVX", "PG", "TGT", "HD", "LOW", "INTC",
    "QCOM", "TXN", "ORCL", "CRM", "ADBE", "IBM", "CSCO", "UBER", "ABNB", "SHOP", "PYPL", "COIN", "PLTR", "SNOW", "SPOT", "BAC", "WFC",
    "GS", "MS", "AXP", "BA", "CAT", "GE", "F", "GM", "T", "VZ"];
  const groupOf = (s) => ETFS.includes(s) ? 0 : POPULAR.includes(s) ? 1 : 2;
  const GROUPS = ["📈 Index funds & ETFs", "⭐ Popular stocks", "📰 In the news & today's movers"];
  function renderPick() {
    const q = ($("#tk-search").value || "").trim().toLowerCase();
    const list = tradables().filter((t) => !q || t.sym.toLowerCase().includes(q) || t.name.toLowerCase().includes(q))
      .sort((a, b) => groupOf(a.sym) - groupOf(b.sym) || (groupOf(a.sym) === 0 ? ETFS.indexOf(a.sym) - ETFS.indexOf(b.sym) : groupOf(a.sym) === 1 ? POPULAR.indexOf(a.sym) - POPULAR.indexOf(b.sym) : a.sym.localeCompare(b.sym)));
    let last = -1;
    $("#tk-list").innerHTML = list.map((t) => { const m = (t.price / t.prev - 1) * 100;
      const g = groupOf(t.sym), head = !q && g !== last ? `<li class="tk-group">${GROUPS[g]}</li>` : ""; last = g;
      return head + `<li><button type="button" class="tk-item" data-pick="${esc(t.sym)}"><span class="co-logo">${esc(t.sym[0])}</span>
        <span class="h-id"><b>${esc(t.sym)}</b><span class="muted small">${esc(t.name)}</span></span>${sparkline(t.hist)}
        <span class="h-val"><b>${money(t.price)}</b><span class="pf-chip ${m >= 0 ? "up" : "down"}">${m >= 0 ? "▲" : "▼"} ${pct(m)}</span></span></button></li>`; }).join("")
      || `<li class="muted">No match. Try a company name or ticker, e.g. Apple or AAPL.</li>`;
  }
  function showStep(step) { ["tk-pick", "tk-ticket", "tk-done"].forEach((id) => ($("#" + id).hidden = id !== step)); }
  async function openTrade(sym) {
    if (!(await ready())) return;
    if (!Object.keys(prices).length) await loadPrices();
    $("#tk-search").value = ""; renderPick();
    sym ? openTicket(sym) : showStep("tk-pick");
    tradeDlg.showModal();
  }
  function openTicket(sym) {
    const t = tradables().find((x) => x.sym === sym);
    if (!t) return MD.toast("That one can't be traded here yet");
    tk.sym = sym;
    $("#tk-name").textContent = t.name; $("#tk-sym").textContent = sym;
    $("#tk-price").textContent = money(t.price);
    const m = (t.price / t.prev - 1) * 100; chip($("#tk-move"), m, "today");
    $("#tk-amt").value = ""; setSide(tk.side); showStep("tk-ticket"); updateEst();
    setTimeout(() => $("#tk-amt").focus(), 50);
  }
  function held(sym) { return myPortfolio.rows.find((r) => r.symbol === sym)?.qty || 0; }
  function setSide(side) {
    tk.side = side;
    $$("[data-side]").forEach((b) => b.setAttribute("aria-selected", b.dataset.side === side));
    $("#tk-go").classList.toggle("sell", side === "sell");
    updateEst();
  }
  function shares() {
    const t = prices[tk.sym], a = parseFloat($("#tk-amt").value);
    if (!t || !(a > 0)) return 0;
    return tk.unit === "usd" ? a / t.price : a;
  }
  function updateEst() {
    const t = prices[tk.sym]; if (!t) return;
    const q = shares(), cost = q * t.price;
    $("#tk-unit-sym").textContent = tk.unit === "usd" ? "$" : "#";
    $("#tk-est").innerHTML = q ? (tk.unit === "usd" ? `≈ <b>${q.toLocaleString(undefined, { maximumFractionDigits: 4 })} shares</b>` : `≈ <b>${money(cost)}</b>`) + ` at ${money(t.price)}` : "";
    $("#tk-bp").textContent = tk.side === "buy" ? `Buying power ${money(myPortfolio.cash)}` : `You own ${held(tk.sym).toLocaleString(undefined, { maximumFractionDigits: 4 })} shares`;
    const tooMuch = tk.side === "buy" ? cost > myPortfolio.cash + 0.005 : q > held(tk.sym) + 1e-9;
    $("#tk-go").disabled = !q || tooMuch;
    $("#tk-go").textContent = !q ? "Enter an amount" : tooMuch ? (tk.side === "buy" ? "Not enough buying power" : "You don't own that many") : `${tk.side === "buy" ? "Buy" : "Sell"} ${tk.unit === "usd" ? money(cost) : q + " shares"} of ${tk.sym}`;
  }
  if (tradeDlg) {
    document.addEventListener("click", (e) => {
      const o = e.target.closest("[data-open-trade]"); if (o) return openTrade();
      const s = e.target.closest("[data-trade-sym]"); if (s) return openTrade(s.dataset.tradeSym);
    });
    tradeDlg.addEventListener("click", async (e) => {
      if (e.target === tradeDlg || e.target.closest("[data-sheet-close]")) return tradeDlg.close();
      const p = e.target.closest("[data-pick]"); if (p) return openTicket(p.dataset.pick);
      if (e.target.closest("[data-tk-back]")) return showStep("tk-pick");
      const sd = e.target.closest("[data-side]"); if (sd) return setSide(sd.dataset.side);
      const u = e.target.closest("[data-unit]");
      if (u) { tk.unit = u.dataset.unit; $$("[data-unit]").forEach((b) => b.setAttribute("aria-selected", b === u)); $("#tk-amt").value = ""; return updateEst(); }
      const a = e.target.closest("[data-amt]");
      if (a) {
        // "Max" on a sell = every share you own (a dollar amount would round down and leave a sliver behind).
        const sellAll = a.dataset.amt === "max" && tk.side === "sell";
        tk.unit = sellAll ? "shares" : "usd"; $$("[data-unit]").forEach((b) => b.setAttribute("aria-selected", b.dataset.unit === tk.unit));
        $("#tk-amt").value = sellAll ? held(tk.sym) : a.dataset.amt === "max" ? Math.floor(myPortfolio.cash * 100) / 100 : a.dataset.amt;
        return updateEst();
      }
      if (e.target.closest("#tk-go")) {
        const q = Math.floor(shares() * 10000) / 10000;
        if (!q) return;
        $("#tk-go").disabled = true; $("#tk-go").textContent = "Placing…";
        const { error } = await MD.sb.rpc("place_order", { p_symbol: tk.sym, p_side: tk.side, p_qty: q });
        if (error) { MD.toast(errMsg(error)); return updateEst(); }
        MD.track("paper_order", { sym: tk.sym, side: tk.side });
        $("#tk-done-title").textContent = `${tk.side === "buy" ? "Buy" : "Sell"} order placed`;
        $("#tk-done-text").textContent = `${q.toLocaleString(undefined, { maximumFractionDigits: 4 })} shares of ${tk.sym}. It fills at the next price update, ${fillWhen()}.`;
        showStep("tk-done");
        loadPortfolio();
      }
    });
    $("#tk-amt").addEventListener("input", updateEst);
    $("#tk-search").addEventListener("input", renderPick);
  }

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-cancel]");
    if (!b) return;
    const { error } = await MD.sb.rpc("cancel_order", { p_id: +b.dataset.cancel });
    MD.toast(error ? errMsg(error) : "Order cancelled");
    loadPortfolio();
  });

  async function loadCalls() {
    const box = $("#calls");
    if (!box || !MD.user) return;
    const { data } = await MD.sb.from("predictions").select("*").eq("user_id", MD.user.id).order("made_at", { ascending: false }).limit(30);
    const done = (data || []).filter((p) => p.status === "right" || p.status === "wrong");
    const right = done.filter((p) => p.status === "right").length;
    $("#calls-sum").textContent = done.length ? `${right} of ${done.length} right (${Math.round((100 * right) / done.length)}%)` : "No results yet";
    box.innerHTML = (data || []).map((p) => `<li><span class="st st-${p.status}">${{ pending: "⏳ pending", right: "✅ right", wrong: "❌ wrong", void: "➖ no change" }[p.status]}</span>
        <b>${esc(p.symbol)}</b> ${p.direction === "up" ? "▲ up" : "▼ down"} from ${money(p.base_price)}
        ${p.settled_price ? `→ ${money(p.settled_price)}` : ""} <span class="muted">${new Date(p.made_at).toLocaleDateString()}</span></li>`).join("")
      || `<li class="muted">No calls yet. Open any company on today's page and tap ▲ or ▼.</li>`;
  }

  async function loadCalibration() {
    const box = $("#calib");
    if (!box || !MD.user) return;
    const { data } = await MD.sb.rpc("my_calibration");
    if (!data || !data.length) { box.innerHTML = `<p class="muted small">Your calibration chart appears after your first scored calls.</p>`; return; }
    // Bars: how often you were right at each confidence level; the dashed tick is where a perfectly calibrated forecaster would be.
    box.innerHTML = `<div class="cal-title small muted">When you say… you're right:</div>` + data.map((b) => {
      const ideal = b.bucket + 5;
      return `<div class="cal-row"><span class="cal-b">${b.bucket}–${b.bucket + 9}%</span>
        <span class="cal-track"><span class="cal-fill ${b.hit_rate + 10 < ideal ? "over" : ""}" style="width:${b.hit_rate}%"></span><span class="cal-ideal" style="left:${ideal}%"></span></span>
        <span class="cal-v">${b.hit_rate}% <span class="muted">(${b.calls})</span></span></div>`;
    }).join("") + `<p class="muted small">Dashed line = perfectly calibrated. Bars well short of it mean you're overconfident at that level.</p>`;
  }
  async function loadCoach() {
    const box = $("#coach");
    if (!box || !MD.user) return;
    const { data } = await MD.sb.rpc("coach");
    const learn = (id) => `${location.pathname.replace(/[^/]*$/, "")}learn.html#${id}`;
    box.innerHTML = (data || []).map((c) => `<div class="tip-card ${c.severity}"><span>${{ warn: "⚠️", info: "💡", good: "✅" }[c.severity] || "💡"}</span>
        <div>${esc(c.message)} <a href="${learn(c.lesson)}">Learn why →</a></div></div>`).join("")
      || `<p class="muted small">Your coach watches your trades for classic investor mistakes (panic selling, putting everything in one stock, overtrading) and explains them here.</p>`;
  }

  function loadPlay() {
    if (!play) return;
    const signedIn = !!MD.user;
    $$("[data-need-auth]").forEach((el) => (el.hidden = !signedIn));
    $$("[data-guest]").forEach((el) => (el.hidden = signedIn));
    if (signedIn) {  // signed in: leaderboard sits in the right column, TrendBot at the end of the left one
      if ($("#lb-slot") && $("#lb")) $("#lb-slot").appendChild($("#lb"));
      if ($("#tb-slot") && $("#trendbot")) $("#tb-slot").appendChild($("#trendbot"));
    }
    loadBoard();
    if (signedIn) { loadFriends(); loadFeed(); loadPortfolio(); loadCalls(); loadCalibration(); loadCoach(); }
  }
  if (play) {
    const pick = $("#lb-pick");
    if (pick) pick.addEventListener("change", () => { board = pick.value; loadBoard(); });
    $$("[data-scope]").forEach((b) => b.addEventListener("click", () => {
      scope = b.dataset.scope;
      $$("[data-scope]").forEach((x) => x.setAttribute("aria-selected", x === b));
      loadBoard();
    }));
    $$("[data-signin]").forEach((b) => b.addEventListener("click", () => needAccount("Sign in to join the game")));
  }

  // Invite links: play.html?follow=username
  async function followFromLink() {
    const u = new URLSearchParams(location.search).get("follow");
    if (!u || !MD.user || !profile || !profile.username) return;
    const { data } = await MD.sb.from("profiles").select("id").eq("username", u.toLowerCase()).maybeSingle();
    if (data && data.id !== MD.user.id) {
      await MD.sb.from("follows").insert({ follower: MD.user.id, followee: data.id });
      MD.toast(`You're now following @${u} 👋`);
      history.replaceState(null, "", location.pathname);
      loadFriends();
    }
  }

  // Today's call: if you already have an open call on this stock, show it instead of the buttons.
  async function showMyCall() {
    const card = $("[data-call-sym]");
    if (!card || !MD.user || !MD.sb) return;
    const { data } = await MD.sb.from("predictions").select("direction, confidence, status, made_at")
      .eq("user_id", MD.user.id).eq("symbol", card.dataset.callSym).order("made_at", { ascending: false }).limit(1);
    const p = data && data[0];
    if (!p || p.status !== "pending") return;
    $(".pr-btns", card).hidden = true; $(".conf", card).hidden = true;
    const made = $(".call-made", card); made.hidden = false;
    made.innerHTML = `<b>Your call is in: ${p.direction === "up" ? "▲ higher" : "▼ lower"}, ${Math.round(p.confidence * 100)}% sure.</b>
      <span class="muted small">Scored at the first market-hours price update after ${new Date(new Date(p.made_at).getTime() + 20 * 3600e3).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}. Right calls earn up to $400.</span>`;
  }
  document.addEventListener("click", (e) => { if (e.target.closest("[data-call-sym] [data-predict]")) setTimeout(showMyCall, 800); });

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-showall]");
    if (!b) return;
    const list = $(b.dataset.showall), all = list.classList.toggle("all");
    b.dataset.label = b.dataset.label || b.textContent;
    b.textContent = all ? "Show fewer" : b.dataset.label;
  });
  const sideCol = $(".rh-side");
  if (sideCol && "ResizeObserver" in window) {
    const fit = () => sideCol.style.setProperty("--side-top", Math.min(76, innerHeight - sideCol.offsetHeight - 16) + "px");
    new ResizeObserver(fit).observe(sideCol); addEventListener("resize", fit);
  }
  const onAuth = async () => {
    // A failed lookup (offline, or tables not set up yet) must not stop the rest of the page from updating.
    try { await loadProfile(); } catch (e) { profile = null; }
    if (MD.user && !(profile && profile.username) && (play || new URLSearchParams(location.search).get("follow"))) openUsername();
    loadPlay();
    followFromLink();
    showMyCall();
  };
  document.addEventListener("md:auth", onAuth);
  if (MD.authReady) onAuth();  // sign-in state arrived before this script loaded
  // Safety net: if the page still shows the guest view while someone is signed in, catch up once everything has loaded.
  addEventListener("load", () => setTimeout(() => {
    const guest = $("[data-guest]");
    if (MD.user && guest && !guest.hidden) onAuth();
  }, 800));
  if (play && !MD.sb) $("#lb-body").innerHTML = `<tr><td colspan="4" class="muted">Leaderboards need the online site.</td></tr>`;
  if (play && MD.sb) loadBoard();
})();
