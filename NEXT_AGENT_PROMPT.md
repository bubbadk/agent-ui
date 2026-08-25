# NEXT_AGENT_PROMPT.md

> Copy-paste teksten i boksen herunder direkte til den næste agent.
> (Denne fil er selve prompten; fuld dokumentation ligger i `HANDOVER.md`.)

---

```text
Du overtager projektet "Atlas/Fusion" — et self-hosted AI-agent-system
(Python stdlib-only engine + grafisk dashboard) som allerede ER i drift og
verificeret. Din allerførste opgave er AT SÆTTE DIG IND, ikke at bygge noget.

START HER (obligatorisk, i denne rækkefølge):
1. Læs /home/bubbadk/agent-ui/HANDOVER.md FULDT. Den er eneste kilde til
   sandhed og dækker: arkitektur, alle API-routes, alt færdigt arbejde pr.
   commit, config-format, bugfix-historik, backlog og overdragelses-checkliste.
   Dokumentér selv alle nye ændringer i `.md`, så næste session kan overtage
   uden mundtlig kontekst.
2. Kør verifikationen i HANDOVER.md §2 og bekræft at ALT er grønt FØR du
   laver noget som helst andet:
   - curl http://127.0.0.1:8123/api/health          → {"ok": true, ...}
   - curl 'http://127.0.0.1:8123/api/models?provider_key=openrouter' → ok:true
   - python3 -m unittest tests.test_engine           → 17 tests, OK
   - node tests/ui_test.mjs                          → ALL UI TESTS PASSED

HARDE KONSTRAINTER (overtrædelse = ødelagt arbejde):
- Projektet bor i /home/bubbadk/agent-ui. /mnt/iaasc er root-ejet og
  skrivebeskyttet — rør det ALDRIG, dets kopier er forældede.
- Serveren kører på port 8123. Port 8787 er PERMANENT optaget af et andet
  system (Hermes) — brug den aldrig.
- Config (~/.agentui/config.json) indeholder en RIGTIG API-nøgle. Skriv
  ALDRIG nøglen til output, logs, tests eller git. Tests skal være
  key-safe: gendan præcis pre-test-tilstand.
- Python-kode skal være stdlib-only. Ingen nye pip-afhængigheder.
- UI-logik samles i fusion/live.js (vanilla JS) — følg eksisterende stil.

PROCESSREGLER (brugerens krav, ingen undtagelser):
1. Verificér FØR du siger "færdig": kør BEGGE test-suitter (unittest +
   node tests/ui_test.mjs) efter hver ændring. jsdom-suitten er projektets
   "done"-gate og har historisk fanget 3 rigtige bugs.
2. Læs HANDOVER.md §6 først — tre bug-mønstre må ALDRIG genindføres:
   a) self.path i BaseHTTPRequestHandler INDHOLDER query-strengen — match
      routes med urlparse(self.path).path eller startswith, aldrig ==.
   b) Ingen lokale re-imports af navne der allerede er importeret på
      modul-niveau i samme funktion (giver UnboundLocalError).
   c) 2-sekunders-polleren må ALDRIG skrive Settings/Agents/Memory-
      formularer — KUN SAVE-knappen gemmer dem.
3. Efter ændringer i server-kode: genstart serveren
   (pkill -f 'server/server.py'; cd /home/bubbadk/agent-ui && nohup
   python3 server/server.py > /tmp/atlas-server.log 2>&1 &) og kør
   begge suitter igen.
4. Commit og push ALLE ændringer til github.com/bubbadk/agent-ui (main).
5. Kommunikér med brugeren på dansk. UI er engelsk, manualen dansk.

AKTUEL STATUS OG FØRSTE OPGAVE:
Cron / standing orders og durable task queue er allerede implementeret og
pushet. Se HANDOVER.md §4.6.1 og §6 for commits `ba3a217`, `3e6fdc9` og
`27ad307`. Implementér ikke disse features igen. Når verifikationen er grøn,
følg backloggen i HANDOVER.md §7: først subagent-visualisering i SECURITY,
derefter dybere Plans & Tasks. Præsenter en kort plan og få godkendelse før
ny feature-implementering.

Status ved overdragelse: standing orders + durable task queue er færdige,
seneste commit `27ad307`, alle tests grønne efter server-genstart, server
kører på 8123, OpenRouter-nøgle er konfigureret via grafisk SETTINGS.
```
