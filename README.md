# Orchestra

Root a strong agent, and let it hand work to a team of smaller ones that run **at the same time**.

Orchestra is a local web portal. You pick a **big agent** to plan and write the final answer, you
define **sub-agents** — each with its own model, its own soul, and its own job — and the big agent
breaks your request into subtasks and fans them out. Independent subtasks run simultaneously, mixing
local models and hosted APIs in the same run.

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
  research.py      keyless search + fetch, SSRF guard, untrusted wrapping
  providers/       base.py is the swap seam; one file per backend
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
- Sub-agents are text-only apart from research. No file or shell access in v1.
- No authentication, and conversation history is per-browser-session and not persisted.
- The keyless search backend is best-effort (see Research above).

## Licence

MIT.
