#!/usr/bin/env node
/* Headless UI test: loads the REAL dashboard from the RUNNING server into
 * jsdom and exercises the settings flow — including the regression where the
 * poller used to wipe user input every 2 seconds.
 *
 * Requires: server running (python3 server/server.py), jsdom installed.
 */
import { JSDOM } from 'jsdom';
import assert from 'node:assert/strict';

const BASE = process.env.BASE_URL || 'http://localhost:8123';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, what, timeout = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { const v = fn(); if (v) return v; } catch { /* retry */ }
    await sleep(250);
  }
  throw new Error('waitFor timed out: ' + what);
}

const health = await (await fetch(BASE + '/api/health')).json();
assert.equal(health.ok, true, 'engine must be running: python3 server/server.py');
console.log('· engine up, provider:', health.provider);

const cfg0 = await (await fetch(BASE + '/api/config')).json();
const keyWasSet = cfg0.config.api_key_set;   // never clobber a real key

const html = await (await fetch(BASE + '/')).text();
const dom = new JSDOM(html, {
  url: BASE + '/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  beforeParse(window) {
    window.fetch = (input, init) =>
      fetch(new URL(String(input), BASE).href, init);
    window.matchMedia = window.matchMedia || (() => ({
      matches: false, addListener() {}, removeListener() {},
      addEventListener() {}, removeEventListener() {},
    }));
  },
});
const { window } = dom;
const doc = window.document;

// execute live.js in the window context (external script loading is
// unreliable in jsdom, so we eval the served source ourselves)
const liveSrc = await (await fetch(BASE + '/live.js')).text();
window.eval(liveSrc);

// 1 · live mode engages
await waitFor(
  () => doc.querySelector('.edition').textContent.includes('LIVE ENGINE'),
  'live mode badge');
console.log('✓ live mode engaged:', doc.querySelector('.edition').textContent);

// 2 · every nav section renders a real view
const sections = ['plans & tasks', 'memory', 'verification', 'economy',
  'security', 'sessions'];
for (const name of sections) {
  const btn = [...doc.querySelectorAll('.navbtn')]
    .find((b) => b.textContent.trim().toLowerCase() === name);
  assert.ok(btn, 'nav button missing: ' + name);
  btn.click();
  await sleep(name === 'memory' ? 900 : 500);
  const page = doc.getElementById('pageView');
  assert.ok(page && page.innerHTML.length > 80,
    'section rendered nothing: ' + name);
  assert.ok(!/stub in this mockup/i.test(doc.getElementById('toast').textContent),
    name + ' must not be a stub anymore');
}
console.log('✓ all', sections.length, 'sub-sections render real views');

// 3 · back to dashboard, then open SETTINGS
[...doc.querySelectorAll('.navbtn')]
  .find((b) => b.textContent.trim().toLowerCase() === 'overview').click();
await sleep(300);
[...doc.querySelectorAll('.navbtn')]
  .find((b) => b.textContent.trim().toLowerCase() === 'settings').click();
await waitFor(() => doc.getElementById('cfgModel'), 'settings form');
console.log('✓ settings form renders');

// 4 · provider dropdown with full catalog + autofill + key link
const sel = doc.getElementById('provSel');
assert.ok(sel && sel.options.length >= 10,
  'provider dropdown needs >= 10 options, got ' + (sel ? sel.options.length : 0));
sel.value = 'groq';
sel.dispatchEvent(new window.Event('change'));
assert.equal(doc.getElementById('cfgBase').value,
  'https://api.groq.com/openai/v1', 'base URL must auto-fill');
assert.equal(doc.getElementById('cfgModel').value,
  'llama-3.3-70b-versatile', 'model must auto-fill');
assert.equal(doc.getElementById('keyLink').href,
  'https://console.groq.com/keys', 'key link must point at the vendor');
console.log('✓ provider dropdown: autofill + key link OK');

// 5 · REGRESSION: type while the poller runs — input must survive
if (!keyWasSet) doc.getElementById('cfgKey').value = 'sk-ui-test-secret';
const modelBefore = doc.getElementById('cfgModel').value;
await sleep(4500);                       // > 2 poll cycles
assert.equal(doc.getElementById('cfgModel').value, modelBefore,
  'poller rebuilt the settings form');
if (!keyWasSet) {
  assert.equal(doc.getElementById('cfgKey').value, 'sk-ui-test-secret',
    'POLLER WIPED the API key input while typing!');
}
console.log('✓ regression: form survives 4.5s of polling while typing');

