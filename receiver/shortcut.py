"""桌面快捷方式生成。

用 pylnk3 纯 Python 写 .lnk（不走 COM），指向 pythonw，双击直接出 GUI 无黑框。
两种运行方式都支持：
  - 源码/git：pythonw <项目目录>/main.py
  - pip 安装：pythonw -m main（main 被装成顶层模块）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 项目根目录（cast-receiver）：本文件位于 cast-receiver/receiver/shortcut.py
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAIN_PY = os.path.join(PROJECT_DIR, 'main.py')
APP_NAME = '森投屏接收端'
# 应用图标（receiver/assets/icon.ico，多尺寸）；pip 安装时随包一起带上
ICON = os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico')
ICON_INDEX = 0
NODE = r'C:\Users\86156\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'


def _desktop():
    """真实桌面路径。开了 OneDrive 桌面重定向后 ~/Desktop 未必是真桌面，
    以注册表 User Shell Folders 为准，取不到再按顺序猜。"""
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
    return pw if os.path.exists(pw) else sys.executable


def _target():
    """返回 (程序, 参数, 工作目录)。源码模式直接跑 main.py；
    pip 装完没有项目目录，用 pythonw -m main。"""
    pw = _pythonw()
    if os.path.exists(MAIN_PY):
        return pw, '"%s"' % MAIN_PY, PROJECT_DIR
    return pw, '-m main', os.path.expanduser('~')


def _stage_path(name=None):
    """先在本地落盘再复制到桌面（直接写桌面在部分环境会被拦）。
    pip 装的包目录多半不可写，那就落到临时目录。"""
    base = PROJECT_DIR if os.access(PROJECT_DIR, os.W_OK) else tempfile.gettempdir()
    return os.path.join(base, (name or APP_NAME) + '.lnk')


def build_lnk(lnk_path, extra_args=None, description=None, icon_index=None):
    """用 pylnk3 生成 .lnk 文件。

    extra_args: 追加给 main.py 的参数，例如 '--backend windows'
                （走系统 Media Foundation 管道，可调用 HEVC/杜比视界扩展 + 硬件解码）。
    """
    target, arguments, workdir = _target()
    if extra_args:
        arguments += ' ' + extra_args
    cmd = [
        _pythonw(), '-m', 'pylnk3', 'create', target, lnk_path,
        '--arguments', arguments,
        '--workdir', workdir,
        '--icon', ICON,
        '--icon-index', str(ICON_INDEX if icon_index is None else icon_index),
        '--description', description or '森投屏接收端 - DLNA/AirPlay/Miracast 投屏接收',
        '--mode', 'Normal',
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return lnk_path


def install_to_desktop(suffix='', extra_args=None, description=None):
    """生成快捷方式并放到桌面。优先直接写，失败（沙箱 EPERM）用 node 复制。

    suffix: 文件名后缀，例如 ' (系统解码·杜比)' -> 森投屏接收端 (系统解码·杜比).lnk
    """
    name = APP_NAME + suffix
    stage = _stage_path(name)
    build_lnk(stage, extra_args=extra_args, description=description)
    dest = os.path.join(DESKTOP, name + '.lnk')
    try:
        shutil.copy2(stage, dest)
    except (PermissionError, OSError):
        script = 'require("fs").copyFileSync(%s, %s)' % (
            json.dumps(stage), json.dumps(dest))
        subprocess.run([NODE, '-e', script], check=True)
    return dest


def desktop_lnk(suffix=''):
    return os.path.join(DESKTOP, APP_NAME + suffix + '.lnk')


def ensure_desktop_shortcut():
    """桌面上没有图标就建一个，有了就不动。

    启动时自动跑一次，所以 pip/git 装完跑起来桌面就有图标，下次双击即可。
    权限不够 / 没装 pylnk3 等情况一律静默跳过，不能因此挡住启动。
    """
    if os.path.exists(desktop_lnk()):
        return None
    try:
        import pylnk3  # noqa: F401
    except Exception:
        return None
    try:
        return install_to_desktop()
    except Exception:
        try:
            return install_to_desktop(suffix=' (系统解码·杜比)',
                                      extra_args='--backend windows')
        except Exception:
            return None


def install_both():
    """一次创建两个快捷方式：默认(ffmpeg,格式广) + 系统解码(Media Foundation,杜比/硬件解码)。"""
    a = install_to_desktop()
    b = install_to_desktop(
        suffix=' (系统解码·杜比)',
        extra_args='--backend windows',
        description='森投屏接收端 - 系统解码模式(Media Foundation, 可用 HEVC/杜比视界扩展+硬件解码)')
    return a, b


def cli():
    """命令行入口：`python -m receiver.shortcut` 或 pip 装完的 `senai-cast-shortcut`。
    强制重建两个桌面图标（默认 ffmpeg + 系统解码）。"""
    made = []
    for p in install_both():
        print('桌面快捷方式已生成: %s' % p)
        made.append(p)
    return made


if __name__ == '__main__':
    cli()
