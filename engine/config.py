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
    'provider_key': 'openai',                # which vendor is selected in UI
    'gates': 'strict',                       # strict | advisory | draft
    'daily_budget': 12.0,
    'sub_budget': 0.5,
    'providers': {},                         # per-vendor: base_url/model/api_key
    'agents': {},                            # named agents (Bot Mode)
    'active_agent': '',
}

PERSIST_KEYS = ('provider', 'base_url', 'model', 'api_key_env', 'api_key',
                'gates', 'daily_budget', 'sub_budget', 'provider_key',
                'providers', 'agents', 'active_agent')

ALL_SKILLS = ['files', 'code', 'shell', 'web', 'subagents']


def config_path():
    return os.path.join(HOME, 'config.json')


def save(cfg):
    """Persist the user-facing subset of cfg to ~/.agentui/config.json."""
    os.makedirs(HOME, exist_ok=True)
    out = {k: cfg[k] for k in PERSIST_KEYS if k in cfg}
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    return out


def effective_task_cfg(cfg):
    """Resolve active agent + selected provider into a flat task config.

    Priority: env key > active provider key > legacy top-level key.
    """
    t = dict(cfg)
    pk = cfg.get('provider_key', 'mock')
    prov = (cfg.get('providers') or {}).get(pk) or {}
    agent = (cfg.get('agents') or {}).get(cfg.get('active_agent') or '')

    if agent:
        pk = agent.get('provider_key') or pk
        prov = (cfg.get('providers') or {}).get(pk) or prov
        t['model'] = agent.get('model') or prov.get('model') or cfg['model']
        t['skills'] = agent.get('skills')          # None = everything allowed
        t['agent_prompt'] = agent.get('prompt', '')
        t['agent_name'] = cfg.get('active_agent')
    else:
        t['model'] = prov.get('model') or cfg['model']

    t['provider_key'] = pk
    if prov.get('base_url'):
        t['base_url'] = prov['base_url']
    key = (os.environ.get(cfg.get('api_key_env', ''), '')
           or prov.get('api_key', '') or cfg.get('api_key', ''))
    t['_api_key'] = key
    return t


def load():
    """Load user config over defaults. Workspace always lives inside the repo."""
    cfg = dict(DEFAULTS)
    p = config_path()
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            cfg.update(json.load(f))
    cfg['root'] = ROOT
    cfg['home'] = HOME

    # Migrate legacy single-provider fields into the providers registry so
    # keys saved before v0.7 keep working.
    if not cfg.get('providers') and (cfg.get('api_key') or cfg.get('model')):
        pk = cfg.get('provider_key') or 'openai'
        if pk != 'mock':
            cfg['providers'] = {pk: {
                'base_url': cfg.get('base_url', ''),
                'model': cfg.get('model', ''),
                'api_key': cfg.get('api_key', ''),
            }}

    # Seed a default agent so Bot Mode always has something to run.
    if not cfg.get('agents'):
        cfg['agents'] = {'atlas': {
            'label': 'Atlas (default)',
            'provider_key': cfg.get('provider_key', 'mock'),
            'model': cfg.get('model', ''),
            'skills': list(ALL_SKILLS),
            'prompt': '',
        }}
        cfg['active_agent'] = 'atlas'
    if cfg.get('active_agent') not in (cfg.get('agents') or {}):
        cfg['active_agent'] = next(iter(cfg.get('agents') or {}), '')

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
