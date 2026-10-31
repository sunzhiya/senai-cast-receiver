import json
import os
import shutil
import subprocess
import sys
import tempfile

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAIN_PY = os.path.join(PROJECT_DIR, 'main.py')
APP_NAME = '森投屏接收端'
ICON = os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico')
ICON_INDEX = 0
NODE = r'C:\Users\86156\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'


def _desktop():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
        val, _ = winreg.QueryValueEx(key, 'Desktop')
        winreg.CloseKey(key)
        val = os.path.expandvars(val)
        if os.path.isdir(val):
            return val
    except Exception:
        pass
    home = os.path.expanduser('~')
    for p in (os.path.join(home, 'Desktop'),
              os.path.join(home, 'OneDrive', 'Desktop'),
              os.path.join(os.environ.get('USERPROFILE', home), 'Desktop')):
        if os.path.isdir(p):
            return p
    return os.path.join(home, 'Desktop')


DESKTOP = _desktop()


def _pythonw():
    base = os.path.dirname(sys.executable)
    pw = os.path.join(base, 'pythonw.exe')
    if os.path.exists(pw):
        return pw
    if os.path.exists(sys.executable):
        return sys.executable
    return 'pythonw.exe'


def _target():
    pw = _pythonw()
    if os.path.exists(MAIN_PY):
        return pw, '"%s"' % MAIN_PY, PROJECT_DIR
    return pw, '-m main', os.path.expanduser('~')


def _stage_path(name=None):
    base = PROJECT_DIR if os.access(PROJECT_DIR, os.W_OK) else tempfile.gettempdir()
    return os.path.join(base, (name or APP_NAME) + '.lnk')


def build_lnk(lnk_path, extra_args=None, description=None, icon_index=None):
    target, arguments, workdir = _target()
    if extra_args:
        arguments += ' ' + extra_args
    cmd = [
        _pythonw(), '-m', 'pylnk3', 'create', target, lnk_path,
        '--arguments', arguments,
        '--workdir', workdir,
        '--icon', ICON,
        '--icon-index', str(ICON_INDEX if icon_index is None else icon_index),
        '--description', description or '森投屏接收端 - 系统解码(杜比)投屏接收',
        '--mode', 'Normal',
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return lnk_path


def install_to_desktop(suffix='', extra_args=None, description=None):
    name = APP_NAME + (suffix if suffix else ' (系统解码·杜比)')
    stage = _stage_path(name)
    build_lnk(stage, extra_args=extra_args or '--backend windows',
               description=description or '森投屏接收端 - 系统解码模式(Media Foundation, 可用 HEVC/AV1/VP9 扩展+硬件解码+杜比)')
    dest = os.path.join(DESKTOP, name + '.lnk')
    try:
        shutil.copy2(stage, dest)
    except (PermissionError, OSError):
        script = 'require("fs").copyFileSync(%s, %s)' % (
            json.dumps(stage), json.dumps(dest))
        subprocess.run([NODE, '-e', script], check=True)
    return dest


def desktop_lnk(suffix=' (系统解码·杜比)'):
    return os.path.join(DESKTOP, APP_NAME + suffix + '.lnk')


def legacy_shortcuts():
    return [
        os.path.join(DESKTOP, APP_NAME + '.lnk'),
        os.path.join(DESKTOP, APP_NAME + ' (系统解码·杜比).lnk'),
    ]


def ensure_desktop_shortcut():
    from .msix import is_packaged
    if is_packaged():
        return None
    if os.path.exists(desktop_lnk()):
        return None
    try:
        import pylnk3
    except Exception:
        return None
    try:
        return install_to_desktop()
    except Exception:
        return None


def install_default():
    path = install_to_desktop()
    for old in legacy_shortcuts():
        try:
            if os.path.exists(old) and old != path:
                os.remove(old)
        except Exception:
            pass
    return [path]


def install_both():
    return install_default()


def cli():
    made = []
    for p in install_default():
        print('桌面快捷方式已生成: %s' % p)
        made.append(p)
    return made


if __name__ == '__main__':
    cli()
