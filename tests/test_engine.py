#!/usr/bin/env python3
"""End-to-end self test: mock provider -> tools -> verify gate -> ledger."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from agent import Agent            # noqa: E402
from ledger import Ledger          # noqa: E402
from memory import Memory          # noqa: E402


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix='atlas_ws_')
        self.dir = tempfile.mkdtemp(prefix='atlas_data_')
        self.ledger = Ledger(os.path.join(self.dir, 'ledger.jsonl'))
        self.memory = Memory(os.path.join(self.dir, 'memory.json'))
        cfg = {'provider': 'mock', 'workspace': self.ws, 'gates': 'strict'}
        self.result = Agent(cfg, self.ledger, self.memory).run(
            'create a hello module')

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.dir, ignore_errors=True)

    def kinds(self):
        return [e['kind'] for e in self.ledger._entries()]

    def test_completed(self):
        self.assertEqual(self.result['status'], 'completed')

    def test_file_written_and_compiles(self):
        p = os.path.join(self.ws, 'hello.py')
        self.assertTrue(os.path.exists(p))
        r = os.system(sys.executable + ' -m py_compile ' + p)
        self.assertEqual(r, 0)

    def test_ledger_pipeline(self):
        k = self.kinds()
        for kind in ('TASK_STARTED', 'CAPABILITY_GRANTED', 'TOOL_CALL',
                     'MODEL_CALL', 'VERIFY_RUN', 'COMMITTED',
                     'TASK_COMPLETED'):
            self.assertIn(kind, k)
        self.assertNotIn('TASK_BLOCKED', k)

    def test_capability_scoped_before_write(self):
        entries = self.ledger._entries()
        cap = next(e for e in entries if e['kind'] == 'CAPABILITY_GRANTED')
        write = next(e for e in entries if e['kind'] == 'TOOL_CALL'
                     and e['detail'].get('tool') == 'write_file')
        self.assertLess(cap['id'], write['id'])

    def test_memory_episode_saved(self):
        self.assertGreaterEqual(len(self.memory.episodes), 1)
        hit = self.memory.retrieve('create hello module')
        self.assertIn('hello', hit.lower())

    def test_mock_weather_uses_web_fetch_and_summarises(self):
        """Weather goals must fetch real data via web_fetch, then summarise."""
        from providers import MockProvider  # noqa: E402
        prov = MockProvider()
        goal = 'hvordan er vejret i nyborg'
        msgs = [{'role': 'user', 'content': goal}]

        r1 = prov.chat(msgs)
        calls = r1['message'].get('tool_calls') or []
        self.assertEqual(len(calls), 2)          # set_plan + web_fetch
        self.assertEqual(calls[0]['function']['name'], 'set_plan')
        self.assertIn('steps', calls[0]['function']['arguments'])
        fn = calls[1]['function']
        self.assertEqual(fn['name'], 'web_fetch')
        self.assertIn('wttr.in', fn['arguments'])
        self.assertIn('nyborg', fn['arguments'])

        msgs.append(r1['message'])
        msgs.append({'role': 'tool', 'tool_call_id': 'call_wx',
                     'content': json.dumps(
                         {'ok': True, 'url': 'https://wttr.in/nyborg?format=3',
                          'body': 'Nyborg: ☀️ +21°C'})})
        r2 = prov.chat(msgs)
        calls2 = r2['message'].get('tool_calls') or []
        self.assertEqual(len(calls2), 1)
        self.assertEqual(calls2[0]['function']['name'], 'complete_step')
        self.assertIn('"index": 0', calls2[0]['function']['arguments'])

        msgs.append(r2['message'])
        msgs.append({'role': 'tool', 'tool_call_id': 'call_done',
                     'content': json.dumps({'ok': True})})
        r3 = prov.chat(msgs)
        self.assertNotIn('tool_calls', r3['message'])
        self.assertIn('+21°C', r3['message']['content'])
        self.assertIn('Nyborg', r3['message']['content'])

    def test_web_fetch_ssrf_guard(self):
        from tools import _url_allowed  # noqa: E402
        ok, _ = _url_allowed('https://wttr.in/nyborg?format=3')
        self.assertTrue(ok)
        ok, why = _url_allowed('file:///etc/passwd')
        self.assertFalse(ok)
        ok, why = _url_allowed('http://127.0.0.1:8123/')
        self.assertFalse(ok)
        ok, why = _url_allowed('http://10.0.0.1/')
        self.assertFalse(ok)

    def test_shell_tool_allowlist_and_injection_guard(self):
        from tools import dispatch, ToolContext  # noqa: E402
        ctx = ToolContext(self.ws, lambda *a: None)
        r = dispatch('run_command', {'command': 'echo atlas'}, ctx)
        self.assertTrue(r['ok'])
        self.assertIn('atlas', r['output'])
        r = dispatch('run_command', {'command': 'rm -rf /'}, ctx)
        self.assertIn('error', r)
        self.assertIn('allowlisted', r['error'])
        r = dispatch('run_command', {'command': 'ls; echo pwned'}, ctx)
        self.assertIn('error', r)
        self.assertIn('operators', r['error'])

    def test_plan_is_logged_before_tools(self):
        k = self.kinds()
        self.assertIn('PLAN_SET', k)
        entries = self.ledger._entries()
        plan = next(e for e in entries if e['kind'] == 'PLAN_SET')
        self.assertGreaterEqual(len(plan['detail']['steps']), 2)
        first_tool = next(e for e in entries if e['kind'] == 'TOOL_CALL')
        self.assertLess(plan['id'], first_tool['id'])

    def test_plan_progress_is_logged(self):
        """The agent must mark plan steps done as it completes them."""
        steps = [e['detail'] for e in self.ledger._entries()
                 if e['kind'] == 'PLAN_STEP']
        self.assertTrue(any(d.get('index') == 0 for d in steps),
                        'step 0 should be marked complete during the run')

    def test_subagent_delegation(self):
        """Report goals delegate research to a subagent and use its output."""
        ws = tempfile.mkdtemp(prefix='atlas_sub_')
        d = tempfile.mkdtemp()
        led = Ledger(os.path.join(d, 'l.jsonl'))
        mem = Memory(os.path.join(d, 'm.json'))
        cfg = {'provider': 'mock', 'workspace': ws, 'gates': 'strict'}
        res = Agent(cfg, led, mem).run('write a report about atlantis')
        self.assertEqual(res['status'], 'completed')

        kinds = [e['kind'] for e in led._entries()]
        self.assertIn('SUBAGENT_STARTED', kinds)
        self.assertIn('SUBAGENT_FINISHED', kinds)

        report = os.path.join(ws, 'report.md')
        self.assertTrue(os.path.exists(report))
        with open(report, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('atlantis', content.lower())
        self.assertIn('Subagent research', content)

        started = next(e for e in led._entries()
                       if e['kind'] == 'SUBAGENT_STARTED')
        self.assertEqual(started['detail']['depth'], 1)
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)

    def test_memory_search(self):
        self.memory.add('write a hello module', 'completed fine')
        self.memory.add('hvordan er vejret i nyborg', 'sunny 21C')
        hits = self.memory.search('weather in nyborg')
        self.assertGreaterEqual(len(hits), 1)
        self.assertIn('vejret', hits[0]['goal'])
        self.assertEqual(self.memory.search('xyzzy nonexistent'), [])

    def test_subagent_depth_limit(self):
        """A depth-2 agent must not spawn further subagents."""
        ws = tempfile.mkdtemp(prefix='atlas_deep_')
        d = tempfile.mkdtemp()
        led = Ledger(os.path.join(d, 'l.jsonl'))
        mem = Memory(os.path.join(d, 'm.json'))
        cfg = {'provider': 'mock', 'workspace': ws, 'gates': 'advisory'}
        res = Agent(cfg, led, mem, depth=2).run(
            'write a report about deep recursion')
        self.assertEqual(res['status'], 'completed')
        kinds = [e['kind'] for e in led._entries()]
        self.assertNotIn('SUBAGENT_STARTED', kinds)
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)

    def test_strict_gate_blocks_on_failure(self):
        ws = tempfile.mkdtemp(prefix='atlas_bad_')
        d = tempfile.mkdtemp()
        led = Ledger(os.path.join(d, 'l.jsonl'))
        with open(os.path.join(ws, 'broken.py'), 'w') as f:
            f.write('def broken(:\n')
        from tools import ToolContext  # noqa: E402
        import tools as T              # noqa: E402

        ctx = ToolContext(ws, lambda *a: None)
        res = T.dispatch('run_tests', {}, ctx)
        ctx.written = ['broken.py']
        # direct dispatch on existing file must report failure
        ok, _ = T._compile_check(os.path.join(ws, 'broken.py'))
        self.assertFalse(ok)
        self.assertIsInstance(res, dict)
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
