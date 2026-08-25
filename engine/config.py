"""Atlas engine configuration."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(os.path.expanduser('~'), '.agentui')

DEFAULTS = {
    'provider': 'mock',                      # 'mock' | 'openai_compat'
    'base_url': 'https://api.openai.com/v1', # any OpenAI-compatible endpoint
    'model': 'gpt-4o-mini',
    'api_key_env': 'OPENAI_API_KEY',
    'gates': 'strict',                       # strict | advisory | draft
    'daily_budget': 12.0,
}


def config_path():
    return os.path.join(HOME, 'config.json')


def load():
    """Load user config over defaults. Workspace always lives inside the repo."""
    cfg = dict(DEFAULTS)
    p = config_path()
    if os.path.exists(p):
        with open(p) as f:
            cfg.update(json.load(f))
    cfg['root'] = ROOT
    cfg['home'] = HOME
    ws = cfg.get('workspace') or 'workspace'
    if not os.path.isabs(ws):
        ws = os.path.join(ROOT, ws)
    os.makedirs(ws, exist_ok=True)
    cfg['workspace'] = os.path.realpath(ws)
    os.makedirs(HOME, exist_ok=True)
    return cfg


def api_key(cfg):
    return os.environ.get(cfg.get('api_key_env', ''), '')
