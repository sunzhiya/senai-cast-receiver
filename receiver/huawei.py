# -*- coding: utf-8 -*-
# 华为 / 安卓手机投到电脑，走的是系统 Miracast，不是一个能自己实现的私有协议。
# 华为 HiSuite、微软 Your Phone 都是闭源客户端，第三方碰不了它们的协议。
# 我们这边能做的就三件：查系统支不支持、帮把该开的开了、给正确入口。


import subprocess
import sys


def _run_ps(script, timeout=25):
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            capture_output=True, timeout=timeout,
            startupinfo=si, stdin=subprocess.DEVNULL).stdout or b''
        return out.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def miracast_available():
    """系统 Miracast 接收组件装没装（「无线显示器」/ Connect 应用）。"""
    if sys.platform != 'win32':
        return True
    out = _run_ps("Get-AppxPackage *Connect* | Select-Object -ExpandProperty Name -Unique")
    return 'Connect' in out


def hisuite_running():
    """华为手机助手在跑没（能多屏协同，但只认华为电脑/装了它的环境）。"""
    out = _run_ps("Get-Process | Where-Object {$_.ProcessName -match 'HiSuite|Huawei'} "
                  "| Select-Object -ExpandProperty ProcessName -Unique")
    return bool(out.strip())


def phone_link_running():
    """微软 Your Phone / Phone Link 在跑没（能投安卓）。"""
    out = _run_ps("Get-Process | Where-Object {$_.ProcessName -match 'PhoneLink|YourPhone|YourPhone'} "
                  "| Select-Object -ExpandProperty ProcessName -Unique")
    return bool(out.strip())


def open_miracast_settings():
    """调起 设置 → 投影到此电脑。"""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl('ms-settings:project'))


def open_connect_app():
    """调起 Windows「连接」应用（等手机投过来的那个窗口）。"""
    try:
        subprocess.Popen(['ms-app://microsoft.windowsconnect'],
                         shell=True, start_new_session=True)
        return True
    except Exception:
        return False


def build_report():
    """给 GUI 用的检测小结，如实说哪条路能走。"""
    has_mira = miracast_available()
    lines = [
        '系统 Miracast 接收: ' + ('已装 [OK]' if has_mira else '未装 [X]（商店搜「无线显示器」装一个）'),
        '华为 HiSuite: ' + ('运行中' if hisuite_running() else '没在跑'),
        '微软 Your Phone: ' + ('运行中' if phone_link_running() else '没在跑'),
    ]
    return lines
