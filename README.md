# Orchestra

**Local-first agent orchestration that shows you exactly what left your machine.**

A big agent plans your request into subtasks and hands them to smaller agents that run **at the same
time** — some on models on your laptop, some on hosted APIs, in the same run. Because those are
different trust boundaries, Orchestra treats them as different trust boundaries: sensitive values
are stripped before anything reaches a hosted model, agents can be pinned to never leave the
machine at all, and every run ends with a receipt showing what stayed and what was sent.

Most agent tools ask you to choose between capable-but-hosted and private-but-limited. This one
routes per subtask, so you get both.

Every model slot is swappable at any time, from a dropdown, with no restart. Local models can be
downloaded, inspected, and deleted from inside the app.

No build step. Clone it and run it.

```bash
git clone <your fork> orchestra
cd orchestra
./run.sh          # Windows: run.bat
```

That creates a virtualenv, installs four dependencies, and opens `http://localhost:8600`.
Python 3.10+ is the only prerequisite.

---

## What it actually does

You ask for something. In **Auto** mode the big agent produces a task graph over your sub-agents:

```
Compare Python and Go for a small CLI tool.

  t1 → Scout      "find startup-time benchmarks"        ┐ these two run
  t2 → Scout      "find distribution/packaging facts"   ┘ at the same time
  t3 → Critic     "stress-test the claims"       depends on t1, t2
  t4 → Writer     "write the recommendation"     depends on t3
```

You watch each agent stream its own output into its own card, with its model and elapsed time.
Then the big agent writes the final answer from their results.

There are two other modes: **Pipeline**, where you wire a fixed order yourself and get a
deterministic run, and **Direct**, which is plain chat with one model.

## Providers

| Provider | What it gives you | Downloads? |
|---|---|---|
| **Ollama** | Models running on your own machine | **Yes** — pull, delete, disk usage |
| **Anthropic** | Claude models, listed live from the API | No — hosted |
| **OpenAI-compatible** | OpenRouter, LM Studio, vLLM, Groq, together.ai, OpenAI, or anything else speaking `/chat/completions` | No — hosted |

Connect any combination. One agent can be on Claude and the next on a 3B model on your laptop, in
the same run.

**On "downloading models":** this only means something for local models. Ollama pulls them onto your
disk and Orchestra shows real byte-level progress. Anthropic and OpenAI-compatible models are hosted
— you select them, there is nothing to download, and the UI says so rather than blurring the two.

You can also pull any GGUF from Hugging Face by pasting a reference like
`hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M` into the Download tab.

## Sub-agents: model + soul + role

An agent is three things, kept separate because different parts of the system read them:

```json
{
  "id": "scout",
  "name": "Scout",
  "role": "Finds and verifies current facts, figures, and sources on a topic",
  "soul": "You are a skeptical field researcher. You distinguish what you verified
           from what you inferred. When sources disagree you report the disagreement
           instead of picking the tidier answer. You never fill a gap with a guess.",
  "model": { "provider": "ollama", "model": "qwen2.5:7b" },
  "capabilities": { "research": true },
  "temperature": 0.3
}
```

- **model** — any provider, per agent, swappable from a dropdown mid-session.
- **soul** — persona, voice, and standards. Optional, and the reason two agents on the *same* model
  behave like different people. In testing, two agents on one 3B model with opposing souls produced
  answers of 336 and 2682 characters to an identical question.
- **role** — one line the planner routes on. Write it for a router, not a human.

Six starter agents ship with the repo — Scout, Summarizer, Coder, Critic, Extractor, Writer — with
filled-in souls to fork. They arrive without a model assigned, because nobody knows what models you
have until you connect a provider. An agent without a model is hidden from the planner so it can
never route work somewhere that cannot run it.

## Parallelism is per-provider, on purpose

Concurrency limits are set per provider, not globally:

| Lane | Default | Why |
|---|---|---|
| Anthropic | 8 | Network-bound — parallelism is nearly free |
| OpenAI-compatible | 8 | Same, per endpoint |
| Ollama | 2 | RAM-bound — several 7B models at once will thrash a laptop |

A five-way fan-out of three cloud agents and two local agents runs all five at once. A busy local
lane never holds up your cloud agents. When a lane is full the UI says *"2 running, 1 queued — lane
full"* rather than just looking slow. All three limits are editable in Settings.

This is measurable, not decorative. A recorded 11-task local run finished in 43.3s of wall time
against 78.2s of summed node time, with 9 overlapping node pairs.

## Privacy-tiered routing

This is the part worth caring about. It has three layers.

