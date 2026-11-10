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
  const refresh = MD.refresh;
  MD.refresh = () => { refresh(); render(); }; // progress synced in from another device
  render();
})();
