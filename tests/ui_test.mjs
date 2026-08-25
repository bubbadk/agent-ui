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
doc.getElementById('cfgKey').value = 'sk-ui-test-secret';
const modelBefore = doc.getElementById('cfgModel').value;
await sleep(4500);                       // > 2 poll cycles
assert.equal(doc.getElementById('cfgKey').value, 'sk-ui-test-secret',
  'POLLER WIPED the API key input while typing!');
assert.equal(doc.getElementById('cfgModel').value, modelBefore,
  'poller rebuilt the settings form');
console.log('✓ regression: form survives 4.5s of polling while typing');

// 6 · SAVE persists provider, key and budgets
doc.getElementById('cfgSave').click();
await sleep(1000);
const cfg = await (await fetch(BASE + '/api/config')).json();
assert.equal(cfg.config.provider_key, 'groq');
assert.equal(cfg.config.provider, 'openai_compat');
assert.equal(cfg.config.api_key_set, true);
assert.equal(cfg.config.base_url, 'https://api.groq.com/openai/v1');
assert.equal(cfg.config.daily_budget,
  parseFloat(doc.getElementById('cfgBudget').value));
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

// 8 · cleanup: back to mock, key cleared
await fetch(BASE + '/api/config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    provider: 'mock', provider_key: 'mock',
    base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini',
    api_key_clear: true, gates: 'strict'
  }),
});
const after = await (await fetch(BASE + '/api/config')).json();
assert.equal(after.config.provider, 'mock');
assert.equal(after.config.api_key_set, false);
console.log('✓ cleanup: mock restored, key cleared');

console.log('\nALL UI TESTS PASSED');
window.close();
process.exit(0);
