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

## The one architectural rule

**Nothing outside `orchestra/providers/` may know which backend is behind a model slot.**

A slot is `{"provider": "...", "model": "..."}`. The planner, runner, agents, and UI all go through
the `Provider` protocol in `providers/base.py`. That constraint is what makes every model swappable
at runtime, and it is easy to break by accident — if you find yourself writing
`if provider_id == "anthropic"` outside `providers/`, the behaviour probably belongs on `Caps`
instead.

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

## Style

Match the surrounding code. Comments explain *why* something is the way it is — the non-obvious
constraint, the failure that motivated it — not what the next line does.
