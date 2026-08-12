/* Orchestra — no framework, no build step. Plain DOM so anyone who clones the
   repo can edit this file and hit refresh. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const state = {
  config: null,
  providers: {},
  models: [],
  agents: [],
  strips: new Map(),
  history: [],
  chosen: [],
  abort: null,
};

/* ------------------------------------------------------------- plumbing */

function el(tag, props = {}, kids = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else n.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) {
    if (kid) n.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  }
  return n;
}

/* Icons are drawn from one 16px grid at a single stroke weight. */
function icon(name, size = 14) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.5");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function stamp(kind, label, pressed = false) {
  return el("span", { class: `stamp ${kind}${pressed ? " press" : ""}` }, [label]);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/* EventSource cannot POST, so SSE is parsed by hand. */
async function stream(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error((await res.text()) || `Stream failed (${res.status})`);

  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop() ?? "";
    for (const block of blocks) {
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* partial frame */ }
      }
    }
  }
}

function say(target, message, kind = "") {
  const host = typeof target === "string" ? $(target) : target;
  host.innerHTML = "";
  if (message) host.appendChild(el("div", { class: `note-strip ${kind}` }, [message]));
}

const bytes = (n) => {
  if (n === null || n === undefined) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let v = n, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
};

const slot = (v) => {
  if (!v) return null;
  const [provider, ...rest] = v.split("::");
  return { provider, model: rest.join("::") };
};

/* --------------------------------------------------------------- desks */

$$(".desk-nav button").forEach((b) => {
  b.addEventListener("click", () => {
    $$(".desk-nav button").forEach((o) => o.setAttribute("aria-current", o === b ? "page" : "false"));
    $$(".desk").forEach((d) => { d.hidden = d.id !== `desk-${b.dataset.desk}`; });
    if (b.dataset.desk === "models") loadInstalled();
  });
});

$$(".tabs button").forEach((b) => {
  b.addEventListener("click", () => {
    $$(".tabs button").forEach((o) => o.setAttribute("aria-selected", String(o === b)));
    for (const t of ["installed", "pull", "router", "hosted"]) {
      $(`#tab-${t}`).hidden = t !== b.dataset.tab;
    }
    if (b.dataset.tab === "installed") loadInstalled();
    if (b.dataset.tab === "router") loadRouter();
    if (b.dataset.tab === "hosted") renderHosted();
  });
});

/* -------------------------------------------------------------- models */

function fillModels(select, current) {
  select.innerHTML = "";
  if (!state.models.length) {
    select.appendChild(el("option", { value: "", text: "No models — connect a provider first" }));
    return;
  }
  select.appendChild(el("option", { value: "", text: "Choose a model…" }));

  const groups = new Map();
  for (const m of state.models) {
    if (!groups.has(m.provider)) groups.set(m.provider, []);
    groups.get(m.provider).push(m);
  }
  for (const [pid, list] of groups) {
    const label = state.providers[pid]?.label || pid;
    const g = el("optgroup", { label: list[0].local ? `${label} — on this machine` : label });
    for (const m of list) {
      g.appendChild(el("option", {
        value: `${m.provider}::${m.id}`,
        text: m.detail ? `${m.label} · ${m.detail}` : m.label,
      }));
    }
    select.appendChild(g);
  }
  select.value = current && state.models.some((m) => `${m.provider}::${m.id}` === current) ? current : "";
}

async function loadModels() {
  state.models = (await api("/api/models")).models;
  const o = state.config.orchestrator || {};
  fillModels($("#chief"), o.provider && o.model ? `${o.provider}::${o.model}` : "");
  markPosting();
  renderAgents();
}

function markPosting() {
  const s = slot($("#chief").value);
  const el_ = $("#posting");
  if (!s) { el_.textContent = "no controlling agent assigned"; return; }
  const local = state.models.find((m) => m.provider === s.provider && m.id === s.model)?.local;
  el_.textContent = `${s.model} · ${local ? "interior" : "crosses the border"}`;
}

$("#chief").addEventListener("change", async () => {
  const s = slot($("#chief").value);
  markPosting();
  state.config = await api("/api/config", {
    method: "PATCH",
    body: { orchestrator: s || { provider: null, model: null } },
  });
});

