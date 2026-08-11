/* Orchestra UI. No build step, no framework — plain DOM so anyone who clones
   the repo can edit it with a text editor and hit refresh. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  config: null,
  providers: {},
  models: [],
  agents: [],
  catalog: [],
  transcript: [],
  nodes: new Map(),
  controller: null,
};

/* ---------------------------------------------------------------- helpers */

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) throw new Error(data.detail || `Request failed (${resp.status})`);
  return data;
}

/* Reads a Server-Sent Events response from a POST. EventSource cannot POST,
   so the stream is parsed by hand. */
async function streamSSE(path, body, onEvent, signal) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail || `Stream failed (${resp.status})`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      for (const line of block.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()));
        } catch {
          /* a partial or malformed frame is not worth killing the run over */
        }
      }
    }
  }
}

function notice(container, message, kind = "") {
  const host = typeof container === "string" ? $(container) : container;
  host.innerHTML = "";
  if (message) host.appendChild(el("div", { class: `notice ${kind}`, text: message }));
}

function humanBytes(bytes) {
  if (!bytes && bytes !== 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

function modelLabel(slot) {
  if (!slot || !slot.provider || !slot.model) return "no model";
  return `${slot.model}`;
}

/* ---------------------------------------------------------------- routing */

$$("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    $$("nav button").forEach((b) => b.classList.toggle("active", b === button));
    $$(".view").forEach((view) => {
      view.hidden = view.id !== `view-${button.dataset.view}`;
    });
    if (button.dataset.view === "models") refreshInstalled();
  });
});

$$(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".tabs button").forEach((b) => b.classList.toggle("active", b === button));
    for (const tab of ["installed", "browse", "cloud"]) {
      $(`#tab-${tab}`).hidden = tab !== button.dataset.tab;
    }
    if (button.dataset.tab === "installed") refreshInstalled();
    if (button.dataset.tab === "cloud") renderCloud();
  });
});

/* ------------------------------------------------------------- model list */

function chatModels() {
  return state.models;
}

function fillModelSelect(select, selected) {
  select.innerHTML = "";
  const models = chatModels();

  if (!models.length) {
    select.appendChild(el("option", { value: "", text: "No models — connect a provider first" }));
    select.value = "";
    return;
  }

  select.appendChild(el("option", { value: "", text: "Choose a model…" }));

  const groups = new Map();
  for (const model of models) {
    if (!groups.has(model.provider)) groups.set(model.provider, []);
    groups.get(model.provider).push(model);
  }

  for (const [providerId, entries] of groups) {
    const label = state.providers[providerId]?.label || providerId;
    const group = el("optgroup", { label: `${label}${entries[0].local ? " — on this machine" : ""}` });
    for (const model of entries) {
      group.appendChild(
        el("option", {
          value: `${model.provider}::${model.id}`,
          text: model.detail ? `${model.label} (${model.detail})` : model.label,
        })
      );
    }
    select.appendChild(group);
  }

  select.value = selected && models.some((m) => `${m.provider}::${m.id}` === selected) ? selected : "";
}

function parseSlot(value) {
  if (!value) return null;
  const [provider, ...rest] = value.split("::");
  return { provider, model: rest.join("::") };
}

/* ------------------------------------------------------------- providers */

