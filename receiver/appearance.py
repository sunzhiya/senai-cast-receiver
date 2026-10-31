import json
import os

APP_DIR = 'SenAICast'
FILE = 'settings.json'

DEFAULT = {
    'splash_enabled': False,
    'splash_image': '',
    'splash_title': '森投屏接收端',
    'splash_subtitle': 'DLNA / AirPlay 投屏接收端',
    'splash_ms': 1800,
    'bg_image': '',
    'bg_color': '#000000',
    'theme': '经典黑',
}


def settings_path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(base, APP_DIR)
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, FILE)
        with open(p, 'a', encoding='utf-8'):
            pass
        return p
    except Exception:
        return os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', FILE))


def load():
    cfg = dict(DEFAULT)
    try:
        with open(settings_path(), encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save(cfg):
    try:
        with open(settings_path(), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        return False