/* ----------------------------------------------------------- providers */

const PROVIDER_FIELDS = {
  ollama: [{ key: "host", label: "Server address", type: "text", note: "Ollama must be running. Start it with `ollama serve`, or open the Ollama app." }],
  anthropic: [{ key: "api_key", label: "API key", type: "password", secret: true, ph: "sk-ant-…" }],
  openrouter: [{ key: "api_key", label: "API key", type: "password", secret: true, ph: "sk-or-v1-…", note: "One key reaches several hundred hosted models. Star the ones you want in Models → OpenRouter." }],
  openai_compat: [
    { key: "base_url", label: "Base URL", type: "text", ph: "https://api.openai.com/v1", note: "Any endpoint speaking /chat/completions — LM Studio, vLLM, Groq, together.ai, OpenAI." },
    { key: "api_key", label: "API key (local servers often need none)", type: "password", secret: true },
  ],
};

function renderProviders() {
  const host = $("#providerCards");
  host.innerHTML = "";

  for (const [id, p] of Object.entries(state.providers)) {
    const cfg = state.config.providers[id] || {};
    const env = cfg._env_managed || [];
    const st = p.status || {};
    const kind = { ok: "cleared", not_configured: "void", unreachable: "refused", error: "refused" }[st.state] || "void";
    const word = { ok: "open", not_configured: "not set up", unreachable: "unreachable", error: "error" }[st.state] || st.state;

    const fields = (PROVIDER_FIELDS[id] || []).map((f) => {
      const managed = env.includes(f.key);
      return el("label", { class: "field" }, [
        el("span", { class: "field-label", text: managed ? `${f.label} — from the environment` : f.label }),
        el("input", {
          type: f.type,
          id: `cfg-${id}-${f.key}`,
          value: cfg[f.key] || "",
          placeholder: f.ph || "",
          disabled: managed,
        }),
        (managed || f.note || f.secret)
          ? el("span", {
              class: "note",
              text: managed
                ? "Supplied by your environment, so it is not editable here and never written to disk."
                : f.secret
                ? "Held on this machine only. Leave the masked value to keep the current key; clear the box to remove it."
                : f.note,
            })
          : null,
      ]);
    });

    host.appendChild(el("div", { class: "panel" }, [
      el("div", { class: "panel-head" }, [
        el("h3", { text: p.label }),
        stamp(kind, word),
        el("span", { class: "spacer" }),
        p.capabilities?.downloadable ? el("span", { class: "chan", text: "downloads" }) : null,
        p.capabilities?.server_side_research ? el("span", { class: "chan", text: "server-side research" }) : null,
      ]),
      el("div", { class: "panel-body" }, [
        el("p", { class: "prose", text: st.detail || "" }),
        ...fields,
        el("div", { class: "row" }, [
          el("button", { class: "btn line sm", text: "Save and test", onclick: () => saveProvider(id) }),
        ]),
      ]),
    ]));
  }

  const lanes = $("#lanes");
  lanes.innerHTML = "";
  for (const [id, p] of Object.entries(state.providers)) {
    lanes.appendChild(el("label", { class: "field", style: "min-width:170px" }, [
      el("span", { class: "field-label", text: p.label }),
      el("input", { type: "number", min: "1", max: "32", id: `lane-${id}`, value: String(state.config.concurrency?.[id] ?? 4) }),
    ]));
  }
}

async function saveProvider(id) {
  const patch = {};
  for (const f of PROVIDER_FIELDS[id] || []) {
    const input = $(`#cfg-${id}-${f.key}`);
    if (input && !input.disabled) patch[f.key] = input.value.trim();
  }
  state.config = await api("/api/config", { method: "PATCH", body: { providers: { [id]: patch } } });
  await loadProviders();
  await loadModels();
}

async function loadProviders() {
  state.providers = (await api("/api/providers")).providers;
  renderProviders();
}

$("#saveLanes").addEventListener("click", async () => {
  const concurrency = {};
  for (const id of Object.keys(state.providers)) concurrency[id] = Number($(`#lane-${id}`).value) || 4;
  state.config = await api("/api/config", { method: "PATCH", body: { concurrency } });
  flash($("#saveLanes"), "Saved");
});

