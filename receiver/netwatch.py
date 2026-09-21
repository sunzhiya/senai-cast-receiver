"""后台监控"最佳投屏 IP"，变了就回调（开关 VPN / 切 Wi-Fi / 插网线都不用手动管）。"""
import threading
import time

from .config import get_local_ip


class NetWatcher:
    def __init__(self, on_change, interval=5, log=None):
        self.on_change = on_change
        self.interval = interval
        self.log = log
        self._stop = threading.Event()
        self._thread = None
        self._current = None
        self._lock = threading.Lock()

    def _log(self, msg):
        if self.log:
            try:
                self.log(msg)
            except Exception:
                pass

    def set_current(self, ip):
        """由外部（启动 / 手动切换后）同步当前在用 IP，避免误触发。"""
        with self._lock:
            self._current = ip

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log('[NetWatch] 已启动网络自动监控（每 %d 秒检测一次 IP 变化）' % self.interval)

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                new_ip = get_local_ip()
            except Exception as e:
                self._log('[NetWatch] 检测异常: %s' % e)
                new_ip = None
            with self._lock:
                cur = self._current
            if new_ip and new_ip != '127.0.0.1' and new_ip != cur:
                self._log('[NetWatch] 检测到投屏 IP 变化: %s -> %s，准备自动切换'
                          % (cur, new_ip))
                with self._lock:
                    self._current = new_ip
                try:
                    self.on_change(new_ip)
                except Exception as e:
                    self._log('[NetWatch] 切换回调异常: %s' % e)
            elif new_ip == '127.0.0.1':
                self._log('[NetWatch] 暂无可用的局域网网卡，等待网络恢复...')
            self._stop.wait(self.interval)