**1. Redaction at the boundary.** Before any text reaches a hosted model, structured identifiers are
replaced with stable placeholders. The same value always gets the same placeholder within a run, so
the model can still tell that two mentions are the same person:

```
you type:      Priya Raman, priya.raman@example.com, card 4111 1111 1111 1111 was double charged
local model:   Priya Raman, priya.raman@example.com, card 4111 1111 1111 1111 was double charged
hosted model:  Priya Raman, [EMAIL_1], card [CARD_1] was double charged
your answer:   …the real values restored here, locally, because they never left in that form
```

Detected by default: emails, phone numbers, Luhn-validated card numbers, US SSNs, API keys and
tokens (`sk-`, `sk-ant-`, `ghp_`, `AKIA…`, `xox…`, and friends), IP addresses, IBANs, and file paths
containing your home directory. Each is toggleable.

**2. Local-only agents.** Tick "local only" on an agent and it can no longer be saved with a hosted
model — the API rejects it, not just the UI. Such an agent is also *told* it may be feeding a hosted
agent downstream, and instructed to hand over an abstraction rather than the raw details. That is
the pattern that makes hybrid work: the local model reads the private material and the hosted model
gets the problem without the data.

**3. Strict mode.** Instead of redacting, refuse. A step whose input contains sensitive values is
automatically moved onto a local model, with a visible notice saying which categories forced the
move. If you have no local model installed, the step fails rather than sending.

### How the guarantee is enforced

Not by remembering to call a function. `providers/registry.build()` is the only way to obtain a
model, and everything it returns is wrapped in `providers/guard.py`. Call sites cannot opt in and
cannot opt out; code added later is covered without its author knowing this exists. If you're
auditing the claim, those two files are the whole story.

"Local" is decided per configured instance, not per provider name — an Ollama pointed at another
machine is **not** local, and an LM Studio endpoint on `localhost` **is**. Addresses that fail to
resolve are treated as remote. Note that a private LAN address counts as local; if you're on a
shared network and that isn't what you want, use strict mode with a loopback-only endpoint.

### What it does not do

Detection is pattern-based, and that is a deliberate trade: a classifier that is right most of the
time cannot back a guarantee, and cannot be audited by reading the source. So it reliably catches
structured identifiers and **does not** catch names, street addresses, dates of birth, or the fact
that a paragraph is about someone's health or finances. For those, mark the agent local-only — that
protection is structural rather than statistical.

The ledger records what Orchestra sent. It cannot tell you what a provider does with it afterwards.

## Research

Any agent can be given read-only web access. It is **off by default, per agent**, and works two
different ways:

- **Anthropic agents** use Anthropic's server-side `web_search` / `web_fetch`. The browsing happens
  on Anthropic's infrastructure — genuinely agentic, and nothing executes locally.
- **Everything else** uses a retrieve-then-answer pass: the agent's own model proposes search
  queries, Orchestra runs them and fetches the pages, and the text comes back as context.

That split is deliberate. Model-driven tool calling is inconsistent enough across small local models
that a 3B model would fail it often and silently, so the local path is retrieval-augmented rather
than agentic. It is the less clever design and the one that actually works.

Two safeguards you should know about:

- Fetched pages are wrapped in `<untrusted_content>` and labelled as data. An agent is told never to
  follow instructions found inside them, and results never feed back into the planner as new
  instructions — so one poisoned page cannot steer the rest of the run.
- The fetcher refuses non-public addresses: loopback, private ranges, link-local, and cloud metadata
  endpoints are all blocked, so a hostile search result cannot turn the backend into a port scanner.

The keyless default uses DuckDuckGo's HTML endpoint, which is not a documented API and can break if
their markup changes. When search returns nothing the agent is told search was unavailable, rather
than being handed silence and left to guess.

## Tools

Research gives an agent read-only web access. Tools give it everything else: reading and writing
files in one folder you nominate, and anything an MCP server offers. **Grants are per agent and
default to none** — adding a server does not widen what any existing agent can do.

Every tool declares where it runs, and that declaration is the whole design:

- **Interior** — the filesystem tool, and any MCP server spawned as a process on this machine.
  Nothing crosses the border. Recorded on the declaration anyway, because "6 of 8 calls never left"
  is only provable if the ones that stayed are counted.
- **Exterior** — a hosted MCP endpoint. Its arguments are inspected under the same policy as a model
  call, redacted or refused the same way, and land on the same declaration as their own row. That
  is enforced in `tools/guard.py`, applied by `tools/registry.build_for()`, which is the only way to
  obtain a tool.