function flash(button, word) {
  const old = button.textContent;
  button.textContent = word;
  setTimeout(() => { button.textContent = old; }, 1400);
}

/* ---------------------------------------------------------- border policy */

const ITEMS = {
  email: "Addresses", phone: "Phone numbers", card: "Card numbers",
  ssn: "Social Security", secret: "Keys and tokens", ip: "IP addresses",
  path: "Home paths", iban: "Bank accounts",
};

const POLICY_NOTE = {
  redact: "Declarable values are substituted with placeholders such as [EMAIL_1] before the text crosses. Local models still receive the real values, and the real values are restored into the finding here on this machine.",
  strict: "Nothing declarable crosses at all. Affected steps are turned back and moved onto a local model; with no local model installed the step fails rather than crossing.",
  off: "No inspection and no substitution. Everything is sent to whichever model an agent holds.",
};

let chosenItems = new Set();

function renderPolicy() {
  const p = state.config.privacy || {};
  $("#policyMode").value = p.mode || "redact";
  $("#policyNote").textContent = POLICY_NOTE[p.mode || "redact"];

  chosenItems = new Set(Array.isArray(p.categories) && p.categories.length ? p.categories : Object.keys(ITEMS));
  const host = $("#policyItems");
  host.innerHTML = "";
  for (const [key, label] of Object.entries(ITEMS)) {
    const on = chosenItems.has(key);
    host.appendChild(el("button", {
      class: "chip", text: label, "aria-pressed": String(on),
      onclick: (e) => {
        const now = !chosenItems.has(key);
        if (now) chosenItems.add(key); else chosenItems.delete(key);
        e.currentTarget.setAttribute("aria-pressed", String(now));
      },
    }));
  }
}

$("#policyMode").addEventListener("change", () => {
  $("#policyNote").textContent = POLICY_NOTE[$("#policyMode").value] || "";
});

$("#savePolicy").addEventListener("click", async () => {
  state.config = await api("/api/config", {
    method: "PATCH",
    body: { privacy: { mode: $("#policyMode").value, categories: [...chosenItems] } },
  });
  flash($("#savePolicy"), "Saved");
});

/* --------------------------------------------------------------- agents */

function renderAgents() {
  const host = $("#agentList");
  host.innerHTML = "";
  if (!state.agents.length) host.appendChild(el("p", { class: "empty", text: "No agents yet." }));

  const unset = state.agents.filter((a) => !a.ready).length;
  say("#agentAlert", unset
    ? `${unset} agent${unset === 1 ? " has" : "s have"} no model yet. Starters ship without one because nobody knows what models you hold until a provider is connected. An agent without a model is hidden from the controlling agent, so work is never routed somewhere that cannot run it.`
    : "");

  for (const a of state.agents) {
    const caps = a.capabilities || {};
    host.appendChild(el("div", { class: "entry" }, [
      el("span", { class: "id", text: a.name || a.id }),
      a.ready ? el("span", { class: "chan", text: a.model.model }) : stamp("void", "no model"),
      caps.local_only ? el("span", { class: "chan green", text: "interior only" }) : null,
      caps.research ? el("span", { class: "chan", text: "reads web" }) : null,
      el("span", { class: "spacer" }),
      el("button", { class: "btn line sm", text: "Edit", onclick: () => openAgent(a) }),
      el("button", {
        class: "btn refuse sm", text: "Delete",
        onclick: async () => {
          if (!confirm(`Delete the agent "${a.name || a.id}"?`)) return;
          await api(`/api/agents/${a.id}`, { method: "DELETE" });
          await loadAgents();
        },
      }),
      el("span", { class: "desc", text: a.role || "" }),
    ]));
  }
  renderRoster();
}

let editing = null;

function openAgent(a) {
  editing = a ? a.id : null;
  $("#dlgTitle").textContent = a ? `Edit ${a.name || a.id}` : "New agent";
  say("#dlgAlert", "");
  $("#fName").value = a?.name || "";
  $("#fId").value = a?.id || "";
  $("#fId").disabled = Boolean(a);
  $("#fRole").value = a?.role || "";
  $("#fSoul").value = a?.soul || "";
  $("#fTemp").value = a?.temperature ?? "";
  $("#fResearch").checked = Boolean(a?.capabilities?.research);
  $("#fLocal").checked = Boolean(a?.capabilities?.local_only);
  fillModels($("#fModel"), a?.model?.provider ? `${a.model.provider}::${a.model.model}` : "");
  $("#agentDlg").showModal();
}

