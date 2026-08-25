"""Model providers: deterministic mock + any OpenAI-compatible endpoint."""
import json
import urllib.request


class MockProvider:
    """Scripted provider so the full pipeline runs without an API key."""

    name = 'mock-frontier'

    def chat(self, messages, tools=None):
        goal = ''
        for m in messages:
            if m.get('role') == 'user':
                goal = m['content']
        gl = goal.lower()

        # Weather: actually fetch it via the engine's web_fetch tool.
        weather = any(w in gl for w in ('weather', 'vejr', 'forecast'))
        if weather:
            import re
            from urllib.parse import quote
            m = re.search(r'(?:vejret|weather|forecast)\s+(?:i|in|for)\s+(.+?)[\s?!.]*$',
                          goal, re.IGNORECASE)
            city = (m.group(1) if m else goal.split()[-1]).strip() or 'nyborg'
            n = sum(1 for x in messages if x.get('role') == 'assistant')
            url = 'https://wttr.in/%s?format=3' % quote(city)
            if n == 0:
                return {'message': {
                    'role': 'assistant',
                    'content': 'Fetching current weather for %s.' % city,
                    'tool_calls': [{
                        'id': 'call_wx',
                        'type': 'function',
                        'function': {'name': 'web_fetch',
                                     'arguments': json.dumps({'url': url})},
                    }]},
                    'usage': {'prompt_tokens': 70, 'completion_tokens': 25}}
            # second turn: read the tool result and summarise it
            obs = ''
            for x in messages:
                if x.get('role') == 'tool':
                    obs = x.get('content', '')
            try:
                body = json.loads(obs).get('body', '')
            except ValueError:
                body = ''
            if body:
                text = 'Current weather — %s' % body.strip()
            else:
                text = ('I could not retrieve the weather right now '
                        '(fetch failed). Raw result: %s' % obs[:200])
            return {'message': {'role': 'assistant', 'content': text},
                    'usage': {'prompt_tokens': 110, 'completion_tokens': 40}}

        n = sum(1 for m in messages if m.get('role') == 'assistant')
        if n == 0:
            msg = {
                'role': 'assistant',
                'content': 'PLAN: write hello module, then verify it compiles.',
                'tool_calls': [{
                    'id': 'call_1',
                    'type': 'function',
                    'function': {
                        'name': 'write_file',
                        'arguments': json.dumps({
                            'path': 'hello.py',
                            'content': '"""Hello module."""\n\n'
                                       'def greet():\n    return "hi"\n\n'
                                       'if __name__ == "__main__":\n'
                                       '    print(greet())\n',
                        }),
                    },
                }],
            }
        elif n == 1:
            msg = {
                'role': 'assistant',
                'content': 'Now verifying the module compiles.',
                'tool_calls': [{
                    'id': 'call_2',
                    'type': 'function',
                    'function': {
                        'name': 'run_tests',
                        'arguments': json.dumps({'target': 'hello.py'}),
                    },
                }],
            }
        else:
            msg = {'role': 'assistant',
                   'content': 'Done: hello.py written and verified. '
                              'All acceptance criteria passed.'}
        return {'message': msg,
                'usage': {'prompt_tokens': 90 + 30 * n,
                          'completion_tokens': 35}}


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
