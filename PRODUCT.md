# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.10+ / FastAPI backend serving a static `web/` directory of plain HTML, CSS, and
JavaScript. **No build step is a hard product constraint, not a preference** — the distribution
promise is `git clone` then `./run.sh`, and any bundler, framework, or `npm install` breaks it.
Four dependencies total (fastapi, uvicorn, httpx, anthropic).

## Users

People who run local language models and have a reason to care where their data goes. Two
concrete situations, both confirmed in this project's own history:

- A developer with Ollama installed who wants several agents working at once, some on a laptop
  model and some on a hosted API, and who is currently choosing between capable-but-hosted and
  private-but-limited.
- The maintainer using it for their own recurring pipeline work (content production for
  MediviseForYou), where the same multi-step job runs repeatedly.

They are technical, they read source before trusting a privacy claim, and they arrive from a
GitHub README rather than a marketing page.

## Product Purpose

Orchestra roots one strong "big agent" that plans a request into a task DAG over user-defined
sub-agents, then runs the independent subtasks simultaneously. Every model slot — the big agent
and each sub-agent — is swappable at runtime with no restart.

Success is that a person can fan work out across local and hosted models in one run, see it
actually happening in parallel, and know exactly what left their machine.

## Positioning

**Per-agent heterogeneous model routing with an enforced trust boundary.** Each sub-agent has its
own model, on its own provider, local or hosted; because those are different trust boundaries,
Orchestra treats them as such — redacting structured identifiers before text reaches a hosted
model, allowing agents to be pinned local-only, and ending every run with a ledger of what stayed
and what was sent.

This is verifiably not what the incumbents do. Open WebUI's sub-agents run "with the same model,
tools, skills and filters as the chat that spawned it" (their docs); their open issue #27598
requests per-sub-agent models and is unaddressed. One model per chat means one trust boundary per
chat, so there is nothing to route between. Flowise and Langflow are provider-agnostic pipes with
no concept of a trust boundary at all.

## Operating Context

Runs on `localhost:8600`, launched from a terminal, used in a browser beside an editor and a
terminal. Long-running: a fan-out of local 3B models takes tens of seconds and the user watches it.
Ollama must be running separately. Keys live in `~/.orchestra/config.json` at mode 0600, never in
the repo. No authentication — binding beyond localhost prints a warning.

## Capabilities and Constraints

- **Providers:** Ollama (local, and the only one that downloads models), Anthropic, OpenRouter
  (409 text-capable models, searchable, starrable), and a generic OpenAI-compatible adapter
  covering LM Studio, vLLM, Groq, together.ai.
- **Agents** are `model + soul + role`. Soul is persona and standards; role is the one line the
  planner routes on. Six starters ship, shipped without a model assigned.
- **Modes:** Auto (planner builds a DAG), Pipeline (user-wired fixed order), Direct (one model).
- **Concurrency is per provider**, not global: Anthropic 8, OpenRouter 8, OpenAI-compat 8,
  Ollama 2 — because cloud lanes are network-bound and the local lane is RAM-bound.
- **Privacy modes:** off / redact / strict, defaulting to redact. Enforced in
  `providers/guard.py`, applied by `registry.build()`, which is the only way to obtain a provider.
- Detection is deterministic regex plus checksums, never a classifier — so it is auditable, and so
  it provably misses names, addresses, and contextual sensitivity.
- Sub-agents are text-only apart from optional read-only web research.
- Conversation history is per-browser-session and not persisted. No accounts, no telemetry.

## Brand Commitments

- Name: **Orchestra**. MIT licensed.
- **No external network requests from the page.** A privacy-first tool that fetches webfonts or
  scripts from a third party on load contradicts its own claim; type must come from system stacks
  or self-hosted files.
- User-pinned for the current design work: build a palette with no relationship to Nous Research;
  make the local/hosted trust boundary literal in the interface rather than a badge; system font
  stacks only.

## Evidence on Hand

Real, measured, reproducible in this repo — not to be restated as rounder numbers:

- An 11-task local run: **43.3s wall against 78.2s of summed node time, 9 overlapping node pairs.**
- Lane isolation with deterministic fakes: 4 local + 3 cloud agents, local lane capped at 2 — all
  three cloud nodes started at **0.00s** while the local lane was saturated.
- Redaction under a spy provider: the hosted backend received
  `Reach me at [EMAIL_1] or [PHONE_1], card [CARD_1].` while the local backend received the real
  values. Secrets reaching the remote backend: none.
- Soul differentiation: two agents, same 3B model, opposing souls, identical question →
  **336 vs 2682 characters.**
- Cold clone: 38 files, 444 KB of source, no secrets, boots from `./run.sh` alone.

There are no users, stars, testimonials, benchmarks against competitors, or deployment claims.
Future work must not invent any.

## Product Principles

1. **The guarantee is structural or it is nothing.** Enforcement lives at the one door every model
   call passes through, never in a convention contributors must remember.
2. **Show the receipts.** Everyone claims parallel and private; this one proves both with
   timestamps and a ledger, including the local calls, because the ratio is the claim.
3. **State the limits plainly.** What pattern-based detection cannot catch is documented, not
   buried. Credibility with this audience comes from precision about failure.
4. **Clone-and-run outranks polish.** Any feature that adds a build step, a service dependency, or
   an external request is the wrong feature.
5. **Degrade, never dead-end.** An unreachable provider, an unparseable plan, a blocked egress —
   each has a defined fallback that keeps the run alive.

## Accessibility & Inclusion

No externally imposed standard. Product-specific needs: long-running async work must be legible
without relying on motion alone, live regions must announce state changes, and the interface is
used for extended sessions in a dim room beside an editor.