$("#newAgent").addEventListener("click", () => openAgent(null));

$("#fName").addEventListener("input", () => {
  if (editing) return;
  $("#fId").value = $("#fName").value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
});

$("#agentDlg").addEventListener("close", async () => {
  if ($("#agentDlg").returnValue !== "save") return;
  const body = {
    name: $("#fName").value.trim(),
    role: $("#fRole").value.trim(),
    soul: $("#fSoul").value.trim(),
    model: slot($("#fModel").value) || { provider: "", model: "" },
    capabilities: { research: $("#fResearch").checked, local_only: $("#fLocal").checked },
    temperature: $("#fTemp").value === "" ? null : Number($("#fTemp").value),
  };
  const id = editing || $("#fId").value.trim();
  try {
    await api(`/api/agents/${id}`, { method: "PUT", body });
    await loadAgents();
  } catch (err) {
    openAgent({ ...body, id });
    say("#dlgAlert", err.message, "bad");
  }
});

async function loadAgents() {
  state.agents = (await api("/api/agents")).agents;
  renderAgents();
}

function renderRoster() {
  const mode = $("#mode").value;
  $("#rosterWrap").hidden = mode === "direct";
  if (mode === "direct") return;

  $("#rosterLabel").textContent = mode === "manual"
    ? "Route, in order. Click to add a step; click again to drop it."
    : "Agents the controlling agent may call on. All ready agents unless you narrow it.";

  const host = $("#roster");
  host.innerHTML = "";
  const ready = state.agents.filter((a) => a.ready);
  if (!ready.length) {
    host.appendChild(el("span", { class: "empty", text: "No agent holds a model yet — assign one under Agents." }));
    return;
  }
  for (const a of ready) {
    const i = state.chosen.indexOf(a.id);
    const on = i !== -1;
    host.appendChild(el("button", {
      class: "chip",
      "aria-pressed": String(on),
      text: mode === "manual" && on ? `${i + 1} · ${a.name}` : a.name,
      title: `${a.role} — ${a.model.model}`,
      onclick: () => {
        if (on) state.chosen.splice(i, 1); else state.chosen.push(a.id);
        renderRoster();
      },
    }));
  }
}

$("#mode").addEventListener("change", () => {
  state.chosen = [];
  renderRoster();
  resetHall();
});

/* ------------------------------------------------------- inspection hall */

function resetHall() {
  state.strips.clear();
  $("#interior").innerHTML = "";
  $("#exterior").innerHTML = "";
  $("#hall").hidden = true;
  $("#slip").hidden = true;
  $("#exteriorLabel").hidden = true;
  $("#borderNote").textContent = "nothing has crossed";
  say("#alert", "");
  tallyHall();
}

function stripFor(id) {
  let s = state.strips.get(id);
  if (s) return s;

  const tick = el("span", { class: "tick" });
  const who = el("span", { class: "who", text: id });
  const badge = el("span", {});
  const head = el("div", { class: "strip-head" }, [tick, who, el("span", { class: "spacer" }), badge]);
  const meta = el("div", { class: "meta" });
  const task = el("div", { class: "task" });
  const out = el("div", { class: "out" });
  const card = el("div", { class: "strip" }, [head, meta, task, out]);

  $("#interior").appendChild(card);
  s = { card, tick, who, badge, meta, task, out, side: "interior", status: "pending" };
  state.strips.set(id, s);
  $("#hall").hidden = false;
  return s;
}

/* Move a strip across the border rule. This is the whole point of the hall:
   where a node sits is where it actually ran. */
function place(s, side) {
  const bay = $(side === "exterior" ? "#exterior" : "#interior");
  if (s.card.parentElement !== bay) bay.appendChild(s.card);
  s.side = side;
  s.card.classList.toggle("exterior", side === "exterior");
  if (side === "exterior") $("#exteriorLabel").hidden = false;
  tallyHall();
}

