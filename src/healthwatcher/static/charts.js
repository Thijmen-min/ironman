/* Minimal SVG chart kit: time panels with shared crosshair, stacked columns, hbars, sparklines. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tip = () => document.getElementById("tooltip");

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function niceTicks(min, max, count) {
    if (min === max) { max = min + 1; }
    const span = max - min;
    const step0 = span / Math.max(count, 1);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const err = step0 / mag;
    const step = mag * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
    return out;
  }

  const fmtNum = (v) => (v == null || isNaN(v) ? "–" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : (Math.round(v * 10) / 10).toString());

  /* ---------------------------------------------------------------- tooltip */
  function showTip(evt, header, rows) {
    const t = tip();
    t.replaceChildren();
    const h = document.createElement("div");
    h.className = "tt-h";
    h.textContent = header;
    t.appendChild(h);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "tt-r";
      const i = document.createElement("i");
      i.style.background = r.color || "transparent";
      if (r.shape === "rect") { i.style.height = "10px"; i.style.width = "10px"; i.style.borderRadius = "2px"; }
      if (r.shape === "dot") { i.style.height = "8px"; i.style.width = "8px"; i.style.borderRadius = "50%"; }
      const b = document.createElement("b");
      b.textContent = r.value;
      const s = document.createElement("span");
      s.textContent = r.name;
      row.append(i, b, s);
      t.appendChild(row);
    });
    t.hidden = false;
    const pad = 14;
    const w = t.offsetWidth, hgt = t.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
    if (y + hgt > window.innerHeight - 8) y = evt.clientY - hgt - pad;
    t.style.left = x + "px";
    t.style.top = y + "px";
  }
  function hideTip() { tip().hidden = true; }

  /* Rounded-end bar path: 4px radius on the data end, square at the baseline. */
  function barPath(x, w, y0, y1, r) {
    const up = y1 < y0;
    const h = Math.abs(y1 - y0);
    r = Math.min(r, w / 2, h);
    if (h < 0.5) return "";
    if (up) {
      return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
    }
    return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
  }

  /* ---------------------------------------------------------------- time chart
   opts: { n, label(i), ticks:[{i,text}], todayIndex, panels:[{height, title, yMin, yMax, zero, bands:[{from,to,label}],
           format(v), series:[{name, type:'line'|'area'|'dots'|'bars', color, values, endLabel, projectedFrom, dash}]}] } */
  function time(container, opts) {
    container.classList.add("chart");
    const draw = () => {
      container.replaceChildren();
      const W = Math.max(container.clientWidth, 280);
      const m = { l: 40, r: 48, t: 8, b: 22 };
      const gap = opts.panels.some((p) => p.title) ? 26 : 18;
      const H = opts.panels.reduce((s, p) => s + p.height, 0) + gap * (opts.panels.length - 1) + m.t + m.b;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", tabindex: 0, "aria-label": opts.aria || "chart" }, container);
      const n = opts.n;
      const step = (W - m.l - m.r) / Math.max(n, 1);
      const X = (i) => m.l + (i + 0.5) * step;
      let top = m.t;
      const layouts = [];
      opts.panels.forEach((p, pi) => {
        const vals = [];
        p.series.forEach((s) => s.values.forEach((v) => v != null && !isNaN(v) && vals.push(v)));
        (p.bands || []).forEach((b) => { if (b.include) { vals.push(b.from, b.to); } });
        let lo = p.yMin != null ? p.yMin : Math.min(...vals, p.zero ? 0 : Infinity);
        let hi = p.yMax != null ? p.yMax : Math.max(...vals, p.zero ? 0 : -Infinity);
        if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
        if (p.yMin == null && !p.zero) { const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad; }
        const ticks = niceTicks(lo, hi, p.height > 140 ? 5 : 3);
        lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
        const Y = (v) => top + p.height - ((v - lo) / (hi - lo || 1)) * p.height;
        layouts.push({ p, Y, top, lo, hi });
        const g = el("g", { class: "grid" }, svg);
        const ax = el("g", { class: "axis" }, svg);
        ticks.forEach((t) => {
          el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, g);
          const tx = el("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, ax);
          tx.textContent = p.format ? p.format(t, true) : fmtNum(t);
        });
        // shaded bands (e.g. HRV baseline, form zones)
        (p.bands || []).forEach((b) => {
          const y1 = Y(Math.min(Math.max(b.to, lo), hi)), y2 = Y(Math.max(Math.min(b.from, hi), lo));
          if (y2 - y1 > 0.5) {
            el("rect", { x: m.l, width: W - m.l - m.r, y: y1, height: y2 - y1, fill: b.fill || "var(--band)" }, svg);
            if (b.label && y2 - y1 > 12) {
              const t = el("text", { class: "zone-lbl", x: m.l + 4, y: y1 + 11 }, svg);
              t.textContent = b.label;
            }
          }
        });
        if (p.title) {
          const t = el("text", { class: "panel-lbl", x: m.l + 2, y: top - 2 }, svg);
          t.textContent = p.title;
        }
        if (lo < 0 && hi > 0) el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0) }, svg);
        else el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: top + p.height, y2: top + p.height }, svg);

        const endLabels = [];
        p.series.forEach((s) => {
          const base = Y(Math.max(lo, Math.min(0, hi)));
          if (s.type === "bars") {
            const bw = Math.max(1, Math.min(24, step * 0.7));
            s.values.forEach((v, i) => {
              if (v == null) return;
              const path = barPath(X(i) - bw / 2, bw, base, Y(v), bw > 6 ? 4 : 1);
              if (path) el("path", { d: path, fill: s.colorFn ? s.colorFn(v, i) : s.color, opacity: s.projectedFrom != null && i >= s.projectedFrom ? 0.45 : 1 }, svg);
            });
          } else if (s.type === "dots") {
            const r = step >= 8 ? 4 : 2.5;
            s.values.forEach((v, i) => {
              if (v == null || v === 0) return;
              el("circle", { cx: X(i), cy: Y(v), r, fill: s.color, stroke: "var(--surface)", "stroke-width": step >= 8 ? 2 : 1,
                opacity: s.projectedFrom != null && i >= s.projectedFrom ? 0.45 : 1 }, svg);
            });
          } else {
            const split = s.projectedFrom != null ? s.projectedFrom : n;
            const segs = [[0, Math.min(split, n - 1), false], [Math.max(split - 1, 0), n - 1, true]];
            segs.forEach(([a, b, proj]) => {
              if (proj && split >= n) return;
              let d = "", pen = false, areaPts = [];
              for (let i = a; i <= b; i++) {
                const v = s.values[i];
                if (v == null || isNaN(v)) { pen = false; continue; }
                d += (pen ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1);
                areaPts.push([X(i), Y(v)]);
                pen = true;
              }
              if (!d) return;
              if (s.type === "area" && !proj && areaPts.length > 1) {
                const ad = `M${areaPts[0][0]},${base}` + areaPts.map((q) => `L${q[0]},${q[1]}`).join("") + `L${areaPts[areaPts.length - 1][0]},${base}Z`;
                el("path", { d: ad, fill: s.color, opacity: 0.1 }, svg);
              }
              el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
                "stroke-dasharray": proj || s.dash ? "4 4" : null }, svg);
            });
          }
          if (s.endLabel) {
            const last = (s.projectedFrom != null ? s.projectedFrom : n) - 1;
            for (let i = Math.min(last, n - 1); i >= 0; i--) {
              if (s.values[i] != null) { endLabels.push({ i, v: s.values[i], s }); break; }
            }
          }
        });
        // end labels: dot + value; drop a label rather than stacking colliding ones
        const placed = [];
        endLabels.forEach(({ i, v, s }) => {
          const y = Y(v);
          el("circle", { cx: X(i), cy: y, r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
          if (placed.some((py) => Math.abs(py - y) < 13)) return;
          placed.push(y);
          const t = el("text", { class: "end-lbl", x: X(i) + 8, y: y + 4 }, svg);
          t.textContent = p.format ? p.format(v) : fmtNum(v);
        });
        top += p.height + gap;
      });

      // x-axis ticks
      const ax = el("g", { class: "axis" }, svg);
      (opts.ticks || []).forEach((t) => {
        const tx = el("text", { x: X(t.i), y: H - 6, "text-anchor": "middle" }, ax);
        tx.textContent = t.text;
      });
      if (opts.todayIndex != null && opts.todayIndex < n - 1) {
        el("line", { class: "today-line", x1: X(opts.todayIndex), x2: X(opts.todayIndex), y1: m.t, y2: H - m.b }, svg);
      }

      // crosshair + tooltip (all series of all panels)
      const xh = el("line", { class: "xhair", y1: m.t, y2: H - m.b, x1: 0, x2: 0, visibility: "hidden" }, svg);
      const hit = el("rect", { class: "hit", x: m.l, y: 0, width: W - m.l - m.r, height: H }, svg);
      let cur = null;
      const show = (i, evt) => {
        cur = i;
        xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("visibility", "visible");
        const rows = [];
        layouts.forEach(({ p }) => p.series.forEach((s) => {
          const v = s.values[i];
          if (v == null || (s.type === "dots" && !v && !s.showZero)) return;
          rows.push({ color: s.color, value: p.format ? p.format(v) : fmtNum(v), name: s.name + (s.projectedFrom != null && i >= s.projectedFrom ? " (planned)" : ""), shape: s.type === "bars" ? "rect" : s.type === "dots" ? "dot" : "line" });
        }));
        if (opts.extraRows) rows.push(...opts.extraRows(i));
        showTip(evt, opts.label(i), rows);
      };
      hit.addEventListener("pointermove", (e) => {
        const r = svg.getBoundingClientRect();
        const sx = ((e.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(n - 1, Math.floor((sx - m.l) / step)));
        show(i, e);
      });
      hit.addEventListener("pointerleave", () => { hideTip(); xh.setAttribute("visibility", "hidden"); });
      if (opts.onClick) hit.addEventListener("click", () => cur != null && opts.onClick(cur));
      svg.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const i = Math.max(0, Math.min(n - 1, (cur == null ? n - 1 : cur) + (e.key === "ArrowRight" ? 1 : -1)));
        const r = svg.getBoundingClientRect();
        show(i, { clientX: r.left + (X(i) / W) * r.width, clientY: r.top + 20 });
      });
      svg.addEventListener("blur", hideTip);
    };
    draw();
    observe(container, draw);
  }

  /* ---------------------------------------------------------------- stacked columns
   opts: { cats:[label], tipLabel(i), series:[{name,color,values}], height, format(v), totalFormat(v), onClick(i) } */
  function columns(container, opts) {
    container.classList.add("chart");
    const draw = () => {
      container.replaceChildren();
      const W = Math.max(container.clientWidth, 280);
      const m = { l: 40, r: 12, t: 16, b: 22 };
      const H = opts.height + m.t + m.b;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": opts.aria || "chart" }, container);
      const n = opts.cats.length;
      const totals = opts.cats.map((_, i) => opts.series.reduce((s, se) => s + (se.values[i] || 0), 0));
      const ticks = niceTicks(0, Math.max(...totals, 1), 4);
      const hi = ticks[ticks.length - 1];
      const Y = (v) => m.t + opts.height - (v / hi) * opts.height;
      const step = (W - m.l - m.r) / Math.max(n, 1);
      const bw = Math.min(24, step * 0.62);
      const g = el("g", { class: "grid" }, svg), ax = el("g", { class: "axis" }, svg);
      ticks.forEach((t) => {
        el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }, g);
        el("text", { x: m.l - 6, y: Y(t) + 4, "text-anchor": "end" }, ax).textContent = fmtNum(t);
      });
      el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0) }, svg);
      const every = Math.ceil(n / Math.max(1, Math.floor((W - m.l - m.r) / 54)));
      opts.cats.forEach((c, i) => {
        const cx = m.l + (i + 0.5) * step;
        let acc = 0;
        const segs = opts.series.map((s) => ({ s, v: s.values[i] || 0 })).filter((x) => x.v > 0);
        const grp = el("g", { class: "bar" }, svg);
        segs.forEach(({ s, v }, k) => {
          const y0 = Y(acc), y1 = Y(acc + v);
          const isTop = k === segs.length - 1;
          // 2px surface gap between stacked segments
          const gapTop = isTop ? 0 : 1, gapBottom = k === 0 ? 0 : 1;
          const path = isTop ? barPath(cx - bw / 2, bw, y0 - gapBottom, y1, 4)
            : `M${cx - bw / 2},${y0 - gapBottom}V${y1 + gapTop}H${cx + bw / 2}V${y0 - gapBottom}Z`;
          if (path && y0 - y1 > 2) el("path", { d: path, fill: s.color }, grp);
          acc += v;
        });
        if (totals[i] > 0 && step >= 30) {
          el("text", { class: "lbl", x: cx, y: Y(totals[i]) - 4, "text-anchor": "middle" }, svg).textContent = (opts.totalFormat || fmtNum)(totals[i]);
        }
        if (i % every === 0) el("text", { x: cx, y: H - 6, "text-anchor": "middle" }, ax).textContent = c;
        const hit = el("rect", { class: "hit", x: cx - step / 2, y: m.t, width: step, height: opts.height }, svg);
        hit.addEventListener("pointermove", (e) => {
          grp.classList.add("hl");
          const rows = opts.series.filter((s) => s.values[i]).map((s) => ({ color: s.color, value: (opts.format || fmtNum)(s.values[i]), name: s.name, shape: "rect" }));
          rows.push({ color: null, value: (opts.format || fmtNum)(totals[i]), name: "Total" });
          showTip(e, opts.tipLabel ? opts.tipLabel(i) : c, rows);
        });
        hit.addEventListener("pointerleave", () => { grp.classList.remove("hl"); hideTip(); });
        if (opts.onClick) { hit.style.cursor = "pointer"; hit.addEventListener("click", () => opts.onClick(i)); }
      });
    };
    draw();
    observe(container, draw);
  }

  /* ---------------------------------------------------------------- horizontal bars (HTML) */
  function hbars(container, rows) {
    container.replaceChildren();
    container.className = "hbars";
    const max = Math.max(...rows.map((r) => r.value), 1);
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "hbar";
      const name = document.createElement("div");
      name.className = "name";
      const sw = document.createElement("i");
      sw.style.background = r.color;
      const nm = document.createElement("span");
      nm.textContent = r.name;
      name.append(sw, nm);
      const track = document.createElement("div");
      track.className = "track";
      const fill = document.createElement("div");
      fill.className = "fill";
      fill.style.width = (r.value / max) * 100 + "%";
      fill.style.background = r.color;
      track.appendChild(fill);
      const val = document.createElement("div");
      val.className = "val";
      val.textContent = r.label;
      row.append(name, track, val);
      row.title = `${r.name}: ${r.label}`;
      container.appendChild(row);
    });
  }

  /* ---------------------------------------------------------------- sparkline */
  function spark(container, values, color) {
    container.replaceChildren();
    const v = values.filter((x) => x != null);
    if (v.length < 2) return;
    const W = 120, H = 28;
    const lo = Math.min(...v), hi = Math.max(...v);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, preserveAspectRatio: "none", "aria-hidden": "true" }, container);
    let d = "", pen = false;
    values.forEach((x, i) => {
      if (x == null) { pen = false; return; }
      const px = (i / (values.length - 1)) * (W - 4) + 2;
      const py = H - 3 - ((x - lo) / (hi - lo || 1)) * (H - 6);
      d += (pen ? "L" : "M") + px.toFixed(1) + "," + py.toFixed(1);
      pen = true;
    });
    el("path", { d, fill: "none", stroke: "var(--muted)", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke" }, svg);
    const li = values.length - 1;
    if (values[li] != null) {
      const py = H - 3 - ((values[li] - lo) / (hi - lo || 1)) * (H - 6);
      el("circle", { cx: W - 2, cy: py, r: 2.5, fill: color || "var(--accent)" }, svg);
    }
  }

  const observers = new WeakMap();
  function observe(container, draw) {
    if (observers.has(container)) observers.get(container).disconnect();
    let w = container.clientWidth;
    const ro = new ResizeObserver(() => {
      if (Math.abs(container.clientWidth - w) > 4) { w = container.clientWidth; draw(); }
    });
    ro.observe(container);
    observers.set(container, ro);
  }

  window.HW = window.HW || {};
  window.HW.charts = { time, columns, hbars, spark, showTip, hideTip, fmtNum };
})();
