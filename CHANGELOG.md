# Changelog

What is built, in the order it was built, with the evidence each claim rests on. Anything asserted
here was measured on a real run — where a number appears, it came from an actual execution, not an
estimate.

Orchestra has not cut a release yet. Everything below is on `main`.

---

## Unreleased

### Tools — filesystem, MCP, and per-agent grants

Agents could only produce text. They can now read and write files in one nominated folder, and call
anything an MCP server offers.

- **Filesystem tool.** One folder, read-only unless you turn writing on. Every path resolves before
  it is checked, so `..`, an absolute path, and a symlink pointing outside all fail — a check on the
  raw string catches none of them. Credential files (`.env`, `.netrc`, `*.pem`) and `.git` are
  refused whatever folder you nominate. Overwrites keep the previous contents as `.orchestra-bak`.
- **MCP client** over stdio and streamable HTTP. Servers publish their own tools, so there is no
  adapter per service.
- **Approval gate.** A stdio server is arbitrary code running as you. Nothing spawns until that
  exact command is approved; editing the command revokes approval, because approval is of a command
  line and not of a name. A shell (`sh`, `bash`, `eval`, `curl`) as the command is refused outright.
- **Grants are per agent and default to none.** Adding a server does not widen what any existing
  agent can do.
- **Remote tool calls cross the same border as model calls** — inspected under the same policy,
  redacted or refused the same way, landing on the same declaration as their own row. Enforced in
  `tools/guard.py`, applied by `tools/registry.build_for()`, which is the only way to obtain a tool.

Verified — path escape, through the real door:

```
door returns: GuardedTool
refused ../../etc/passwd     resolves outside the workspace
refused /etc/hosts           resolves outside the workspace
refused out (symlink→passwd) resolves outside the workspace
refused .env                 looks like a credential file
reads inside: True
read-only holds: This filesystem tool is read-only.
```

Verified — a remote tool under each privacy mode:

```
redact  remote server received: 'Email [EMAIL_1], card [CARD_1]'
        declaration -> remote_calls=1 blocked=0 redacted={'email':1,'card':1}
strict  blocked before any call: ['card','email']; server saw nothing
        declaration -> remote_calls=1 blocked=1
```

### The small-model warning

Tool calling is a structured-output problem, and models under roughly 7B fail it *quietly*: they
describe a call in prose, nothing runs, and the step looks like it succeeded. The agent editor
estimates this from the model you picked and **warns rather than blocks** — it is your machine.

The loop is one text protocol across every provider, not each vendor's native tool API. A loop built
on native calling would work on Claude and silently do nothing on the local models this project
exists to make useful.

The Tools desk states what a small local agent is actually for: bulk transformation over text
already in the prompt, the privacy lane, wide parallel fan-out, and first-pass triage — and what to
leave to a larger agent.

Verified in the live UI: a 1B local model with a grant warns, a hosted 120B model with the same
grant does not, and no grant never warns.

### Simultaneous local models, and what actually limits them

Three *different* local models, three different tasks, one run, real inference:

```
ollama lane cap = 3
t1   llama3.2:1b    0.00s → 4.37s  |████████████████████████████████████████
t2   llama3.2:3b    0.05s → 1.03s  |█████████
t3   qwen2.5:3b     0.06s → 3.56s  |████████████████████████████████

summed work 8.9s   wall clock 4.4s   overlapping pairs 3/3
```

All three started within 0.06s of each other and each returned a real, distinct answer. At the
default lane cap of 2 the third correctly queued instead.

The local lane number is what decides this, and nothing said so. Settings now states both real
ceilings where the number is edited: memory (each model stays resident while it works, checked
against detected usable RAM) and Ollama's own `OLLAMA_MAX_LOADED_MODELS`, which swaps models in and
out rather than running them together if the lane is set above it.

### OpenRouter: a revoked key no longer looks healthy

OpenRouter's model catalogue is a **public endpoint**. A revoked key therefore browses all 400+
models perfectly — you could star them, wire them to agents, and only discover the problem at run
time. `configured()` could never catch this, because it can only tell you a key exists.

