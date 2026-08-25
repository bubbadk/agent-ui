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

### Security model (v0.2)

* Tools can only touch paths inside `<repo>/workspace/`.
* `run_command` allowlists binaries (ls, cat, grep, python3, git, …), rejects
  all shell operators (`; | & \`` etc.), runs with `shell=False`, 30s timeout.
* Every capability is scoped and logged: `fs:write workspace/`,
  `net:get`, `shell:sandbox` — shown live (with countdown) in the UI.
* Strict gates: a task is only COMMITTED if every acceptance check passes,
  otherwise it is BLOCKED and recorded as such.

### Tools (v0.4)

`set_plan` (publishes the plan shown in the UI) · `complete_step` (marks plan
progress) · `write_file` · `read_file` · `list_dir` · `run_tests` (py-compile
acceptance check) · `run_command` (allowlisted, sandboxed) · `web_fetch`
(SSRF-guarded) · `spawn_subagent` (delegation)

### Subagents (v0.4)

`spawn_subagent` runs a sub-goal through a fresh agent instance that shares
the ledger (its events are visible in the same timeline). Guardrails:

* **Depth limit**: max 2 levels — a subagent cannot spawn further subagents.
* **Budget**: each subagent gets a cost cap (`sub_budget`, default $0.50);
  exceeding it blocks the subagent and returns the reason to the parent.
* The parent receives the child's summary as a tool result and uses it in
  its own work (e.g. delegating research, then writing the report).

## Tests

```bash
python3 -m unittest tests.test_engine -v
```
