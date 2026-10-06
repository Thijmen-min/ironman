/* HealthWatcher UI - TrainingPeaks-style views over the local API. */
(function () {
  const C = HW.charts;
  const $ = (s, r = document) => r.querySelector(s);
  const SPORTS = ["Run", "Bike", "Swim", "Strength", "Walk/Hike", "Other"];
  const SPORT_COLOR = { Run: "var(--s1)", Bike: "var(--s2)", Swim: "var(--s3)", Strength: "var(--s4)", "Walk/Hike": "var(--s5)", Other: "var(--s6)" };
  const SPORT_ICON = {
    Run: '<path d="M13 4a2 2 0 1 0 0 .1M7 21l3-6 3 2v5M6 12l3-4 4 1 3 4h3M10 15l-1-4" />',
    Bike: '<circle cx="6" cy="16" r="4"/><circle cx="18" cy="16" r="4"/><path d="M6 16l4-8h5l3 8M10 8l2 8h-2" />',
    Swim: '<path d="M2 18c2 0 2-1.5 4-1.5S8 18 10 18s2-1.5 4-1.5 2 1.5 4 1.5 2-1.5 4-1.5M7 13l4-5 4 3M17 7a2 2 0 1 0 0 .1"/>',
    Strength: '<path d="M4 9v6M7 7v10M17 7v10M20 9v6M7 12h10"/>',
    "Walk/Hike": '<path d="M13 4a2 2 0 1 0 0 .1M9 21l2-7 3 3v4M8 11l3-3 3 2 2 4M11 14l-1-4"/>',
    Other: '<circle cx="12" cy="12" r="7"/><path d="M12 8v4l3 2"/>',
  };
  const STATUS_ICON = { good: "✓", warning: "!", serious: "!", critical: "×" };

  /* ---------------------------------------------------------------- utils */
  const api = async (path, opts) => {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).detail || msg; } catch (e) { /* not json */ }
      throw new Error(msg);
    }
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.text();
  };
  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const monday = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const todayIso = () => iso(new Date());
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const fmtDay = (s) => { const d = parse(s); return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}`; };
  const dur = (s) => { if (!s) return "–"; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}:${String(m).padStart(2, "0")}` : `${m}m`; };
  const hrs = (s) => (s ? (s / 3600).toFixed(1) : "–");
  const km = (m) => (m ? (m / 1000).toFixed(m >= 100000 ? 0 : 1) : "–");
  const r0 = (v) => (v == null ? "–" : Math.round(v));
  const r1 = (v) => (v == null ? "–" : (Math.round(v * 10) / 10).toFixed(1));
  const pace = (ms, group) => {
    if (!ms) return "–";
    if (group === "Run" || group === "Walk/Hike") { const spk = 1000 / ms; return `${Math.floor(spk / 60)}:${String(Math.round(spk % 60)).padStart(2, "0")} /km`; }
    if (group === "Swim") { const sp = 100 / ms; return `${Math.floor(sp / 60)}:${String(Math.round(sp % 60)).padStart(2, "0")} /100m`; }
    return `${(ms * 3.6).toFixed(1)} km/h`;
  };
  const h = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "class") n.className = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
      else if (k === "style" && typeof attrs[k] === "object") {
        for (const [p, v] of Object.entries(attrs[k])) {
          if (p.startsWith("--")) n.style.setProperty(p, v); else n.style[p] = v;
        }
      }
      else if (attrs[k] != null && attrs[k] !== false) n.setAttribute(k, attrs[k]);
    }
    kids.flat().forEach((c) => c != null && n.append(c.nodeType ? c : document.createTextNode(String(c))));
    return n;
  };
  const sportIcon = (g) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "sport-ico");
    s.setAttribute("fill", "none");
    s.setAttribute("stroke", "currentColor");
    s.setAttribute("stroke-width", "2");
    s.setAttribute("stroke-linecap", "round");
    s.setAttribute("stroke-linejoin", "round");
    s.innerHTML = SPORT_ICON[g] || SPORT_ICON.Other;
    return s;
  };
  const status = (level, text) => h("span", { class: `status ${level}` }, h("span", { class: "ico", "aria-hidden": "true" }, STATUS_ICON[level] || "•"), text);
  const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600); };

  function card(title, sub, body, opts = {}) {
    const tools = h("div", { class: "card-tools" });
    const head = h("div", { class: "card-head" }, h("h3", null, title), sub ? h("span", { class: "sub" }, sub) : null, h("span", { class: "spacer" }), tools);
    const b = h("div", { class: "card-body" });
    if (body) b.append(body);
    const c = h("div", { class: "card " + (opts.cls || "") }, head, b);
    if (opts.table) {
      // chart <-> table toggle (every chart has a table twin)
      const chartBtn = h("button", { class: "on" }, "Chart"), tblBtn = h("button", null, "Table");
      let tblNode = null;
      chartBtn.onclick = () => { chartBtn.classList.add("on"); tblBtn.classList.remove("on"); body.hidden = false; if (tblNode) tblNode.hidden = true; };
      tblBtn.onclick = () => {
        tblBtn.classList.add("on"); chartBtn.classList.remove("on"); body.hidden = true;
        if (!tblNode) { tblNode = table(...opts.table()); tblNode.classList.add("tbl-scroll"); b.append(tblNode); }
        tblNode.hidden = false;
      };
      tools.append(chartBtn, tblBtn);
    }
    return c;
  }

  function table(cols, rows) {
    const t = h("table", { class: "tbl" },
      h("thead", null, h("tr", null, cols.map((c, i) => h("th", { class: i === 0 ? "l" : null }, c)))),
      h("tbody", null, rows.map((r) => h("tr", null, r.map((v, i) => h("td", { class: i === 0 ? "l" : null }, v == null ? "–" : v))))));
    return h("div", { class: "tbl-wrap" }, t);
  }

  function legend(items) {
    return h("div", { class: "legend" }, items.map((it) =>
      h("span", null, h("i", { class: it.shape || "", style: { background: it.color, color: it.color } }), it.name)));
  }

  function dayTicks(days) {
    const n = days.length, out = [];
    if (n <= 50) {
      days.forEach((d, i) => { const x = parse(d); if (x.getDay() === 1) out.push({ i, text: `${x.getDate()} ${MON[x.getMonth()]}` }); });
    } else {
      days.forEach((d, i) => { const x = parse(d); if (x.getDate() === 1) out.push({ i, text: MON[x.getMonth()] + (x.getMonth() === 0 ? ` ${x.getFullYear()}` : "") }); });
    }
    return out;
  }

  /* ---------------------------------------------------------------- status / sync */
  let STATUS = null;
  async function refreshStatus() {
    try { STATUS = await api("/api/status"); } catch (e) { return; }
    const pill = $("#syncPill"), txt = $("#syncText"), btn = $("#syncBtn");
    const s = STATUS.sync;
    pill.className = "sync-pill " + (s.busy ? "busy" : s.error ? "err" : STATUS.garmin.last_sync ? "ok" : "");
    btn.classList.toggle("spin", !!s.busy);
    if (s.busy) txt.textContent = s.total ? `Syncing ${s.phase} ${s.done}/${s.total}` : "Syncing…";
    else if (s.error === "auth" || !STATUS.garmin.has_tokens) txt.textContent = "Garmin not connected";
    else if (s.error) txt.textContent = "Sync error";
    else txt.textContent = STATUS.garmin.last_sync ? "Synced " + ago(STATUS.garmin.last_sync) : "Never synced";
    const banner = $("#banner");
    if (!STATUS.garmin.has_tokens) {
      banner.replaceChildren(status("warning", "Garmin Connect isn't connected yet."), h("a", { class: "btn primary", href: "#settings" }, "Connect Garmin"));
      banner.hidden = false;
    } else banner.hidden = true;
    const wasBusy = refreshStatus._busy;
    refreshStatus._busy = s.busy;
    if (wasBusy && !s.busy) { render(true); }
  }
  function ago(ts) {
    const m = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    if (m < 1440) return `${Math.round(m / 60)} h ago`;
    return `${Math.round(m / 1440)} d ago`;
  }
  $("#syncBtn").onclick = async () => { await post("/api/sync"); toast("Sync started"); refreshStatus(); };
  setInterval(refreshStatus, 4000);

  /* ---------------------------------------------------------------- drawer */
  function openDrawer(title, nodes) {
    $("#drawerTitle").replaceChildren(title);
    $("#drawerBody").replaceChildren(...nodes);
    $("#drawer").hidden = false;
    $("#scrim").hidden = false;
  }
  function closeDrawer() { $("#drawer").hidden = true; $("#scrim").hidden = true; C.hideTip(); }
  $("#drawerClose").onclick = closeDrawer;
  $("#scrim").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  async function openActivity(a) {
    const g = a.group;
    const head = h("div", null,
      h("div", { class: "row" }, h("span", { style: { color: SPORT_COLOR[g], display: "inline-flex" } }, sportIcon(g)), h("h2", null, a.name || a.sport)),
      h("div", { class: "muted" }, `${fmtDay(a.day)} · ${a.start_local.slice(11)} · ${a.sport}${a.strava_id ? " · on Strava" : ""}`));
    const kv = (k, v, u) => h("div", null, h("div", { class: "k" }, k), h("div", { class: "v" }, v, u ? h("small", null, " " + u) : null));
    const stats = h("div", { class: "kv" },
      kv("Duration", dur(a.duration_s)), kv("Moving", dur(a.moving_s)), kv("Distance", km(a.distance_m), "km"),
      kv("TSS", r0(a.tss), a.tss_method), kv("Garmin load", r0(a.training_load)), kv("Pace / speed", pace(a.avg_speed_ms, g)),
      kv("Avg HR", r0(a.avg_hr), "bpm"), kv("Max HR", r0(a.max_hr), "bpm"), kv("Power", r0(a.norm_power || a.avg_power), a.norm_power ? "W NP" : "W"),
      kv("Aerobic TE", r1(a.aerobic_te)), kv("Anaerobic TE", r1(a.anaerobic_te)), kv("Elevation", r0(a.elev_gain_m), "m"),
      kv("Calories", r0(a.calories), "kcal"), kv("Suffer score", r0(a.suffer_score)), kv("Kudos / PRs", `${a.kudos ?? "–"} / ${a.pr_count ?? "–"}`));
    const nodes = [stats];
    const zones = [1, 2, 3, 4, 5].map((z) => a[`hr_z${z}_s`] || 0);
    if (zones.some((z) => z > 0)) {
      const zb = h("div");
      C.hbars(zb, zones.map((s, i) => ({ name: `Zone ${i + 1}`, color: `var(--z${i + 1})`, value: s, label: dur(s) })));
      nodes.push(card("Time in HR zones", null, zb));
    }
    if (a.te_label) nodes.push(h("div", { class: "muted" }, `Training effect: ${a.te_label.replace(/_/g, " ").toLowerCase()}`));
    openDrawer(head, nodes);
  }

  /* ---------------------------------------------------------------- check-in form */
  function checkinForm(day, existing, onSaved) {
    const state = Object.assign({ day, energy: null, soreness: null, mood: null, motivation: null, illness: 0, injury: "", notes: "" }, existing || {});
    const scale = (key, label, hint) => {
      const wrap = h("div", { class: "scale", role: "radiogroup", "aria-label": label });
      for (let i = 1; i <= 5; i++) {
        const b = h("button", { type: "button", class: state[key] === i ? "on" : null, "aria-pressed": state[key] === i ? "true" : "false" }, i);
        b.onclick = () => { state[key] = state[key] === i ? null : i; [...wrap.children].forEach((c, k) => c.classList.toggle("on", state[key] === k + 1)); };
        wrap.append(b);
      }
      return h("label", { class: "field" }, `${label} `, h("span", { class: "muted", style: { fontWeight: 400 } }, hint), wrap);
    };
    const ill = h("input", { type: "checkbox" }); ill.checked = !!state.illness;
    const inj = h("input", { type: "text", value: state.injury || "", placeholder: "e.g. left calf tight" });
    const notes = h("textarea", { rows: 2, placeholder: "How do you feel? Anything Claude should know?" }); notes.value = state.notes || "";
    const save = h("button", { class: "btn primary", type: "button" }, "Save check-in");
    save.onclick = async () => {
      Object.assign(state, { illness: ill.checked ? 1 : 0, injury: inj.value.trim() || null, notes: notes.value.trim() || null });
      await post("/api/checkin", state);
      toast("Check-in saved");
      onSaved && onSaved();
    };
    return h("div", { class: "stack" },
      h("div", { class: "ci-grid" },
        scale("energy", "Energy", "1 low – 5 high"), scale("soreness", "Soreness", "1 none – 5 very"),
        scale("mood", "Mood", "1 low – 5 great"), scale("motivation", "Motivation", "1 low – 5 high")),
      h("div", { class: "ci-grid" },
        h("label", { class: "field" }, "Injury / niggle", inj),
        h("label", { class: "field", style: { alignContent: "end" } }, h("span", { class: "row" }, ill, "Feeling ill"))),
      h("label", { class: "field" }, "Notes", notes),
      h("div", null, save));
  }

  /* ================================================================ HOME */
  async function renderHome(view) {
    const t = todayIso();
    const [today, dash, ci] = await Promise.all([api(`/api/today?day=${t}`), api(`/api/dashboard?start=${iso(addDays(new Date(), -42))}`), api(`/api/checkin?day=${t}`)]);
    const a = today.assessment, d = today.daily || {};
    const daily = dash.daily;
    const series = (k, f = (x) => x) => daily.slice(-14).map((r) => (r[k] == null ? null : f(r[k])));
    const prevAvg = (k, f = (x) => x) => { const v = daily.slice(-31, -1).map((r) => r[k]).filter((x) => x != null).map(f); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };

    const lvl = { Rest: "critical", Recovery: "serious", "Easy / moderate": "warning", Train: "good", Go: "good" }[a.verdict];
    const verdict = card("Today", fmtDay(t), h("div", { class: "stack" },
      h("div", { class: "verdict" },
        h("div", { class: "hero" }, a.verdict),
        h("div", null,
          lvl ? status(lvl, { critical: "Rest advised", serious: "Recovery advised", warning: "Some fatigue signals", good: "Good to train" }[lvl]) : null,
          h("div", { class: "advice" }, a.advice),
          a.form_zone ? h("div", { class: "muted" }, `Form (TSB) zone: ${a.form_zone}`) : null)),
      a.flags.length ? h("ul", { class: "flags" }, a.flags.map((f) => h("li", null, status(f.level, ""), h("span", { class: "metric" }, f.metric), h("span", { class: "ink2" }, f.message)))) : null));

    const tile = (label, value, unit, delta, spark) => {
      const sp = h("div", { class: "spark" });
      if (spark) C.spark(sp, spark);
      return h("div", { class: "tile" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value ?? "–", unit ? h("small", null, unit) : null), h("div", { class: "delta" }, delta || " "), sp);
    };
    const dl = (v, base, unit, digits = 0) => (v != null && base != null ? `${v - base >= 0 ? "+" : "−"}${Math.abs(v - base).toFixed(digits)} ${unit} vs 30-day avg` : "");
    const L = a.load || {};
    const tiles = h("div", { class: "tiles" },
      tile("Form (TSB)", L.tsb != null ? Math.round(L.tsb) : null, null, `Fitness ${r0(L.ctl)} · Fatigue ${r0(L.atl)}`, dash.pmc.filter((p) => !p.projected).slice(-14).map((p) => p.tsb)),
      tile("Sleep", d.sleep_s ? hrs(d.sleep_s) : null, "h", d.sleep_score ? `Score ${d.sleep_score}` : "", series("sleep_s", (x) => x / 3600)),
      tile("HRV", d.hrv_last_night, "ms", d.hrv_status ? d.hrv_status.toLowerCase() : dl(d.hrv_last_night, prevAvg("hrv_last_night"), "ms"), series("hrv_last_night")),
      tile("Resting HR", d.rhr, "bpm", dl(d.rhr, prevAvg("rhr"), "bpm"), series("rhr")),
      tile("Body Battery", d.bb_latest ?? d.bb_high, null, d.bb_wake != null ? `Woke at ${d.bb_wake}` : "", series("bb_high")),
      tile("Readiness", d.readiness, null, d.readiness_level ? d.readiness_level.toLowerCase() : "", series("readiness")),
      tile("Stress", d.avg_stress, null, d.stress_high_min ? `${d.stress_high_min} min high` : "", series("avg_stress")),
      tile("Steps", d.steps != null ? d.steps.toLocaleString() : null, null, d.intensity_vig_min != null ? `${(d.intensity_mod_min || 0) + 2 * (d.intensity_vig_min || 0)} intensity min` : "", series("steps")));

    // intraday small multiples (no dual axis): HR, stress, body battery on a 5-min grid
    const intr = today.intraday;
    const t0 = parse(t).getTime();
    const grid = (pts) => { const a = new Array(288).fill(null); pts.forEach(([ts, v]) => { const i = Math.floor((ts - t0) / 300000); if (i >= 0 && i < 288) a[i] = a[i] == null ? v : Math.max(a[i], v); }); return a; };
    const hasIntraday = intr.hr.length || intr.stress.length || intr.body_battery.length;
    const intraEl = h("div");
    const intraCard = card("Today, minute by minute", "heart rate · stress · body battery", hasIntraday ? intraEl : h("div", { class: "empty" }, "No intraday data yet for today."), {
      table: () => [["Time", "HR", "Stress", "Body Battery"], gHR.map((_, i) => [lbl(i), gHR[i], gST[i], gBB[i]]).filter((r) => r[1] != null || r[2] != null || r[3] != null)],
    });
    const gHR = grid(intr.hr), gST = grid(intr.stress), gBB = grid(intr.body_battery);
    const lbl = (i) => `${String(Math.floor(i / 12)).padStart(2, "0")}:${String((i % 12) * 5).padStart(2, "0")}`;

    const ciCard = card("How do you feel?", "daily check-in - feeds the coach", checkinForm(t, ci.updated_at ? ci : null));

    const upcoming = h("div", { class: "stack" });
    const recentCard = card("Recent sessions", null, upcoming);
    const recent = (await api(`/api/calendar?start=${iso(addDays(new Date(), -10))}&end=${iso(addDays(new Date(), 7))}`)).days;
    const fut = recent.filter((x) => x.day >= t).flatMap((x) => x.planned.map((p) => ({ ...p, planned: true })));
    const past = recent.filter((x) => x.day <= t).flatMap((x) => x.activities).reverse().slice(0, 6);
    if (fut.length) upcoming.append(h("div", { class: "muted" }, "Planned"), ...fut.slice(0, 4).map((p) => workoutCard(p, true)));
    if (past.length) upcoming.append(h("div", { class: "muted" }, "Completed"), ...past.map((x) => workoutCard(x)));
    if (!fut.length && !past.length) upcoming.append(h("div", { class: "empty" }, "No sessions in the last 10 days."));

    view.replaceChildren(h("div", { class: "grid g3" },
      h("div", { class: "span2 stack" }, verdict, tiles, intraCard),
      h("div", { class: "stack" }, ciCard, recentCard)));

    if (hasIntraday) {
      const ticks = [0, 36, 72, 108, 144, 180, 216, 252].map((i) => ({ i, text: lbl(i) }));
      C.time(intraEl, {
        n: 288, label: (i) => lbl(i), ticks, aria: "Intraday heart rate, stress and body battery",
        panels: [
          { height: 90, title: "Heart rate (bpm)", series: [{ name: "Heart rate", type: "line", color: "var(--s1)", values: gHR }] },
          { height: 70, title: "Stress", yMin: 0, yMax: 100, series: [{ name: "Stress", type: "bars", color: "var(--s2)", values: gST }] },
          { height: 70, title: "Body Battery", yMin: 0, yMax: 100, series: [{ name: "Body Battery", type: "area", color: "var(--s3)", values: gBB, endLabel: true }] },
        ],
      });
    }
  }

  function workoutCard(x, planned) {
    const g = x.group || "Other";
    const done = x.completed;
    const isPast = x.day < todayIso();
    const badge = planned ? (done ? h("span", { class: "badge done" }, "Done") : isPast ? h("span", { class: "badge missed" }, "Missed") : h("span", { class: "badge" }, "Planned")) : null;
    const b = h("button", { class: "wk" + (planned ? " planned" : ""), style: { "--sport": SPORT_COLOR[g] }, title: `${x.name || ""} (${x.sport || g})` },
      h("div", { class: "t" }, sportIcon(g), h("span", null, x.name || x.sport || g), badge),
      h("div", { class: "d" },
        x.duration_s ? h("span", null, h("b", null, dur(x.duration_s))) : null,
        x.distance_m ? h("span", null, km(x.distance_m) + " km") : null,
        !planned && x.tss != null ? h("span", null, h("b", null, Math.round(x.tss)), " TSS") : null,
        !planned && x.avg_hr ? h("span", null, Math.round(x.avg_hr) + " bpm") : null));
    if (!planned) b.onclick = () => openActivity(x);
    else b.onclick = () => openDrawer(h("h2", null, x.name || "Planned workout"), [h("div", { class: "muted" }, `${fmtDay(x.day)} · ${x.sport || ""} · ${dur(x.duration_s)}${x.distance_m ? " · " + km(x.distance_m) + " km" : ""}`), h("div", null, "Scheduled in Garmin Connect. Ask Claude to adjust or create workouts - they sync to your watch.")]);
    return b;
  }

  /* ================================================================ CALENDAR */
  let calAnchor = monday(new Date());
  async function renderCalendar(view) {
    const weeksShown = 6;
    const start = addDays(calAnchor, -7 * (weeksShown - 2));
    const end = addDays(start, 7 * weeksShown - 1);
    const data = await api(`/api/calendar?start=${iso(start)}&end=${iso(end)}`);
    const t = todayIso();
    const prev = h("button", { class: "btn", title: "Earlier" }, "‹");
    const next = h("button", { class: "btn", title: "Later" }, "›");
    const tdy = h("button", { class: "btn" }, "Today");
    prev.onclick = () => { calAnchor = addDays(calAnchor, -28); render(); };
    next.onclick = () => { calAnchor = addDays(calAnchor, 28); render(); };
    tdy.onclick = () => { calAnchor = monday(new Date()); render(); };
    const sMid = parse(data.days[Math.floor(data.days.length / 2)].day);
    const toolbar = h("div", { class: "toolbar" }, h("h2", null, `${MON[sMid.getMonth()]} ${sMid.getFullYear()}`), prev, tdy, next,
      h("span", { class: "spacer", style: { flex: 1 } }),
      legend(SPORTS.map((s) => ({ name: s, color: SPORT_COLOR[s] }))));

    const cal = h("div", { class: "cal" },
      h("div", { class: "cal-head" }, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Week summary"].map((d) => h("div", null, d))));
    const weeks = {};
    data.weeks.forEach((w) => (weeks[w.week] = w));
    const midMonth = sMid.getMonth();
    for (let w = 0; w < weeksShown; w++) {
      const row = h("div", { class: "cal-week" });
      const days = data.days.slice(w * 7, w * 7 + 7);
      days.forEach((d) => {
        const dt = parse(d.day);
        const m = d.metrics || {};
        // mark planned workouts as completed when an activity of the same sport exists that day
        const usedActs = new Set();
        d.planned.forEach((p) => {
          const hit = d.activities.find((a, k) => !usedActs.has(k) && a.group === p.group && usedActs.add(k));
          p.completed = !!hit;
        });
        const metricsBits = [];
        if (m.sleep_s) metricsBits.push(h("span", null, "Sleep ", h("b", null, hrs(m.sleep_s) + "h")));
        if (m.hrv_last_night) metricsBits.push(h("span", null, "HRV ", h("b", null, m.hrv_last_night)));
        if (m.rhr) metricsBits.push(h("span", null, "RHR ", h("b", null, m.rhr)));
        if (m.bb_wake != null) metricsBits.push(h("span", null, "BB ", h("b", null, m.bb_wake)));
        if (d.checkin && d.checkin.energy) metricsBits.push(h("span", null, "Energy ", h("b", null, d.checkin.energy + "/5")));
        const chip = metricsBits.length ? h("div", { class: "metrics-chip", title: "Day metrics" }, metricsBits) : null;
        if (chip) chip.onclick = () => openDay(d);
        const addCi = h("button", { class: "addci", title: "Check-in / day details" }, d.checkin ? "✎" : "+");
        addCi.onclick = () => openDay(d);
        row.append(h("div", { class: "cal-day" + (dt.getMonth() !== midMonth ? " other" : "") + (d.day === t ? " today" : "") },
          h("div", { class: "dnum" }, h("span", null, dt.getDate() === 1 || (w === 0 && dt.getDay() === 1) ? `${MON[dt.getMonth()]} ${dt.getDate()}` : dt.getDate()), addCi),
          chip,
          d.activities.map((a) => workoutCard(a)),
          d.planned.filter((p) => !p.completed || d.day >= t).filter((p) => !p.completed).map((p) => workoutCard(p, true))));
      });
      const wk = weeks[days[0].day] || {};
      const sum = h("div", { class: "cal-sum" },
        h("div", { class: "row" }, h("span", null, "Total TSS"), h("b", null, wk.tss ?? 0)),
        h("div", { class: "row" }, h("span", null, "Duration"), h("b", null, dur(wk.duration_s))),
        h("div", { class: "row" }, h("span", null, "Distance"), h("b", null, km(wk.distance_m) + " km")),
        h("hr"),
        h("div", { class: "row" }, h("span", null, "Fitness (CTL)"), h("b", null, r0(wk.ctl))),
        h("div", { class: "row" }, h("span", null, "Fatigue (ATL)"), h("b", null, r0(wk.atl))),
        h("div", { class: "row" }, h("span", null, "Form (TSB)"), h("b", null, r0(wk.tsb))),
        h("hr"),
        SPORTS.filter((s) => wk.by_sport && wk.by_sport[s].count).map((s) =>
          h("div", { class: "row" }, h("span", { class: "sp", style: { "--sport": SPORT_COLOR[s] } }, h("i"), s), h("b", null, `${dur(wk.by_sport[s].duration_s)}${wk.by_sport[s].distance_m ? " · " + km(wk.by_sport[s].distance_m) : ""}`))));
      row.append(sum);
      cal.append(row);
    }
    view.replaceChildren(toolbar, h("div", { class: "cal-wrap" }, cal));
  }

  async function openDay(d) {
    const m = d.metrics || {};
    const kv = (k, v, u) => h("div", null, h("div", { class: "k" }, k), h("div", { class: "v" }, v ?? "–", u ? h("small", null, " " + u) : null));
    const ci = await api(`/api/checkin?day=${d.day}`);
    openDrawer(h("h2", null, fmtDay(d.day)), [
      h("div", { class: "kv" },
        kv("Sleep", m.sleep_s ? hrs(m.sleep_s) : null, "h"), kv("Sleep score", m.sleep_score), kv("HRV", m.hrv_last_night, "ms"),
        kv("Resting HR", m.rhr, "bpm"), kv("BB at wake", m.bb_wake), kv("Readiness", m.readiness),
        kv("Avg stress", m.avg_stress), kv("Steps", m.steps != null ? m.steps.toLocaleString() : null), kv("Weight", m.weight_kg, "kg")),
      card("Check-in", null, checkinForm(d.day, ci.updated_at ? ci : null, () => { closeDrawer(); render(); })),
    ]);
  }

  /* ================================================================ DASHBOARD */
  let dashRange = 90, dashMetric = "tss";
  async function renderDashboard(view, soft) {
    if (soft && view.firstChild) view.classList.add("loading");
    const start = iso(addDays(new Date(), -dashRange));
    const data = await api(`/api/dashboard?start=${start}&metric=${dashMetric}`);
    view.classList.remove("loading");
    const seg = (opts, cur, on) => h("div", { class: "seg" }, opts.map(([v, l]) => h("button", { class: v === cur ? "on" : null, onclick: () => on(v) }, l)));
    const toolbar = h("div", { class: "toolbar" }, h("h2", null, "Dashboard"),
      seg([[42, "6 weeks"], [90, "3 months"], [182, "6 months"], [365, "1 year"], [730, "2 years"]], dashRange, (v) => { dashRange = v; renderDashboard(view, true); }),
      seg([["tss", "TSS (est.)"], ["garmin", "Garmin load"]], dashMetric, (v) => { dashMetric = v; renderDashboard(view, true); }));

    const p = data.pmc, L = data.load || {};
    const days = p.map((x) => x.day);
    const projFrom = p.findIndex((x) => x.projected);
    const pf = projFrom >= 0 ? projFrom : null;
    const todayIdx = days.indexOf(todayIso());
    const pmcEl = h("div");
    const pmcCard = card("Performance Management Chart", dashMetric === "tss" ? "TSS-based · dashed = planned" : "Garmin training load", h("div", null,
      legend([{ name: "Fitness (CTL)", color: "var(--fitness)", shape: "line" }, { name: "Fatigue (ATL)", color: "var(--fatigue)", shape: "line" },
        { name: "Form (TSB)", color: "var(--form)" }, { name: dashMetric === "tss" ? "Daily TSS" : "Daily load", color: "var(--tss-dot)", shape: "dot" }]), pmcEl),
    { cls: "span-all", table: () => [["Day", "Load", "CTL", "ATL", "TSB"], p.slice().reverse().map((x) => [x.day + (x.projected ? " (plan)" : ""), r0(x.tss), r1(x.ctl), r1(x.atl), r1(x.tsb)])] });

    const tiles = h("div", { class: "tiles span-all" },
      ...[["Fitness (CTL)", r0(L.ctl)], ["Fatigue (ATL)", r0(L.atl)], ["Form (TSB)", r0(L.tsb)], ["Ramp rate", L.ramp_rate != null ? (L.ramp_rate > 0 ? "+" : "") + L.ramp_rate : "–", "CTL/wk"],
        ["Load last 7 days", r0(L.tss_7d)], ["ACWR", L.acwr ?? "–"]].map(([l, v, u]) =>
        h("div", { class: "tile" }, h("div", { class: "label" }, l), h("div", { class: "value" }, v, u ? h("small", null, u) : null))));

    const wkEl = h("div");
    const weeks = data.weeks;
    const wkCard = card("Weekly TSS by sport", null, h("div", null, legend(SPORTS.map((s) => ({ name: s, color: SPORT_COLOR[s] }))), wkEl),
      { cls: "span2", table: () => [["Week", "TSS", ...SPORTS.map((s) => s + " TSS"), "Time", "km"], weeks.slice().reverse().map((w) => [w.week, w.tss, ...SPORTS.map((s) => r0(w.by_sport[s].tss)), dur(w.duration_s), km(w.distance_m)])] });

    const sportEl = h("div");
    const sportCard = card("Fitness summary", `by sport · ${dashRange} days`, sportEl, {
      table: () => [["Sport", "Sessions", "Time", "km", "TSS"], SPORTS.map((s) => [s, data.sports[s].count, dur(data.sports[s].duration_s), km(data.sports[s].distance_m), r0(data.sports[s].tss)])],
    });
    const zoneEl = h("div");
    const zoneCard = card("Time in heart-rate zones", `${dashRange} days`, zoneEl, {
      table: () => [["Zone", "Time", "%"], data.zones_s.map((s, i) => [`Zone ${i + 1}`, dur(s), r0((100 * s) / (data.zones_s.reduce((a, b) => a + b, 0) || 1)) + "%"])],
    });

    // wellness small multiples (one measure per chart, shared date range)
    const dmap = {}; data.daily.forEach((r) => (dmap[r.day] = r));
    const wDays = [];
    for (let d = parse(data.range.start); iso(d) <= data.range.end; d = addDays(d, 1)) wDays.push(iso(d));
    const col = (k, f = (x) => x) => wDays.map((d) => (dmap[d] && dmap[d][k] != null ? f(dmap[d][k]) : null));
    const wellness = [
      { title: "HRV (overnight)", unit: "ms", k: "hrv_last_night", band: true },
      { title: "Resting heart rate", unit: "bpm", k: "rhr" },
      { title: "Sleep", unit: "h", k: "sleep_s", f: (x) => Math.round((x / 3600) * 10) / 10, type: "bars", zero: true },
      { title: "Sleep score", unit: "", k: "sleep_score" },
      { title: "Body Battery at wake", unit: "", k: "bb_wake", type: "bars", zero: true },
      { title: "Average stress", unit: "", k: "avg_stress" },
      { title: "Training readiness", unit: "", k: "readiness" },
      { title: "Weight", unit: "kg", k: "weight_kg", dots: true },
      { title: "VO2max", unit: "", k: "vo2max" },
    ];
    const wellCards = wellness.map((w) => {
      const vals = col(w.k, w.f);
      const elc = h("div");
      const last = [...vals].reverse().find((v) => v != null);
      const c = card(w.title, last != null ? `latest ${last}${w.unit ? " " + w.unit : ""}` : "no data", elc, {
        table: () => [["Day", w.title], wDays.map((d, i) => [d, vals[i]]).filter((r) => r[1] != null).reverse()],
      });
      c._draw = () => {
        if (!vals.some((v) => v != null)) { elc.replaceChildren(h("div", { class: "empty" }, "No data in this range")); return; }
        const bands = [];
        if (w.band) {
          const lo = col("hrv_baseline_low"), hi = col("hrv_baseline_high");
          const li = lo.map((v, i) => [v, hi[i]]).filter((x) => x[0] != null).pop();
          if (li) bands.push({ from: li[0], to: li[1], label: "baseline", include: true });
        }
        C.time(elc, {
          n: wDays.length, label: (i) => fmtDay(wDays[i]), ticks: dayTicks(wDays), aria: w.title,
          panels: [{ height: 110, zero: w.zero, bands, format: (v, axis) => (axis ? C.fmtNum(v) : C.fmtNum(v) + (w.unit ? " " + w.unit : "")),
            series: [{ name: w.title, type: w.type || (w.dots ? "dots" : "line"), color: "var(--s1)", values: vals, endLabel: !w.type }] }],
        });
      };
      return c;
    });

    view.replaceChildren(toolbar, h("div", { class: "grid g3" }, tiles, pmcCard, wkCard, h("div", { class: "stack" }, sportCard, zoneCard),
      h("h2", { class: "span-all", style: { marginTop: "8px" } }, "Health & recovery"), ...wellCards));

    C.time(pmcEl, {
      n: days.length, label: (i) => fmtDay(days[i]), ticks: dayTicks(days), todayIndex: todayIdx >= 0 ? todayIdx : null, aria: "Performance management chart",
      panels: [
        { height: 230, zero: true, series: [
          { name: dashMetric === "tss" ? "Daily TSS" : "Daily load", type: "dots", color: "var(--tss-dot)", values: p.map((x) => x.tss || null), projectedFrom: pf },
          { name: "Fitness (CTL)", type: "area", color: "var(--fitness)", values: p.map((x) => x.ctl), endLabel: true, projectedFrom: pf },
          { name: "Fatigue (ATL)", type: "line", color: "var(--fatigue)", values: p.map((x) => x.atl), endLabel: true, projectedFrom: pf },
        ] },
        { height: 110, title: "Form (TSB)", bands: [
            { from: 5, to: 25, label: "fresh" }, { from: -30, to: -10, label: "optimal training" }, { from: -200, to: -30, label: "high risk", fill: "color-mix(in srgb, var(--critical) 8%, transparent)" }],
          series: [{ name: "Form (TSB)", type: "bars", color: "var(--form)", values: p.map((x) => x.tsb), projectedFrom: pf }] },
      ],
    });
    C.columns(wkEl, {
      cats: weeks.map((w) => { const d = parse(w.week); return `${d.getDate()} ${MON[d.getMonth()]}`; }),
      tipLabel: (i) => `Week of ${fmtDay(weeks[i].week)}`, height: 200, format: (v) => Math.round(v) + " TSS", totalFormat: (v) => Math.round(v),
      series: SPORTS.map((s) => ({ name: s, color: SPORT_COLOR[s], values: weeks.map((w) => w.by_sport[s].tss) })),
    });
    C.hbars(sportEl, SPORTS.filter((s) => data.sports[s].count).map((s) => ({ name: s, color: SPORT_COLOR[s], value: data.sports[s].duration_s, label: `${dur(data.sports[s].duration_s)} · ${data.sports[s].count}×` })));
    if (!sportEl.children.length) sportEl.append(h("div", { class: "empty" }, "No sessions in range"));
    const ztot = data.zones_s.reduce((a, b) => a + b, 0) || 1;
    C.hbars(zoneEl, data.zones_s.map((s, i) => ({ name: `Zone ${i + 1}`, color: `var(--z${i + 1})`, value: s, label: `${dur(s)} · ${Math.round((100 * s) / ztot)}%` })));
    wellCards.forEach((c) => c._draw());
  }

  /* ================================================================ COACH */
  function mdToNodes(md) {
    // tiny markdown renderer for the briefing (headings, lists, tables, bold/italic)
    const root = h("div", { class: "md" });
    const inline = (s) => {
      const span = h("span");
      s.split(/(\*\*[^*]+\*\*|_[^_]+_)/).forEach((part) => {
        if (/^\*\*.*\*\*$/.test(part)) span.append(h("b", null, part.slice(2, -2)));
        else if (/^_.*_$/.test(part)) span.append(h("i", null, part.slice(1, -1)));
        else span.append(part);
      });
      return span;
    };
    const lines = md.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (l.startsWith("# ")) root.append(h("h1", null, l.slice(2)));
      else if (l.startsWith("## ")) root.append(h("h2", null, l.slice(3)));
      else if (l.startsWith("- ")) {
        const ul = h("ul");
        while (i < lines.length && lines[i].startsWith("- ")) { ul.append(h("li", null, inline(lines[i].slice(2)))); i++; }
        i--; root.append(ul);
      } else if (l.startsWith("|")) {
        const rows = [];
        while (i < lines.length && lines[i].startsWith("|")) { rows.push(lines[i]); i++; }
        i--;
        const cells = (r) => r.split("|").slice(1, -1).map((c) => c.trim());
        const t = h("table", null, h("thead", null, h("tr", null, cells(rows[0]).map((c) => h("th", null, c)))),
          h("tbody", null, rows.slice(2).map((r) => h("tr", null, cells(r).map((c) => h("td", null, c))))));
        root.append(h("div", { class: "tbl-wrap" }, t));
      } else if (l.trim()) root.append(h("p", null, inline(l)));
    }
    return root;
  }

  async function renderCoach(view) {
    const md = await api("/api/briefing?days=14");
    const copy = h("button", { class: "btn primary" }, "Copy briefing for Claude");
    copy.onclick = async () => { try { await navigator.clipboard.writeText(md); toast("Copied - paste it into Claude"); } catch (e) { toast("Copy failed - select the text instead"); } };
    const how = card("Using Claude as your coach", null, h("div", { class: "stack" },
      h("div", null, "Claude Code in this project folder has two tools wired up: ", h("b", null, "healthwatcher"), " (this database: briefing, trends, load model, check-ins, SQL) and ",
        h("b", null, "garmin"), " (live Garmin Connect: create & schedule structured workouts that sync to your watch)."),
      h("pre", { class: "code" }, "cd \"" + (STATUS?.project_root || "healthwatcher") + "\"\nclaude\n> How am I recovering? Plan my next training week."),
      h("div", { class: "muted" }, "Or copy the briefing below into any Claude chat.")));
    view.replaceChildren(h("div", { class: "toolbar" }, h("h2", null, "Coach briefing"), copy),
      h("div", { class: "grid g3" }, h("div", { class: "card span2" }, h("div", { class: "card-body" }, mdToNodes(md))), h("div", { class: "stack" }, how)));
  }

  /* ================================================================ SETTINGS */
  async function renderSettings(view) {
    await refreshStatus();
    const s = STATUS;
    // Garmin
    const gBody = h("div", { class: "stack" });
    if (s.garmin.has_tokens) {
      const out = h("button", { class: "btn" }, "Disconnect");
      out.onclick = async () => { await post("/api/garmin/logout"); render(); };
      gBody.append(status("good", `Connected${s.garmin.profile_name ? " as " + s.garmin.profile_name : ""}`),
        h("div", { class: "muted" }, `Last sync: ${s.garmin.last_sync || "never"} · ${s.counts.days} days, ${s.counts.garmin_acts} activities stored${s.counts.first_day ? " since " + s.counts.first_day : ""}`),
        h("div", { class: "muted" }, `Auto-sync every ${s.sync.interval_min} min while the app is open.`), h("div", null, out));
    } else {
      const email = h("input", { type: "email", autocomplete: "username", placeholder: "you@example.com" });
      const pw = h("input", { type: "password", autocomplete: "current-password" });
      const mfa = h("input", { type: "text", inputmode: "numeric", placeholder: "123456" });
      const mfaRow = h("label", { class: "field", hidden: true }, "MFA code (check your email / authenticator)", mfa);
      const msg = h("div", { class: "muted" }, "Your password goes straight to Garmin and is not stored - only the session tokens are kept in ~/.garminconnect.");
      const go = h("button", { class: "btn primary" }, "Connect Garmin");
      let mfaStage = false;
      const submit = async () => {
        go.disabled = true; msg.textContent = "Connecting…";
        try {
          if (!mfaStage) {
            const r = await post("/api/garmin/login", { email: email.value.trim(), password: pw.value });
            if (r.status === "needs_mfa") { mfaStage = true; mfaRow.hidden = false; msg.textContent = "Enter the MFA code Garmin sent you."; go.textContent = "Verify"; mfa.focus(); }
            else { msg.textContent = "Connected - first sync started (backfill can take a few minutes)."; setTimeout(render, 800); }
          } else {
            await post("/api/garmin/mfa", { code: mfa.value });
            msg.textContent = "Connected - first sync started (backfill can take a few minutes)."; setTimeout(render, 800);
          }
        } catch (e) { msg.textContent = "Failed: " + e.message; }
        go.disabled = false;
      };
      go.onclick = submit;
      [email, pw, mfa].forEach((i) => i.addEventListener("keydown", (e) => e.key === "Enter" && submit()));
      gBody.append(h("div", { class: "form" }, h("label", { class: "field" }, "Garmin email", email), h("label", { class: "field" }, "Password", pw), mfaRow, h("div", null, go), msg));
    }
    // Strava
    const sBody = h("div", { class: "stack" });
    if (s.strava.connected) {
      const dc = h("button", { class: "btn" }, "Disconnect");
      dc.onclick = async () => { await post("/api/strava/disconnect"); render(); };
      sBody.append(status("good", `Connected${s.strava.athlete ? " as " + s.strava.athlete : ""}`),
        h("div", { class: "muted" }, `Last sync: ${s.strava.last_sync || "never"} · ${s.counts.strava_acts} activities, matched to Garmin sessions automatically.`), h("div", null, dc));
    } else if (s.strava.configured) {
      sBody.append(h("div", null, "Strava API app configured."), h("div", null, h("a", { class: "btn primary", href: "/strava/connect" }, "Connect Strava")));
    } else {
      sBody.append(
        h("div", null, "Strava needs a (free) personal API application:"),
        h("ol", null,
          h("li", null, "Open strava.com/settings/api and create an app."),
          h("li", null, "Set ", h("b", null, "Authorization Callback Domain"), " to ", h("code", null, "localhost"), "."),
          h("li", null, "Put the Client ID and Client Secret in the ", h("code", null, ".env"), " file of this project:"),
        ),
        h("pre", { class: "code" }, "STRAVA_CLIENT_ID=12345\nSTRAVA_CLIENT_SECRET=abc123…"),
        h("div", { class: "muted" }, "Then restart the app and click Connect Strava."));
    }
    const th = s.thresholds;
    const thBody = table(["Threshold", "Value", "Source"], [
      ["Lactate threshold HR", th.lthr + " bpm", th.lthr_source], ["FTP", th.ftp ? th.ftp + " W" : "–", th.ftp_source || "not set (HW_FTP in .env)"],
      ["Max HR (observed)", th.max_hr ?? "–", "activities"], ["Resting HR (30d)", th.rhr_30d ?? "–", "Garmin"], ["Sleep target", th.sleep_target_h + " h", "HW_SLEEP_TARGET_H"]]);
    const logBody = table(["Time", "Source", "Status", "Message"], s.log.map((l) => [l.ts.replace("T", " "), l.source, l.status, l.message]));
    view.replaceChildren(h("div", { class: "toolbar" }, h("h2", null, "Settings & connections")),
      h("div", { class: "grid g2" },
        card("Garmin Connect", null, gBody), card("Strava", null, sBody),
        card("Training thresholds", "used for TSS - override in .env (HW_LTHR, HW_FTP)", thBody), card("Sync log", null, logBody)));
  }

  /* ---------------------------------------------------------------- router */
  const VIEWS = { home: renderHome, calendar: renderCalendar, dashboard: renderDashboard, coach: renderCoach, settings: renderSettings };
  let current = null;
  async function render(soft) {
    const name = (location.hash.slice(1).split("?")[0] || "home");
    const v = VIEWS[name] ? name : "home";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.id !== "view-" + v));
    document.querySelectorAll("[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === v));
    const view = $("#view-" + v);
    if (current !== v && !soft) view.replaceChildren(h("div", { class: "empty" }, "Loading…"));
    current = v;
    try { await VIEWS[v](view, soft); }
    catch (e) { view.replaceChildren(h("div", { class: "empty" }, "Couldn't load: " + e.message)); console.error(e); }
  }
  window.addEventListener("hashchange", () => render());
  refreshStatus().then(() => render());
})();
