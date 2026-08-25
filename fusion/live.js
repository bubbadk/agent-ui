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
  var lastState = null;
  var currentView = 'dashboard';
  var pageEl = null;

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
    lastState = s;
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
    if (currentView !== 'dashboard') renderPage(s);
  }

  function renderEconomy(s) {
    var rows = s.ledger.filter(function (e) { return e.cost != null; });
    var byModel = {};
    rows.forEach(function (e) {
      byModel[e.model] = (byModel[e.model] || 0) + e.cost;
    });
    var chips = Object.keys(byModel).map(function (m) {
      return '<span>' + esc(m) + ' <b style="color:var(--acc)">$' +
        byModel[m].toFixed(4) + '</b></span>';
    }).join('');
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">ECONOMY \u00b7 FULL LEDGER</h3>' +
      '<div style="display:flex;gap:20px;flex-wrap:wrap;font-family:var(--mono);' +
      'font-size:12px;color:var(--mut);margin-bottom:14px">' +
      '<span>TOTAL <b style="color:var(--acc)">$' + s.budget.spent.toFixed(4) +
      '</b> / $' + s.budget.limit.toFixed(0) + '</span>' + chips + '</div>' +
      '<table style="width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11.5px">' +
      '<thead><tr>' +
      ['Time', 'Event', 'Model', 'Tok', 'Cost'].map(function (h, i) {
        return '<th style="text-align:' + (i >= 3 ? 'right' : 'left') +
          ';padding:5px 8px;color:var(--mut);font-weight:400;border-bottom:1px solid var(--ink)">' +
          h.toUpperCase() + '</th>';
      }).join('') + '</tr></thead><tbody>' +
      rows.map(function (e) {
        return '<tr>' +
          '<td style="padding:6px 8px;color:var(--mut)">' + e.t + '</td>' +
          '<td style="padding:6px 8px">' + esc(e.kind.toLowerCase()) + '</td>' +
          '<td style="padding:6px 8px">' + esc(e.model || '') + '</td>' +
          '<td style="padding:6px 8px;text-align:right">' +
          ((e.tokens && (e.tokens['in'] + e.tokens.out)) || '-') + '</td>' +
          '<td style="padding:6px 8px;text-align:right">$' +
          (e.cost.toFixed ? e.cost.toFixed(4) : e.cost) + '</td></tr>';
      }).join('') +
      '</tbody></table>' +
      '<p style="font-style:italic;color:var(--mut);font-size:12.5px;margin-top:10px">' +
      'Showing the recent ledger window (' + rows.length +
      ' priced events). Older entries live in data/ledger.jsonl.</p></div>';
  }

  function renderSessions(s) {
    var tasks = [];
    var cur = null;
    s.ledger.forEach(function (e) {
      if (e.kind === 'TASK_STARTED') {
        cur = { goal: e.detail.goal || '(no goal)', cost: 0,
                status: 'running', summary: '' };
        tasks.push(cur);
      } else if (cur) {
        if (e.cost) cur.cost += e.cost;
        if (e.kind === 'TASK_COMPLETED') {
          cur.status = 'completed';
          cur.summary = e.detail.summary || '';
        } else if (e.kind === 'TASK_BLOCKED') {
          cur.status = 'blocked';
          cur.summary = e.detail.reason || 'gates failed';
        }
      }
    });
    var MK2 = { done: '\u2713', running: '\u25c8', blocked: '\u25ae' };
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">SESSIONS \u00b7 TASK HISTORY</h3>' +
      (tasks.length ? tasks.map(function (t) {
        var cls = t.status === 'completed' ? 'done' : t.status;
        return '<div class="node ' + cls + '">' +
          '<span class="mk">' + MK2[cls] + '</span>' +
          '<span class="ti">' + esc(t.goal) +
          (t.summary ? '<br><small style="color:var(--mut)">' +
           esc(t.summary.slice(0, 140)) + '</small>' : '') +
          '</span><span class="st">' + t.status + ' \u00b7 $' +
          t.cost.toFixed(4) + '</span></div>';
      }).join('')
        : '<p style="font-style:italic;color:var(--mut)">No tasks in the recent ledger window.</p>') +
      '</div>';
  }

  function renderPage(s) {
    if (!pageEl) return;
    if (currentView === 'economy') renderEconomy(s);
    else if (currentView === 'sessions') renderSessions(s);
    else if (currentView === 'plans') renderPlans(s);
    else if (currentView === 'verification') renderVerification(s);
    else if (currentView === 'security') renderSecurity(s);
  }

  function nodeRow(cls, mk, title, sub, st) {
    return '<div class="node ' + cls + '"><span class="mk">' + mk + '</span>' +
      '<span class="ti">' + esc(title) +
      (sub ? '<br><small style="color:var(--mut)">' + esc(sub) + '</small>' : '') +
      '</span><span class="st">' + st + '</span></div>';
  }

  function renderPlans(s) {
    var MKP = { done: '\u2713', running: '\u25c8',
                blocked: '\u25ae', pending: '\u00b7' };
    var vr = null;
    s.ledger.forEach(function (e) { if (e.kind === 'VERIFY_RUN') vr = e; });
    var critHtml;
    if (vr && vr.detail && vr.detail.criteria) {
      critHtml = vr.detail.criteria.map(function (c) {
        return '<div class="node ' + (c.pass ? 'done' : 'blocked') + '">' +
          '<span class="mk">' + (c.pass ? '\u2713' : '\u2717') + '</span>' +
          '<span class="ti">' + esc(c.check) + '</span>' +
          '<span class="st">' + (c.pass ? 'pass' : 'fail') + '</span></div>';
      }).join('');
    } else {
      critHtml = '<p style="font-style:italic;color:var(--mut)">No gate run yet.</p>';
    }
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">PLANS &amp; TASKS \u00b7 CURRENT PLAN</h3>' +
      (s.tree.length ? s.tree.map(function (n) {
        return nodeRow(n.s, MKP[n.s] || '\u00b7', n.t, '', n.s);
      }).join('') :
        '<p style="font-style:italic;color:var(--mut)">No active task. Give the agent a goal on the dashboard.</p>') +
      '</div>' +
      '<div class="glass card" style="margin-top:16px">' +
      '<h3 class="ct">ACCEPTANCE CRITERIA \u00b7 LATEST GATE RUN</h3>' +
      critHtml + '</div>';
  }

  function renderMemory(d) {
    var eps = d.episodes || [];
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">MEMORY \u00b7 EPISODIC STORE (' + d.count + ' entries)</h3>' +
      (eps.length ? eps.map(function (ep) {
        return nodeRow('', '\u25c6', ep.goal,
          ep.t + ' \u00b7 ' + ep.outcome, 'memory');
      }).join('') :
        '<p style="font-style:italic;color:var(--mut)">No episodes yet \u2014 completed tasks are remembered here.</p>') +
      '</div>';
  }

  function renderVerification(s) {
    var runs = s.ledger.filter(function (e) {
      return e.kind === 'VERIFY_RUN';
    });
    var passed = runs.filter(function (e) {
      return e.detail && e.detail.passed;
    }).length;
    var list = runs.slice(-8).reverse().map(function (e) {
      var cs = (e.detail.criteria || []).map(function (c) {
        return '<div style="font-family:var(--mono);font-size:11px;color:var(--mut);padding:2px 0">' +
          (c.pass ? '\u2713' : '\u2717') + ' ' + esc(c.check) + '</div>';
      }).join('');
      return '<div style="border-bottom:1px dotted var(--rule);padding:10px 0">' +
        '<div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px">' +
        '<span>' + e.t + '</span><span style="color:' +
        (e.detail.passed ? 'var(--good)' : 'var(--bad)') + '">' +
        (e.detail.passed ? 'PASS' : 'FAIL') + '</span></div>' + cs + '</div>';
    }).join('');
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">VERIFICATION \u00b7 GATE MODE</h3>' +
      '<div style="font-family:var(--mono);font-size:12px;margin-bottom:14px">' +
      'MODE: <b style="color:var(--acc)">' + esc(s.gates.toUpperCase()) +
      '</b> \u00b7 RUNS: ' + runs.length +
      ' \u00b7 PASSED: <b style="color:var(--good)">' + passed + '</b></div>' +
      (list || '<p style="font-style:italic;color:var(--mut)">No gate runs yet.</p>') +
      '</div>';
  }

  function renderSecurity(s) {
    var granted = {};
    s.ledger.forEach(function (e) {
      if (e.kind === 'CAPABILITY_GRANTED' && e.detail.scope)
        granted[e.detail.scope] = e.t;
    });
    var denials = s.ledger.filter(function (e) {
      return e.kind === 'TOOL_RESULT' && e.detail && e.detail.ok === false;
    });
    pageEl.innerHTML = '<div class="glass card">' +
      '<h3 class="ct">SECURITY \u00b7 ACTIVE CAPABILITY GRANTS</h3>' +
      (s.caps.length ? s.caps.map(function (c) {
        return nodeRow('', '\u25c6', c.scope, 'auto-expiring',
          'live \u00b7 ' + c.left);
      }).join('') :
        '<p style="font-style:italic;color:var(--mut)">No active grants.</p>') +
      '</div><div class="glass card" style="margin-top:16px">' +
      '<h3 class="ct">GRANT HISTORY</h3>' +
      (Object.keys(granted).length ?
        Object.keys(granted).map(function (scope) {
          return nodeRow('', '\u25c6', scope,
            'granted at ' + granted[scope], 'logged');
        }).join('') :
        '<p style="font-style:italic;color:var(--mut)">None yet.</p>') +
      '</div><div class="glass card" style="margin-top:16px">' +
      '<h3 class="ct">TOOL ERRORS &amp; DENIALS</h3>' +
      (denials.length ? denials.map(function (e) {
        return nodeRow('blocked', '\u2717', 'tool result: error',
          'at ' + e.t, 'check');
      }).join('') :
        '<p style="font-style:italic;color:var(--mut)">None in the recent window. Default-deny holds.</p>') +
      '</div>';
  }

  function showView(v) {
    currentView = v;
    var dash = document.querySelector('.main3');
    var stats = document.querySelector('.stats');
    if (v === 'dashboard') {
      dash.style.display = ''; stats.style.display = '';
      if (pageEl) pageEl.style.display = 'none';
    } else {
      dash.style.display = 'none'; stats.style.display = 'none';
      if (pageEl) {
        pageEl.style.display = '';
        if (v === 'memory') {
          pageEl.innerHTML = '<div class="glass card"><h3 class="ct">MEMORY \u00b7 LOADING\u2026</h3></div>';
          fetch('/api/memory', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (currentView === 'memory') renderMemory(d);
            })
            .catch(function () {});
        } else if (lastState) renderPage(lastState);
      }
    }
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

    pageEl = document.createElement('div');
    pageEl.id = 'pageView';
    pageEl.style.display = 'none';
    document.querySelector('.main3').insertAdjacentElement('afterend', pageEl);

    function setNav(btn) {
      document.querySelectorAll('.navbtn').forEach(function (x) {
        x.classList.remove('on');
      });
      btn.classList.add('on');
    }
    var VIEWS = {
      'overview': 'dashboard', 'plans & tasks': 'plans',
      'memory': 'memory', 'verification': 'verification',
      'economy': 'economy', 'security': 'security',
      'sessions': 'sessions'
    };
    document.querySelectorAll('.navbtn').forEach(function (b) {
      var name = b.textContent.trim().toLowerCase();
      b.onclick = function () {
        var v = VIEWS[name];
        if (!v) { toast(name + ' — unknown section'); return; }
        setNav(b);
        showView(v);
      };
    });

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
