/* Atlas live-engine wiring.
 * If the local engine (server/server.py) answers, the dashboard switches to
 * LIVE mode and renders real ledger data. Otherwise it stays a mockup.
 * Rendering is incremental + change-detected so nothing blinks. */
(function () {
  'use strict';

  var TAGMAP = {
    TASK_STARTED: 'tg-mem', MODEL_CALL: 'tg-route', TOOL_CALL: 'tg-tool',
    TOOL_RESULT: 'tg-tool', CAPABILITY_GRANTED: 'tg-sec',
    VERIFY_RUN: 'tg-fold', COMMITTED: 'tg-ok',
    TASK_COMPLETED: 'tg-ok', TASK_BLOCKED: 'tg-sec'
  };
  var MK = { done: '\u2713', running: '\u25c8', blocked: '\u25ae', pending: '\u00b7' };
  var seen = { consoleUpTo: 0, treeSig: '', tableSig: '', lastReply: 0 };
  var replyCard = null;

  function el(id) { return document.getElementById(id); }
  function esc(x) {
    return String(x == null ? '' : x)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;');
  }

  async function health() {
    try {
      var r = await fetch('/api/health', { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  }

  function shortDetail(e) {
    var d = e.detail || {};
    return d.goal || d.preview ||
      (d.args ? d.tool + ' ' + JSON.stringify(d.args).slice(0, 80) : '') ||
      (d.scope ? d.scope + ' granted' : '') ||
      (typeof d.passed === 'boolean' ? 'gates passed=' + d.passed : '') ||
      (d.summary ? d.summary.slice(0, 80) : '') || '';
  }

  function lineHtml(e) {
    return '<div class="ln"><span class="t">' + e.t + '</span> ' +
      '<span class="tag ' + (TAGMAP[e.kind] || 'tg-ok') + '">' +
      e.kind.replace('TASK_', '').replace('_', ' ') + '</span>' +
      esc(shortDetail(e)).slice(0, 110) + '</div>';
  }

  /* append only NEW lines — existing lines are never touched, so their
     fade-in animation does not re-trigger (no blinking) */
  function renderConsole(ledger) {
    var c = el('console');
    if (!ledger.length) return;
    if (state_consoleEmpty()) {
      c.innerHTML = ledger.slice(-40).map(lineHtml).join('');
    } else {
      ledger.forEach(function (e) {
        if (e.id > seen.consoleUpTo) c.insertAdjacentHTML('beforeend', lineHtml(e));
      });
      while (c.children.length > 60) c.removeChild(c.firstChild);
    }
    seen.consoleUpTo = ledger[ledger.length - 1].id;
    c.scrollTop = c.scrollHeight;
  }
  function state_consoleEmpty() {
    return seen.consoleUpTo === 0 || el('console').children.length === 0;
  }

  function renderTree(tree) {
    var sig = JSON.stringify(tree);
    if (sig === seen.treeSig) return;          // unchanged -> touch nothing
    seen.treeSig = sig;
    if (!tree.length) { el('tree').innerHTML = ''; return; }
    el('tree').innerHTML = tree.map(function (n) {
      return '<div class="node ' + n.s + '" data-depth="' + n.d + '">' +
        '<span class="mk' + (n.s === 'running' ? ' spin' : '') + '">' +
        MK[n.s] + '</span><span class="ti">' + esc(n.t) + '</span>' +
        '<span class="st">' + n.s + '</span></div>';
    }).join('');
  }

  function renderTable(ledger) {
    var rows = ledger.filter(function (e) {
      return e.kind === 'MODEL_CALL' || e.kind === 'COMMITTED';
    });
    var last = rows.length ? rows[rows.length - 1].id : 0;
    if (last === seen.tableSig) return;        // unchanged -> touch nothing
    seen.tableSig = last;
    var html = rows.slice(-6).map(function (e) {
      var m = e.model || '';
      return '<tr>' +
        '<td style="padding:6px 8px;color:var(--mut)">' + e.t + '</td>' +
        '<td style="padding:6px 8px">' + esc(e.kind.toLowerCase()) + '</td>' +
        '<td style="padding:6px 8px;color:' +
        (m.indexOf('mock') === 0 || m.indexOf('local') === 0 ||
         m.indexOf('mini') >= 0 ? 'var(--mut)' : 'var(--acc)') +
        '">' + esc(m) + '</td>' +
        '<td style="padding:6px 8px;text-align:right">' +
        ((e.tokens && (e.tokens['in'] + e.tokens.out)) || '-') + '</td>' +
        '<td style="padding:6px 8px;text-align:right">$' +
        (e.cost != null ? (e.cost.toFixed ? e.cost.toFixed(4) : e.cost) : '0') +
        '</td></tr>';
    }).join('') +
      '<tr><td colspan="4" style="padding:7px 8px;border-top:1px solid var(--ink);font-weight:600">TOTAL</td>' +
      '<td style="padding:7px 8px;text-align:right;border-top:1px solid var(--ink);font-weight:600">$' +
      (rows.reduce(function (a, e) { return a + (e.cost || 0); }, 0)).toFixed(4) +
      '</td></tr>';
    el('ledgerBody').innerHTML = html;
  }

  function renderReply(ledger) {
    var fin = null;
    ledger.forEach(function (e) {
      if (e.kind === 'TASK_COMPLETED' || e.kind === 'TASK_BLOCKED') fin = e;
    });
    if (!fin || fin.id === seen.lastReply) return;   // unchanged -> no touch
    seen.lastReply = fin.id;
    var text = (fin.kind === 'TASK_BLOCKED' ? 'BLOCKED — ' : '') +
      (fin.detail.summary || fin.detail.reason || '');
    if (!text || !replyCard) return;
    el('replyBody').textContent = text;
    replyCard.style.display = '';
  }

  function render(s) {
    renderConsole(s.ledger);
    renderTree(s.tree || []);
    renderTable(s.ledger);
    renderReply(s.ledger);
    el('sbCaps').innerHTML = s.caps.map(function (cp) {
      return '<span class="chip"><b>' + esc(cp.scope) + '</b>' + cp.left + '</span>';
    }).join('');
    el('budTxt').textContent =
      '$' + s.budget.spent.toFixed(2) + '/$' + s.budget.limit.toFixed(0);
    el('budBar').style.width =
      Math.min(100, s.budget.spent / s.budget.limit * 100) + '%';
  }

  async function init() {
    var h = await health();
    if (!h || !h.ok) return;               // stay in demo/mockup mode

    window.__ATLAS_LIVE__ = true;          // silence the demo simulators
    document.querySelector('.edition').textContent =
      'FUSION · LIVE ENGINE (' + h.provider + ')';

    var form = document.createElement('form');
    form.style.cssText = 'display:flex;gap:8px;margin-bottom:12px';
    form.innerHTML =
      '<input id="goalIn" placeholder="Give the agent a goal…" style="flex:1;' +
      'background:none;border:1px solid var(--gborder);color:inherit;' +
      'font-family:var(--mono);font-size:12px;padding:9px 12px;border-radius:99px">' +
      '<button type="submit" class="tbtn" style="border-color:var(--acc);color:var(--acc)">RUN</button>';
    el('console').insertAdjacentElement('beforebegin', form);

    replyCard = document.createElement('div');
    replyCard.className = 'glass card';
    replyCard.style.cssText = 'margin-bottom:16px;display:none';
    replyCard.innerHTML = '<h3 class="ct">AGENT REPLY</h3>' +
      '<div id="replyBody" style="font-style:italic;line-height:1.65"></div>';
    form.insertAdjacentElement('afterend', replyCard);

    form.onsubmit = async function (ev) {
      ev.preventDefault();
      var g = el('goalIn').value.trim();
      if (!g) return;
      await fetch('/api/task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: g })
      });
      el('goalIn').value = '';
      toast('Task started');
    };

    async function loop() {
      try {
        var r = await fetch('/api/state', { cache: 'no-store' });
        if (r.ok) render(await r.json());
      } catch (e) { /* engine went away; keep last frame */ }
    }
    setInterval(loop, 2000);
    loop();
  }

  init();
})();
