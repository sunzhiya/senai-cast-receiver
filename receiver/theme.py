import json
import os

from .appearance import settings_path

THEMES_FILE = 'themes.json'

BUILTIN = {
    '经典黑': {
        'accent': '#2e7d32',
        'bg': '#0e0e0e',
        'fg': '#e8e8e8',
        'panel': '#1e1e1e',
    },
    '深邃蓝': {
        'accent': '#3f8cff',
        'bg': '#0b1220',
        'fg': '#dce6f5',
        'panel': '#16233a',
    },
    '暗夜紫': {
        'accent': '#9b6dff',
        'bg': '#120f1c',
        'fg': '#e6dff5',
        'panel': '#211a35',
    },
    '暖阳橙': {
        'accent': '#ff8a3d',
        'bg': '#17120c',
        'fg': '#f2e5d8',
        'panel': '#2b1f14',
    },
    '青瓷绿': {
        'accent': '#20b2aa',
        'bg': '#0c1614',
        'fg': '#d8ece9',
        'panel': '#152825',
    },
    '樱粉': {
        'accent': '#ff6f91',
        'bg': '#180f13',
        'fg': '#f2dfe5',
        'panel': '#2b1a20',
    },
}

DEFAULT_THEME = '经典黑'


def _themes_path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(base, 'SenAICast')
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, THEMES_FILE)
        with open(p, 'a', encoding='utf-8'):
            pass
        return p
    except Exception:
        return os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', THEMES_FILE))


def builtin_names():
    return list(BUILTIN.keys())


def get(name):
    custom = load_custom()
    if name in custom:
        return dict(custom[name])
    return dict(BUILTIN.get(name, BUILTIN[DEFAULT_THEME]))


def load_custom():
    try:
        with open(_themes_path(), encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_custom(name, colors):
    if not name:
        return False
    data = load_custom()
    data[name] = {k: colors.get(k, BUILTIN[DEFAULT_THEME][k])
                  for k in ('accent', 'bg', 'fg', 'panel')}
    try:
        with open(_themes_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def delete_custom(name):
    data = load_custom()
    if name in data:
        del data[name]
        try:
            with open(_themes_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            pass
    return False


def all_names():
    names = list(BUILTIN.keys())
    for k in load_custom():
        if k not in names:
            names.append(k)
    return names


def stylesheet(colors):
    accent = colors.get('accent', '#2e7d32')
    bg = colors.get('bg', '#0e0e0e')
    fg = colors.get('fg', '#e8e8e8')
    panel = colors.get('panel', '#1e1e1e')
    return """
    QWidget { background:%s; color:%s; }
    QToolBar { background:%s; border:none; spacing:4px; }
    QToolBar QLabel { color:%s; }
    QPushButton {
        background:%s; color:%s; border:1px solid #444;
        border-radius:4px; padding:4px 10px;
    }
    QPushButton:hover { background:#3a3a3a; }
    QPushButton:disabled { color:#777; }
    QComboBox {
        background:%s; color:%s; border:1px solid #444;
        border-radius:4px; padding:3px 6px;
    }
    QComboBox QAbstractItemView {
        background:%s; color:%s; selection-background-color:%s;
    }
    QLineEdit, QSpinBox, QTextEdit {
        background:#1a1a1a; color:%s; border:1px solid #444; border-radius:3px;
    }
    QSlider::groove:horizontal { height:6px; background:#333; border-radius:3px; }
    QSlider::sub-page:horizontal { background:%s; border-radius:3px; }
    QSlider::handle:horizontal {
        width:14px; margin:-5px 0; background:%s; border-radius:7px;
    }
    QDockWidget { color:%s; }
    QDockWidget::title { background:%s; padding:4px; }
    QTextEdit { background:#121212; }
    QLabel#posLabel, QLabel#durLabel { color:%s; }
    """ % (bg, fg, panel, fg, panel, fg, panel, fg, panel, fg, accent,
           fg, accent, fg, fg, panel, fg)


def progress_stylesheet(colors):
    accent = colors.get('accent', '#2e7d32')
    return (
        'QFrame { background:%s; }'
        'QSlider::groove:horizontal { height:6px; background:#333; border-radius:3px; }'
        'QSlider::sub-page:horizontal { background:%s; border-radius:3px; }'
        'QSlider::handle:horizontal { width:14px; margin:-5px 0; '
        'background:#e0e0e0; border-radius:7px; }'
        'QPushButton { background:#2a2a2a; color:#e8e8e8; border:1px solid #444; '
        'border-radius:4px; }'
        'QPushButton:hover { background:#3a3a3a; }'
    ) % (colors.get('bg', '#0e0e0e'), accent)
