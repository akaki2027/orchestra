# Contributing

Thanks for looking. Orchestra is deliberately small and dependency-light so that reading it end to
end is realistic in an afternoon.

## Running it

```bash
./run.sh --reload
```

`--reload` restarts the backend when you edit Python. The UI has no build step, so editing anything
in `web/` just needs a browser refresh.

To work against a scratch config instead of your real one:

```bash
ORCHESTRA_HOME=/tmp/orchestra-dev ./run.sh --port 8601
```

## Two architectural rules

**1. Nothing outside `orchestra/providers/` may know which backend is behind a model slot.**

A slot is `{"provider": "...", "model": "..."}`. The planner, runner, agents, and UI all go through
the `Provider` protocol in `providers/base.py`. That constraint is what makes every model swappable
at runtime, and it is easy to break by accident — if you find yourself writing
`if provider_id == "anthropic"` outside `providers/`, the behaviour probably belongs on `Caps`
instead.

**2. `registry.build()` is the only way to get a provider, and it always wraps in the guard.**

The privacy guarantee in the README is only true because there is exactly one door. Do not add a
path that returns `_raw(...)` un-wrapped, do not construct `OllamaProvider()` directly in
application code, and do not add a "just this once" bypass for a fast path. If the guard is in your
way, the right fix is a policy change in `privacy.py`, not a second door.

A new provider must implement `is_local()` honestly. It is a method rather than a flag because the
answer depends on configuration — a remote Ollama is not local. Getting this backwards silently
breaks the guarantee, which is the one bug in this codebase that would matter.

## Adding a provider

1. Implement the protocol in `providers/base.py`: `configured()`, `status()`, `list_models()`, and
   `chat()` as an async generator of `Chunk`.
2. Declare what it can do via `Caps` — `json_schema` decides whether the planner constrains output
   natively or falls back to prompting; `server_side_research` decides which research path an agent
   on it takes.
3. Register it in `providers/registry.py` and add its config shape to `config.DEFAULTS`.
4. Add its fields to the settings card in `web/app.js`.

Degrade, don't raise. An unreachable provider should return a `Status`, contribute nothing to the
model list, and leave the rest of the app working.

## Adding a starter agent

Drop a JSON file in `agents/`. Leave `model` empty — users assign it after connecting a provider.
Write the `role` for a router and the `soul` for the model. Starters are copied into the user's home
once and never overwritten, so an edit here only affects new installs.

## Testing

There is no test suite yet; contributions welcome. Until then, the checks that matter are in the
README's design claims, and they should be re-run when you touch the relevant code:

- **Simultaneity** — log node `started_at` / `ended_at` from `/api/run` and assert intervals overlap
  and wall time is near the slowest node, not the sum. Regressions here are silent.
- **Lane isolation** — a full local lane must not delay cloud nodes.
- **Planner fallbacks** — `planner._loads` must survive fenced JSON, prose wrappers, and prose-only
  replies; `planner.validate` must reject unknown agents and cycles and repair dangling deps.
- **SSRF guard** — `research.safe_url` must block loopback, private ranges, link-local, cloud
  metadata, and non-HTTP schemes.
- **Model swap** — change an agent's model and confirm the next run uses it with no restart.
- **The privacy guarantee** — the important one. Substitute a spy provider that records exactly
  what it was handed, then assert: a remote backend never receives a raw email, phone, or card
  number under `redact`; strict mode raises before the remote backend is called at all; clean text
  passes through byte-for-byte; a remote Ollama reports `is_local() == False`; and the ledger counts
  local calls as well as remote ones (the ratio is the claim).

## Style

Match the surrounding code. Comments explain *why* something is the way it is — the non-obvious
constraint, the failure that motivated it — not what the next line does.

## Recording what you changed

`CHANGELOG.md` is how anyone arriving at this repo sees where it actually stands, so add to it under
**Unreleased** as part of the change rather than afterwards.

Two rules keep it worth reading:

- **Numbers come from runs, not estimates.** If you claim something is faster, parallel, or blocked,
  paste the output that shows it.
- **Keep "Not built yet" honest.** A changelog that only advertises what works is a sales page. If
  your change reveals a gap, add the gap.
