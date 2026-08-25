# Atlas Agent UI & Engine

A self-hosted agent system front-end (the **Atlas / Fusion "Aurum Edition"**
dashboard) plus a small, real **agent engine** behind it.

> Status: v0.1 — engine runs fully offline with a deterministic mock provider;
> plug in any OpenAI-compatible API key to use a real model.

## Run it

```bash
python3 server/server.py          # serves on http://localhost:8123
```

Open <http://localhost:8123/> — the dashboard detects the engine and switches
from **mockup** to **LIVE ENGINE** mode (badge in the masthead). Type a goal,
press RUN, and watch the plan tree, telemetry console, cost ledger and
capability grants update from the real ledger (`data/ledger.jsonl`).

Without the server, the HTML files are standalone design mockups.

## Use a real model

Edit `~/.agentui/config.json`:

```json
{
  "provider": "openai_compat",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key_env": "OPENAI_API_KEY"
}
```

Then `export OPENAI_API_KEY=sk-...` before starting the server. Any
OpenAI-compatible endpoint works (OpenRouter, LM Studio, llama.cpp…).
Costs are estimated into the ledger at $0.15/M input, $0.60/M output tokens.

## Architecture

```
fusion/  concept-4-fusion.html   dashboard UI (demo mode when opened as file)
         live.js                 polls /api/state, renders real ledger data
server/  server.py               stdlib HTTP server: static files + REST API
engine/  agent.py                plan -> act (tools) -> verify gate -> commit
         providers.py            mock provider + OpenAI-compatible provider
         tools.py                sandboxed tools (paths locked to workspace/)
         ledger.py               append-only JSONL operation ledger
         memory.py               episodic memory w/ keyword retrieval
         config.py               ~/.agentui/config.json handling
tests/   test_engine.py          end-to-end self tests
```

### Security model (v0.1)

* Tools can only touch paths inside `<repo>/workspace/`.
* Writes/tests require an explicit `CAPABILITY_GRANTED` ledger entry.
* Strict gates: a task is only COMMITTED if every acceptance check passes,
  otherwise it is BLOCKED and recorded as such.

## Tests

```bash
python3 -m unittest tests.test_engine -v
```