function tallyHall() {
  const all = [...state.strips.values()];
  const inside = all.filter((s) => s.side === "interior").length;
  const outside = all.length - inside;
  const live = all.filter((s) => s.status === "working").length;
  const queued = all.filter((s) => s.status === "queued").length;

  $("#interiorCount").textContent = inside ? `${inside}` : "";
  $("#exteriorCount").textContent = outside ? `${outside}` : "";
  $("#borderNote").textContent = outside
    ? `${outside} of ${all.length} crossed`
    : all.length ? "nothing has crossed" : "nothing has crossed";

  const bits = [];
  if (live) bits.push(`${live} working`);
  if (queued) bits.push(`${queued} held — lane full`);
  const done = all.filter((s) => s.status === "done").length;
  const failed = all.filter((s) => s.status === "failed").length;
  if (done) bits.push(`${done} cleared`);
  if (failed) bits.push(`${failed} failed`);
  $("#hallCount").textContent = bits.join(" · ");
}

function isLocalProvider(pid) {
  // The server is authoritative; this only decides which side to draw on
  // before the ledger arrives.
  return pid === "ollama" || state.models.some((m) => m.provider === pid && m.local);
}

/* ------------------------------------------------------------ the slip */

function renderSlip(summary, mapping) {
  const rows = $("#slipRows");
  rows.innerHTML = "";

  const remote = summary.remote_calls || 0;
  const local = summary.local_calls || 0;
  const held = summary.protected_values || 0;

  $("#slip").hidden = false;
  $("#verdict").textContent = remote === 0
    ? "nothing to declare"
    : held > 0 ? `${held} item${held === 1 ? "" : "s"} withheld` : "goods declared";

  for (const e of summary.entries || []) {
    const counts = Object.entries(e.redacted || {});
    const channel = e.blocked
      ? el("span", { class: "decl void" }, ["turned back"])
      : e.destination === "local"
      ? el("span", { class: "decl green" }, ["green"])
      : el("span", { class: "decl red" }, ["red"]);
    rows.appendChild(el("tr", {}, [
      el("td", { class: "route" }, [`${e.provider} · ${e.model}`]),
      el("td", {}, [channel]),
      el("td", { class: "qty" }, [
        e.blocked ? "—"
          : e.destination === "local" ? "stayed"
          : counts.length
          ? `${counts.reduce((a, [, n]) => a + n, 0)} withheld · ${e.chars.toLocaleString()} chars`
          : `${e.chars.toLocaleString()} chars`,
      ]),
    ]));
  }

  const redacted = Object.entries(summary.redacted || {});
  $("#slipNote").textContent = remote === 0
    ? `Every call in this run stayed on this machine. ${local} call${local === 1 ? "" : "s"}, nothing crossed the border.`
    : redacted.length
    ? `Withheld at the checkpoint: ${redacted.map(([k, n]) => `${n} × ${(ITEMS[k] || k).toLowerCase()}`).join(", ")}. The real values were restored into the finding above, here, on this machine.`
    : "No declarable pattern was found in what crossed.";

  const parts = [
    "ORC", (summary.mode || "off").toUpperCase(),
    `LOCAL${String(local).padStart(3, "0")}`,
    `REMOTE${String(remote).padStart(3, "0")}`,
    `HELD${String(held).padStart(3, "0")}`,
  ];
  const line = parts.join("<");
  $("#mrz").textContent = `${line}${"<".repeat(Math.max(4, 58 - line.length))}`;
}

/* The finding streams in with placeholders, because that is literally what the
   hosted model produced. Restoring happens here — the values never left. */
function restore(mapping) {
  if (!mapping || !Object.keys(mapping).length) return;
  const body = $$("#transcript .msg.answer .body").pop();
  if (!body) return;
  body.textContent = body.textContent.replace(/\[([A-Z]+)_(\d+)\]/g, (t) => mapping[t] ?? t);
}

/* --------------------------------------------------------------- events */

