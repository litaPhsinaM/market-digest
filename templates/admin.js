// Team insights page. Data comes from the admin_insights() database function, which returns nothing unless the
// signed-in account is listed in public.admins, so this page is safe to publish.
(function () {
  const MD = window.MD;
  const root = document.getElementById("admin");
  if (!MD || !root) return;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n) => Number(n || 0).toLocaleString();
  const LABELS = { open: "Opened the app", story_open: "Opened a story", story_read: "Marked a story read", quiz_done: "Finished the daily quiz",
    listen: "Played the audio briefing", stories_open: "Used Today in 60s", share: "Shared a card", star: "Starred a company",
    lesson_open: "Opened a lesson", lesson_done: "Completed a lesson", practice_start: "Started practice", practice_done: "Finished practice",
    predict: "Made a prediction", paper_order: "Placed a paper trade", follow: "Followed a friend", sign_in: "Signed in", username_set: "Picked a username" };
  let days = 30;

  // Single-series line chart with a lighter second line; hover shows the day's values.
  function line(el, rows, key, key2) {
    if (!rows.length) return (el.innerHTML = `<p class="muted small">No data yet.</p>`);
    const W = el.clientWidth || 640, H = 200, L = 34, R = 8, T = 10, B = 22;
    const max = Math.max(1, ...rows.map((r) => r[key]));
    const X = (i) => L + (rows.length === 1 ? (W - L - R) / 2 : (i / (rows.length - 1)) * (W - L - R));
    const Y = (v) => T + (1 - v / max) * (H - T - B);
    const path = (k) => rows.map((r, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(r[k] || 0).toFixed(1)}`).join("");
    const ticks = [0, Math.round(max / 2), max];
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="adm-svg" role="img" aria-label="${key} per day">
      ${ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="axis" x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join("")}
      <text class="axis" x="${L}" y="${H - 4}">${rows[0].day.slice(5)}</text><text class="axis" x="${W - R}" y="${H - 4}" text-anchor="end">${rows[rows.length - 1].day.slice(5)}</text>
      ${key2 ? `<path d="${path(key2)}" class="ln2"/>` : ""}<path d="${path(key)}" class="ln"/>
      ${rows.map((r, i) => `<circle cx="${X(i)}" cy="${Y(r[key])}" r="3" class="dt"><title>${r.day}: ${fmt(r[key])}${key2 ? " · signed in " + fmt(r[key2]) : ""}</title></circle>`).join("")}
    </svg>`;
  }
  // Horizontal bars: label, value, bar scaled to the largest value.
  function bars(el, pairs, unit = "") {
    if (!pairs.length) return (el.innerHTML = `<p class="muted small">No data yet.</p>`);
    const max = Math.max(...pairs.map((p) => p[1]), 1);
    el.innerHTML = pairs.map(([label, v, note]) => `<div class="hb"><span class="hb-l" title="${esc(label)}">${esc(label)}</span>
      <span class="hb-t"><span class="hb-f" style="width:${(100 * v) / max}%"></span></span><span class="hb-v">${fmt(v)}${unit}${note ? ` <span class="muted">${esc(note)}</span>` : ""}</span></div>`).join("");
  }

  async function load() {
    if (!MD.sb || !MD.user) { $("#adm-gate").hidden = false; $("#adm-body").hidden = true; return; }
    const { data, error } = await MD.sb.rpc("admin_insights", { p_days: days });
    if (error || !data) {
      $("#adm-gate").textContent = error ? error.message : "This account isn't an admin. Add it to public.admins in Supabase.";
      $("#adm-gate").hidden = false; $("#adm-body").hidden = true; return;
    }
    $("#adm-gate").hidden = true; $("#adm-body").hidden = false;
    if (MD.device) MD.sb.rpc("mark_internal_device", { p_device: MD.device() }); // keep the team's own device out of the stats
    const t = data.totals;
    $("#adm-tiles").innerHTML = [["Active devices (7d)", t.devices_7d], ["Active devices (30d)", t.devices_30d], ["Accounts", t.users],
      ["With username", t.profiles], ["Paper portfolios", t.portfolios], ["Predictions", t.predictions], ["Friend follows", t.follows], ["Your devices (excluded)", t.internal_devices]]
      .map(([k, v]) => `<div class="tile"><div class="tile-name">${k}</div><div class="tile-price">${fmt(v)}</div></div>`).join("");
    line($("#ch-daily"), data.daily, "devices", "signed_in");
    bars($("#ch-features"), Object.entries(data.features).filter(([k]) => k !== "setup_check").sort((a, b) => b[1] - a[1]).map(([k, v]) => [LABELS[k] || k, v]));
    bars($("#ch-platforms"), Object.entries(data.platforms).sort((a, b) => b[1] - a[1]).map(([k, v]) => [{ web: "Website", pwa: "Installed web app", android: "Android app", ios: "iPhone app" }[k] || k, v]));
    bars($("#ch-retention"), data.retention.map((r) => [`Week of ${r.cohort}`, r.d7_return_pct, `of ${r.devices}`]), "%");
    bars($("#ch-lessons"), Object.entries(data.lessons).sort((a, b) => a[0].localeCompare(b[0])).map(([k, v]) => [`Lesson ${+k.slice(1) || k}`, v]));
    bars($("#ch-practice"), data.practice.map((p) => [p.level, p.rounds, `avg ${p.avg_score}/10`]));
    line($("#ch-signups"), data.signups.map((s) => ({ day: s.day, n: s.n })), "n");
    loadPeople();
  }
  const ago = (t) => {
    if (!t) return "—";
    const s = (Date.now() - new Date(t)) / 1000;
    return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(t).toLocaleDateString();
  };
  async function loadPeople() {
    const [{ data: people }, { data: live }] = await Promise.all([MD.sb.rpc("admin_people", { p_limit: 200 }), MD.sb.rpc("admin_live", { p_limit: 40 })]);
    if (live) {
      $("#live-10m").textContent = live.online_10m; $("#live-1h").textContent = live.online_1h;
      $("#feed").innerHTML = live.feed.map((e) => `<li><span class="muted small" style="min-width:76px">${ago(e.created_at)}</span>
        <b>${esc(LABELS[e.event] || e.event)}</b> <span class="muted small">${esc({ web: "website", pwa: "installed web app", android: "Android app", ios: "iPhone app" }[e.platform] || e.platform || "")}
        ${e.signed_in ? "· signed in" : ""} · device ${esc(e.device)}</span></li>`).join("") || `<li class="muted">Nothing yet. Activity shows up here as people use the app.</li>`;
    }
    $("#people").innerHTML = (people || []).map((p) => `<tr>
        <td><b>${esc(p.username ? "@" + p.username : p.email)}</b>${p.username ? `<div class="muted small">${esc(p.email)}</div>` : ""}${p.confirmed ? "" : ` <span class="st st-pending">unconfirmed</span>`}</td>
        <td>${esc(p.device || "—")}</td><td>${ago(p.joined)}</td><td>${ago(p.last_sign_in)}</td>
        <td class="num">${p.streak ?? 0}</td><td class="num">${p.stories_read ?? 0}</td><td class="num">${p.quizzes ?? 0}</td><td class="num">${p.trades}</td><td class="num">${p.predictions}</td>
        <td class="manage">${p.is_admin ? `<span class="st st-filled">admin</span>` : ""}${p.banned ? `<span class="st st-rejected">banned</span>` : ""}
          ${MD.user && p.id === MD.user.id ? `<span class="muted small">you</span>` : `<select data-user="${p.id}" data-who="${esc(p.username ? "@" + p.username : p.email)}" aria-label="Manage this account">
            <option value="">Manage…</option>
            ${p.banned ? `<option value="unban">Unban</option>` : `<option value="ban">Ban (sign out + block)</option>`}
            ${p.username ? `<option value="clear_username">Clear username</option>` : ""}
            ${p.is_admin ? `<option value="remove_admin">Remove admin</option>` : `<option value="make_admin">Make admin</option>`}
            <option value="delete">Delete account…</option></select>`}</td></tr>`).join("")
      || `<tr><td colspan="10" class="muted">No accounts yet.</td></tr>`;
  }
  setInterval(() => { if (!$("#adm-body").hidden) loadPeople(); }, 30000);

  // Manage an account. Destructive actions ask for the name to be typed back, so nothing happens by accident.
  const ACTION_TEXT = { ban: "ban", unban: "unban", clear_username: "clear the username of", make_admin: "make an admin", remove_admin: "remove admin rights from", delete: "PERMANENTLY DELETE" };
  document.addEventListener("change", async (e) => {
    const sel = e.target.closest("select[data-user]");
    if (!sel || !sel.value) return;
    const action = sel.value, who = sel.dataset.who;
    sel.value = "";
    if (action === "delete" || action === "ban") {
      const typed = window.prompt(`Type ${who} to ${ACTION_TEXT[action]} this account${action === "delete" ? " and all their progress (can't be undone)" : ""}:`);
      if (typed !== who) return MD.toast("Cancelled");
    }
    const { data, error } = await MD.sb.rpc("admin_user_action", { p_user: sel.dataset.user, p_action: action });
    MD.toast(error ? error.message : `${who}: ${data}`);
    loadPeople();
  });

  // Tabs: Overview / People / Live activity (also reachable as admin.html#people etc.)
  function showTab(tab, reload = true) {
    if (!["overview", "people", "activity"].includes(tab)) tab = "overview";
    $$("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
    $$("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== tab));
    history.replaceState(null, "", "#" + tab);
    if (tab === "overview" && reload) load();  // charts need a visible box to size themselves
  }
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  addEventListener("hashchange", () => showTab(location.hash.slice(1)));

  $$("[data-days]").forEach((b) => b.addEventListener("click", () => {
    days = +b.dataset.days;
    $$("[data-days]").forEach((x) => x.setAttribute("aria-selected", x === b));
    load();
  }));
  const onAuth = () => { load().then(() => showTab(location.hash.slice(1), false)); };
  document.addEventListener("md:auth", onAuth);
  if (MD.authReady) onAuth();
})();