function renderProviders() {
  const host = $("#providerCards");
  host.innerHTML = "";

  for (const [id, provider] of Object.entries(state.providers)) {
    const settings = state.config.providers[id] || {};
    const envManaged = settings._env_managed || [];
    const status = provider.status || {};

    const fields = [];

    if (id === "ollama") {
      fields.push(
        el("label", { class: "field" }, [
          el("span", { text: "Server address" }),
          el("input", { type: "text", id: "cfg-ollama-host", value: settings.host || "" }),
          el("span", {
            class: "hint",
            text: "Ollama must be running. Start it with `ollama serve`, or open the Ollama app.",
          }),
        ])
      );
    }

    if (id === "anthropic") {
      const managed = envManaged.includes("api_key");
      fields.push(
        el("label", { class: "field" }, [
          el("span", { text: managed ? "API key — set by ANTHROPIC_API_KEY" : "API key" }),
          el("input", {
            type: "password",
            id: "cfg-anthropic-key",
            value: settings.api_key || "",
            placeholder: "sk-ant-…",
            disabled: managed,
          }),
          el("span", {
            class: "hint",
            text: managed
              ? "Coming from your environment, so it is not editable here and is never written to disk."
              : "Stored on this machine only. Leave the masked value alone to keep the current key; clear the box to remove it.",
          }),
        ])
      );
    }

    if (id === "openai_compat") {
      const managed = envManaged.includes("api_key");
      fields.push(
        el("label", { class: "field" }, [
          el("span", { text: "Base URL" }),
          el("input", {
            type: "text",
            id: "cfg-openai-url",
            value: settings.base_url || "",
            placeholder: "https://openrouter.ai/api/v1",
          }),
          el("span", {
            class: "hint",
            text: "Works with OpenRouter, LM Studio, vLLM, Groq, together.ai, OpenAI — anything speaking /chat/completions.",
          }),
        ]),
        el("label", { class: "field" }, [
          el("span", { text: managed ? "API key — set by OPENAI_API_KEY" : "API key (optional for local servers)" }),
          el("input", {
            type: "password",
            id: "cfg-openai-key",
            value: settings.api_key || "",
            disabled: managed,
          }),
        ])
      );
    }

    const card = el("div", { class: "card" }, [
      el("div", { class: "card-head" }, [
        el("span", { class: `dot ${status.state || ""}` }),
        el("h3", { text: provider.label }),
        el("span", { class: "spacer" }),
        provider.capabilities?.downloadable ? el("span", { class: "badge", text: "downloadable" }) : null,
        provider.capabilities?.server_side_research
          ? el("span", { class: "badge", text: "server-side research" })
          : null,
      ]),
      el("p", { class: "detail", text: status.detail || "" }),
      ...fields,
      el("div", { class: "row" }, [
        el("button", {
          class: "btn small",
          text: "Save & test",
          onclick: () => saveProvider(id),
        }),
      ]),
    ]);
    host.appendChild(card);
  }

  const lanes = $("#laneLimits");
  lanes.innerHTML = "";
  for (const [id, provider] of Object.entries(state.providers)) {
    lanes.appendChild(
      el("label", { class: "field", style: "margin:0;min-width:180px" }, [
        el("span", { text: provider.label }),
        el("input", {
          type: "number",
          min: "1",
          max: "32",
          id: `lane-${id}`,
          value: String(state.config.concurrency?.[id] ?? 4),
        }),
      ])
    );
  }
}

async function saveProvider(id) {
  const patch = { providers: {} };
  if (id === "ollama") patch.providers.ollama = { host: $("#cfg-ollama-host").value.trim() };
  if (id === "anthropic") patch.providers.anthropic = { api_key: $("#cfg-anthropic-key").value.trim() };
  if (id === "openai_compat") {
    patch.providers.openai_compat = {
      base_url: $("#cfg-openai-url").value.trim(),
      api_key: $("#cfg-openai-key").value.trim(),
    };
  }
  state.config = await api("/api/config", { method: "PATCH", body: patch });
  await refreshProviders();
  await refreshModels();
}

$("#saveLanes").addEventListener("click", async () => {
  const concurrency = {};
  for (const id of Object.keys(state.providers)) {
    concurrency[id] = Number($(`#lane-${id}`).value) || 4;
  }
  state.config = await api("/api/config", { method: "PATCH", body: { concurrency } });
  notice("#runNotice", "");
  $("#saveLanes").textContent = "Saved";
  setTimeout(() => ($("#saveLanes").textContent = "Save limits"), 1400);
});

async function refreshProviders() {
  const data = await api("/api/providers");
  state.providers = data.providers;
  renderProviders();
}

async function refreshModels() {
  const data = await api("/api/models");
  state.models = data.models;
  const current = state.config.orchestrator || {};
  fillModelSelect(
    $("#bigAgentModel"),
    current.provider && current.model ? `${current.provider}::${current.model}` : ""
  );
  updateBigAgentLabel();
  renderAgents();
}

function updateBigAgentLabel() {
  const slot = parseSlot($("#bigAgentModel").value);
  $("#bigAgentLabel").textContent = slot ? `big agent: ${slot.model}` : "no big agent selected";
}

