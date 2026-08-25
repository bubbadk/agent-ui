#!/usr/bin/env python3
"""Local API + static server for the Atlas engine.

  python3 server/server.py            -> http://localhost:8123

Routes:
  GET  /                     Fusion UI (concept-4-fusion.html)
  GET  /live.js              UI wiring for live engine mode
  GET  /api/health           {"ok":true,"provider":...}
  GET  /api/state            ledger tail, plan tree, grants, budget
  GET  /api/memory           episodic memory entries
  POST /api/task             {"goal": "..."} — starts the agent in a thread
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from agent import Agent          # noqa: E402
from config import api_key, load  # noqa: E402
from ledger import Ledger        # noqa: E402
from memory import Memory        # noqa: E402

CFG = load()
LEDGER = Ledger(os.path.join(ROOT, 'data', 'ledger.jsonl'))
MEMORY = Memory(os.path.join(ROOT, 'data', 'memory.json'))

STATE = {'phase': 'idle', 'goal': '', 'last_seen': 0, 'grants': [],
         'plan': None}
STATE_LOCK = threading.Lock()


def _refresh_state():
    with STATE_LOCK:
        for e in LEDGER.since(STATE['last_seen']):
            STATE['last_seen'] = e['id']
            k = e['kind']
            if k == 'TASK_STARTED':
                STATE['phase'] = 'running'
                STATE['goal'] = e['detail'].get('goal', '')
                STATE['plan'] = None
            elif k == 'PLAN_SET':
                steps = e['detail'].get('steps') or []
                if steps:
                    STATE['plan'] = [{'t': str(s)[:80], 'done': False}
                                     for s in steps]
            elif k == 'PLAN_STEP':
                idx = e['detail'].get('index', -1)
                plan = STATE.get('plan')
                if plan and 0 <= idx < len(plan):
                    plan[idx]['done'] = True
            elif k == 'COMMITTED':
                STATE['phase'] = 'committed'
            elif k == 'TASK_COMPLETED':
                STATE['phase'] = 'done'
            elif k == 'TASK_BLOCKED':
                STATE['phase'] = 'blocked'
            elif k == 'CAPABILITY_GRANTED':
                scope = e['detail'].get('scope', 'cap')
                STATE['grants'] = [g for g in STATE['grants']
                                   if g['scope'] != scope]
                STATE['grants'].append(
                    {'scope': scope, 'exp': time.time() + 900})
    return STATE


def _tree():
    ph = STATE['phase']
    if ph == 'idle':
        return []
    plan = STATE.get('plan')
    if not plan:
        # fallback before the model has published a plan
        s0 = ('done' if ph in ('committed', 'done')
              else 'blocked' if ph == 'blocked' else 'running')
        s1 = {'running': 'pending', 'committed': 'running',
              'done': 'done', 'blocked': 'blocked'}[ph]
        return [{'d': 0, 't': STATE['goal'][:60] or '(goal)', 's': s0},
                {'d': 1, 't': 'verify gates & commit', 's': s1}]

    def status(i, item):
        if ph in ('committed', 'done'):
            return 'done'
        if ph == 'blocked':
            return 'blocked'
        if item.get('done'):
            return 'done'
        first_open = next((j for j, p in enumerate(plan)
                           if not p.get('done')), None)
        return 'running' if i == first_open else 'pending'

    return [{'d': i, 't': str(p['t'])[:60], 's': status(i, p)}
            for i, p in enumerate(plan)]


def _start_task(goal):
    with STATE_LOCK:
        if STATE['phase'] == 'running':
            return {'error': 'a task is already running'}
        STATE['phase'] = 'starting'

    def work():
        cfg = dict(CFG)
        cfg['_api_key'] = api_key(CFG)
        Agent(cfg, LEDGER, MEMORY).run(goal)

    threading.Thread(target=work, daemon=True).start()
    return {'started': True, 'goal': goal}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype='application/json'):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/api/health':
            prov = CFG['provider']
            key_ok = bool(api_key(CFG)) or prov == 'mock'
            return self._send(200, json.dumps(
                {'ok': bool(key_ok), 'provider': prov}))
        if self.path == '/api/memory':
            return self._send(200, json.dumps({
                'ok': True,
                'count': len(MEMORY.episodes),
                'episodes': list(reversed(MEMORY.episodes[-50:])),
            }))
        if self.path == '/api/state':
            st = dict(_refresh_state())
            now = time.time()
            grants = []
            for g in st['grants']:
                left = int(g['exp'] - now)
                if left > 0:
                    grants.append({'scope': g['scope'],
                                   'left': '%02d:%02d' % (left // 60,
                                                          left % 60)})
            return self._send(200, json.dumps({
                'ok': True,
                'provider': CFG['provider'],
                'gates': CFG.get('gates', 'strict'),
                'budget': {'spent': LEDGER.spent(),
                           'limit': float(CFG['daily_budget'])},
                'ledger': LEDGER.tail(60),
                'tree': _tree(),
                'caps': grants,
                'phase': st['phase'],
            }))
        path = self.path.lstrip('/') or 'fusion/concept-4-fusion.html'
        if path == 'live.js':
            path = 'fusion/live.js'
        fp = os.path.realpath(os.path.join(ROOT, path))
        if not fp.startswith(ROOT) or not os.path.isfile(fp):
            return self._send(404, '{"error":"not found"}')
        ctype = ('text/javascript' if fp.endswith('.js')
                 else 'text/html; charset=utf-8')
        with open(fp, 'rb') as f:
            return self._send(200, f.read(), ctype)

    def do_POST(self):
        if self.path != '/api/task':
            return self._send(404, '{"error":"not found"}')
        try:
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, '{"error":"bad json"}')
        goal = (body.get('goal') or '').strip()
        if not goal:
            return self._send(400, '{"error":"missing goal"}')
        return self._send(200, json.dumps(_start_task(goal)))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    print('Atlas engine serving on http://localhost:%d' % port)
    print('UI:      http://localhost:%d/' % port)
    print('Provider: %s (set ~/.agentui/config.json + %s for a real model)'
          % (CFG['provider'], CFG['api_key_env']))
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