function onEvent(ev, answer) {
  switch (ev.type) {
    case "plan":
      for (const t of ev.plan.tasks) {
        const s = stripFor(t.id);
        s.task.textContent = t.instruction;
      }
      tallyHall();
      break;

    case "node_waiting": {
      const s = stripFor(ev.id);
      s.status = "waiting";
      s.tick.className = "tick wait";
      s.meta.textContent = `waiting on ${ev.depends_on.join(", ")}`;
      tallyHall();
      break;
    }

    case "node_queued": {
      const s = stripFor(ev.id);
      s.status = "queued";
      s.tick.className = "tick wait";
      s.meta.textContent = `held — ${ev.lane} lane full (limit ${ev.limit})`;
      s.badge.innerHTML = "";
      s.badge.appendChild(stamp("transit", "held"));
      tallyHall();
      break;
    }

    case "node_start": {
      const s = stripFor(ev.id);
      const outside = !isLocalProvider(ev.provider);
      s.status = "working";
      s.who.textContent = ev.agent_name;
      s.meta.textContent = `${ev.model} · ${ev.provider}`;
      s.tick.className = `tick live ${outside ? "out" : "on"}`;
      s.card.className = `strip working${outside ? " exterior" : ""}`;
      s.badge.innerHTML = "";
      s.badge.appendChild(stamp(outside ? "declared" : "cleared", outside ? "crossing" : "interior", true));
      s.started = ev.started_at;
      place(s, outside ? "exterior" : "interior");
      break;
    }

    case "node_token": {
      const s = stripFor(ev.id);
      s.out.textContent += ev.text;
      s.out.scrollTop = s.out.scrollHeight;
      break;
    }

    case "node_tool": {
      const s = stripFor(ev.id);
      s.meta.textContent += ` · ${ev.name || "tool"}`;
      break;
    }

    case "node_rerouted": {
      const s = stripFor(ev.id);
      s.meta.textContent = `turned back — ${ev.categories.join(", ")} may not cross. Moved to ${ev.to}.`;
      s.badge.innerHTML = "";
      s.badge.appendChild(stamp("refused", "turned back", true));
      place(s, "interior");
      break;
    }

    case "node_done": {
      const s = stripFor(ev.id);
      s.status = "done";
      s.card.className = `strip${s.side === "exterior" ? " exterior" : ""}`;
      s.tick.className = `tick ${s.side === "exterior" ? "out" : "on"}`;
      s.badge.innerHTML = "";
      s.badge.appendChild(stamp("cleared", `${(ev.ended_at - ev.started_at).toFixed(1)}s`, true));
      tallyHall();
      break;
    }

    case "node_error": {
      const s = stripFor(ev.id);
      s.status = "failed";
      s.card.className = `strip${s.side === "exterior" ? " exterior" : ""}`;
      s.tick.className = "tick";
      s.badge.innerHTML = "";
      s.badge.appendChild(stamp("refused", "failed", true));
      s.out.appendChild(el("div", { class: "fail", text: ev.message }));
      tallyHall();
      break;
    }

    case "plan_failed":
      say("#alert", `The controlling agent could not produce a usable plan (${ev.message}). Answering directly instead.`, "warn");
      break;

    case "synthesis_start":
      answer.label.textContent = "Finding";
      break;

    case "token":
      answer.body.textContent += ev.text;
      break;

    case "done":
      if (ev.privacy) renderSlip(ev.privacy, ev.restore);
      if (ev.restore) restore(ev.restore);
      break;

    case "error":
      say("#alert", ev.message, "bad");
      break;
  }
}

function addMessage(kind, text) {
  const host = $("#transcript");
  if (host.querySelector(".empty")) host.innerHTML = "";
  const label = el("span", { class: "field-label", text: kind === "you" ? "Request" : "Finding" });
  const body = el("div", { class: "body", text: text || "" });
  host.appendChild(el("div", { class: `msg ${kind}` }, [label, body]));
  return { label, body };
}