$("#bigAgentModel").addEventListener("change", async () => {
  const slot = parseSlot($("#bigAgentModel").value);
  updateBigAgentLabel();
  state.config = await api("/api/config", {
    method: "PATCH",
    body: { orchestrator: slot || { provider: null, model: null } },
  });
});

/* ---------------------------------------------------------------- agents */

function renderAgents() {
  const host = $("#agentList");
  host.innerHTML = "";

  if (!state.agents.length) {
    host.appendChild(el("p", { class: "empty", text: "No agents yet." }));
  }

  const unassigned = state.agents.filter((a) => !a.ready).length;
  notice(
    "#agentsNotice",
    unassigned
      ? `${unassigned} agent${unassigned === 1 ? "" : "s"} still need a model. ` +
        "Starter agents ship without one because nobody knows what models you have until you connect a provider. " +
        "Agents without a model are hidden from the big agent so it never routes work somewhere that cannot run it."
      : ""
  );

  for (const agent of state.agents) {
    host.appendChild(
      el("div", { class: "agent-row" }, [
        el("span", { class: "name", text: agent.name || agent.id }),
        agent.ready
          ? el("span", { class: "badge", text: modelLabel(agent.model) })
          : el("span", { class: "badge warn", text: "needs a model" }),
        agent.capabilities?.research ? el("span", { class: "badge accent", text: "research" }) : null,
        agent.soul ? null : el("span", { class: "badge", text: "no soul" }),
        el("span", { class: "spacer" }),
        el("button", { class: "btn small ghost", text: "Edit", onclick: () => openAgent(agent) }),
        el("button", {
          class: "btn small danger",
          text: "Delete",
          onclick: async () => {
            if (!confirm(`Delete the agent "${agent.name || agent.id}"?`)) return;
            await api(`/api/agents/${agent.id}`, { method: "DELETE" });
            await refreshAgents();
          },
        }),
        el("span", { class: "role", text: agent.role || "" }),
      ])
    );
  }

  renderAgentPicker();
}

let editingId = null;

function openAgent(agent) {
  editingId = agent ? agent.id : null;
  $("#agentDialogTitle").textContent = agent ? `Edit ${agent.name || agent.id}` : "New agent";
  notice("#agentFormError", "");
  $("#fName").value = agent?.name || "";
  $("#fId").value = agent?.id || "";
  $("#fId").disabled = Boolean(agent);
  $("#fRole").value = agent?.role || "";
  $("#fSoul").value = agent?.soul || "";
  $("#fTemp").value = agent?.temperature ?? "";
  $("#fResearch").checked = Boolean(agent?.capabilities?.research);
  fillModelSelect(
    $("#fModel"),
    agent?.model?.provider ? `${agent.model.provider}::${agent.model.model}` : ""
  );
  $("#agentDialog").showModal();
}

$("#newAgent").addEventListener("click", () => openAgent(null));

$("#fName").addEventListener("input", () => {
  // Suggest an id from the name, but only while creating.
  if (editingId) return;
  const suggested = $("#fName").value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  $("#fId").value = suggested;
});

$("#agentDialog").addEventListener("close", async () => {
  if ($("#agentDialog").returnValue !== "save") return;

  const slot = parseSlot($("#fModel").value);
  const body = {
    name: $("#fName").value.trim(),
    role: $("#fRole").value.trim(),
    soul: $("#fSoul").value.trim(),
    model: slot || { provider: "", model: "" },
    capabilities: { research: $("#fResearch").checked },
    temperature: $("#fTemp").value === "" ? null : Number($("#fTemp").value),
  };
  const id = editingId || $("#fId").value.trim();

  try {
    await api(`/api/agents/${id}`, { method: "PUT", body });
    await refreshAgents();
  } catch (error) {
    // Reopen with the message rather than silently losing what was typed.
    openAgent({ ...body, id });
    notice("#agentFormError", error.message, "err");
  }
});

async function refreshAgents() {
  const data = await api("/api/agents");
  state.agents = data.agents;
  renderAgents();
}

/* ------------------------------------------------------- agent selection */

