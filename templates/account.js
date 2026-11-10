// Optional accounts + cross-device sync (Supabase), and anonymous usage events.
// Everything works signed out; signing in merges this device's progress with the account's and keeps
// every open device in step (live updates via Supabase Realtime).
(function () {
  const MD = window.MD, body = document.body;
  const url = body.dataset.sbUrl, key = body.dataset.sbKey;
  if (!MD || !url || !key || !window.supabase) return;
  const $ = (s, r = document) => r.querySelector(s);
  const native = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  const platform = native ? window.Capacitor.getPlatform() : matchMedia("(display-mode: standalone)").matches ? "pwa" : "web";
  const sb = supabase.createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" } });
  let user = null, channel = null;

  // ---------- anonymous usage events ----------
  let device;
  try { device = localStorage.getItem("device") || crypto.randomUUID(); localStorage.setItem("device", device); } catch (e) { device = "unknown"; }
  const day = ($(".actions") || {}).dataset?.day || null;
  MD.track = (event, props = {}) => {
    fetch(url + "/rest/v1/events", {
      method: "POST", keepalive: true,
      headers: { apikey: key, Authorization: "Bearer " + key, "Content-Type": "application/json", Prefer: "return=minimal" },
      body: JSON.stringify({ event, day, device: device.slice(0, 40), platform, signed_in: !!user, props }),
    }).catch(() => {});
  };
  try {
    if (localStorage.getItem("opened") !== MD.todayLocal()) { localStorage.setItem("opened", MD.todayLocal()); MD.track("open"); }
  } catch (e) {}

  // ---------- progress document ----------
  const SYNCED = (k) => k === "days" || k === "stars" || k === "log" || k.startsWith("read:") || k.startsWith("quiz:");
  function collect() {
    const doc = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.startsWith("md:") && SYNCED(k.slice(3))) { try { doc[k.slice(3)] = JSON.parse(localStorage.getItem(k)); } catch (e) {} }
    }
    return doc;
  }
  // Merge two progress documents. Streak days and quiz answers only ever grow; read/star toggles resolve by
  // the most recent change (the "log"), so un-starring on one device also un-stars on the others.
  function merge(a, b) {
    const out = {}, log = { ...(a.log || {}) };
    for (const [k, v] of Object.entries(b.log || {})) if (!log[k] || v.t > log[k].t) log[k] = v;
    out.log = log;
    out.days = [...new Set([...(a.days || []), ...(b.days || [])])].sort().slice(-400);
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) {
      if (k.startsWith("quiz:")) out[k] = { ...(b[k] || {}), ...(a[k] || {}) };
      if (k.startsWith("read:")) {
        const ids = new Set([...(a[k] || []), ...(b[k] || [])]);
        for (const [lk, v] of Object.entries(log)) if (lk.startsWith(k + ":")) v.on ? ids.add(lk.slice(k.length + 1)) : ids.delete(lk.slice(k.length + 1));
        out[k] = [...ids];
      }
    }
    const stars = [...new Set([...(a.stars || []), ...(b.stars || [])])].filter((s) => !log["star:" + s] || log["star:" + s].on);
    for (const [lk, v] of Object.entries(log)) if (lk.startsWith("star:") && v.on && !stars.includes(lk.slice(5))) stars.push(lk.slice(5));
    out.stars = stars.sort((x, y) => (log["star:" + x]?.t || 0) - (log["star:" + y]?.t || 0));
    return out;
  }
  function apply(doc) {
    try { for (const [k, v] of Object.entries(doc)) localStorage.setItem("md:" + k, JSON.stringify(v)); } catch (e) {}
    MD.refresh();
    renderAccount();
  }

  // ---------- sync ----------
  let pushTimer = null, syncing = false;
  async function sync() {
    if (!user || syncing) return;
    syncing = true; setStatus("Syncing…");
    try {
      const { data, error } = await sb.from("user_state").select("state").eq("user_id", user.id).maybeSingle();
      if (error) throw error;
      const merged = merge((data && data.state) || {}, collect());
      apply(merged);
      const { error: e2 } = await sb.from("user_state").upsert({ user_id: user.id, state: merged, updated_at: new Date().toISOString() });
      if (e2) throw e2;
      setStatus("Synced across your devices");
    } catch (e) {
      setStatus(navigator.onLine ? "Sync failed, will retry" : "Offline: changes are saved and will sync later");
    } finally { syncing = false; }
  }
  MD.changed = (k) => {
    if (!user || !SYNCED(k)) return;
    clearTimeout(pushTimer); pushTimer = setTimeout(sync, 700);
  };
  addEventListener("online", () => sync());

  function listen() {
    if (channel) sb.removeChannel(channel);
    channel = sb.channel("state-" + user.id)
      .on("postgres_changes", { event: "*", schema: "public", table: "user_state", filter: `user_id=eq.${user.id}` }, (p) => {
        if (p.new && p.new.state) apply(merge(p.new.state, collect()));
      })
      .subscribe();
  }

  // ---------- UI ----------
  const btn = $("#acct-btn"), dlg = $("#acct"), statusEl = () => $("#acct-status");
  function setStatus(t) { const s = statusEl(); if (s) s.textContent = t; }
  function stats() {
    const doc = collect();
    const read = Object.entries(doc).filter(([k]) => k.startsWith("read:")).reduce((n, [, v]) => n + v.length, 0);
    const quizzes = Object.entries(doc).filter(([k]) => k.startsWith("quiz:")).length;
    return { read, quizzes, days: (doc.days || []).length };
  }
  function renderAccount() {
    if (!btn) return;
    btn.hidden = false;
    const name = user && (user.user_metadata?.full_name || user.email || "");
    btn.classList.toggle("in", !!user);
    btn.innerHTML = user
      ? (user.user_metadata?.avatar_url ? `<img src="${user.user_metadata.avatar_url}" alt="" referrerpolicy="no-referrer">` : `<span>${(name[0] || "?").toUpperCase()}</span>`)
      : `<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="7" r="3.5"/><path d="M3.5 17c1-3.3 3.5-5 6.5-5s5.5 1.7 6.5 5"/></svg><span class="lbl">Sign in</span>`;
    btn.setAttribute("aria-label", user ? "Your account" : "Sign in to sync your progress");
    $("#acct-out").hidden = !!user;
    $("#acct-in").hidden = !user;
    if (user) {
      const s = stats();
      $("#acct-name").textContent = user.user_metadata?.full_name || user.email;
      $("#acct-email").textContent = user.email || "";
      $("#acct-stats").innerHTML = `<div><b>${s.days}</b><span>days active</span></div><div><b>${s.read}</b><span>stories read</span></div><div><b>${s.quizzes}</b><span>quizzes</span></div>`;
    }
  }
  btn && btn.addEventListener("click", () => { renderAccount(); dlg.showModal(); });
  dlg && dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest("[data-acct-close]")) dlg.close(); });

  // Google sign-in (only shown once it's switched on in Supabase; in the native app Google blocks embedded sign-in).
  fetch(url + "/auth/v1/settings", { headers: { apikey: key } }).then((r) => r.json()).then((s) => {
    if (s.external && s.external.google && !native) $("#acct-google").hidden = false;
  }).catch(() => {});
  $("#acct-google") && $("#acct-google").addEventListener("click", () => {
    sb.auth.signInWithOAuth({ provider: "google", options: { redirectTo: location.origin + location.pathname } });
  });

  // Email: a sign-in link, or the 6-digit code from the same email (works inside the app and across devices).
  let email = "";
  $("#acct-email-form") && $("#acct-email-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    email = $("#acct-email-in").value.trim();
    const b = e.submitter || $("#acct-email-form button"); b.disabled = true;
    const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: native ? undefined : location.origin + location.pathname } });
    b.disabled = false;
    if (error) { setMsg(error.message); return; }
    $("#acct-code-form").hidden = false;
    setMsg(`Check ${email}: tap the link, or type the 6-digit code here.`);
    $("#acct-code-in").focus();
  });
  $("#acct-code-form") && $("#acct-code-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { error } = await sb.auth.verifyOtp({ email, token: $("#acct-code-in").value.trim(), type: "email" });
    if (error) setMsg(error.message);
  });
  function setMsg(t) { const m = $("#acct-msg"); m.textContent = t; m.hidden = !t; }
  $("#acct-signout") && $("#acct-signout").addEventListener("click", async () => {
    await sb.auth.signOut();
    MD.toast("Signed out. Your progress stays on this device.");
    dlg.close();
  });

  sb.auth.onAuthStateChange((event, session) => {
    const was = user;
    user = session ? session.user : null;
    renderAccount();
    if (user && (!was || was.id !== user.id)) {
      sync(); listen();
      if (event === "SIGNED_IN") { MD.toast("✓ Signed in, your progress now syncs"); MD.track("sign_in"); if (dlg.open) dlg.close(); }
    }
    if (!user && channel) { sb.removeChannel(channel); channel = null; }
  });
  renderAccount();
})();
