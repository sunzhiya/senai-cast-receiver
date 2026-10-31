import os
import shutil
import subprocess

_CACHE = {}


def _nvidia_smi():
    exe = shutil.which('nvidia-smi')
    if not exe:
        for p in (r'C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe',
                  r'C:\Windows\System32\nvidia-smi.exe'):
            if os.path.exists(p):
                exe = p
                break
    if not exe:
        return None
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        out = subprocess.run(
            [exe, '--query-gpu=name,driver_version', '--format=csv,noheader'],
            capture_output=True, timeout=8, startupinfo=si,
            stdin=subprocess.DEVNULL).stdout or b''
        line = out.decode('utf-8', errors='ignore').strip().splitlines()
        if not line:
            return None
        parts = [x.strip() for x in line[0].split(',')]
        return {'name': parts[0], 'driver': parts[1] if len(parts) > 1 else ''}
    except Exception:
        return None


def probe():
    if _CACHE:
        return _CACHE
    info = {'supported': False, 'gpu': '', 'driver': '', 'reason': ''}
    gpu = _nvidia_smi()
    if not gpu:
        info['reason'] = '未检测到 NVIDIA 显卡或驱动'
        _CACHE.update(info)
        return info
    info['gpu'] = gpu['name']
    info['driver'] = gpu['driver']
    name = gpu['name'].upper()
    rt_series = ('RTX 20', 'RTX 30', 'RTX 40', 'RTX 50', 'RTX A', 'RTX ADA',
                 'QUADRO RTX', 'RTX 2000', 'RTX 4000', 'RTX 5000', 'RTX 6000')
    if any(k in name for k in rt_series):
        info['supported'] = True
    else:
        info['reason'] = '当前 NVIDIA 显卡不支持 RTX 超分（需 RTX 20 系及以上）'
    _CACHE.update(info)
    return info


def is_supported():
    return bool(probe().get('supported'))


def description():
    p = probe()
    if not p.get('supported'):
        return p.get('reason') or '当前设备不支持'
    return '%s（驱动 %s）' % (p.get('gpu', ''), p.get('driver', ''))


def open_nvidia_control_panel():
    for exe in (r'C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe',
                r'C:\Program Files\WindowsApps'):
        if exe.endswith('nvcplui.exe') and os.path.exists(exe):
            try:
                os.startfile(exe)
                return True
            except Exception:
                pass
    try:
        os.startfile('ms-settings:display-advancedgraphics')
        return True
    except Exception:
        return False
