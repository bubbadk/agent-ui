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
    'api_key': '',                           # optional key stored in config
    'gates': 'strict',                       # strict | advisory | draft
    'daily_budget': 12.0,
    'sub_budget': 0.5,
}

PERSIST_KEYS = ('provider', 'base_url', 'model', 'api_key_env', 'api_key',
                'gates', 'daily_budget', 'sub_budget')


def config_path():
    return os.path.join(HOME, 'config.json')


def save(cfg):
    """Persist the user-facing subset of cfg to ~/.agentui/config.json."""
    os.makedirs(HOME, exist_ok=True)
    out = {k: cfg[k] for k in PERSIST_KEYS if k in cfg}
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    return out


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
    """Env var wins; otherwise a key stored in the config file."""
    return (os.environ.get(cfg.get('api_key_env', ''), '')
            or cfg.get('api_key', ''))
