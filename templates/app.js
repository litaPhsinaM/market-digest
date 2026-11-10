// Charts (sparklines + company price chart), info tooltips and the company dialog. No dependencies.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = document.getElementById("tip");
  const fmtNum = (v) => v.toLocaleString(undefined, { maximumFractionDigits: v >= 1000 ? 0 : 2, minimumFractionDigits: v >= 1000 ? 0 : 2 });
  const fmtDate = (d) => new Date(d + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function showTip(html, x, y) {
    // an open modal dialog sits in the browser's top layer, so the tip must live inside it to be seen
    const host = [...document.querySelectorAll("dialog[open]")].pop() || document.body;
    if (tip.parentElement !== host) host.appendChild(tip);
    tip.innerHTML = html;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(8, x - r.width / 2), innerWidth - r.width - 8) + "px";
    tip.style.top = (y - r.height - 12 < 8 ? y + 18 : y - r.height - 12) + "px";
  }
  const hideTip = () => (tip.hidden = true);

  // ---- line chart (sparkline when axes = false) ----
  function draw(svg, series, opts) {
    const { w, h, axes, fmt } = opts;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    if (series.length < 2) return;
    const vals = series.map((p) => p[1]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const L = axes ? 44 : 1, R = axes ? 8 : 1, T = axes ? 10 : 2, B = axes ? 24 : 2;
    const X = (i) => L + (i / (series.length - 1)) * (w - L - R);
    const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
    const up = vals[vals.length - 1] >= vals[0];
    (svg.closest(".chart") || svg).classList.remove("up", "down");
    (svg.closest(".chart") || svg).classList.add(up ? "up" : "down");

    if (axes) {
      // round-number gridlines (e.g. 180 / 200 / 220) instead of arbitrary values
      const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw)));
      const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
      for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
        el("line", { class: "grid", x1: L, x2: w - R, y1: Y(v), y2: Y(v) }, svg);
        const t = el("text", { class: "axis", x: L - 8, y: Y(v) + 4, "text-anchor": "end" }, svg);
        t.textContent = fmtNum(v);
      }
      [0, Math.floor((series.length - 1) / 2), series.length - 1].forEach((i, n) => {
        const t = el("text", { class: "axis", x: X(i), y: h - 6, "text-anchor": ["start", "middle", "end"][n] }, svg);
        t.textContent = new Date(series[i][0] + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
      });
    }
    const d = series.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    el("path", { class: "area", d: `${d}L${X(series.length - 1)},${h - B}L${L},${h - B}Z` }, svg);
    el("path", { class: "line", d }, svg);

    // hover: crosshair + dot + tooltip
    const xh = el("line", { class: "xhair", y1: T, y2: h - B, visibility: "hidden" }, svg);
    const dot = el("circle", { class: "dot", r: axes ? 5 : 3.5, visibility: "hidden" }, svg);
    if (!axes) { xh.setAttribute("visibility", "hidden"); dot.setAttribute("stroke", "none"); }
    const hit = el("rect", { x: 0, y: 0, width: w, height: h, fill: "transparent" }, svg);
    const show = (e) => {
      const box = svg.getBoundingClientRect();
      const px = ((e.clientX - box.left) / box.width) * w;
      const i = Math.round(((px - L) / (w - L - R)) * (series.length - 1));
      const p = series[Math.max(0, Math.min(series.length - 1, i))];
      const ix = series.indexOf(p);
      if (axes) { xh.setAttribute("x1", X(ix)); xh.setAttribute("x2", X(ix)); xh.setAttribute("visibility", "visible"); }
      dot.setAttribute("cx", X(ix)); dot.setAttribute("cy", Y(p[1])); dot.setAttribute("visibility", "visible");
      const v = fmt === "pct" ? p[1].toFixed(2) + "%" : fmtNum(p[1]);
      showTip(`<b>${v}</b> · ${fmtDate(p[0])}`, box.left + (X(ix) / w) * box.width, box.top + (Y(p[1]) / h) * box.height);
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "touch") return; // a finger "leaves" right after lifting; keep the reading until the next tap elsewhere
      xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
  }

  // sparklines
  document.querySelectorAll("svg.spark").forEach((svg) => {
    const r = svg.getBoundingClientRect();
    draw(svg, JSON.parse(svg.dataset.series), { w: r.width || 84, h: r.height || 30, axes: false, fmt: svg.dataset.fmt });
  });

  // ---- company dialog ----
  const RANGES = { "1M": 22, "6M": 126, "1Y": Infinity };
  function renderChart(dlg) {
    const box = dlg.querySelector(".chart");
    const all = JSON.parse(box.dataset.series);
    const sel = dlg.querySelector(".range [aria-selected=true]").dataset.range;
    const series = all.slice(-Math.min(all.length, RANGES[sel]));
    let svg = box.querySelector("svg") || el("svg", { role: "img" }, box);
    draw(svg, series, { w: box.clientWidth || 700, h: box.clientHeight || 240, axes: true });
    const a = series[0][1], b = series[series.length - 1][1], pct = (b / a - 1) * 100;
    const out = dlg.querySelector(".range-chg");
    out.className = "range-chg " + (pct >= 0 ? "up" : "down");
    out.textContent = `${pct >= 0 ? "▲ +" : "▼ −"}${Math.abs(pct).toFixed(2)}% past ${sel === "1Y" ? "year" : sel === "6M" ? "6 months" : "month"}`;
    svg.setAttribute("aria-label", `Price over the past ${sel}: ${out.textContent}`);
  }

  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open]");
    if (opener) {
      const dlg = document.getElementById("co-" + opener.dataset.open);
      if (dlg) { dlg.showModal(); renderChart(dlg); }
      return;
    }
    const tab = e.target.closest(".range button");
    if (tab) {
      tab.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b === tab));
      renderChart(tab.closest("dialog"));
      return;
    }
    const dlg = e.target.closest("dialog");
    if (e.target.closest("[data-close]") || (e.target.tagName === "DIALOG")) { (dlg || e.target).close(); hideTip(); }
  });
  addEventListener("resize", () => document.querySelectorAll("dialog[open]").forEach(renderChart));
  // Deep link: page.html#co-NVDA opens that company.
  function openLinked() {
    const linked = location.hash.startsWith("#co-") && document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (linked && linked.tagName === "DIALOG" && !linked.open) { linked.showModal(); renderChart(linked); }
  }
  openLinked();
  addEventListener("hashchange", openLinked); // e.g. picking a company in search while already on this page
  // closing a deep-linked company clears the hash, so the same link can open it again
  document.querySelectorAll(".co-dialog").forEach((d) => d.addEventListener("close", () => {
    hideTip();
    if (location.hash === "#" + d.id) history.replaceState(null, "", location.pathname + location.search);
  }));

  // ---- info tooltips ----
  document.querySelectorAll("[data-tip]").forEach((b) => {
    const on = () => { const r = b.getBoundingClientRect(); showTip(b.dataset.tip.replace(/</g, "&lt;"), r.left + r.width / 2, r.top); };
    b.addEventListener("mouseenter", on);
    b.addEventListener("focus", on);
    b.addEventListener("click", (e) => { e.stopPropagation(); on(); });
    b.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") hideTip(); }); // touch: hidden by the next tap elsewhere
    b.addEventListener("blur", hideTip);
  });
  // touch: tapping anywhere else dismisses a tip
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch" && !e.target.closest("[data-tip], .chart, .spark")) hideTip();
  }, true);
})();

// movers tabs
document.querySelectorAll(".mv-tabs button").forEach((b) => b.addEventListener("click", () => {
  const box = b.closest(".movers");
  box.querySelectorAll(".mv-tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  box.querySelectorAll("[data-mv-list]").forEach((l) => (l.hidden = l.dataset.mvList !== b.dataset.mv));
}));
