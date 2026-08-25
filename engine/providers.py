"""Model providers: deterministic mock + any OpenAI-compatible endpoint."""
import json
import urllib.request


class MockProvider:
    """Scripted provider so the full pipeline runs without an API key.
    Publishes a plan first, then demos two flows end-to-end:
    hello-module (fs tools) and weather (web_fetch)."""

    name = 'mock-frontier'

    def chat(self, messages, tools=None):
        # subagent children get a one-shot mock answer
        if (messages and messages[0].get('role') == 'system'
                and messages[0]['content'].startswith('[SUBAGENT')):
            goal = ''
            for m in messages:
                if m.get('role') == 'user':
                    goal = m['content']
            return {'message': {'role': 'assistant', 'content':
                'Subagent research complete for "%s". Mock findings: '
                '3 data points gathered; a real model would browse and '
                'cite sources here.' % goal[:80]},
                'usage': {'prompt_tokens': 80, 'completion_tokens': 50}}

        goal = ''
        for m in messages:
            if m.get('role') == 'user':
                goal = m['content']
        gl = goal.lower()
        n = sum(1 for m in messages if m.get('role') == 'assistant')

        if any(w in gl for w in ('weather', 'vejr', 'forecast')):
            return self._weather(goal, messages, n)
        if any(w in gl for w in ('report', 'delegate', 'research',
                                 'rapport', 'undersøg')):
            return self._report_flow(goal, messages, n)
        if any(w in gl for w in ('hello', 'module', 'script',
                                 'write', 'skriv', 'lav')):
            return self._hello_demo(n)
        return {'message': {'role': 'assistant', 'content':
            'This scripted mock can demo two flows: "write a hello module" '
            'and weather questions ("hvordan er vejret i <by>"). For '
            'general tasks, configure a real model in '
            '~/.agentui/config.json (provider "openai_compat").'},
            'usage': {'prompt_tokens': 50, 'completion_tokens': 45}}

    @staticmethod
    def _plan_call(steps):
        return {'id': 'call_plan', 'type': 'function', 'function': {
            'name': 'set_plan',
            'arguments': json.dumps({'steps': steps})}}

    def _weather(self, goal, messages, n):
        import re
        from urllib.parse import quote
        m = re.search(
            r'(?:vejret|weather|forecast)\s+(?:i|in|for)\s+(.+?)[\s?!.]*$',
            goal, re.IGNORECASE)
        city = (m.group(1) if m else goal.split()[-1]).strip() or 'nyborg'
        url = 'https://wttr.in/%s?format=3' % quote(city)
        if n == 0:
            msg = {'role': 'assistant',
                   'content': 'Plan set. Fetching current weather for %s.' % city,
                   'tool_calls': [
                       self._plan_call(['Fetch weather for %s' % city,
                                        'Summarise result']),
                       {'id': 'call_wx', 'type': 'function', 'function': {
                           'name': 'web_fetch',
                           'arguments': json.dumps({'url': url})}}]}
        elif n == 1:
            msg = {'role': 'assistant',
                   'content': 'Weather fetched; marking the step done.',
                   'tool_calls': [{'id': 'call_done', 'type': 'function',
                                   'function': {'name': 'complete_step',
                                                'arguments': json.dumps(
                                                    {'index': 0})}}]}
        else:
            body = ''
            for x in messages:
                if x.get('role') == 'tool':
                    try:
                        d = json.loads(x.get('content', ''))
                    except ValueError:
                        continue
                    if isinstance(d, dict) and 'body' in d:
                        body = d.get('body', '')
            text = ('Current weather — %s' % body.strip()) if body else \
                ('I could not retrieve the weather right now.')
            msg = {'role': 'assistant', 'content': text}
        return {'message': msg,
                'usage': {'prompt_tokens': 70 + 40 * n,
                          'completion_tokens': 30}}

    def _hello_demo(self, n):
        if n == 0:
            msg = {'role': 'assistant',
                   'content': 'PLAN: write hello module, then verify it.',
                   'tool_calls': [
                       self._plan_call(['Write hello module',
                                        'Verify it compiles']),
                       {'id': 'call_1', 'type': 'function', 'function': {
                           'name': 'write_file',
                           'arguments': json.dumps({
                               'path': 'hello.py',
                               'content': '"""Hello module."""\n\n'
                                          'def greet():\n    return "hi"\n\n'
                                          'if __name__ == "__main__":\n'
                                          '    print(greet())\n'})}}]}
        elif n == 1:
            msg = {'role': 'assistant',
                   'content': 'Step 1 done. Now verifying the module compiles.',
                   'tool_calls': [
                       {'id': 'call_s1', 'type': 'function', 'function': {
                           'name': 'complete_step',
                           'arguments': json.dumps({'index': 0})}},
                       {'id': 'call_2', 'type': 'function', 'function': {
                           'name': 'run_tests',
                           'arguments': json.dumps({'target': 'hello.py'})}}]}
        else:
            msg = {'role': 'assistant',
                   'content': 'Done: hello.py written and verified. '
                              'All acceptance criteria passed.'}
        return {'message': msg,
                'usage': {'prompt_tokens': 90 + 30 * n,
                          'completion_tokens': 35}}

    def _report_flow(self, goal, messages, n):
        import re
        m = re.search(r'(?:about|om)\s+(.+?)[\s?!.]*$', goal, re.IGNORECASE)
        topic = (m.group(1) if m else 'the requested topic').strip()
        if n == 0:
            msg = {'role': 'assistant',
                   'content': 'PLAN: delegate research, then write the report.',
                   'tool_calls': [
                       self._plan_call(['Delegate research to a subagent',
                                        'Write report.md']),
                       {'id': 'call_sub', 'type': 'function', 'function': {
                           'name': 'spawn_subagent',
                           'arguments': json.dumps(
                               {'goal': 'gather key facts about ' + topic})}}]}
        elif n == 1:
            summary = ''
            for x in messages:
                if x.get('role') == 'tool':
                    try:
                        d = json.loads(x.get('content', ''))
                    except ValueError:
                        continue
                    if isinstance(d, dict) and 'summary' in d:
                        summary = d['summary']
            report = ('# Report: %s\n\n%s\n\n'
                      '_Compiled by Atlas agent (mock provider)._'
                      % (topic, summary or 'No research returned.'))
            msg = {'role': 'assistant',
                   'content': 'Research returned. Writing report.md.',
                   'tool_calls': [
                       {'id': 'call_wf', 'type': 'function', 'function': {
                           'name': 'write_file',
                           'arguments': json.dumps(
                               {'path': 'report.md', 'content': report})}},
                       {'id': 'call_cs', 'type': 'function', 'function': {
                           'name': 'complete_step',
                           'arguments': json.dumps({'index': 0})}}]}
        elif n == 2:
            msg = {'role': 'assistant',
                   'content': 'Report written; marking the last step done.',
                   'tool_calls': [{'id': 'call_cs2', 'type': 'function',
                                   'function': {'name': 'complete_step',
                                                'arguments': json.dumps(
                                                    {'index': 1})}}]}
        else:
            msg = {'role': 'assistant',
                   'content': 'Done: report.md written using subagent '
                              'research. All gates passed.'}
        return {'message': msg,
                'usage': {'prompt_tokens': 100 + 40 * n,
                          'completion_tokens': 45}}


class OpenAICompat:
    """Works with OpenAI, OpenRouter, local llama.cpp/LM Studio, etc."""

    def __init__(self, cfg, api_key):
        self.name = cfg['model']
        self.base = cfg['base_url'].rstrip('/')
        self.key = api_key

    def chat(self, messages, tools=None):
        payload = {'model': self.name, 'messages': messages}
        if tools:
            payload['tools'] = tools
        req = urllib.request.Request(
            self.base + '/chat/completions',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + self.key})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        usage = d.get('usage') or {}
        return {'message': d['choices'][0]['message'],
                'usage': {'in': usage.get('prompt_tokens', 0),
                          'out': usage.get('completion_tokens', 0)}}


def make_provider(cfg, api_key):
    if cfg['provider'] == 'mock':
        return MockProvider()
    return OpenAICompat(cfg, api_key)