async function present() {
  const text = $("#request").value.trim();
  if (!text) return;

  const s = slot($("#chief").value);
  if (!s) { say("#alert", "Assign a controlling agent before presenting a request.", "bad"); return; }

  const mode = $("#mode").value;
  if (mode === "manual" && !state.chosen.length) {
    say("#alert", "Choose at least one step for the route.", "bad");
    return;
  }

  $("#request").value = "";
  addMessage("you", text);
  resetHall();
  const answer = addMessage("answer", "");
  answer.label.textContent = mode === "direct" ? "Finding" : "Planning";

  state.abort = new AbortController();
  $("#send").disabled = true;
  $("#halt").hidden = false;

  try {
    if (mode === "direct") {
      state.history.push({ role: "user", content: text });
      await stream("/api/chat",
        { provider: s.provider, model: s.model, messages: state.history },
        (ev) => {
          if (ev.type === "token") answer.body.textContent += ev.text;
          else if (ev.type === "error") say("#alert", ev.message, "bad");
        }, state.abort.signal);
      state.history.push({ role: "assistant", content: answer.body.textContent });
    } else {
      await stream("/api/run",
        { message: text, provider: s.provider, model: s.model, mode, agents: state.chosen },
        (ev) => onEvent(ev, answer), state.abort.signal);
    }
  } catch (err) {
    if (err.name !== "AbortError") say("#alert", err.message, "bad");
  } finally {
    $("#send").disabled = false;
    $("#halt").hidden = true;
    state.abort = null;
    if (!answer.body.textContent) answer.label.textContent = "Finding";
  }
}

$("#send").addEventListener("click", present);
$("#halt").addEventListener("click", () => state.abort?.abort());
$("#request").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) present();
});

/* -------------------------------------------------------- local models */

async function loadInstalled() {
  const data = await api("/api/local/models");
  const host = $("#installedList");
  host.innerHTML = "";

  if (!data.available) {
    say("#installedAlert", data.status.detail, "bad");
    host.appendChild(el("p", { class: "empty", text: "Local models appear here once Ollama is running." }));
    return;
  }
  say("#installedAlert", "");
  if (!data.models.length) {
    host.appendChild(el("p", { class: "empty", text: "Nothing on disk yet. Pull a model from the Pull tab." }));
    return;
  }

  for (const m of data.models) {
    host.appendChild(el("div", { class: "entry" }, [
      el("span", { class: "id", text: m.id }),
      m.loaded ? el("span", { class: "chan green", text: "in memory" }) : null,
      el("span", { class: "spacer" }),
      el("span", { class: "sub", text: [m.detail, bytes(m.size_bytes)].filter(Boolean).join(" · ") }),
      el("button", {
        class: "btn refuse sm",
        onclick: async () => {
          if (!confirm(`Delete ${m.id} from disk?`)) return;
          await api(`/api/local/models/${encodeURIComponent(m.id)}`, { method: "DELETE" });
          await loadInstalled();
          await loadModels();
        },
      }, [icon("trash", 13), " Delete"]),
    ]));
  }
}

async function loadSuggested() {
  let list = [];
  try { list = (await (await fetch("/static/catalog.json")).json()).models || []; } catch { /* offline */ }
  const host = $("#suggested");
  host.innerHTML = "";
  for (const m of list) {
    host.appendChild(el("div", { class: "entry" }, [
      el("div", { class: "grow" }, [
        el("div", { class: "id", text: m.name }),
        el("div", { class: "sub", text: m.use }),
      ]),
      el("span", { class: "sub", text: `${m.size} · ${m.ram}` }),
      el("button", {
        class: "btn line sm", text: "Pull",
        onclick: () => { $("#pullName").value = m.name; doPull(); },
      }),
    ]));
  }
}

async function doPull() {
  const name = $("#pullName").value.trim();
  if (!name) return;
  const host = $("#pullState");
  host.innerHTML = "";
  const label = el("p", { class: "prose", text: `Starting ${name}…` });
  const fill = el("i");
  host.append(label, el("div", { class: "gauge" }, [fill]));

  $("#pullGo").disabled = true;
  try {
    await stream("/api/local/pull", { name }, (ev) => {
      if (ev.type === "progress") {
        if (ev.total) {
          const pct = Math.min(100, Math.round((ev.completed / ev.total) * 100));
          fill.style.transform = `scaleX(${pct / 100})`;
          label.textContent = `${ev.status || "downloading"} — ${pct}% of ${bytes(ev.total)}`;
        } else label.textContent = ev.status || "working…";
      } else if (ev.type === "done") {
        fill.style.transform = "scaleX(1)";
        label.textContent = `${ev.name} is on disk.`;
        loadInstalled(); loadModels();
      } else if (ev.type === "error") say(host, ev.message, "bad");
    });
  } catch (err) { say(host, err.message, "bad"); }
  finally { $("#pullGo").disabled = false; }
}

