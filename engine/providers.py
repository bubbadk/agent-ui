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

        # Honest refusal for things the scripted mock cannot do.
        weather = any(w in gl for w in ('weather', 'vejr', 'forecast'))
        if weather:
            return {'message': {'role': 'assistant', 'content':
                'I cannot check the weather: I am running on the scripted '
                'mock provider, which has no network access. Start the engine '
                'with a real model (provider "openai_compat" in '
                '~/.agentui/config.json) and I will fetch '
                'https://wttr.in/nyborg?format=3 via the web_fetch tool.'},
                'usage': {'prompt_tokens': 60, 'completion_tokens': 55}}

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