function renderAgentPicker() {
  const mode = $("#mode").value;
  const picker = $("#agentPicker");
  picker.hidden = mode === "direct";
  if (mode === "direct") return;

  $("#agentPickerLabel").textContent =
    mode === "manual"
      ? "Pipeline steps, in order. Click to add; click again to remove."
      : "Sub-agents the big agent may use. All ready agents are available unless you narrow it down.";

  const host = $("#agentPickerList");
  host.innerHTML = "";
  const ready = state.agents.filter((a) => a.ready);

  if (!ready.length) {
    host.appendChild(
      el("span", { class: "detail", text: "No agents with a model yet — set one in the Agents tab." })
    );
    return;
  }

  for (const agent of ready) {
    const index = selectedAgents.indexOf(agent.id);
    const active = index !== -1;
    host.appendChild(
      el("button", {
        class: `btn small ${active ? "" : "ghost"}`,
        text: mode === "manual" && active ? `${index + 1}. ${agent.name}` : agent.name,
        title: `${agent.role} — ${modelLabel(agent.model)}`,
        onclick: () => {
          if (active) selectedAgents.splice(index, 1);
          else selectedAgents.push(agent.id);
          renderAgentPicker();
        },
      })
    );
  }
}

let selectedAgents = [];

$("#toggleNodes").addEventListener("click", () => {
  const nodes = $("#nodes");
  const hidden = nodes.hasAttribute("hidden");
  if (hidden) nodes.removeAttribute("hidden");
  else nodes.setAttribute("hidden", "");
  $("#toggleNodes").textContent = hidden ? "Hide" : "Show";
});

$("#mode").addEventListener("change", () => {
  selectedAgents = [];
  renderAgentPicker();
  $("#runPanel").hidden = true;
});

/* ------------------------------------------------------------------- run */

function resetRun() {
  state.nodes.clear();
  $("#nodes").innerHTML = "";
  $("#laneSummary").textContent = "";
  notice("#runNotice", "");
}

function nodeCard(id) {
  let entry = state.nodes.get(id);
  if (entry) return entry;

  const out = el("div", { class: "out" });
  const head = el("div", { class: "head" }, [el("span", { class: "name", text: id })]);
  const meta = el("div", { class: "meta" });
  const instruction = el("div", { class: "instruction" });
  const card = el("div", { class: "node" }, [head, meta, instruction, out]);

  $("#nodes").appendChild(card);
  entry = { card, head, meta, instruction, out, status: "pending" };
  state.nodes.set(id, entry);
  return entry;
}

function updateLaneSummary() {
  const counts = { running: 0, queued: 0, done: 0, failed: 0 };
  for (const node of state.nodes.values()) counts[node.status] = (counts[node.status] || 0) + 1;

  const parts = [];
  if (counts.running) parts.push(`${counts.running} running`);
  if (counts.queued) parts.push(`${counts.queued} queued — lane full`);
  if (counts.done) parts.push(`${counts.done} done`);
  if (counts.failed) parts.push(`${counts.failed} failed`);
  $("#laneSummary").textContent = parts.join(" · ");
}

