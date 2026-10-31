import os
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'SenAICastReceiver'


def _is_packaged():
    try:
        from .msix import is_packaged
        return bool(is_packaged())
    except Exception:
        return False


def _aumid():
    try:
        from .msix import package_family_name
        fam = package_family_name()
        if fam:
            return '%s!App' % fam
    except Exception:
        pass
    return 'sensen.3730939450514_1b09t5391d734!App'


def _command(silent):
    if _is_packaged():
        return 'explorer.exe shell:AppsFolder\\%s' % _aumid()
    if getattr(sys, 'frozen', False):
        exe = sys.executable
    else:
        exe = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'main.py'))
        exe = '"%s" "%s"' % (sys.executable, exe)
    if silent:
        if getattr(sys, 'frozen', False):
            return '"%s" --silent' % exe
        return '%s --silent' % exe
    return exe


def _reg():
    try:
        import winreg
        return winreg
    except Exception:
        return None


def is_enabled():
    winreg = _reg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except Exception:
        return False


def current_command():
    winreg = _reg()
    if winreg is None:
        return ''
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, VALUE_NAME)[0]
    except Exception:
        return ''


def enable(silent=False):
    winreg = _reg()
    if winreg is None:
        return False, '当前系统不支持注册表操作'
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _command(silent))
        return True, _command(silent)
    except Exception as e:
        return False, str(e)


def disable():
    winreg = _reg()
    if winreg is None:
        return False, '当前系统不支持注册表操作'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
        return True, ''
    except FileNotFoundError:
        return True, ''
    except Exception as e:
        return False, str(e)


def silent_supported():
    return not _is_packaged()
