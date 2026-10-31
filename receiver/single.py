
import ctypes
import os
from ctypes import wintypes

MUTEX_NAME = 'Local\\SenAICastReceiver.SingleInstance'
WINDOW_TITLE = '森投屏接收端'

ERROR_ALREADY_EXISTS = 183
SW_SHOW = 5
SW_RESTORE = 9

_handle = None


def acquire():
    global _handle
    if os.name != 'nt':
        return True
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                     wintypes.LPCWSTR]
        h = k32.CreateMutexW(None, False, MUTEX_NAME)
        err = ctypes.get_last_error()
        if not h:
            return True
        if err == ERROR_ALREADY_EXISTS:
            k32.CloseHandle(h)
            return False
        _handle = h
        return True
    except Exception:
        return True


def release():
    global _handle
    if _handle is None:
        return
    try:
        ctypes.WinDLL('kernel32').CloseHandle(_handle)
    except Exception:
        pass
    _handle = None


def activate_existing(title=WINDOW_TITLE):
    if os.name != 'nt':
        return False
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.FindWindowW.restype = wintypes.HWND
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetForegroundWindow.argtypes = [wintypes.HWND]
        u32.IsIconic.argtypes = [wintypes.HWND]
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return False
        u32.ShowWindow(hwnd, SW_RESTORE if u32.IsIconic(hwnd) else SW_SHOW)
        u32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
