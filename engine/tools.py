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
]


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

    return {'error': 'unknown tool: %s' % name}
