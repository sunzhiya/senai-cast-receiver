import ctypes
import os

_cached = None


def is_packaged():
    global _cached
    if _cached is not None:
        return _cached
    ok = False
    try:
        length = ctypes.c_uint32(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(
            ctypes.byref(length), None)
        if length.value:
            buf = ctypes.create_unicode_buffer(length.value)
            ctypes.windll.kernel32.GetCurrentPackageFullName(
                ctypes.byref(length), buf)
            ok = bool(buf.value)
        else:
            ok = False
        del rc
    except Exception:
        ok = False
    if not ok:
        for k in ('PACKAGE_FULL_NAME', 'APPX_PACKAGE_FULL_NAME'):
            if os.environ.get(k):
                ok = True
                break
    _cached = ok
    return ok


def package_family_name():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages')
        idx = 0
        while True:
            try:
                name = winreg.EnumKey(key, idx)
            except OSError:
                break
            idx += 1
            if name:
                return name
    except Exception:
        pass
    return ''


def install_root():
    try:
        import ctypes
        from ctypes import wintypes
        length = wintypes.DWORD(0)
        rc = ctypes.windll.kernel32.GetCurrentPackagePath(None, ctypes.byref(length), None)
        if length.value:
            buf = ctypes.create_unicode_buffer(length.value)
            ctypes.windll.kernel32.GetCurrentPackagePath(None, ctypes.byref(length), buf)
            return buf.value
        del rc
    except Exception:
        pass
    return ''


def package_version():
    try:
        length = ctypes.c_uint32(0)
        ctypes.windll.kernel32.GetCurrentPackageFullName(
            ctypes.byref(length), None)
        if not length.value:
            return ''
        buf = ctypes.create_unicode_buffer(length.value)
        ctypes.windll.kernel32.GetCurrentPackageFullName(
            ctypes.byref(length), buf)
        parts = buf.value.split('_')
        return parts[1] if len(parts) > 1 else ''
    except Exception:
        return ''


def summary():
    if not is_packaged():
        return '非 MSIX（源码/绿色版运行）'
    root = install_root()
    return 'MSIX 商店版运行中 | 安装目录: %s' % (root or '(未知)')