function handleRunEvent(event, answer) {
  switch (event.type) {
    case "plan": {
      $("#runPanel").hidden = false;
      for (const task of event.plan.tasks) {
        const node = nodeCard(task.id);
        node.instruction.textContent = task.instruction;
        node.status = "pending";
      }
      break;
    }
    case "node_waiting": {
      const node = nodeCard(event.id);
      node.meta.textContent = `waiting on ${event.depends_on.join(", ")}`;
      break;
    }
    case "node_queued": {
      const node = nodeCard(event.id);
      node.status = "queued";
      node.meta.textContent = `queued — ${event.lane} lane full (limit ${event.limit})`;
      break;
    }
    case "node_start": {
      const node = nodeCard(event.id);
      node.status = "running";
      node.card.className = "node running";
      node.head.innerHTML = "";
      node.head.append(
        el("span", { class: "dot ok pulse" }),
        el("span", { class: "name", text: event.agent_name })
      );
      node.meta.textContent = `${event.model} · ${event.lane}`;
      node.startedAt = event.started_at;
      break;
    }
    case "node_token": {
      const node = nodeCard(event.id);
      node.out.textContent += event.text;
      node.out.scrollTop = node.out.scrollHeight;
      break;
    }
    case "node_tool": {
      const node = nodeCard(event.id);
      node.meta.textContent += ` · using ${event.name || "tool"}`;
      break;
    }
    case "node_done": {
      const node = nodeCard(event.id);
      node.status = "done";
      node.card.className = "node done";
      node.head.querySelector(".dot")?.classList.remove("pulse");
      const seconds = (event.ended_at - event.started_at).toFixed(1);
      node.meta.textContent += ` · ${seconds}s`;
      break;
    }
    case "node_error": {
      const node = nodeCard(event.id);
      node.status = "failed";
      node.card.className = "node failed";
      node.head.innerHTML = "";
      node.head.append(el("span", { class: "dot error" }), el("span", { class: "name", text: event.id }));
      node.out.appendChild(el("div", { class: "err", text: event.message }));
      break;
    }
    case "plan_failed": {
      notice(
        "#runNotice",
        `The big agent could not produce a usable plan (${event.message}). Answering directly instead.`
      );
      break;
    }
    case "synthesis_start": {
      answer.who.textContent = "Final answer";
      answer.who.scrollIntoView({ behavior: "smooth", block: "nearest" });
      break;
    }
    case "token": {
      answer.body.textContent += event.text;
      break;
    }
    case "error": {
      notice("#runNotice", event.message, "err");
      break;
    }
    default:
      break;
  }
  updateLaneSummary();
}

function addMessage(role, text) {
  const transcriptHost = $("#transcript");
  if (transcriptHost.querySelector(".empty")) transcriptHost.innerHTML = "";

  const who = el("div", { class: "who", text: role === "user" ? "You" : "Answer" });
  const body = el("div", { class: "body", text: text || "" });
  transcriptHost.appendChild(el("div", { class: `msg ${role}` }, [who, body]));
  transcriptHost.scrollTop = transcriptHost.scrollHeight;
  return { who, body };
}

async function send() {
  const text = $("#prompt").value.trim();
  if (!text) return;

  const slot = parseSlot($("#bigAgentModel").value);
  if (!slot) {
    notice("#runNotice", "Pick a model for the big agent first.", "err");
    return;
  }

  const mode = $("#mode").value;
  if (mode === "manual" && !selectedAgents.length) {
    notice("#runNotice", "Pick at least one step for the pipeline.", "err");
    return;
  }

  $("#prompt").value = "";
  addMessage("user", text);
  resetRun();

  const answer = addMessage("assistant", "");
  answer.who.textContent = mode === "direct" ? "Answer" : "Planning…";

  state.controller = new AbortController();
  $("#send").disabled = true;
  $("#stop").hidden = false;

  try {
    if (mode === "direct") {
      state.transcript.push({ role: "user", content: text });
      await streamSSE(
        "/api/chat",
        { provider: slot.provider, model: slot.model, messages: state.transcript },
        (event) => {
          if (event.type === "token") answer.body.textContent += event.text;
          else if (event.type === "error") notice("#runNotice", event.message, "err");
        },
        state.controller.signal
      );
      state.transcript.push({ role: "assistant", content: answer.body.textContent });
    } else {
      await streamSSE(
        "/api/run",
        {
          message: text,
          provider: slot.provider,
          model: slot.model,
          mode,
          agents: selectedAgents,
        },
        (event) => handleRunEvent(event, answer),
        state.controller.signal
      );
    }
  } catch (error) {
    if (error.name !== "AbortError") notice("#runNotice", error.message, "err");
  } finally {
    $("#send").disabled = false;
    $("#stop").hidden = true;
    state.controller = null;
    if (!answer.body.textContent) answer.who.textContent = "Answer";
  }
}

$("#send").addEventListener("click", send);
$("#stop").addEventListener("click", () => state.controller?.abort());
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
});

/* --------------------------------------------------------- model portal */

