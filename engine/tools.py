"""Sandboxed tools. Every path access is confined to the agent workspace."""
import glob
import json
import os
import subprocess
import sys

SCHEMAS = [
    {'type': 'function', 'function': {
        'name': 'write_file',
        'description': 'Create or overwrite a text file inside the workspace.',
        'parameters': {'type': 'object',
                       'properties': {'path': {'type': 'string'},
                                      'content': {'type': 'string'}},
                       'required': ['path', 'content']}}},
    {'type': 'function', 'function': {
        'name': 'read_file',
        'description': 'Read a text file inside the workspace.',
        'parameters': {'type': 'object',
                       'properties': {'path': {'type': 'string'}},
                       'required': ['path']}}},
    {'type': 'function', 'function': {
        'name': 'list_dir',
        'description': 'List files in the workspace (or a subfolder).',
        'parameters': {'type': 'object',
                       'properties': {'path': {'type': 'string'}}}}},
    {'type': 'function', 'function': {
        'name': 'run_tests',
        'description': 'Byte-compile Python files to verify they are valid '
                       '(acceptance check). Defaults to every .py written this task.',
        'parameters': {'type': 'object',
                       'properties': {'target': {'type': 'string'}}}}},
    {'type': 'function', 'function': {
        'name': 'run_command',
        'description': 'Run an allowlisted shell command inside the workspace '
                       '(ls, cat, echo, grep, python3, git, ...). No shell '
                       'operators; 30s timeout.',
        'parameters': {'type': 'object',
                       'properties': {'command': {'type': 'string'}},
                       'required': ['command']}}},
    {'type': 'function', 'function': {
        'name': 'set_plan',
        'description': 'Publish the plan for this task: 2-4 short steps. '
                       'Call this first, before any other tool.',
        'parameters': {'type': 'object',
                       'properties': {'steps': {'type': 'array',
                                                'items': {'type': 'string'}}},
                       'required': ['steps']}}},
    {'type': 'function', 'function': {
        'name': 'web_fetch',
        'description': 'Fetch an http(s) URL and return the response body as '
                       'text (first 4000 chars). Example: '
                       'https://wttr.in/nyborg?format=3 for weather.',
        'parameters': {'type': 'object',
                       'properties': {'url': {'type': 'string'}},
                       'required': ['url']}}},
]


def _url_allowed(url):
    """Block non-http(s) schemes and private/loopback targets (SSRF guard)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        return False, 'only http(s) URLs are allowed'
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except OSError as exc:
        return False, 'cannot resolve host: %s' % exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast):
            return False, 'refusing to fetch private/loopback address'
    return True, ''


def _web_fetch(url):
    import urllib.request
    ok, reason = _url_allowed(url)
    if not ok:
        raise PermissionError(reason)
    req = urllib.request.Request(url, headers={'User-Agent': 'atlas-agent/0.1'})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read(20000).decode('utf-8', 'replace')
    return body[:4000]


class ToolContext:
    def __init__(self, workspace, on_event):
        self.ws = os.path.realpath(workspace)
        self.on_event = on_event
        self.written = []          # workspace-relative paths written this task

    def resolve(self, p):
        rp = os.path.realpath(os.path.join(self.ws, p))
        if not (rp == self.ws or rp.startswith(self.ws + os.sep)):
            raise PermissionError('path outside workspace: %s' % p)
        return rp


SHELL_ALLOW = {'ls', 'cat', 'echo', 'pwd', 'date', 'whoami', 'grep', 'wc',
               'head', 'tail', 'python3', 'pip', 'git', 'find', 'sort',
               'uniq', 'diff'}
SHELL_OPS = {';', '&&', '||', '|', '&', '`', '>', '<', '$(', '>'}


def _run_command(cmd, ctx):
    import shlex
    parts = shlex.split(cmd)
    if not parts:
        raise ValueError('empty command')
    for tok in parts:
        if tok in SHELL_OPS or any(ch in tok for ch in ';&|`<>$'):
            raise PermissionError('shell operators not allowed: %s' % tok)
    if parts[0] not in SHELL_ALLOW:
        raise PermissionError('binary not allowlisted: %s' % parts[0])
    r = subprocess.run(parts, cwd=ctx.ws, capture_output=True,
                       text=True, timeout=30)
    return {'ok': r.returncode == 0, 'exit': r.returncode,
            'output': (r.stdout + r.stderr)[-4000:]}


def _compile_check(path):
    r = subprocess.run([sys.executable, '-m', 'py_compile', path],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr)[-500:]


def dispatch(name, args, ctx):
    """Execute one tool call. Returns a JSON-serialisable dict."""
    ctx.on_event('TOOL_CALL', {'tool': name, 'args': {
        k: (v if k != 'content' else v[:80] + '…') for k, v in args.items()}})
    try:
        result = _dispatch(name, args, ctx)
    except Exception as exc:                      # noqa: BLE001 - report to model
        result = {'error': '%s: %s' % (type(exc).__name__, exc)}
    ctx.on_event('TOOL_RESULT', {'tool': name,
                                 'ok': 'error' not in result})
    return result


def _dispatch(name, args, ctx):
    if name == 'write_file':
        rp = ctx.resolve(args['path'])
        os.makedirs(os.path.dirname(rp) or rp, exist_ok=True)
        with open(rp, 'w', encoding='utf-8') as f:
            f.write(args.get('content', ''))
        rel = os.path.relpath(rp, ctx.ws)
        if rel not in ctx.written:
            ctx.written.append(rel)
        return {'ok': True, 'bytes': len(args.get('content', '')), 'path': rel}

    if name == 'read_file':
        rp = ctx.resolve(args['path'])
        with open(rp, encoding='utf-8') as f:
            return {'ok': True, 'content': f.read()[:8000]}

    if name == 'list_dir':
        base = ctx.resolve(args.get('path') or '.')
        items = sorted(glob.glob(os.path.join(base, '*')))
        return {'ok': True, 'entries': [
            os.path.basename(i) + ('/' if os.path.isdir(i) else '')
            for i in items][:200]}

    if name == 'run_tests':
        target = args.get('target')
        targets = [ctx.resolve(target)] if target else \
            [ctx.resolve(w) for w in ctx.written]
        results = []
        for t in targets:
            ok, out = _compile_check(t)
            results.append({'file': os.path.relpath(t, ctx.ws),
                            'pass': ok, 'output': out})
        return {'ok': all(r['pass'] for r in results), 'results': results}

    if name == 'run_command':
        return _run_command(args.get('command', ''), ctx)

    if name == 'set_plan':
        return {'ok': True}

    if name == 'web_fetch':
        body = _web_fetch(args['url'])
        return {'ok': True, 'url': args['url'], 'body': body}

    return {'error': 'unknown tool: %s' % name}