$("#pullGo").addEventListener("click", doPull);
$("#pullName").addEventListener("keydown", (e) => { if (e.key === "Enter") doPull(); });

/* ---------------------------------------------------------- OpenRouter */

let routerTimer = null;

async function loadRouter() {
  const q = $("#routerQ").value.trim();
  const free = $("#fFree").getAttribute("aria-pressed") === "true";
  const vision = $("#fVision").getAttribute("aria-pressed") === "true";

  const host = $("#routerList");
  let data;
  try {
    data = await api(`/api/openrouter/models?q=${encodeURIComponent(q)}&free=${free}&vision=${vision}&limit=60`);
  } catch (err) { say("#routerAlert", err.message, "bad"); return; }

  say("#routerAlert", data.configured ? "" : "Browsing works without a key. Add an OpenRouter key under Settings before an agent can actually use one of these.", "warn");
  $("#routerCount").textContent = `${data.matched} of ${data.total}`;

  host.innerHTML = "";
  if (!data.models.length) {
    host.appendChild(el("p", { class: "empty", text: "Nothing matches. Try a vendor name like anthropic, or clear the filters." }));
    return;
  }

  for (const m of data.models) {
    const price = m.free ? "free" : `$${m.prompt_price}/M in · $${m.completion_price}/M out`;
    host.appendChild(el("div", { class: "entry" }, [
      el("button", {
        class: "star", "aria-pressed": String(m.starred),
        "aria-label": m.starred ? `Unstar ${m.id}` : `Star ${m.id}`,
        onclick: () => toggleStar(m.id, !m.starred),
      }, [icon("star", 15)]),
      el("div", { class: "grow" }, [
        el("div", { class: "id", text: m.id }),
        el("div", { class: "sub", text: `${m.name} · ${(m.context || 0).toLocaleString()} ctx` }),
      ]),
      m.free ? el("span", { class: "chan green", text: "free" }) : null,
      m.input_modalities?.includes("image") ? el("span", { class: "chan", text: "vision" }) : null,
      el("span", { class: "sub", text: price }),
      m.description ? el("span", { class: "desc", text: m.description.slice(0, 190) }) : null,
    ]));
  }
}

async function toggleStar(id, starred) {
  await api("/api/openrouter/starred", { method: "POST", body: { id, starred } });
  await loadRouter();
  await loadModels();
}

$("#routerQ").addEventListener("input", () => {
  clearTimeout(routerTimer);
  routerTimer = setTimeout(loadRouter, 220);
});
for (const id of ["#fFree", "#fVision"]) {
  $(id).addEventListener("click", (e) => {
    const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
    e.currentTarget.setAttribute("aria-pressed", String(on));
    loadRouter();
  });
}
$("#routerAddGo").addEventListener("click", async () => {
  const id = $("#routerAdd").value.trim();
  if (!id) return;
  try {
    await toggleStar(id, true);
    $("#routerAdd").value = "";
    say("#routerAlert", "");
  } catch (err) { say("#routerAlert", err.message, "bad"); }
});

function renderHosted() {
  const host = $("#hostedList");
  host.innerHTML = "";
  const hosted = state.models.filter((m) => !m.local);
  if (!hosted.length) {
    host.appendChild(el("p", { class: "empty", text: "No hosted models yet. Add a key under Settings, or star models under OpenRouter." }));
    return;
  }
  for (const m of hosted) {
    host.appendChild(el("div", { class: "entry" }, [
      el("span", { class: "id", text: m.label }),
      el("span", { class: "spacer" }),
      el("span", { class: "sub", text: state.providers[m.provider]?.label || m.provider }),
      el("span", { class: "chan red", text: "crosses the border" }),
    ]));
  }
}

/* ----------------------------------------------------------------- boot */

async function boot() {
  try { $("#homePath").textContent = (await api("/api/health")).home; } catch { /* cosmetic */ }
  state.config = await api("/api/config");
  renderPolicy();
  await loadProviders();
  await loadModels();
  await loadAgents();
  await loadSuggested();
  renderRoster();

  if (!Object.values(state.providers).some((p) => p.status?.state === "ok")) {
    say("#alert", "No provider is connected yet. Open Settings to add a key, or point at a local Ollama server.", "warn");
  }
}

boot();
