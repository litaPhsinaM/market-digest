// Everyday features: theme, streak, reading progress, quiz, watchlist, ⌘K search, "Today in 60 seconds",
// audio player, share cards, offline app. Personal progress is saved in this browser (localStorage) first;
// account.js syncs it across devices for signed-in users through the window.MD hooks below.
(function () {
  const MD = (window.MD = window.MD || {});
  MD.changed = MD.changed || (() => {}); // account.js replaces these
  MD.track = MD.track || (() => {});
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const base = document.body.dataset.base || "";
  const store = {
    get(k, d) { try { const v = localStorage.getItem("md:" + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("md:" + k, JSON.stringify(v)); } catch (e) {} MD.changed(k); },
  };
  // Last-writer-wins log of toggles (read/unread, star/unstar) so un-doing something on one device syncs correctly.
  function logToggle(key, on) {
    const log = store.get("log", {});
    log[key] = { on, t: Date.now() };
    store.set("log", log);
  }
  const todayLocal = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false; t.classList.add("on");
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.classList.remove("on"); setTimeout(() => (t.hidden = true), 250); }, 2400);
  }

  // ---------- theme ----------
  const themeBtn = $("#theme-btn");
  const effective = () => document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  // In the Android/iOS app, keep the phone's status bar in step with the theme (dark icons on light, and vice versa).
  function syncStatusBar() {
    const bar = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.StatusBar;
    if (!bar) return;
    const dark = effective() === "dark";
    bar.setStyle({ style: dark ? "DARK" : "LIGHT" }).catch(() => {});
    bar.setBackgroundColor({ color: dark ? "#111110" : "#f4f3ef" }).catch(() => {});
  }
  syncStatusBar();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncStatusBar);
  themeBtn && themeBtn.addEventListener("click", () => {
    const next = effective() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    syncStatusBar();
  });

  // ---------- streak ----------
  function markActive() {
    const days = new Set(store.get("days", []));
    const before = days.size;
    days.add(todayLocal());
    store.set("days", [...days].sort().slice(-400));
    renderStreak(before !== days.size);
  }
  function streakCount() {
    const days = new Set(store.get("days", []));
    let n = 0;
    const d = new Date();
    if (!days.has(d.toLocaleDateString("en-CA"))) d.setDate(d.getDate() - 1); // streak survives until today ends
    while (days.has(d.toLocaleDateString("en-CA"))) { n++; d.setDate(d.getDate() - 1); }
    return n;
  }
  function renderStreak(bumped) {
    const el = $("#streak"), n = streakCount();
    if (!el || !n) return;
    el.hidden = false; el.querySelector("b").textContent = n;
    el.title = `${n}-day streak: days in a row you've read a story or taken the quiz`;
    if (bumped) { el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); toast(n > 1 ? `🔥 ${n}-day streak! Keep it going.` : "🔥 Streak started! Come back tomorrow."); }
  }
  renderStreak(false);

  // ---------- reading progress ----------
  const actions = $(".actions");
  const day = actions && actions.dataset.day;
  const total = actions ? +actions.dataset.total : 0;
  function renderRead() {
    if (!day) return;
    const read = store.get("read:" + day, []);
    $$("[data-read]").forEach((b) => {
      const on = read.includes(b.dataset.read);
      b.setAttribute("aria-pressed", on);
      b.querySelector(".lbl").textContent = on ? "Read" : "Mark as read";
      b.closest(".ep")?.classList.toggle("is-read", on);
    });
    $$(".sc[data-story]").forEach((c) => c.classList.toggle("is-read", read.includes(c.dataset.story)));
    const n = read.filter((id) => document.getElementById(id)).length;
    if ($("#read-n")) {
      $("#read-n").textContent = n;
      $("#ring-fg").style.strokeDashoffset = 94.25 * (1 - (total ? n / total : 0));
      $("#read-msg").textContent = n === 0 ? "Tap ✓ on each story when you're done" : n < total ? `${total - n} to go · tap for the next` : "All done today 🎉";
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-read]");
    if (!b) return;
    const read = new Set(store.get("read:" + day, []));
    const on = !read.has(b.dataset.read);
    on ? (read.add(b.dataset.read), markActive(), MD.track("story_read", { id: b.dataset.read })) : read.delete(b.dataset.read);
    logToggle(`read:${day}:${b.dataset.read}`, on);
    store.set("read:" + day, [...read]);
    renderRead();
    if (read.size === total && total) toast("🎉 You've read everything today!");
    else if (on && b.closest("dialog.sheet")) toast("✓ Marked as read. Tap “Next story” to keep going");
  });
  renderRead();
  // ---------- story sheets: tap a card to read, ✓ to mark read, then on to the next ----------
  const sheets = $$("dialog.sheet");
  function openStory(id) {
    const d = document.getElementById(id);
    if (!d || !d.classList.contains("sheet")) return false;
    $$("dialog[open]").forEach((x) => x !== d && x.close());
    if (!d.open) d.showModal();
    d.scrollTop = 0;
    history.replaceState(null, "", "#" + id);
    MD.track("story_open", { id });
    return true;
  }
  function nextUnread(afterId) {
    const read = store.get("read:" + day, []);
    const ids = sheets.map((d) => d.id);
    const start = afterId ? ids.indexOf(afterId) + 1 : 0;
    return [...ids.slice(start), ...ids.slice(0, start)].find((id) => !read.includes(id) && id !== afterId);
  }
  function goNext(fromId) {
    const next = nextUnread(fromId);
    if (next) return openStory(next);
    $$("dialog.sheet[open]").forEach((d) => d.close());
    toast("🎉 That's every story. Try the quiz!");
    $("#quiz")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  sheets.forEach((d) => {
    d.addEventListener("click", (e) => { if (e.target === d || e.target.closest("[data-sheet-close]")) d.close(); });
    d.addEventListener("close", () => { if (location.hash === "#" + d.id) history.replaceState(null, "", location.pathname + location.search); });
  });
  document.addEventListener("click", (e) => {
    const card = e.target.closest("[data-story]");
    if (card) return void openStory(card.dataset.story);
    const nx = e.target.closest("[data-next-story]");
    if (nx) return void goNext(nx.closest("dialog").id);
    const a = e.target.closest('a[href^="#"]');
    if (a && a.getAttribute("href").length > 1 && openStory(a.getAttribute("href").slice(1))) {
      e.preventDefault();
      a.closest("dialog:not(.sheet)")?.close();
    }
  });
  addEventListener("hashchange", () => openStory(location.hash.slice(1)));
  if (location.hash.length > 1) setTimeout(() => openStory(decodeURIComponent(location.hash.slice(1))), 0);
  $("#next-unread") && $("#next-unread").addEventListener("click", () => {
    const next = nextUnread(null);
    next ? openStory(next) : $("#quiz")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  // ---------- quiz ----------
  const quiz = $("#quiz");
  if (quiz) {
    const key = "quiz:" + quiz.dataset.day;
    const answers = store.get(key, {});
    const qs = $$(".q", quiz);
    const show = (q, pick, animate) => {
      const right = +q.dataset.answer;
      $$(".q-opt", q).forEach((o) => {
        const i = +o.dataset.opt;
        o.disabled = true;
        o.classList.toggle("right", i === right);
        o.classList.toggle("wrong", i === pick && pick !== right);
      });
      q.classList.add("done", pick === right ? "ok" : "no");
      $(".q-exp", q).hidden = false;
      $(".q-exp", q).dataset.verdict = pick === right ? "Correct!" : "Not quite.";
      if (animate && pick === right) q.classList.add("burst");
    };
    const score = () => {
      const done = Object.keys(answers).length;
      const right = qs.filter((q) => answers[q.dataset.q] === +q.dataset.answer).length;
      const status = $("#quiz-status");
      if (status) status.textContent = done === qs.length ? `You scored ${right}/${qs.length}` : `${qs.length} questions`;
      if (done === qs.length) { const s = $("#quiz-score"); s.hidden = false; s.textContent = `${right} / ${qs.length}`; }
      return { done, right };
    };
    qs.forEach((q) => {
      if (q.dataset.q in answers) show(q, answers[q.dataset.q], false);
      $$(".q-opt", q).forEach((o) => o.addEventListener("click", () => {
        answers[q.dataset.q] = +o.dataset.opt;
        store.set(key, answers);
        show(q, +o.dataset.opt, true);
        markActive();
        const { done, right } = score();
        if (done === qs.length) {
          toast(right === qs.length ? "🏆 Perfect score!" : `Quiz done: ${right}/${qs.length}. See you tomorrow!`);
          MD.track("quiz_done", { right, of: qs.length });
        }
      }));
    });
    score();
    MD.refreshQuiz = () => {  // answers arriving from another device
      Object.assign(answers, store.get(key, {}));
      qs.forEach((q) => { if (q.dataset.q in answers && !q.classList.contains("done")) show(q, answers[q.dataset.q], false); });
      score();
    };
  }

  // ---------- watchlist (stars) ----------
  function renderStars() {
    const stars = store.get("stars", []);
    $$("[data-star]").forEach((b) => {
      const on = stars.includes(b.dataset.star);
      b.setAttribute("aria-pressed", on);
      b.textContent = on ? "★" : "☆";
      b.setAttribute("aria-label", `${on ? "Remove" : "Add"} ${b.dataset.star} ${on ? "from" : "to"} your watchlist`);
    });
    // starred companies float to the top, in the order they were starred
    for (const list of $$(".cos, .earn")) {
      const rows = $$(":scope > li", list);
      rows.sort((a, b) => {
        const ia = stars.indexOf(a.dataset.sym), ib = stars.indexOf(b.dataset.sym);
        return (ia < 0 ? 1e9 : ia) - (ib < 0 ? 1e9 : ib);
      }).forEach((r) => { r.classList.toggle("starred", stars.includes(r.dataset.sym)); list.appendChild(r); });
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-star]");
    if (!b) return;
    e.stopPropagation();
    const stars = store.get("stars", []);
    const i = stars.indexOf(b.dataset.star);
    i < 0 ? stars.push(b.dataset.star) : stars.splice(i, 1);
    logToggle("star:" + b.dataset.star, i < 0);
    store.set("stars", stars);
    if (i < 0) MD.track("star", { sym: b.dataset.star });
    renderStars();
    toast(i < 0 ? `★ ${b.dataset.star} added to your watchlist` : `${b.dataset.star} removed from your watchlist`);
  }, true);
  renderStars();

  // Redraw everything personal, e.g. after account.js merges in progress from another device.
  Object.assign(MD, { store, toast, todayLocal, logToggle,
    refresh() { renderStreak(false); renderRead(); renderStars(); MD.refreshQuiz && MD.refreshQuiz(); } });

  // ---------- ⌘K search ----------
  const pal = $("#palette"), palQ = $("#pal-q"), palRes = $("#pal-res"), palHint = $("#pal-hint");
  let index = null, sel = 0;
  async function openSearch() {
    if (!pal) return;
    pal.showModal(); palQ.value = ""; palRes.innerHTML = ""; palHint.hidden = false; palQ.focus();
    if (!index) {
      try { index = await (await fetch(base + "search.json")).json(); } catch (e) { index = []; palHint.textContent = "Search works once the site is online."; }
    }
  }
  function runSearch() {
    const q = palQ.value.trim().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    palHint.hidden = !!q;
    if (!q || !index) { palRes.innerHTML = ""; return; }
    const hits = index.map((r) => {
      const hay = (r.t + " " + r.s + " " + r.m).toLowerCase(), title = r.t.toLowerCase();
      if (!words.every((w) => hay.includes(w))) return null;
      return { r, score: words.reduce((s, w) => s + (title.includes(w) ? 3 : 1), 0) + (title.startsWith(q) ? 5 : 0) };
    }).filter(Boolean).sort((a, b) => b.score - a.score || (b.r.d || "").localeCompare(a.r.d || "")).slice(0, 12);
    sel = 0;
    palRes.innerHTML = hits.length ? hits.map(({ r }, i) => `<li role="option" aria-selected="${i === 0}"><a href="${base + r.u}">
      <span class="pal-k k-${r.k.toLowerCase()}">${esc(r.k)}</span><span class="pal-t">${esc(r.t)}</span>
      <span class="pal-s">${esc(r.s.slice(0, 110))}${r.s.length > 110 ? "…" : ""}</span><span class="pal-m">${esc(r.m)}${r.d ? " · " + r.d : ""}</span></a></li>`).join("")
      : `<li class="pal-none">No results for “${esc(q)}”</li>`;
  }
  function moveSel(d) {
    const items = $$("li[role=option]", palRes);
    if (!items.length) return;
    items[sel].setAttribute("aria-selected", false);
    sel = (sel + d + items.length) % items.length;
    items[sel].setAttribute("aria-selected", true);
    items[sel].scrollIntoView({ block: "nearest" });
  }
  if (pal) {
    palQ.addEventListener("input", runSearch);
    palQ.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
      if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
      if (e.key === "Enter") { const a = $("li[aria-selected=true] a", palRes); if (a) { pal.close(); location.href = a.href; } }
    });
    // close on pick too, so a result on this same page (just a #hash jump) doesn't leave the palette open
    pal.addEventListener("click", (e) => { if (e.target === pal || e.target.closest("a")) pal.close(); });
  }
  $$("[data-search]").forEach((b) => b.addEventListener("click", openSearch));
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openSearch(); }
    else if (e.key === "/" && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); openSearch(); }
  });

  // ---------- Today in 60 seconds ----------
  const stories = $("#stories");
  const slides = $("#slides-data") ? JSON.parse($("#slides-data").textContent) : [];
  let cur = 0, timer = null, started = 0, paused = false, remaining = 0;
  const DUR = 9000;
  function renderSlide() {
    const s = slides[cur];
    $("#st-bars").innerHTML = slides.map((_, i) => `<span class="${i < cur ? "full" : ""}"><i ${i === cur ? 'class="run"' : ""}></i></span>`).join("");
    const mood = s.mood ? `<div class="st-mood"><b>${s.mood.score}</b> Market mood: ${esc(s.mood.label)}</div>` : "";
    const extra = s.why ? `<p class="st-why"><span>Why it matters</span>${esc(s.why)}</p>` : s.lesson ? `<p class="st-why"><span>The lesson</span>${esc(s.lesson)}</p>` : "";
    const cta = s.href ? `<a class="st-cta" href="${esc(s.href)}" data-st-close>${s.kind === "quiz" ? "Take the quiz →" : "Read the full story →"}</a>` : "";
    $("#st-card").className = "st-card k-" + s.kind;
    $("#st-card").innerHTML = s.kind === "cover"
      ? `<div class="st-brand">Market Digest</div><div class="st-label">Today in 60 seconds</div><h2>${esc(s.title)}</h2>${mood}<p>${esc(s.text)}</p><div class="st-tap">Tap the right side for the next card · left to go back · hold to pause</div>`
      : `<div class="st-label">${esc(s.label)}</div><h2>${esc(s.title)}</h2><p>${esc(s.text)}</p>${extra}${cta}`;
    $("#st-card").classList.remove("in"); void $("#st-card").offsetWidth; $("#st-card").classList.add("in");
    schedule(DUR);
  }
  function schedule(ms) {
    clearTimeout(timer); started = Date.now(); remaining = ms;
    const bar = $("#st-bars .run");
    if (bar) { bar.style.animationDuration = ms + "ms"; bar.style.animationPlayState = "running"; }
    timer = setTimeout(() => go(1), ms);
  }
  function go(d) {
    if (cur + d >= slides.length) return closeStories(true);
    cur = Math.max(0, cur + d);
    renderSlide();
  }
  function pause(on) {
    const bar = $("#st-bars .run");
    if (on && !paused) { paused = true; clearTimeout(timer); remaining -= Date.now() - started; if (bar) bar.style.animationPlayState = "paused"; }
    else if (!on && paused) { paused = false; schedule(remaining); if (bar) bar.style.animationPlayState = "running"; }
  }
  let opener = null;
  function openStories() {
    if (!slides.length) return;
    opener = document.activeElement;
    cur = 0; paused = false; stories.hidden = false; document.body.classList.add("noscroll");
    MD.track("stories_open");
    renderSlide(); markActive();
    $("#st-x").focus();
  }
  function closeStories(finished, toStory) {
    clearTimeout(timer); stories.hidden = true; document.body.classList.remove("noscroll");
    if (!toStory && opener && opener.focus) opener.focus({ preventScroll: true });
    if (finished === true) toast("✓ You're caught up for today");
  }
  if (stories) {
    $$("[data-stories]").forEach((b) => b.addEventListener("click", openStories));
    $("#st-x").addEventListener("click", () => closeStories());
    $("#st-next").addEventListener("click", () => go(1));
    $("#st-prev").addEventListener("click", () => go(-1));
    stories.addEventListener("click", (e) => { if (e.target.closest("[data-st-close]")) closeStories(false, true); });
    let downAt = 0, x0 = 0;
    stories.addEventListener("pointerdown", (e) => { downAt = Date.now(); x0 = e.clientX; pause(true); });
    stories.addEventListener("pointerup", (e) => {
      pause(false);
      const dx = e.clientX - x0;
      if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
    });
    document.addEventListener("keydown", (e) => {
      if (stories.hidden) return;
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); go(1); }
      if (e.key === "ArrowLeft") go(-1);
      if (e.key === "Escape") closeStories();
      if (e.key === "Tab") { // keep keyboard focus inside the overlay
        const f = $$("button, a[href]", stories), i = f.indexOf(document.activeElement);
        e.preventDefault(); f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    });
  }

  // ---------- audio player ----------
  const player = $("#player"), audio = $("#audio");
  if (player && audio) {
    const fmt = (s) => isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00";
    const playBtn = $("#pl-play"), seek = $("#pl-seek");
    const speeds = [1, 1.25, 1.5, 0.75];
    const sync = () => { playBtn.textContent = audio.paused ? "▶" : "❚❚"; playBtn.setAttribute("aria-label", audio.paused ? "Play" : "Pause"); };
    $$("[data-listen]").forEach((b) => b.addEventListener("click", () => { player.hidden = false; audio.play(); markActive(); MD.track("listen"); }));
    playBtn.addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
    audio.addEventListener("play", sync); audio.addEventListener("pause", sync);
    audio.addEventListener("loadedmetadata", () => ($("#pl-dur").textContent = fmt(audio.duration)));
    audio.addEventListener("timeupdate", () => {
      $("#pl-cur").textContent = fmt(audio.currentTime);
      if (audio.duration) seek.value = (audio.currentTime / audio.duration) * 1000;
    });
    audio.addEventListener("ended", () => toast("✓ Briefing finished. Nice!"));
    seek.addEventListener("input", () => { if (audio.duration) audio.currentTime = (seek.value / 1000) * audio.duration; });
    $("#pl-speed").addEventListener("click", (e) => {
      const next = speeds[(speeds.indexOf(audio.playbackRate) + 1) % speeds.length];
      audio.playbackRate = next; e.currentTarget.textContent = next + "×";
    });
    $("#pl-tx").addEventListener("click", (e) => {
      const s = $("#pl-script"); s.hidden = !s.hidden; e.currentTarget.setAttribute("aria-expanded", !s.hidden);
    });
    $("#pl-x").addEventListener("click", () => { audio.pause(); player.hidden = true; });
  }

  // ---------- share cards ----------
  function wrap(ctx, text, maxW, maxLines) {
    const words = text.split(/\s+/), lines = [];
    let line = "";
    for (const w of words) {
      const test = line ? line + " " + w : w;
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = w; } else line = test;
    }
    if (line) lines.push(line);
    if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, "…"); }
    return lines;
  }
  async function shareCard(kind, title, text) {
    const W = 1080, H = 1350, c = document.createElement("canvas");
    c.width = W; c.height = H;
    const x = c.getContext("2d");
    const g = x.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#0f2a23"); g.addColorStop(1, "#111110");
    x.fillStyle = g; x.fillRect(0, 0, W, H);
    const font = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    // brand
    x.fillStyle = "#1f6f5c"; x.beginPath(); x.roundRect(80, 80, 64, 64, 16); x.fill();
    x.strokeStyle = "#fff"; x.lineWidth = 7; x.lineCap = x.lineJoin = "round";
    x.beginPath(); x.moveTo(96, 124); x.lineTo(110, 110); x.lineTo(119, 119); x.lineTo(130, 104); x.stroke();
    x.fillStyle = "#f0efec"; x.font = `700 38px ${font}`; x.fillText("Market Digest", 166, 125);
    x.fillStyle = "#5cc0a2"; x.font = `700 28px ${font}`; x.fillText(kind.toUpperCase(), 80, 260);
    x.fillStyle = "#ffffff"; x.font = `800 72px ${font}`;
    let y = 350;
    for (const l of wrap(x, title, W - 160, 5)) { x.fillText(l, 80, y); y += 86; }
    x.fillStyle = "#c3c2b7"; x.font = `400 38px ${font}`; y += 30;
    for (const l of wrap(x, text, W - 160, 8)) { x.fillText(l, 80, y); y += 54; }
    x.fillStyle = "#2c2c2a"; x.fillRect(80, H - 170, W - 160, 2);
    x.fillStyle = "#f0efec"; x.font = `700 32px ${font}`; x.fillText("Learn the market in 5 minutes a day", 80, H - 105);
    x.fillStyle = "#8f8e86"; x.font = `400 28px ${font}`; x.fillText(location.host || "market digest", 80, H - 62);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const file = new File([blob], "market-digest.png", { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title, text: `${title}, via Market Digest` }); return; } catch (e) { if (e.name === "AbortError") return; }
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "market-digest.png"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast("Image saved, ready to post");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-share]");
    if (b) { shareCard(b.dataset.kind, b.dataset.title, b.dataset.text); MD.track("share"); }
  });

  // ---------- offline / installable app ----------
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    addEventListener("load", () => navigator.serviceWorker.register(base + "sw.js").catch(() => {}));
  }
})();