### Filesystem

One folder, read-only unless you turn writing on. The entire risk is path escape, so every path is
resolved *before* it is checked — `..`, an absolute path, and a symlink pointing at `~/.ssh` all
fail, which a check on the raw string would not catch. Credential files (`.env`, `.netrc`, keys,
`.pem`) and `.git` are refused whatever folder you nominate. A replaced file keeps its previous
contents beside it as `.orchestra-bak`.

Your editor reloads from disk, so an agent editing your project appears as a diff in VS Code without
anything driving the editor.

### MCP

Servers publish their own tools, which is why Orchestra needs no adapter per service. Two transports:
`stdio` (a process here, interior) and streamable HTTP (someone else's, exterior).

A stdio server is arbitrary code running as you — `npx -y some-package` downloads and executes
whatever is behind that name. So Orchestra **never installs anything**, shows you the exact command
verbatim, and refuses to spawn it until you have approved that command. Changing the command revokes
the approval, because approval is of a command line and not of a name. A shell (`sh`, `bash`, `eval`,
`curl`) is refused as the command outright: approving one once would approve anything it was later
handed.

### Tool calling is where small models break

Calling a tool means emitting exact JSON on demand. Models under roughly 7B do that unreliably —
they describe the call in prose instead of making it, and the step then looks like it succeeded
while nothing ran. Orchestra estimates this from the model you picked and **warns in the agent
editor rather than blocking**, because it is your machine.

The loop itself is one text protocol across every provider, not each vendor's native tool API. A
loop built on native calling would work on Claude and silently do nothing on the local models this
project exists to make useful.

### What a small local agent is actually for

Not tools. A 3B model on your machine is a different instrument, and it is genuinely good at:

- **Bulk transformation over text you already have** — summarising, reformatting, extracting fields,
  translating. No decision to get wrong, the input is in the prompt, and it never leaves.
- **The privacy lane** — any step touching real names, keys, or client data. This is the one thing
  no hosted model can offer at any size.
- **Wide parallel fan-out** — twelve documents, one question each, several at once.
- **First-pass drafting and triage** — deciding what deserves a bigger model.

Leave tool calling, multi-step reasoning, and final synthesis to a larger agent.

## Where your keys live

In `~/.orchestra/config.json`, mode `0600`, on your machine only. Never in the repo — the directory
is gitignored. The API returns keys masked, and the UI never round-trips a real key back to the
server.

Environment variables override the file and are never written to disk:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OLLAMA_HOST=http://127.0.0.1:11434
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENAI_API_KEY=...
```

Orchestra binds `127.0.0.1` by default. It has **no authentication**, so if you pass
`--host 0.0.0.0` anyone who can reach the port can use your keys and your models. It warns you when
you do.

## Layout

```
orchestra/
  config.py        user config, 0600, env overrides
  agents.py        agent CRUD; composes soul + role into a system prompt
  planner.py       big agent -> task DAG, with fallbacks
  runner.py        parallel executor, per-provider lanes, event stream
  privacy.py       detectors, redaction, policy, and the per-run ledger
  research.py      keyless search + fetch, SSRF guard, untrusted wrapping
  tools/
    base.py        the tool seam; every tool declares local or remote reach
    filesystem.py  workspace-confined file access, resolve-then-contain
    mcp.py         MCP client over stdio and HTTP, plus the approval gate
    guard.py       the second egress choke point, for remote tool calls
    executor.py    the tool-calling loop, one protocol for every provider
    registry.py    grants, and the only source of tools
  providers/
    base.py        the swap seam
    guard.py       the egress choke point — read this to audit the claim
    registry.py    the only source of providers, and where the guard is applied
  routes/          the JSON + SSE API
web/               the UI — plain HTML, CSS, and JS. No bundler.
agents/            starter sub-agents
```

To add a provider, implement the `Provider` protocol in `providers/base.py` and register it in
`providers/registry.py`. Nothing above that layer knows which backend is behind a model slot.

## Known limitations

- **Plan quality tracks the big agent.** A 3B local planner will over-decompose — one test run
  produced 11 tasks for a question that needed 3. Sub-agents can be small; the big agent benefits
  from being the strongest model you have.
- **Tool calling needs a capable model.** Below ~7B it fails often and quietly; the agent editor
  warns you. There is still no shell access — files and MCP only.
- MCP resources and prompts are not supported yet, only tools.
- No authentication, and conversation history is per-browser-session and not persisted.
- The keyless search backend is best-effort (see Research above).

## Licence

MIT.
