#!/usr/bin/env python3
"""Local API + static server for the Atlas engine.

  python3 server/server.py            -> http://localhost:8123

Routes:
  GET  /                     Fusion UI (concept-4-fusion.html)
  GET  /live.js              UI wiring for live engine mode
  GET  /api/health           {"ok":true,"provider":...}
  GET  /api/state            ledger tail, plan tree, grants, budget
  GET  /api/memory           episodic memory (?q=... for keyword search)
  GET  /api/task_events      ?start=<TASK_STARTED id> — one task's full event block
  POST /api/gates            {"gates":"strict|advisory|draft"} — runtime switch
  POST /api/task             {"goal": "..."} — starts the agent in a thread
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'engine'))

import config as config_mod      # noqa: E402
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
SCHEDULE_LOCK = threading.Lock()


def _normalise_schedules(items):
    """Return key-safe, bounded recurring schedule definitions."""
    out = []
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get('id', '')).strip().lower()
        goal = str(raw.get('goal', '')).strip()[:2000]
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', sid) or not goal:
            continue
        try:
            interval = max(1, int(raw.get('interval_seconds', 3600)))
        except (TypeError, ValueError):
            interval = 3600
        try:
            next_run = float(raw.get('next_run', 0) or 0)
        except (TypeError, ValueError):
            next_run = 0
        out.append({'id': sid, 'goal': goal, 'interval_seconds': interval,
                    'enabled': bool(raw.get('enabled', True)),
                    'next_run': next_run})
    return out


CFG['schedules'] = _normalise_schedules(CFG.get('schedules', []))


def _run_scheduled(schedule):
    """Log and execute one standing order without exposing credentials."""
    result = _start_task(schedule['goal'])
    if result.get('started'):
        LEDGER.append('SCHEDULED_RUN', detail={
            'schedule_id': schedule['id'], 'goal': schedule['goal']})


def _scheduler_loop():
    while True:
        time.sleep(1)
        _refresh_state()
        now = time.time()
        with SCHEDULE_LOCK:
            schedules = CFG.get('schedules') or []
            for schedule in schedules:
                if not schedule.get('enabled'):
                    continue
                due = float(schedule.get('next_run') or 0)
                if due > now:
                    continue
                with STATE_LOCK:
                    available = STATE['phase'] not in ('starting', 'running')
                if not available:
                    schedule['next_run'] = now + 5
                    continue
                schedule['next_run'] = now + schedule['interval_seconds']
                threading.Thread(target=_run_scheduled, args=(dict(schedule),),
                                 daemon=True).start()
                break


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
        if STATE['phase'] in ('starting', 'running'):
            return {'error': 'a task is already running'}
        STATE['phase'] = 'starting'

    def work():
        cfg = config_mod.effective_task_cfg(CFG)
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
        # NB: self.path includes the query string — match on the path part
        path = urlparse(self.path).path
        if path == '/api/models':
            from urllib.parse import parse_qs
            pk = parse_qs(urlparse(self.path).query).get(
                'provider_key', [CFG.get('provider_key', '')])[0]
            prov = (CFG.get('providers') or {}).get(pk) or {}
            base = prov.get('base_url') or CFG['base_url']
            key = prov.get('api_key', '') or api_key(CFG)
            if pk == 'mock':
                return self._send(200, json.dumps(
                    {'ok': True, 'models': ['mock-frontier']}))
            try:
                import urllib.request
                headers = {'Authorization': 'Bearer ' + key} if key else {}
                req = urllib.request.Request(
                    base.rstrip('/') + '/models', headers=headers)
                with urllib.request.urlopen(req, timeout=20) as r:
                    d = json.load(r)
                ids = sorted({m.get('id') for m in d.get('data', [])
                              if m.get('id')})
                return self._send(200, json.dumps({'ok': True, 'models': ids}))
            except Exception as exc:              # noqa: BLE001
                return self._send(200, json.dumps(
                    {'ok': False, 'error': str(exc)[:300]}))
        if path == '/api/agents':
            return self._send(200, json.dumps({
                'ok': True,
                'agents': CFG.get('agents', {}),
                'active': CFG.get('active_agent', ''),
                'provider_keys': ['mock'] +
                    sorted((CFG.get('providers') or {}).keys()),
            }))
        if path == '/api/config':
            return self._send(200, json.dumps({'ok': True, 'config': {
                'provider': CFG['provider'],
                'model': CFG['model'],
                'base_url': CFG['base_url'],
                'api_key_env': CFG['api_key_env'],
                'api_key_set': bool(api_key(CFG)),
                'provider_key': CFG.get('provider_key', 'openai'),
                'daily_budget': float(CFG['daily_budget']),
                'sub_budget': float(CFG.get('sub_budget', 0.5)),
                'gates': CFG['gates'],
                'schedules': CFG.get('schedules', []),
            }}))
        if path == '/api/schedules':
            return self._send(200, json.dumps({
                'ok': True, 'schedules': CFG.get('schedules', [])}))
        if path == '/api/health':
            prov = CFG['provider']
            key_ok = bool(api_key(CFG)) or prov == 'mock'
            return self._send(200, json.dumps(
                {'ok': bool(key_ok), 'provider': prov}))
        if path == '/api/memory' and not urlparse(self.path).query:
            return self._send(200, json.dumps({
                'ok': True,
                'count': len(MEMORY.episodes),
                'episodes': list(reversed(MEMORY.episodes[-50:])),
            }))
        if path == '/api/memory':
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query).get('q', [''])[0]
            if q:
                return self._send(200, json.dumps({
                    'ok': True, 'query': q,
                    'results': MEMORY.search(q),
                }))
            return self._send(200, json.dumps({
                'ok': True,
                'count': len(MEMORY.episodes),
                'episodes': list(reversed(MEMORY.episodes[-50:])),
            }))
        if path == '/api/task_events':
            from urllib.parse import parse_qs
            start = int(parse_qs(urlparse(self.path).query)
                        .get('start', ['0'])[0])
            events = []
            started = False
            for e in LEDGER._entries():
                if started and e['kind'] == 'TASK_STARTED':
                    break
                if e['id'] == start and e['kind'] == 'TASK_STARTED':
                    started = True
                if started:
                    events.append(e)
            return self._send(200, json.dumps({'ok': True, 'events': events}))
        if path == '/api/state':
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
                'agent': CFG.get('active_agent', ''),
            }))
        path = self.path.lstrip('/') or 'fusion/concept-4-fusion.html'
        if path == 'live.js':
            path = 'fusion/live.js'
        if path == 'manual':
            path = 'fusion/manual.html'
        fp = os.path.realpath(os.path.join(ROOT, path))
        if not fp.startswith(ROOT) or not os.path.isfile(fp):
            return self._send(404, '{"error":"not found"}')
        ctype = ('text/javascript' if fp.endswith('.js')
                 else 'text/html; charset=utf-8')
        with open(fp, 'rb') as f:
            return self._send(200, f.read(), ctype)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/agents':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            name = str(body.get('name', '')).strip().lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', name):
                return self._send(400, json.dumps(
                    {'error': 'name must be a-z, 0-9, dash (max 32)'}))
            pk = str(body.get('provider_key', 'mock'))
            if pk != 'mock' and pk not in (CFG.get('providers') or {}):
                return self._send(400, json.dumps(
                    {'error': 'provider "%s" is not configured yet '
                              '(add it under SETTINGS first)' % pk}))
            skills = [s for s in (body.get('skills') or [])
                      if s in config_mod.ALL_SKILLS]
            CFG.setdefault('agents', {})[name] = {
                'label': str(body.get('label') or name)[:60],
                'provider_key': pk,
                'model': str(body.get('model', '')).strip()[:120],
                'skills': skills,
                'prompt': str(body.get('prompt', ''))[:2000],
            }
            if body.get('activate'):
                CFG['active_agent'] = name
            config_mod.save(CFG)
            return self._send(200, json.dumps({
                'ok': True, 'name': name,
                'active': CFG['active_agent'],
                'agents': CFG['agents']}))
        if path == '/api/agents/activate':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            name = str(body.get('name', ''))
            if name not in (CFG.get('agents') or {}):
                return self._send(404, '{"error":"unknown agent"}')
            CFG['active_agent'] = name
            config_mod.save(CFG)
            return self._send(200, json.dumps({'ok': True, 'active': name}))
        if path == '/api/agents/delete':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            name = str(body.get('name', ''))
            agents = CFG.get('agents') or {}
            if name not in agents:
                return self._send(404, '{"error":"unknown agent"}')
            if len(agents) < 2:
                return self._send(400,
                                  '{"error":"cannot delete the last agent"}')
            del agents[name]
            if CFG.get('active_agent') == name:
                CFG['active_agent'] = next(iter(agents))
            config_mod.save(CFG)
            return self._send(200, json.dumps(
                {'ok': True, 'active': CFG['active_agent']}))
        if path == '/api/config':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            if body.get('provider') not in (None, 'mock', 'openai_compat'):
                return self._send(400, '{"error":"invalid provider"}')
            if body.get('gates') not in (None, 'strict', 'advisory', 'draft'):
                return self._send(400, '{"error":"invalid gates"}')
            for field in ('model', 'base_url'):
                if field in body:
                    CFG[field] = str(body[field]).strip() or CFG[field]
            for field in ('daily_budget', 'sub_budget'):
                if field in body:
                    try:
                        CFG[field] = max(0.0, float(body[field]))
                    except (TypeError, ValueError):
                        pass
            if 'provider' in body:
                CFG['provider'] = body['provider']
            if 'gates' in body:
                CFG['gates'] = body['gates']
            if 'api_key' in body and body['api_key']:
                CFG['api_key'] = str(body['api_key'])
            if body.get('api_key_clear'):
                CFG['api_key'] = ''
            if body.get('provider_key'):
                CFG['provider_key'] = str(body['provider_key'])
            config_mod.save(CFG)
            return self._send(200, json.dumps({
                'ok': True, 'provider': CFG['provider'],
                'model': CFG['model'], 'gates': CFG['gates'],
                'api_key_set': bool(api_key(CFG))}))
        if path == '/api/schedules':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            schedules = _normalise_schedules(body.get('schedules', []))
            now = time.time()
            for schedule in schedules:
                if not schedule['next_run'] or schedule['next_run'] < now:
                    schedule['next_run'] = now + schedule['interval_seconds']
            with SCHEDULE_LOCK:
                CFG['schedules'] = schedules
                config_mod.save(CFG)
            return self._send(200, json.dumps({'ok': True,
                                               'schedules': schedules}))
        if path == '/api/test_model':
            cfg = dict(CFG)
            cfg['_api_key'] = api_key(CFG)
            try:
                from providers import make_provider
                r = make_provider(cfg, cfg['_api_key']).chat(
                    [{'role': 'user', 'content': 'Reply with exactly: OK'}])
                reply = (r['message'].get('content') or '')[:80]
                return self._send(200, json.dumps(
                    {'ok': True, 'reply': reply}))
            except Exception as exc:                  # noqa: BLE001
                return self._send(200, json.dumps(
                    {'ok': False, 'error': str(exc)[:300]}))
        if path == '/api/gates':
            try:
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            g = body.get('gates')
            if g not in ('strict', 'advisory', 'draft'):
                return self._send(400, '{"error":"invalid gates"}')
            CFG['gates'] = g
            return self._send(200, json.dumps({'ok': True, 'gates': g}))
        if path != '/api/task':
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
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
