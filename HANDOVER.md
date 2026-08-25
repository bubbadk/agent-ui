# HANDOVER — Atlas/Fusion Agent System

> **Dokumentens formål:** Komplet overdragelses-dokumentation. Enhver ny agent
> (eller udvikler) skal kunne overtage projektet herfra uden at skulle gætte
> noget. Sidst opdateret: **v0.7.1, commit `5753016`** (25. aug 2026).

---

## 1. Projektets identitet

| Emne | Værdi |
|---|---|
| Projektnavn | **Atlas / Fusion ("Aurum Edition")** — self-hosted AI-agent-motor + grafisk dashboard |
| Repo | `github.com/bubbadk/agent-ui` (branch `main`) |
| Lokal sti | **`/home/bubbadk/agent-ui`** (IKKE `/mnt/iaasc` — den er root-ejet og skrivebeskyttet) |
| Server | `python3 server/server.py` → **http://localhost:8123** (8787 var optaget af Hermes — brug ALDRIG 8787) |
| Teknologi | Python **stdlib-only** (ingen pip-afhængigheder), UI = vanilla JS (én fil: `fusion/live.js`), tests via Node + jsdom |
| Python-version | 3.14 (system-python) |
| Config | `~/.agentui/config.json` (redigeres KUN via grafisk SETTINGS — ikke i hånden mens serveren kører) |
| Data | `data/ledger.jsonl` (append-only hovedbog) + `data/memory.json` (episodisk hukommelse) |
| Sandbox | Alt tool-arbejde låses til `<repo>/workspace/` |

**Kører lige nu:** Serveren kører som `nohup python3 server/server.py` med log
i `/tmp/atlas-server.log`. Genstart: `pkill -f 'server/server.py'` og start
igen som ovenfor.

---

## 2. Verificér at alt virker (første 2 minutter som ny agent)

```bash
cd /home/bubbadk/agent-ui

# 1. Serveren svarer?
curl -s http://127.0.0.1:8123/api/health
# forventet: {"ok": true, "provider": "openai_compat"}

# 2. Model-liste (bugfixet i 5753016 — se §6):
curl -s 'http://127.0.0.1:8123/api/models?provider_key=openrouter' | head -c 200
# forventet: {"ok": true, "models": ["aion-labs/...", ...]}  (hundredvis af modeller)

# 3. Engine-tests (17 stk):
python3 -m unittest tests.test_engine -v          # forventet: OK, 17 tests

# 4. UI-tests (headless jsdom — dette er projektets "done"-gate):
node tests/ui_test.mjs                            # forventet: ALL UI TESTS PASSED
```

**PROCESSREGEL fra brugeren:** Verificér FØR du siger "færdig". jsdom-suitten
er gate'en — den har allerede fanget 3 rigtige bugs (se §6).

---

## 3. Filoversigt (ansvarsfordeling)

```
fusion/concept-4-fusion.html   Dashboard-UI (demo/mockup når åbnet som fil; LIVE når serveren kører)
fusion/live.js        (931 l)  AL UI-logik: poller, LIVE-detektion, alle 9 sektioner, settings, agent-builder
fusion/manual.html    (244 l)  Dansk brugermanual, serveres på /manual (📖-link i masthead)
server/server.py      (390 l)  stdlib HTTP-server: statiske filer + REST API (alle routes i §5)
engine/agent.py       (187 l)  Agent-løkke: plan → act (tools) → verify-gate → commit
engine/providers.py   (210 l)  Mock-provider + OpenAI-kompatibel provider (chat-completions)
engine/tools.py       (232 l)  Sandkassede tools + SKILL_MAP (skill → tool-navne)
engine/ledger.py       (64 l)  Append-only JSONL-ledger med cost-estimering
engine/memory.py       (60 l)  Episodisk hukommelse + nøgleordssøgning
engine/config.py      (118 l)  ~/.agentui/config.json: load/save, migration, effective_task_cfg()
tests/test_engine.py  (273 l)  17 unittests (end-to-end + security)
tests/ui_test.mjs     (208 l)  Headless jsdom UI-suite (kører mod den RIGTIGE server på 8123)
tests/debug_live.mjs           Debug-hjælper til live.js
index.html                     Galleri/forside med links til alle 4 designkoncepter
nexus|aura|atlas/*.html        De 3 andre designkoncepter (historisk/bevaringsværdige)
```

---

## 4. Detaljeret: hvad er FÆRDIGT (pr. commit)

