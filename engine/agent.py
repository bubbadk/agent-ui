"""Atlas agent core: plan -> act (tools) -> verify gate -> commit."""
import json
import os

import tools as T
from providers import make_provider

SYSTEM_PROMPT = (
    'You are Atlas, a careful autonomous agent. Always call set_plan first '
    'with 2-4 short steps, then work step by step using the provided tools. '
    'Keep everything inside the workspace. When you believe the goal is met, '
    'stop calling tools and give a one-paragraph summary.'
)


class Agent:
    def __init__(self, cfg, ledger, memory, depth=0):
        self.cfg = cfg
        self.ledger = ledger
        self.memory = memory
        self.depth = depth
        self.provider = make_provider(cfg, cfg.get('_api_key', ''))
        self.skills = cfg.get('skills')            # None = unrestricted
        self.allowed = T.allowed_names(self.skills)
        self.schemas = T.schemas_for(self.skills)
        self.agent_prompt = cfg.get('agent_prompt', '')

    def log(self, kind, **kw):
        return self.ledger.append(kind, model=self.provider.name, **kw)

    def run(self, goal, max_cost=None):
        self.log('TASK_STARTED', detail={'goal': goal,
                                         'depth': self.depth})

        mem = self.memory.retrieve(goal)
        system = ('[SUBAGENT depth %d] ' % self.depth
                  if self.depth else '') + SYSTEM_PROMPT
        if self.agent_prompt:
            system += '\n\nAgent persona:\n' + self.agent_prompt
        if mem:
            system += '\n\nRelevant memory from previous tasks:\n' + mem

        msgs = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': goal}]
        ctx = T.ToolContext(
            self.cfg['workspace'],
            lambda kind, detail: self.log(kind, detail=detail))

        granted = set()
        final = None
        spent = 0.0
        for _ in range(16):
            resp = self.provider.chat(msgs, self.schemas)
            u = resp.get('usage') or {}
            tin = u.get('in', u.get('prompt_tokens', 0))
            tout = u.get('out', u.get('completion_tokens', 0))
            spent += (tin * 0.15 + tout * 0.60) / 1e6
            self.log('MODEL_CALL', tokens={'in': tin, 'out': tout},
                detail={'preview': (resp['message'].get('content') or '')[:120]})
            if max_cost is not None and spent > max_cost:
                self.log('TASK_BLOCKED',
                         detail={'reason': 'subagent budget exhausted'})
                return {'status': 'blocked', 'summary': 'budget exhausted'}
            m = resp['message']
            msgs.append(m)

            calls = m.get('tool_calls') or []
            if not calls:
                final = m.get('content')
                break

            for tc in calls:
                fn = tc['function']['name']

                if self.allowed is not None and fn not in self.allowed:
                    self.log('TOOL_CALL', detail={'tool': fn, 'denied': True})
                    msgs.append({'role': 'tool',
                                 'tool_call_id': tc.get('id'),
                                 'content': json.dumps(
                                     {'error': 'skill not enabled '
                                               'for this agent'})})
                    continue

                if fn == 'set_plan':
                    try:
                        steps = json.loads(
                            tc['function'].get('arguments') or '{}'
                        ).get('steps', [])
                    except ValueError:
                        steps = []
                    self.log('PLAN_SET', detail={
                        'steps': [str(s)[:80] for s in steps]})
                    msgs.append({'role': 'tool',
                                 'tool_call_id': tc.get('id'),
                                 'content': json.dumps({'ok': True})})
                    continue

                if fn == 'complete_step':
                    try:
                        idx = int(json.loads(
                            tc['function'].get('arguments') or '{}'
                        ).get('index', -1))
                    except (ValueError, TypeError):
                        idx = -1
                    self.log('PLAN_STEP', detail={'index': idx})
                    msgs.append({'role': 'tool',
                                 'tool_call_id': tc.get('id'),
                                 'content': json.dumps({'ok': True})})
                    continue

                if fn == 'spawn_subagent':
                    if self.depth >= 2:
                        res = {'error': 'subagent depth limit reached (max 2)'}
                    else:
                        try:
                            sub_goal = json.loads(
                                tc['function'].get('arguments') or '{}'
                            ).get('goal', '')
                        except ValueError:
                            sub_goal = ''
                        self.log('SUBAGENT_STARTED', detail={
                            'goal': sub_goal[:120],
                            'depth': self.depth + 1})
                        child = Agent(self.cfg, self.ledger, self.memory,
                                      depth=self.depth + 1)
                        child_res = child.run(
                            sub_goal,
                            max_cost=self.cfg.get('sub_budget', 0.5))
                        summary = child_res.get('summary', '')
                        self.log('SUBAGENT_FINISHED', detail={
                            'status': child_res['status'],
                            'summary': summary[:200]})
                        res = {'ok': True, 'summary': summary}
                    msgs.append({'role': 'tool',
                                 'tool_call_id': tc.get('id'),
                                 'content': json.dumps(res)[:2000]})
                    continue

                scope = None
                if fn in ('write_file', 'run_tests'):
                    scope = ('fs:write ' +
                             os.path.basename(self.cfg['workspace']) + '/')
                elif fn == 'web_fetch':
                    scope = 'net:get'
                elif fn == 'run_command':
                    scope = 'shell:sandbox'
                if scope and scope not in granted:
                    granted.add(scope)
                    self.log('CAPABILITY_GRANTED', detail={
                        'scope': scope, 'reason': 'required by plan'})
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
            path = os.path.join(ctx.ws, rel)
            if rel.endswith('.py'):
                ok, out = T._compile_check(path)
                criteria.append({'check': 'compiles: ' + rel,
                                 'pass': ok, 'output': out[-200:]})
            else:
                ok = os.path.exists(path) and os.path.getsize(path) > 0
                criteria.append({'check': 'written: ' + rel,
                                 'pass': ok, 'output': ''})
        passed = all(c['pass'] for c in criteria) if criteria else True
        self.log('VERIFY_RUN', detail={'criteria': [
            {k: c[k] for k in ('check', 'pass')} for c in criteria],
            'passed': passed})

        gates = self.cfg.get('gates', 'strict')
        if gates == 'strict' and not passed:
            self.log('VERIFY_FAIL')
            self.log('TASK_BLOCKED', detail={'reason': 'acceptance gates failed'})
            self.memory.add(goal, 'BLOCKED — acceptance gates failed')
            return {'status': 'blocked', 'summary': 'acceptance gates failed'}

        self.log('COMMITTED', detail={'files': list(ctx.written)})
        self.log('TASK_COMPLETED', detail={'summary': (final or '')[:300]})
        self.memory.add(goal, final or '')
        return {'status': 'completed', 'summary': final or ''}
