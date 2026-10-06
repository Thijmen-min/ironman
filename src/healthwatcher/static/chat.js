/* Coach chat panel: talks to an embedded Claude Code session via /api/chat (SSE). */
(function () {
  const { h, mdToNodes, toast, fmtDay, api, post, chatIcon } = HW.ui;
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* storage off */ } },
  };

  let convId = store.get("hw.chat.conv");
  let busy = false;
  let context = null; // {label, context}
  let streamBubble = null, streamText = "";
  const tools = {}; // tool_use id -> line element

  /* ---------------------------------------------------------------- DOM */
  const list = h("div", { class: "chat-msgs", role: "log", "aria-live": "polite" });
  const input = h("textarea", { rows: 1, placeholder: "Ask your coach…", "aria-label": "Message" });
  const sendBtn = h("button", { class: "btn primary chat-send", type: "button" }, "Send");
  const ctxChip = h("div", { class: "chat-ctx", hidden: true });
  const convSelect = h("select", { class: "chat-select", "aria-label": "Conversation" });
  const newBtn = h("button", { class: "btn", type: "button", title: "Start a new conversation" }, "New");
  const delBtn = h("button", { class: "btn-ghost chat-del", type: "button", title: "Delete this conversation" }, "🗑");
  const closeBtn = h("button", { class: "btn-ghost", type: "button", "aria-label": "Close chat" }, "×");
  const panel = h("aside", { class: "chat", id: "chat", hidden: true, "aria-label": "Coach chat" },
    h("div", { class: "chat-head" }, h("div", { class: "chat-title" }, chatIcon(), "Coach"), convSelect, newBtn, delBtn, closeBtn),
    list,
    h("div", { class: "chat-foot" }, ctxChip, h("div", { class: "chat-input" }, input, sendBtn)));
  document.body.appendChild(panel);

  const topBtn = h("button", { class: "btn-top", id: "chatBtn", title: "Coach chat (Claude)" }, chatIcon(), "Coach chat");
  $(".topbar-right").insertBefore(topBtn, $("#syncBtn"));
  topBtn.onclick = () => (panel.hidden ? open({}) : close());
  closeBtn.onclick = close;

  /* ---------------------------------------------------------------- open / close */
  function open(opts) {
    panel.hidden = false;
    document.body.classList.add("chat-open");
    store.set("hw.chat.open", "1");
    if (opts && opts.context) setContext({ label: opts.label || opts.context, context: opts.context });
    if (opts && opts.prompt) input.value = opts.prompt;
    if (!list.childElementCount) loadConversation(convId);
    setTimeout(() => input.focus(), 50);
    window.dispatchEvent(new Event("resize"));
  }
  function close() {
    panel.hidden = true;
    document.body.classList.remove("chat-open");
    store.set("hw.chat.open", null);
    window.dispatchEvent(new Event("resize"));
  }

  function setContext(c) {
    context = c;
    ctxChip.replaceChildren();
    if (!c) { ctxChip.hidden = true; return; }
    const x = h("button", { class: "btn-ghost", type: "button", "aria-label": "Remove context" }, "×");
    x.onclick = () => setContext(null);
    ctxChip.append(h("span", { class: "muted" }, "About: "), h("b", null, c.label), x);
    ctxChip.hidden = false;
  }

  /* ---------------------------------------------------------------- conversations */
  async function refreshList() {
    const convs = await api("/api/chat/conversations");
    convSelect.replaceChildren(h("option", { value: "" }, "New conversation"),
      ...convs.map((c) => h("option", { value: c.id }, (c.title || "Chat").slice(0, 48))));
    convSelect.value = convId && convs.some((c) => c.id === convId) ? convId : "";
    delBtn.hidden = !convSelect.value;
  }
  convSelect.onchange = () => loadConversation(convSelect.value || null);
  newBtn.onclick = () => loadConversation(null);
  delBtn.onclick = async () => {
    if (!convId || busy) return;
    if (delBtn.dataset.confirm !== "1") { delBtn.dataset.confirm = "1"; delBtn.textContent = "Delete?"; setTimeout(() => { delBtn.dataset.confirm = ""; delBtn.textContent = "🗑"; }, 3000); return; }
    await api(`/api/chat/conversations/${convId}`, { method: "DELETE" });
    delBtn.dataset.confirm = ""; delBtn.textContent = "🗑";
    loadConversation(null);
  };

  async function loadConversation(id) {
    if (busy) { toast("Wait for the current answer to finish"); return; }
    convId = id || null;
    store.set("hw.chat.conv", convId);
    list.replaceChildren();
    if (convId) {
      const msgs = await api(`/api/chat/conversations/${convId}`);
      msgs.forEach(renderStored);
      if (!msgs.length) emptyState();
    } else emptyState();
    await refreshList();
    scroll(true);
  }

  function emptyState() {
    const ideas = [
      ["What should I do today?", null],
      ["How is my recovery trending this week?", null],
      ["Plan my training for next week around my schedule.", null],
      ["Compare this week to last week.", null],
      ["How is my swim / bike / run balance for Knokke?", null],
    ];
    list.append(h("div", { class: "chat-empty" },
      h("div", { class: "chat-empty-title" }, "Your coach has your Garmin & Strava data"),
      h("div", { class: "muted" }, "Ask anything, or use “Discuss with Claude” on a day, workout or week."),
      h("div", { class: "chat-ideas" }, ideas.map(([q]) => {
        const b = h("button", { class: "chat-idea", type: "button" }, q);
        b.onclick = () => { input.value = q; send(); };
        return b;
      }))));
  }

  function renderStored(m) {
    if (m.role === "user") addUser(m.content, m.context);
    else if (m.role === "assistant") addAssistant(m.content);
    else if (m.role === "error") addError(m.content);
    else if (m.role === "tool") {
      let t = {};
      try { t = JSON.parse(m.content); } catch (e) { return; }
      if (t.permission) addNote(`${t.permission === "allowed" ? "✓ You allowed" : "✕ You declined"} ${prettyTool(t.name)}`);
      else if (t.name && !HIDDEN_TOOLS.has(t.name)) addTool({ id: null, name: t.name, input: t.input }, true);
    }
  }

  /* ---------------------------------------------------------------- rendering */
  const HIDDEN_TOOLS = new Set(["ToolSearch", "TodoWrite"]);
  function prettyTool(name) {
    const m = /^mcp__([^_]+(?:_[^_]+)*)__(.+)$/.exec(name || "");
    return m ? `${m[1]} · ${m[2].replace(/_/g, " ")}` : name;
  }
  function scroll(force) {
    const near = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    if (force || near) list.scrollTop = list.scrollHeight;
  }
  function clearEmpty() { const e = list.querySelector(".chat-empty"); if (e) e.remove(); }
  function addUser(text, ctx) {
    clearEmpty();
    list.append(h("div", { class: "msg user" }, ctx ? h("div", { class: "msg-ctx" }, ctx) : null, h("div", { class: "bubble" }, text)));
    scroll(true);
  }
  function addAssistant(md) {
    clearEmpty();
    const b = h("div", { class: "msg assistant" }, h("div", { class: "bubble" }, mdToNodes(md)));
    list.append(b);
    scroll();
    return b;
  }
  function addError(msg) { list.append(h("div", { class: "msg error" }, h("div", { class: "bubble" }, msg))); scroll(true); }
  function addNote(msg) { list.append(h("div", { class: "msg note" }, msg)); scroll(); }
  function addTool(ev, done) {
    if (HIDDEN_TOOLS.has(ev.name)) return;
    let arg = "";
    try { const inp = typeof ev.input === "string" ? JSON.parse(ev.input) : ev.input; arg = Object.values(inp || {}).filter((v) => typeof v !== "object").join(", "); } catch (e) { arg = ""; }
    const line = h("div", { class: "msg tool" + (done ? " done" : "") }, h("span", { class: "tool-state" }, done ? "✓" : ""),
      h("span", { class: "tool-name" }, prettyTool(ev.name)), arg ? h("span", { class: "tool-arg" }, arg.slice(0, 80)) : null);
    list.append(line);
    if (ev.id) tools[ev.id] = line;
    scroll();
  }
  function addPermission(ev) {
    const allow = h("button", { class: "btn primary", type: "button" }, "Allow");
    const deny = h("button", { class: "btn", type: "button" }, "Deny");
    const card = h("div", { class: "msg permission" },
      h("div", null, h("b", null, "Claude wants to run "), h("code", null, prettyTool(ev.tool))),
      h("pre", { class: "code" }, ev.input),
      h("div", { class: "row" }, allow, deny));
    const answer = async (ok) => {
      allow.disabled = deny.disabled = true;
      await post("/api/chat/permission", { conversation_id: convId, id: ev.id, allow: ok });
      card.replaceChildren(h("span", { class: "muted" }, `${ok ? "✓ Allowed" : "✕ Declined"}: ${prettyTool(ev.tool)}`));
      card.classList.add("answered");
    };
    allow.onclick = () => answer(true);
    deny.onclick = () => answer(false);
    list.append(card);
    scroll(true);
  }

  /* ---------------------------------------------------------------- sending */
  function setBusy(b) {
    busy = b;
    sendBtn.textContent = b ? "Stop" : "Send";
    sendBtn.classList.toggle("primary", !b);
    panel.classList.toggle("busy", b);
  }

  async function send() {
    if (busy) {
      if (convId) await post("/api/chat/interrupt", { conversation_id: convId });
      return;
    }
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    autosize();
    const ctx = context;
    addUser(text, ctx ? ctx.label : null);
    setContext(null);
    setBusy(true);
    const thinking = h("div", { class: "msg note typing" }, h("span", { class: "dots" }, h("i"), h("i"), h("i")), "Coach is thinking…");
    list.append(thinking);
    scroll(true);
    streamBubble = null; streamText = "";
    try {
      const r = await fetch("/api/chat/send", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: convId, message: text, context: ctx ? ctx.context : null }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
          thinking.remove();
          handle(ev);
        }
      }
    } catch (e) {
      addError("Chat failed: " + e.message);
    } finally {
      thinking.remove();
      finishStream();
      setBusy(false);
      refreshList();
      input.focus();
    }
  }

  function finishStream() {
    if (streamBubble) { streamBubble.remove(); streamBubble = null; }
    streamText = "";
  }

  function handle(ev) {
    switch (ev.type) {
      case "conversation":
        convId = ev.id; store.set("hw.chat.conv", convId);
        break;
      case "delta":
        if (!streamBubble) {
          streamBubble = h("div", { class: "msg assistant streaming" }, h("div", { class: "bubble" }));
          list.append(streamBubble);
        }
        streamText += ev.text;
        streamBubble.firstChild.textContent = streamText;
        scroll();
        break;
      case "text":
        finishStream();
        addAssistant(ev.text);
        break;
      case "tool":
        finishStream();
        addTool(ev);
        break;
      case "tool_result": {
        const line = tools[ev.id];
        if (line) { line.classList.add(ev.is_error ? "failed" : "done"); line.firstChild.textContent = ev.is_error ? "✕" : "✓"; if (ev.is_error) line.title = ev.preview; }
        break;
      }
      case "permission":
        finishStream();
        addPermission(ev);
        break;
      case "error":
        finishStream();
        addError(ev.message);
        break;
      case "done":
        if (ev.is_error) addError("The turn ended with an error.");
        break;
    }
  }

  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
  sendBtn.onclick = send;

  // restore open state (?chat=open or ?chat=<conversation id> also opens it)
  const qp = new URLSearchParams(location.search).get("chat");
  if (qp && qp !== "open") convId = qp;
  if (qp || store.get("hw.chat.open") === "1") open({});
  api("/api/chat/status").then((s) => {
    if (!s.cli) { topBtn.title = "Claude Code CLI not found - install it to use the coach chat"; }
  }).catch(() => {});

  HW.chat = { open, close };
})();
