/* Atlas live-engine wiring.
 * If the local engine (server/server.py) answers, the dashboard switches to
 * LIVE mode and renders real ledger data. Otherwise it stays a mockup. */
(function () {
  'use strict';

  var TAGMAP = {
    TASK_STARTED: 'tg-mem', MODEL_CALL: 'tg-route', TOOL_CALL: 'tg-tool',
    TOOL_RESULT: 'tg-tool', CAPABILITY_GRANTED: 'tg-sec',
    VERIFY_RUN: 'tg-fold', COMMITTED: 'tg-ok',
    TASK_COMPLETED: 'tg-ok', TASK_BLOCKED: 'tg-sec'
  };
  var MK = { done: '\u2713', running: '\u25c8', blocked: '\u25ae', pending: '\u00b7' };

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

  function render(s) {
    var c = el('console');
    c.innerHTML = s.ledger.map(function (e) {
      return '<div class="ln"><span class="t">' + e.t + '</span> ' +
        '<span class="tag ' + (TAGMAP[e.kind] || 'tg-ok') + '">' +
        e.kind.replace('TASK_', '').replace('_', ' ') + '</span>' +
        esc(shortDetail(e)).slice(0, 110) + '</div>';
    }).join('');
    c.scrollTop = c.scrollHeight;

    if (s.tree && s.tree.length) {
      el('tree').innerHTML = s.tree.map(function (n) {
        return '<div class="node ' + n.s + '" data-depth="' + n.d + '">' +
          '<span class="mk' + (n.s === 'running' ? ' spin' : '') + '">' +
          MK[n.s] + '</span><span class="ti">' + esc(n.t) + '</span>' +
          '<span class="st">' + n.s + '</span></div>';
      }).join('');
    }

    var rows = s.ledger.filter(function (e) {
      return e.kind === 'MODEL_CALL' || e.kind === 'COMMITTED';
    }).slice(-6);
    var total = s.budget.spent;
    el('ledgerBody').innerHTML = rows.map(function (e) {
      var m = e.model || '';
      return '<tr>' +
        '<td style="padding:6px 8px;color:var(--mut)">' + e.t + '</td>' +
        '<td style="padding:6px 8px">' + esc(e.kind.toLowerCase()) + '</td>' +
        '<td style="padding:6px 8px;color:' +
        (m.indexOf('mock') === 0 || m.indexOf('local') === 0 ||
         m.indexOf('gpt-4o-mini') === 0 ? 'var(--mut)' : 'var(--acc)') +
        '">' + esc(m) + '</td>' +
        '<td style="padding:6px 8px;text-align:right">' +
        ((e.tokens && (e.tokens['in'] + e.tokens.out)) || '-') + '</td>' +
        '<td style="padding:6px 8px;text-align:right">$' +
        (e.cost != null ? e.cost.toFixed ? e.cost.toFixed(4) : e.cost : '0') +
        '</td></tr>';
    }).join('') +
      '<tr><td colspan="4" style="padding:7px 8px;border-top:1px solid var(--ink);font-weight:600">TOTAL</td>' +
      '<td style="padding:7px 8px;text-align:right;border-top:1px solid var(--ink);font-weight:600">$' +
      total.toFixed(4) + '</td></tr>';

    el('sbCaps').innerHTML = s.caps.map(function (cp) {
      return '<span class="chip"><b>' + esc(cp.scope) + '</b>' + cp.left + '</span>';
    }).join('');

    el('budTxt').textContent =
      '$' + s.budget.spent.toFixed(2) + '/$' + s.budget.limit.toFixed(0);
    el('budBar').style.width =
      Math.min(100, s.budget.spent / s.budget.limit * 100) + '%';

    var fin = null;
    s.ledger.forEach(function (e) {
      if (e.kind === 'TASK_COMPLETED' || e.kind === 'TASK_BLOCKED') fin = e;
    });
    if (fin && fin.id !== render._lastReply) {
      render._lastReply = fin.id;
      var body = el('replyBody');
      if (body) {
        body.textContent = (fin.kind === 'TASK_BLOCKED'
          ? 'BLOCKED — ' : '') + (fin.detail.summary || fin.detail.reason || '');
        reply.style.display = fin.detail.summary || fin.detail.reason ? '' : 'none';
      }
    }
  }

  async function init() {
    var h = await health();
    if (!h || !h.ok) return;               // stay in demo/mockup mode

    document.querySelector('.edition').textContent =
      'FUSION \u00b7 LIVE ENGINE (' + h.provider + ')';

    var form = document.createElement('form');
    form.style.cssText = 'display:flex;gap:8px;margin-bottom:12px';
    form.innerHTML =
      '<input id="goalIn" placeholder="Give the agent a goal\u2026" style="flex:1;' +
      'background:none;border:1px solid var(--gborder);color:inherit;' +
      'font-family:var(--mono);font-size:12px;padding:9px 12px;border-radius:99px">' +
      '<button type="submit" class="tbtn" style="border-color:var(--acc);color:var(--acc)">RUN</button>';
    el('console').insertAdjacentElement('beforebegin', form);

    var reply = document.createElement('div');
    reply.className = 'glass card';
    reply.style.cssText = 'margin-bottom:16px;display:none';
    reply.innerHTML = '<h3 class="ct">AGENT REPLY</h3>' +
      '<div id="replyBody" style="font-style:italic;line-height:1.65"></div>';
    form.insertAdjacentElement('afterend', reply);

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
    setInterval(loop, 1500);
    loop();
  }

  init();
})();