- New `key_state()` distinguishes *missing* / *rejected* / *unreachable* / *ok*, cached per key for
  60s so changing the key re-checks immediately.
- A key OpenRouter answers `"User not found"` for was revoked or its account is gone, and is named
  as such — distinct from a typo, and only fixable by issuing a new one.
- *Unreachable* is never reported as *rejected*. Sending someone to regenerate a key that was never
  the problem is its own bug.
- The model browser now carries the warning, since that is where the damage starts.

### Hardware detection and model fit rating

stdlib-only detection of chip, RAM, VRAM, and memory bandwidth, all editable because detection is
best-effort and the user is not. Every model in the catalogue is rated against the machine —
`clears` / `passes` / `tight` / `won't fit` — with an estimated tokens per second.

### Privacy-tiered routing

The differentiator. Deterministic regex plus checksums, never a classifier, so it is auditable —
and so it provably misses names, addresses, and contextual sensitivity, which is stated plainly
rather than hidden.

- Modes: `off` / `redact` / `strict`, defaulting to **redact**, because a protection nobody switches
  on protects nobody.
- Enforced in `providers/guard.py`, applied by `registry.build()` — the only way to obtain a
  provider, so future providers and code paths are covered without knowing the module exists.
- Agents can be pinned **interior only**, refused at save time against a hosted model.
- Strict mode reroutes blocked work to a local model rather than failing the run.
- Every run ends with a declaration: what left, what stayed, what was protected on the way out.

Verified with a spy provider: the remote model received
`Reach me at [EMAIL_1] or [PHONE_1], card [CARD_1].` while the local model received the real values;
strict mode blocked before any remote call was made; an Ollama pointed at a remote host was
correctly *not* treated as local.

### The border-post interface

Full visual rebuild. Oxblood ink ground, security paper used once per run for the declaration,
pressed rubber stamps, and a hatched border band that the run's agents physically sit above or
below. No build step, no framework, no external network request from the page.

### Foundations

- FastAPI backend serving static files. Four dependencies. `git clone` → `./run.sh` is the whole
  install story, and that is a hard product constraint rather than a preference.
- Provider seam (`providers/base.py`): a model slot is `{"provider": ..., "model": ...}` and no code
  above that layer knows which backend is behind it. Ollama, Anthropic, OpenRouter, and a generic
  OpenAI-compatible adapter.
- Model portal: pull with live progress, delete, disk usage, Hugging Face GGUF refs.
- Agents are `model + soul + role`, each a JSON file in `~/.orchestra/agents/`.
- Planner produces a task DAG; the runner launches every task at once and each awaits only its own
  dependencies, so work starts the instant its inputs are ready.
- Concurrency is **per provider**, not global — a busy local lane never holds up hosted work.
  Verified: 11-task run, 43.3s wall against 78.2s summed, 9 overlapping pairs; three cloud nodes all
  started at 0.00s while the local lane sat at its cap.
- Souls verified as load-bearing: 336 vs 2682 characters from the same 3B model under opposing
  souls.
- `scripts/smoke.py` sweeps 27 routes and fails on any 5xx. It exists because an
  `isinstance(provider, OllamaProvider)` assert survived the privacy guard landing — `build()`
  started returning a wrapper, and `/api/local/models` 500'd for three commits while every other
  route stayed green.

---

## Not built yet

Listed because a repo that only advertises what works is not an honest picture.

- **Chats, histories, and projects.** Conversation state is per-browser-session and not persisted.
  When it lands it must live in `~/.orchestra` at `0600`, because transcripts hold pre-redaction
  values.
- **OpenRouter discovery.** All 410 models are present and reachable by search, but an empty search
  returns the first 60 alphabetically by vendor, so `moonshotai/kimi-k2` and anything late in the
  alphabet is invisible until you type. Needs newest-first ordering, vendor chips, and a
  "showing 60 of 410" count.
- **Authentication.** None. `--host 0.0.0.0` warns, and should.
- **MCP resources and prompts.** Only tools are supported.
- **Mid-run replanning.** The plan is fixed once made; agents pass outputs forward but cannot talk
  to each other or revise the DAG.
