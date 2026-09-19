"""外观设置持久化：开屏动画 + 自定义背景。

存在 %APPDATA%/SenAICast/settings.json（exe 安装版也适用）；
写不了就退回程序同目录，保证便携模式可用。
"""
import json
import os

APP_DIR = 'SenAICast'
FILE = 'settings.json'

DEFAULT = {
    # 开屏默认关闭：不动手设置就直进主窗口，想要的人自己去「外观」里开并配素材
    'splash_enabled': False,
    'splash_image': '',        # 开屏背景图，空=用渐变；gif 会当动图播
    'splash_title': '森投屏接收端',
    'splash_subtitle': 'DLNA / AirPlay 投屏接收端',
    'splash_ms': 1800,         # 开屏停留时长
    'bg_image': '',            # 播放器背景图，空=用纯色
    'bg_color': '#000000',     # 播放器背景色
}


def settings_path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(base, APP_DIR)
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, FILE)
        # 确认真的可写，否则退回程序目录
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