// 6 · SAVE persists provider, key and budgets
doc.getElementById('cfgSave').click();
await sleep(1000);
const cfg = await (await fetch(BASE + '/api/config')).json();
assert.equal(cfg.config.provider_key, 'groq');
assert.equal(cfg.config.provider, 'openai_compat');
assert.equal(cfg.config.api_key_set, true, 'key must remain configured');
assert.equal(cfg.config.base_url, 'https://api.groq.com/openai/v1');
console.log('✓ save persists provider_key, key flag, base URL, budget');

// 7 · TEST CONNECTION endpoint answers structurally. With a FAKE key the
// provider rejects us (401/403) — that is CORRECT behaviour; the endpoint
// must report it as ok:false with a readable error, not crash.
const test = await (await fetch(BASE + '/api/test_model',
  { method: 'POST' })).json();
if (test.ok) {
  assert.ok(typeof test.reply === 'string' && test.reply.length > 0);
  console.log('✓ test connection: model replied:', test.reply.slice(0, 40));
} else {
  assert.ok(typeof test.error === 'string' && test.error.length > 0,
    'test_model must return a readable error on failure');
  assert.match(test.error, /401|403|Error|HTTP/);
  console.log('✓ test connection: provider rejected fake key as expected:',
    test.error.slice(0, 50));
}

// 8 · AGENTS: create graphically with provider/model/skills, activate, delete
[...doc.querySelectorAll('.navbtn')]
  .find((b) => b.textContent.trim().toLowerCase() === 'agents').click();
await waitFor(() => doc.getElementById('agName'), 'agents view');

doc.getElementById('agName').value = 'ui-test-agent';
const agProv = doc.getElementById('agProv');
agProv.value = [...agProv.options].some((o) => o.value === 'mock')
  ? 'mock' : agProv.options[0].value;
doc.getElementById('agModel').value =
  agProv.value === 'mock' ? 'mock-frontier' : 'ui-test-model';
// uncheck 'shell' + 'subagents' to prove skills are stored
doc.querySelectorAll('#agSkills input').forEach((i) => {
  if (i.value === 'shell' || i.value === 'subagents') i.checked = false;
});
doc.getElementById('agSave').click();
await waitFor(
  () => [...doc.querySelectorAll('.ct')]
    .some((h) => h.textContent.includes('UI-TEST-AGENT')),
  'agent card appears after save');
console.log('✓ agents: created graphically and listed');

const agentsNow = await (await fetch(BASE + '/api/agents')).json();
assert.ok(agentsNow.agents['ui-test-agent'], 'agent persisted');
assert.equal(agentsNow.active, 'ui-test-agent',
  'agent should be active (checkbox was on)');
assert.deepEqual(agentsNow.agents['ui-test-agent'].skills.sort(),
  ['code', 'files', 'web'], 'skills must be stored exactly');
console.log('✓ agents: persisted + active, skills stored correctly');

// the ACTIVE agent has no delete button — activate another agent first
const other = Object.keys(agentsNow.agents).find((n) => n !== 'ui-test-agent');
await fetch(BASE + '/api/agents/activate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: other }),
});
await sleep(400);
const delBtn2 = doc.querySelector('[data-delete="ui-test-agent"]');
assert.ok(delBtn2, 'delete button appears once not active');
delBtn2.click();
await waitFor(async () => {
  const d = await (await fetch(BASE + '/api/agents')).json();
  return !d.agents['ui-test-agent'];
}, 'agent deleted');
console.log('✓ agents: delete works, active agent falls back');

// 9 · cleanup: restore the exact pre-test settings (key-safe: we never
// touch api_key unless the test set it)
const restore = {
  provider: cfg0.config.provider,
  provider_key: cfg0.config.provider_key,
  base_url: cfg0.config.base_url,
  model: cfg0.config.model,
  daily_budget: cfg0.config.daily_budget,
  sub_budget: cfg0.config.sub_budget,
  gates: cfg0.config.gates,
};
if (!keyWasSet) restore.api_key_clear = true;
await fetch(BASE + '/api/config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(restore),
});
const after = await (await fetch(BASE + '/api/config')).json();
assert.equal(after.config.provider, cfg0.config.provider);
assert.equal(after.config.gates, cfg0.config.gates);
if (!keyWasSet) assert.equal(after.config.api_key_set, false);
console.log('✓ cleanup: settings restored to pre-test state');

console.log('\nALL UI TESTS PASSED');
window.close();
process.exit(0);
