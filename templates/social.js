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
  let profile = null;

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
    $("#uname-in").value = (MD.user.email || "").split("@")[0].toLowerCase().replace(/[^a-z0-9_]/g, "").slice(0, 20);
    $("#uname-msg").hidden = true;
    d.showModal();
  }
  $("#uname-form") && $("#uname-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = $("#uname-in").value.trim().toLowerCase();
    const display_name = $("#uname-name").value.trim() || null;
    if (!/^[a-z0-9_]{3,20}$/.test(username)) return showUnameErr("3–20 characters: letters, numbers or _");
    const row = { id: MD.user.id, username, ...(display_name ? { display_name } : {}) };
    let { error } = await MD.sb.from("profiles").upsert(row);
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
  let board = "streak", scope = "all";
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
    } else if (board === "calls") {
      const { data, error } = await MD.sb.rpc("leaderboard_predictions");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      // Rank by forecasting skill (Brier score vs. a 50/50 guess) once someone has 5+ scored calls; luck alone can't top this board.
      const scored = (r) => r.calls >= 5 && r.skill != null;
      rows = data.sort((a, b) => (scored(b) - scored(a)) || (b.skill ?? -999) - (a.skill ?? -999) || b.right_calls - a.right_calls);
      col = "🔮 Forecasting skill (60 days)";
      fmt = (r) => r.skill != null ? `<b>${r.skill > 0 ? "+" : ""}${r.skill}</b> <span class="muted">${r.right_calls}/${r.calls} right</span>` : `<span class="muted">${r.calls} pending</span>`;
    } else {
      const { data, error } = await MD.sb.rpc("leaderboard_portfolios");
      if (error) return (tbody.innerHTML = `<tr><td colspan="4">${esc(errMsg(error))}</td></tr>`);
      rows = data.sort((a, b) => b.return_pct - a.return_pct);
      col = "💼 Return on $100k";
      fmt = (r) => `<span class="${r.return_pct >= 0 ? "pos" : "neg"}">${pct(r.return_pct)}</span> <span class="muted">${money(r.value)}</span>`;
    }
    if (scope === "friends" && MD.user) {
      const { data } = await MD.sb.from("follows").select("followee").eq("follower", MD.user.id);
      const ids = new Set((data || []).map((f) => f.followee).concat(MD.user.id));
      rows = rows.filter((r) => ids.has(r.id));
    }
    $("#lb-col").textContent = col;
    tbody.innerHTML = rows.length ? rows.slice(0, 50).map((r, i) => `<tr class="${MD.user && r.id === MD.user.id ? "me" : ""}">
        <td class="rank">${i < 3 ? ["🥇", "🥈", "🥉"][i] : i + 1}</td>
        <td><b>${esc(r.display_name || r.username)}</b> <span class="muted">@${esc(r.username)}</span></td>
        <td class="num">${fmt(r)}</td>
        <td>${MD.user && r.id !== MD.user.id ? `<button class="mini" type="button" data-follow="${r.id}">Follow</button>` : ""}</td></tr>`).join("")
      : `<tr><td colspan="4" class="muted">${scope === "friends" ? "No friends here yet. Share your invite link!" : "Nobody here yet. Be the first!"}</td></tr>`;
    markFollowing();
  }

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

  async function loadPortfolio() {
    const box = $("#portfolio");
    if (!box || !MD.user) return;
    const [{ data: pf }, { data: pos }, { data: orders }, { data: lp }] = await Promise.all([
      MD.sb.from("portfolios").select("cash").eq("user_id", MD.user.id).maybeSingle(),
      MD.sb.from("positions").select("*").eq("user_id", MD.user.id),
      MD.sb.from("orders").select("*").eq("user_id", MD.user.id).order("placed_at", { ascending: false }).limit(15),
      MD.sb.from("latest_prices").select("symbol, price, name, as_of"),
    ]);
    const price = Object.fromEntries((lp || []).map((p) => [p.symbol, p]));
    const cash = pf ? Number(pf.cash) : 100000;
    const rows = (pos || []).map((p) => ({ ...p, now: price[p.symbol]?.price ?? p.avg_buy_price, name: price[p.symbol]?.name || p.symbol }));
    const invested = rows.reduce((s, r) => s + r.qty * r.now, 0);
    const total = cash + invested, ret = (total / 100000 - 1) * 100;
    $("#pf-total").textContent = money(total);
    $("#pf-ret").innerHTML = `<span class="${ret >= 0 ? "pos" : "neg"}">${pct(ret)}</span> since you started with $100,000`;
    $("#pf-cash").textContent = money(cash);
    $("#pf-inv").textContent = money(invested);
    $("#pf-pos").innerHTML = rows.length ? rows.map((r) => {
      const g = (r.now / r.avg_buy_price - 1) * 100;
      return `<tr><td><b>${esc(r.symbol)}</b><div class="muted small">${esc(r.name)}</div></td><td class="num">${Number(r.qty).toLocaleString()}</td>
        <td class="num">${money(r.avg_buy_price)}</td><td class="num">${money(r.now)}</td><td class="num">${money(r.qty * r.now)} <span class="${g >= 0 ? "pos" : "neg"}">${pct(g)}</span></td></tr>`;
    }).join("") : `<tr><td colspan="5" class="muted">No holdings yet. Try buying a few shares of SPY (the whole S&P 500 in one fund) below.</td></tr>`;
    $("#pf-orders").innerHTML = (orders || []).map((o) => `<li><span class="st st-${o.status}">${o.status}</span>
        ${o.side === "buy" ? "Buy" : "Sell"} ${Number(o.qty)} <b>${esc(o.symbol)}</b>
        ${o.fill_price ? "at " + money(o.fill_price) : ""} <span class="muted">${new Date(o.placed_at).toLocaleString()}</span>
        ${o.note ? `<span class="muted">· ${esc(o.note)}</span>` : ""}
        ${o.status === "pending" ? `<button class="mini" type="button" data-cancel="${o.id}">Cancel</button>` : ""}</li>`).join("") || `<li class="muted">No orders yet.</li>`;
    const sel = $("#qt-sym");
    if (sel && !sel.options.length) {
      const tradable = (lp || []).filter((p) => !p.symbol.startsWith("^")).sort((a, b) => a.symbol.localeCompare(b.symbol));
      const funds = ["SPY", "QQQ", "VTI"];
      sel.innerHTML = tradable.sort((a, b) => (funds.includes(b.symbol) - funds.includes(a.symbol))).map((p) => `<option value="${esc(p.symbol)}" data-price="${p.price}">${esc(p.symbol)} · ${esc(p.name || "")} · ${money(p.price)}</option>`).join("");
      sel.dispatchEvent(new Event("change"));
    }
  }
  $("#qt-sym") && $("#qt-sym").addEventListener("change", (e) => {
    const box = e.target.closest(".trade"), opt = e.target.selectedOptions[0];
    if (!opt) return;
    box.dataset.sym = opt.value; box.dataset.price = opt.dataset.price;
    $(".trade-qty", box).dispatchEvent(new Event("input", { bubbles: true }));
  });
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
    loadBoard();
    if (signedIn) { loadFriends(); loadPortfolio(); loadCalls(); loadCalibration(); loadCoach(); }
  }
  if (play) {
    $$("[data-board]").forEach((b) => b.addEventListener("click", () => {
      board = b.dataset.board;
      $$("[data-board]").forEach((x) => x.setAttribute("aria-selected", x === b));
      loadBoard();
    }));
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

  const onAuth = async () => {
    // A failed lookup (offline, or tables not set up yet) must not stop the rest of the page from updating.
    try { await loadProfile(); } catch (e) { profile = null; }
    if (MD.user && !(profile && profile.username) && (play || new URLSearchParams(location.search).get("follow"))) openUsername();
    loadPlay();
    followFromLink();
  };
  document.addEventListener("md:auth", onAuth);
  if (MD.authReady) onAuth();  // sign-in state arrived before this script loaded
  if (play && !MD.sb) $("#lb-body").innerHTML = `<tr><td colspan="4" class="muted">Leaderboards need the online site.</td></tr>`;
  if (play && MD.sb) loadBoard();
})();
