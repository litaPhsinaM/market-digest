// "Start here" course: lesson sheets, per-lesson quiz, completion and progress (synced like the rest via md:lesson:*).
(function () {
  const MD = window.MD;
  const prog = document.getElementById("learn-progress");
  if (!MD || !prog) return;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sheets = $$("dialog.lesson");
  const ids = sheets.map((d) => d.id);
  const get = (id) => MD.store.get("lesson:" + id, {});

  function render() {
    const done = ids.filter((id) => get(id).done);
    $$("[data-lesson]").forEach((c) => c.classList.toggle("is-done", !!get(c.dataset.lesson).done));
    $$("[data-complete]").forEach((b) => {
      const on = !!get(b.dataset.complete).done;
      b.setAttribute("aria-pressed", on);
      b.querySelector(".lbl").textContent = on ? "Completed" : "Complete lesson";
    });
    $("#lp-n").textContent = done.length;
    $("#lp-ring").style.strokeDashoffset = 94.25 * (1 - done.length / ids.length);
    const next = ids.find((id) => !get(id).done);
    const btn = $("#lp-next");
    btn.textContent = !done.length ? "Start lesson 1 →" : next ? `Continue: lesson ${+next.slice(1)} →` : "Course complete 🎓";
    btn.disabled = !next;
    $("#lp-msg").textContent = !done.length ? $("#lp-msg").textContent : next ? `${ids.length - done.length} to go. One a day keeps the streak alive 🔥` : "You finished the course. The daily digest will make a lot more sense now!";
    // quizzes
    sheets.forEach((d) => {
      const answers = get(d.id).quiz || {};
      $$(".q", d).forEach((q) => { if (q.dataset.q in answers) show(q, answers[q.dataset.q]); });
    });
  }
  function show(q, pick) {
    const right = +q.dataset.answer;
    $$(".q-opt", q).forEach((o) => {
      const i = +o.dataset.opt;
      o.disabled = true;
      o.classList.toggle("right", i === right);
      o.classList.toggle("wrong", i === pick && pick !== right);
    });
    q.classList.add("done", pick === right ? "ok" : "no");
    const exp = $(".q-exp", q); exp.hidden = false; exp.dataset.verdict = pick === right ? "Correct!" : "Not quite.";
  }
  function save(id, patch) { MD.store.set("lesson:" + id, { ...get(id), ...patch }); }

  function open(id) {
    const d = document.getElementById(id);
    if (!d) return;
    $$("dialog[open]").forEach((x) => x !== d && x.close());
    if (!d.open) d.showModal();
    d.scrollTop = 0;
    history.replaceState(null, "", "#" + id);
    MD.track("lesson_open", { id });
  }
  const nextAfter = (id) => ids.slice(ids.indexOf(id) + 1).find((x) => !get(x).done) || ids.find((x) => !get(x).done);

  document.addEventListener("click", (e) => {
    const card = e.target.closest("[data-lesson]");
    if (card) return open(card.dataset.lesson);
    const opt = e.target.closest(".lquiz .q-opt");
    if (opt && !opt.disabled) {
      const q = opt.closest(".q"), id = opt.closest("dialog").id;
      save(id, { quiz: { ...(get(id).quiz || {}), [q.dataset.q]: +opt.dataset.opt } });
      show(q, +opt.dataset.opt);
      if (+opt.dataset.opt === +q.dataset.answer) q.classList.add("burst");
      return;
    }
    const c = e.target.closest("[data-complete]");
    if (c) {
      const id = c.dataset.complete, on = !get(id).done;
      save(id, { done: on ? MD.todayLocal() : false });
      if (on) {
        const days = new Set(MD.store.get("days", [])); days.add(MD.todayLocal()); MD.store.set("days", [...days].sort());
        MD.refresh(); MD.track("lesson_done", { id });
        const left = ids.filter((x) => !get(x).done).length;
        MD.toast(left ? `🎓 Lesson done! ${left} to go` : "🎓 Course complete! Amazing work.");
      }
      return render();
    }
    if (e.target.closest("[data-next-lesson]")) {
      const id = e.target.closest("dialog").id, n = nextAfter(id);
      n && n !== id ? open(n) : (e.target.closest("dialog").close(), MD.toast("🎓 That's the whole course!"));
    }
  });
  sheets.forEach((d) => {
    d.addEventListener("click", (e) => { if (e.target === d || e.target.closest("[data-sheet-close]")) d.close(); });
    d.addEventListener("close", () => { if (location.hash === "#" + d.id) history.replaceState(null, "", location.pathname); });
  });
  $("#lp-next").addEventListener("click", () => { const n = ids.find((id) => !get(id).done); n && open(n); });
  if (location.hash.length > 1 && ids.includes(location.hash.slice(1))) open(location.hash.slice(1));
  // ---------- practice rounds: 10 questions at a chosen level ----------
  const bank = $("#practice-data") ? JSON.parse($("#practice-data").textContent) : [];
  const run = $("#practice-run");
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let round = null;
  function renderBest() {
    $$("[data-best]").forEach((el) => {
      const p = MD.store.get("practice:" + el.dataset.best, {});
      el.textContent = p.rounds ? `Best ${p.best}/10` : "";
    });
  }
  function startRound(level) {
    const pool = bank.filter((q) => q.level === level);
    const qs = pool.map((q) => [Math.random(), q]).sort((a, b) => a[0] - b[0]).slice(0, 10).map((x) => x[1]);
    round = { level, qs, i: 0, right: 0 };
    $("#pr-title").textContent = level[0].toUpperCase() + level.slice(1) + " practice";
    $$("dialog[open]").forEach((d) => d.close());
    run.showModal();
    showQ();
    MD.track("practice_start", { level });
  }
  function showQ() {
    const q = round.qs[round.i];
    $("#pr-meta").textContent = `Question ${round.i + 1} of ${round.qs.length} · ${q.topic}`;
    $("#pr-bar").style.width = (100 * round.i) / round.qs.length + "%";
    $("#pr-next").disabled = true;
    $("#pr-next").textContent = round.i + 1 < round.qs.length ? "Next question →" : "See my score →";
    const lesson = document.getElementById(q.lesson);
    $("#pr-q").innerHTML = `<div class="q" data-answer="${q.answer}">
        <p class="q-text"><span class="q-n">${round.i + 1}</span><span>${esc(q.question)} <span class="diff d-${q.level}">${q.level}</span></span></p>
        <div class="q-opts">${q.options.map((o, i) => `<button type="button" class="q-opt" data-opt="${i}"><span class="q-key">${"ABCD"[i]}</span>${esc(o)}</button>`).join("")}</div>
        <p class="q-exp" hidden>${esc(q.explanation)}</p>
        <p class="pr-more" hidden>${lesson ? `📘 <a href="#${q.lesson}" data-to-lesson="${q.lesson}">Lesson: ${esc(lesson.querySelector(".ep-title").textContent)}</a>` : ""}
          ${q.learn_more ? ` · 🔗 <a href="${esc(q.learn_more.url)}" target="_blank" rel="noopener">${esc(q.learn_more.title)}</a>` : ""}
          <span class="muted small"> · ${esc(q.basis || "")}</span></p></div>`;
    run.scrollTop = 0;
  }
  if (run) {
    $$("[data-level]").forEach((b) => b.addEventListener("click", () => startRound(b.dataset.level)));
    run.addEventListener("click", (e) => {
      if (e.target === run || e.target.closest("[data-sheet-close]")) return run.close();
      const toLesson = e.target.closest("[data-to-lesson]");
      if (toLesson) { e.preventDefault(); run.close(); return open(toLesson.dataset.toLesson); }
      const opt = e.target.closest(".q-opt");
      if (opt && !opt.disabled) {
        const q = opt.closest(".q"), pick = +opt.dataset.opt;
        show(q, pick);
        if (pick === +q.dataset.answer) { round.right++; q.classList.add("burst"); }
        $(".pr-more", q).hidden = false;
        $("#pr-next").disabled = false;
      }
    });
    $("#pr-next").addEventListener("click", () => {
      if (round.finished) return run.close();  // "Done" on the score screen
      if (round.i + 1 < round.qs.length) { round.i++; return showQ(); }
      round.finished = true;
      const key = "practice:" + round.level, prev = MD.store.get(key, {});
      MD.store.set(key, { best: Math.max(prev.best || 0, round.right), rounds: (prev.rounds || 0) + 1 });
      const days = new Set(MD.store.get("days", [])); days.add(MD.todayLocal()); MD.store.set("days", [...days].sort());
      MD.refresh(); MD.track("practice_done", { level: round.level, right: round.right });
      $("#pr-bar").style.width = "100%";
      const msg = round.right >= 9 ? "🏆 Outstanding!" : round.right >= 7 ? "🎉 Strong work!" : round.right >= 5 ? "👍 Solid. Review the lessons for the ones you missed and try again." : "📘 Good start. The lessons above this practice section will help.";
      $("#pr-q").innerHTML = `<div class="pr-done"><div class="pr-score">${round.right}/${round.qs.length}</div><p>${msg}</p></div>`;
      $("#pr-next").textContent = "Done";
    });
  }

  const refresh = MD.refresh;
  MD.refresh = () => { refresh(); render(); renderBest(); }; // progress synced in from another device
  render();
  renderBest();
})();
