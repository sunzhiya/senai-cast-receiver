

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
    if sys.platform != 'win32':
        return True
    out = _run_ps("Get-AppxPackage *Connect* | Select-Object -ExpandProperty Name -Unique")
    return 'Connect' in out


def hisuite_running():
    out = _run_ps("Get-Process | Where-Object {$_.ProcessName -match 'HiSuite|Huawei'} "
                  "| Select-Object -ExpandProperty ProcessName -Unique")
    return bool(out.strip())


def phone_link_running():
    out = _run_ps("Get-Process | Where-Object {$_.ProcessName -match 'PhoneLink|YourPhone|YourPhone'} "
                  "| Select-Object -ExpandProperty ProcessName -Unique")
    return bool(out.strip())


def open_miracast_settings():
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl('ms-settings:project'))


def open_connect_app():
    try:
        subprocess.Popen(['ms-app://microsoft.windowsconnect'],
                         shell=True, start_new_session=True)
        return True
    except Exception:
        return False


def build_report():
    has_mira = miracast_available()
    lines = [
        '系统 Miracast 接收: ' + ('已装 [OK]' if has_mira else '未装 [X]（商店搜「无线显示器」装一个）'),
        '华为 HiSuite: ' + ('运行中' if hisuite_running() else '没在跑'),
        '微软 Your Phone: ' + ('运行中' if phone_link_running() else '没在跑'),
    ]
    return lines