Hvert punkt er **verificeret** og kan overtages som det er. Commit-referencer
i parentes.

### 4.1 Design-fase (`4f92751`)
- 4 designkoncepter som selvstændige, klikbare HTML-prototyper:
  `nexus/` (Nexus HUD), `aura/` (Aura glass), `atlas/` (Atlas ledger),
  `fusion/` (Fusion = blandingen af alle tre — **det valgte koncept**).
- Fusion-prototypen: 12 hovedsektioner / 50 undermenuer, engelsksproget.
- `index.html` = galleri med links til alle koncepter.

### 4.2 Dansk brugermanual (`208c543`)
- `fusion/manual.html`, serveres på **/manual**, 📖-link i masthead.

### 4.3 Engine-kernen (`fd5ae78` → `c27fff7`)
- **Agent-løkke** (`engine/agent.py`): `set_plan` (2–4 steps) → act med tools →
  **verify-gate** → commit. Gates: `strict` (resultater SKAL bestå checks),
  `advisory`, `draft`.
- **Providers** (`engine/providers.py`): deterministisk mock (demo uden nøgle;
  vejr-mål henter RIGTIGE data via web_fetch) + OpenAI-kompatibel provider.
- **Tools** (`engine/tools.py`), alle sandkassede til `workspace/`:
  `read_file`, `write_file`, `list_dir`, `run_tests`, `run_command`
  (binær-allowlist: ls, cat, grep, python3, git …; shell-operatorer `; | & \``
  afvises; `shell=False`; 30 s timeout), `web_fetch` (SSRF-guard: blokerer
  localhost/privat-IP), `spawn_subagent` (depth ≤ 2, budget-cap),
  `set_plan`/`complete_step` (driver UI'ets plan-træ).
- **Ledger** (`engine/ledger.py`): append-only JSONL; cost-estimering
  $0.15/M input + $0.60/M output tokens; `spent()` og `tail(n)` bruges af API.
- **Memory** (`engine/memory.py`): episodisk hukommelse; `retrieve(goal)`
  indsprøjtes i system-prompt; `search(q)` eksponeres via API.
- **Sikkerhedsmodel**: default-deny capabilities med udløbende grants (logges
  i ledger, vises med nedtælling i UI), path-jail til workspace/,
  allowlistet shell, SSRF-guard, subagent depth/budget-caps.
- **Subagents** (`c27fff7`): `spawn_subagent` med depth ≤ 2 og per-subagent
  budget (`sub_budget`, default $0.5).

### 4.4 Server + LIVE-wiring (`c9620bf` → `517f396`)
Alle REST-routes i `server/server.py`:

| Method | Route | Formål |
|---|---|---|
| GET | `/api/health` | ok-flag + provider-navn |
| GET | `/api/state` | HELE live-tilstanden: ledger-tail, plan-træ, grants, budget, phase, aktiv agent |
| GET | `/api/models?provider_key=X` | LIVE modelliste fra providerens `{base_url}/models` (mock → `["mock-frontier"]`). **Bugfixet i `5753016`** — se §6 |
| GET | `/api/config` | Engine-settings (nøgle ALDRIG med — kun `api_key_set`-flag) |
| GET | `/api/agents` | Alle agenter + aktiv agent + gyldige provider_keys |
| GET | `/api/memory[?q=]` | Episoder / nøgleordssøgning |
| GET | `/api/task_events?start=ID` | Event-replay af én task (fra TASK_STARTED-id) |
| POST | `/api/task` | Start ny task (afviser hvis én kører) — baggrundstråd |
| POST | `/api/config` | Gem settings (provider, model, base_url, budgetter, gates) |
| POST | `/api/test_model` | Test-forbindelse (fejler læsbart på 401/403) |
| POST | `/api/gates` | Skift gate runtime (strict/advisory/draft) |
| POST | `/api/agents` | Opret agent (navn valideres `[a-z0-9][a-z0-9_-]{0,31}`) |
| POST | `/api/agents/activate` | Sæt aktiv agent |
| POST | `/api/agents/delete` | Slet agent (fallback til forrige aktiv) |
| GET | `/manual`, `live.js`, statisk | Filservering med path-jail (`realpath` + ROOT-præfiks) |

### 4.5 UI — `fusion/live.js` (`f0ab8fe` → `517f396`)
- **LIVE-detektion**: poller `/api/health`; uden server = design-mockup, med
  server = "FUSION · LIVE ENGINE"-badge. Demo-løkker slås fra via
  `window.__ATLAS_LIVE__`.
- **Inkrementel rendering**: change-detected DOM-opdatering (ingen blinking,
  fixet i `f16b1f7`). AGENT REPLY-kort viser agentens slutsummarie.
- **Alle 9 navsektioner viser rigtige data** (`1979d7e`, `b1780e4`,
  `1811384`): herunder Sessions-replay-overlay, memory-søgning, Economy
  (ledger), SECURITY (grants med nedtælling), runtime gate-skift.
- **SETTINGS (v0.6, `9165ddd` + `714d333`)**: grafisk form, "SAVED TO
  ~/.agentui/config.json". 12 providere i `PROVIDERS`-objektet (live.js:252):
  mock, openai, openrouter, anthropic, gemini, groq, mistral, deepseek, xai,
  together, ollama, lmstudio, custom. Valg auto-fylder base_url + default
  model + direkte link til providerens key-side. `↻ MODELS` henter levende
  modelliste → datalist. `TEST CONNECTION` viser 401/403 læsbart.
  **KRITISK DETALJE:** Settings/Memory/Agents-visninger er fritaget for
  2-sekunders-polleren — KUN SAVE skriver dem (poller-reset-bug, se §6).
- **AGENTS — grafisk agent-builder (v0.7, `517f396`)**: navn, provider, model
  (med live-liste), skills-checkboxes, persona-prompt; activate/delete;
  aktiv agent vises i masthead.

### 4.6 Bot Mode / multi-agent (v0.7)
- **Provider-registry** i config: `providers.<key> = {base_url, model,
  api_key}` pr. leverandør. Legacy topnøgler (`base_url`, `api_key`) migreres
  automatisk ved load (`engine/config.py`).
- **Nøgle-prioritet** i `effective_task_cfg()`: **env-var > provider-key >
  legacy-key**.
- **SKILL_MAP** (`engine/tools.py:142`):
  `files → read_file/write_file/list_dir`, `code → run_tests`,
  `shell → run_command`, `web → web_fetch`, `subagents → spawn_subagent`.
  `set_plan`/`complete_step` er altid tilladt. `skills: null` = ubegrænset.
- Engine filtrerer tools pr. agent ud fra dens skills; persona-prompt appendes
  til system-prompt.
- Default-agent `atlas` seedes ved første kørsel. (Brugerens nuværende config
  har desuden agenten `james`: provider openrouter, model `stealth/ox-alpha`,
  alle 5 skills.)

### 4.7 Test-suite (gate'en)
- **`tests/test_engine.py` — 17 tests, alle grønne:** completed-goal,
  file-written-and-compiles, ledger-pipeline, capability-scope-before-write,
  memory-episode, mock-weather-via-web_fetch, SSRF-guard,
  shell-allowlist+injection-guard, plan-log-before-tools, plan-progress,
  subagent-delegation, memory-search, skills-restrict-tools,
  effective_task_cfg-resolution, config-roundtrip, subagent-depth-limit,
  strict-gate-blocks-on-failure.
- **`tests/ui_test.mjs` — headless jsdom mod rigtig server på 8123:**
  live-mode, alle undersektioner, settings-form, provider-dropdown autofill,
  **regression: form overlever 4,5 s polling mens der tastes**, save
  persistens, test-connection (afviser fake key med 403), agents
  create/persist/activate/delete, **key-safe cleanup: gendanner præcis
  pre-test-tilstand og clobberer ALDRIG en konfigureret API-nøgle**.

---

## 5. Config-format (`~/.agentui/config.json`)

```jsonc
{
  "provider": "openai_compat",          // "mock" eller "openai_compat"
  "base_url": "https://openrouter.ai/api/v1",   // legacy-felt, migreres
  "model": "openrouter/auto",                   // legacy-felt
  "api_key_env": "OPENAI_API_KEY",      // navn på env-var (prioritet 1)
  "api_key": "...",                     // legacy (prioritet 3)
  "gates": "strict",
  "daily_budget": 20.0,
  "sub_budget": 0.5,
  "provider_key": "openrouter",         // aktiv provider i registry
  "providers": {
    "openrouter": { "base_url": "...", "model": "...", "api_key": "..." }
  },
  "agents": {
    "<navn>": { "label": "...", "provider_key": "...", "model": "...",
                "skills": ["files","code","shell","web","subagents"],
                "prompt": "persona..." }
  },
  "active_agent": "<navn>"
}
```

---

## 6. Bugfix-historik (lær af disse — mønstrene gentager sig)

| Commit/lektion | Bug | Rodårsag & fix |
|---|---|---|
| `f16b1f7` | UI blinkede konstant i live-mode | Fuld re-render hver poll → inkrementel change-detected rendering |
| `714d333` | Settings resettede til "mock" | 2 s-poller overskrev formen mens man tastede → settings/agents/memory fritaget for poller; kun SAVE skriver |
| (fanget af suite) | `CRIT` vs `CRITS`-typo | Fanget af jsdom-suiten |
| (fanget af suite) | `UnboundLocalError` i `do_POST` | Fanget af suitten |
| **`5753016`** (nyeste) | **"Model list failed: not found"** i SETTINGS | `/api/models` blev matchet med `self.path == '/api/models'`, men `self.path` INDLUDERER query-strengen (`?provider_key=...`) → faldt igennem til 404. **Fix:** match på `urlparse(self.path).path`. `urlparse` er nu importeret på modul-niveau, og de lokale `from urllib.parse import parse_qs, urlparse` i `/api/memory`- og `/api/task_events`-grene er fjernet (lokale imports skygger modul-navnet og giver `UnboundLocalError`). |

**Mønstre at huske:**
1. `self.path` i `BaseHTTPRequestHandler` indeholder query-strengen — brug
   ALTID `urlparse(self.path).path` til route-matching (eller `startswith`).
2. Ingen lokale re-imports af navne der findes på modul-niveau i samme funktion.
3. Polleren må ALDRIG skrive formularer — kun SAVE gør det.

---

## 7. Hvad MANGLER (backlog — aftalt med brugeren, i prioriteret rækkefølge)

1. **Cron / standing orders** — planlagte opgaver (f.eks. "kør hver morgen").
   Skitse: schedule-felt i config/UI + baggrundstråd i `server.py` der kalder
   `Agent.run()` + ledger-entry `SCHEDULED_RUN`.
2. **Task-kø + durable execution** — tasks skal overleve server-genstart
   (persistér køen i `data/`, genoptag ved boot). I dag: nye tasks afvises
   mens én kører, og en kørende task DØR ved genstart.
3. **Subagent-visualisering i SECURITY-view** — subagent-depth/grants findes i
   ledgeren men vises ikke grafisk endnu.
4. **Dybere Plans & Tasks** — task-kø-listing i UI (kørende/kø/afsluttede).

### Øvrige åbne punkter
- **Rig LLM-kørsel**: OpenRouter-nøgle ER konfigureret (via grafisk SETTINGS),
  men der mangler en end-to-end verificering af en RIGTIG task med rigtig
  model (indtil nu er reelle kørsler testet med mock + 401/403-paths).
- **README.md er forældet**: skriver stadig "Status: v0.1" og viser kun
  legacy-config uden providers/agents. Bør opdateres til v0.7 (eller pege på
  denne fil + manualen).
- `/mnt/iaasc` er root-ejet og skrivebeskyttet — projektet lever UDDELØST
  under `/home/bubbadk/agent-ui`. Kopier i `/mnt/iaasc` er forældede.
- Port 8123 er hårdkodet i `server.py` — overvej CLI-arg/env, men 8787 må
  IKKE bruges (optaget af Hermes permanent).
- `engine/__init__.py` er 1 linje — engine-moduler importerer indbyrdes med
  bare modulnavne (virker kun når sys.path inkluderer `engine/`); fint indtil
  videre, men en rigtig pakke-gøring ville være pænere.

---

## 8. Overdragelses-checkliste

1. Kør verifikationen i §2 — alt skal være grønt FØR du bygger videre.
2. Læs §6 (bug-mønstre) — undgå at genindføre dem.
3. Nye features: følg backlog-rækkefølgen i §7, eller spørg brugeren.
4. Alle ændringer commites og pushes til `github.com/bubbadk/agent-ui`
   (main). Seneste push: `5753016`.
5. Efter server-kodeændringer: genstart (`pkill -f 'server/server.py'`, start
   igen med nohup, log til `/tmp/atlas-server.log`) og kør BEGGE
   test-suitter igen.
6. Sprog: brugeren kommunikerer på dansk; UI er engelsk, manualen dansk.
   Brugerens kerneregel: **verificér før du siger "færdig"**.