async function refreshInstalled() {
  const data = await api("/api/local/models");
  const host = $("#installedList");
  host.innerHTML = "";

  if (!data.available) {
    notice("#installedNotice", data.status.detail, "err");
    host.appendChild(el("p", { class: "empty", text: "Local models will appear here once Ollama is running." }));
    return;
  }

  notice("#installedNotice", "");
  if (!data.models.length) {
    host.appendChild(
      el("p", { class: "empty", text: "No models installed yet. Use the Download tab to pull one." })
    );
    return;
  }

  for (const model of data.models) {
    host.appendChild(
      el("div", { class: "model-row" }, [
        el("span", { class: "id", text: model.id }),
        model.loaded ? el("span", { class: "badge ok", text: "in memory" }) : null,
        el("span", { class: "spacer" }),
        el("span", { class: "sub", text: [model.detail, humanBytes(model.size_bytes)].filter(Boolean).join(" · ") }),
        el("button", {
          class: "btn small danger",
          text: "Delete",
          onclick: async () => {
            if (!confirm(`Delete ${model.id} from disk?`)) return;
            await api(`/api/local/models/${encodeURIComponent(model.id)}`, { method: "DELETE" });
            await refreshInstalled();
            await refreshModels();
          },
        }),
      ])
    );
  }
}

async function renderCatalog() {
  try {
    const data = await (await fetch("/static/catalog.json")).json();
    state.catalog = data.models || [];
  } catch {
    state.catalog = [];
  }

  const host = $("#catalogList");
  host.innerHTML = "";
  for (const entry of state.catalog) {
    host.appendChild(
      el("div", { class: "model-row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "id", text: entry.name }),
          el("div", { class: "sub", text: entry.use }),
        ]),
        el("span", { class: "sub", text: `${entry.size} · ${entry.ram} RAM` }),
        el("button", {
          class: "btn small ghost",
          text: "Download",
          onclick: () => {
            $("#pullName").value = entry.name;
            pull();
          },
        }),
      ])
    );
  }
}

async function pull() {
  const name = $("#pullName").value.trim();
  if (!name) return;

  const host = $("#pullStatus");
  host.innerHTML = "";
  const label = el("div", { class: "detail", text: `Starting ${name}…` });
  const fill = el("div");
  host.append(label, el("div", { class: "progress" }, [fill]));

  $("#pullBtn").disabled = true;
  try {
    await streamSSE("/api/local/pull", { name }, (event) => {
      if (event.type === "progress") {
        const { completed, total, status } = event;
        if (total) {
          const pct = Math.min(100, Math.round((completed / total) * 100));
          fill.style.width = `${pct}%`;
          label.textContent = `${status || "downloading"} — ${pct}% of ${humanBytes(total)}`;
        } else {
          label.textContent = status || "working…";
        }
      } else if (event.type === "done") {
        fill.style.width = "100%";
        label.textContent = `${event.name} is installed.`;
        refreshInstalled();
        refreshModels();
      } else if (event.type === "error") {
        notice(host, event.message, "err");
      }
    });
  } catch (error) {
    notice(host, error.message, "err");
  } finally {
    $("#pullBtn").disabled = false;
  }
}

$("#pullBtn").addEventListener("click", pull);
$("#pullName").addEventListener("keydown", (event) => {
  if (event.key === "Enter") pull();
});

function renderCloud() {
  const host = $("#cloudList");
  host.innerHTML = "";
  const hosted = state.models.filter((m) => !m.local);

  if (!hosted.length) {
    host.appendChild(
      el("p", {
        class: "empty",
        text: "No cloud models. Add an Anthropic key or an OpenAI-compatible endpoint in Settings.",
      })
    );
    return;
  }

  for (const model of hosted) {
    host.appendChild(
      el("div", { class: "model-row" }, [
        el("span", { class: "id", text: model.label }),
        el("span", { class: "spacer" }),
        el("span", { class: "sub", text: state.providers[model.provider]?.label || model.provider }),
        el("span", { class: "badge", text: "hosted — nothing to download" }),
      ])
    );
  }
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  try {
    const health = await api("/api/health");
    $("#homePath").textContent = health.home;
  } catch {
    /* the header hint is cosmetic */
  }

  state.config = await api("/api/config");
  await refreshProviders();
  await refreshModels();
  await refreshAgents();
  await renderCatalog();
  renderAgentPicker();

  const anyReady = Object.values(state.providers).some((p) => p.status?.state === "ok");
  if (!anyReady) {
    notice(
      "#runNotice",
      "No provider is connected yet. Open Settings to add an Anthropic key or point at a local Ollama server."
    );
  }
}

boot();
