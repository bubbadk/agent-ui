"""Atlas agent core: plan -> act (tools) -> verify gate -> commit."""
import json
import os

import tools as T
from providers import make_provider

SYSTEM_PROMPT = (
    'You are Atlas, a careful autonomous agent. Work step by step using the '
    'provided tools. Keep everything inside the workspace. When you believe '
    'the goal is met, stop calling tools and give a one-paragraph summary.'
)


class Agent:
    def __init__(self, cfg, ledger, memory):
        self.cfg = cfg
        self.ledger = ledger
        self.memory = memory
        self.provider = make_provider(cfg, cfg.get('_api_key', ''))

    def log(self, kind, **kw):
        return self.ledger.append(kind, model=self.provider.name, **kw)

    def run(self, goal):
        self.log('TASK_STARTED', detail={'goal': goal})

        mem = self.memory.retrieve(goal)
        system = SYSTEM_PROMPT
        if mem:
            system += '\n\nRelevant memory from previous tasks:\n' + mem

        msgs = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': goal}]
        ctx = T.ToolContext(
            self.cfg['workspace'],
            lambda kind, detail: self.log(kind, detail=detail))

        granted = set()
        final = None
        for _ in range(12):
            resp = self.provider.chat(msgs, T.SCHEMAS)
            u = resp.get('usage') or {}
            self.log('MODEL_CALL', tokens={
                'in': u.get('in', u.get('prompt_tokens', 0)),
                'out': u.get('out', u.get('completion_tokens', 0))},
                detail={'preview': (resp['message'].get('content') or '')[:120]})
            m = resp['message']
            msgs.append(m)

            calls = m.get('tool_calls') or []
            if not calls:
                final = m.get('content')
                break

            for tc in calls:
                fn = tc['function']['name']
                if fn in ('write_file', 'run_tests') and \
                        'fs:write' not in granted:
                    granted.add('fs:write')
                    self.log('CAPABILITY_GRANTED', detail={
                        'scope': 'fs:write ' +
                                 os.path.basename(self.cfg['workspace']) + '/',
                        'reason': 'required by plan'})
                try:
                    args = json.loads(tc['function'].get('arguments') or '{}')
                except ValueError:
                    args = {}
                res = T.dispatch(fn, args, ctx)
                msgs.append({'role': 'tool',
                             'tool_call_id': tc.get('id'),
                             'content': json.dumps(res)[:2000]})

        # ── verify gate ────────────────────────────────────────────────
        criteria = []
        for rel in dict.fromkeys(ctx.written):
            ok, out = T._compile_check(os.path.join(ctx.ws, rel))
            criteria.append({'check': 'compiles: ' + rel, 'pass': ok,
                             'output': out[-200:]})
        passed = all(c['pass'] for c in criteria) if criteria else True
        self.log('VERIFY_RUN', detail={'criteria': [
            {k: c[k] for k in ('check', 'pass')} for c in criteria],
            'passed': passed})

        gates = self.cfg.get('gates', 'strict')
        if gates == 'strict' and not passed:
            self.log('VERIFY_FAIL')
            self.log('TASK_BLOCKED', detail={'reason': 'acceptance gates failed'})
            self.memory.add(goal, 'BLOCKED — acceptance gates failed')
            return {'status': 'blocked'}

        self.log('COMMITTED', detail={'files': list(ctx.written)})
        self.log('TASK_COMPLETED', detail={'summary': (final or '')[:300]})
        self.memory.add(goal, final or '')
        return {'status': 'completed'}
