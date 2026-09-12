import argparse
import os
import sys
import threading
import traceback
from datetime import datetime

from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtWidgets import QApplication, QMessageBox

from receiver.config import (get_local_ip, get_best_local_ip,
                             DEFAULT_DEVICE_NAME, DEFAULT_PORT)
from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState
from receiver.player import PlayerBridge
from receiver.gui import MainWindow
from receiver.netwatch import NetWatcher


def _install_crash_handler():
    """崩溃兜底：写入日志文件并尽量弹窗，避免 pythonw 下'默默没反应'。"""
    log_path = os.path.join(os.environ.get('TEMP', '.'), 'cast-receiver-crash.log')

    def handler(exc_type, exc_value, tb):
        msg = ''.join(traceback.format_exception(exc_type, exc_value, tb))
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write('\n[%s] CRASH\n%s' % (stamp, msg))
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None, '森投屏接收端启动失败',
                    '启动出错（详情见 %s）：\n\n%s' % (log_path, msg[-1500:]))
        except Exception:
            pass

    sys.excepthook = handler


def _disable_lan_proxy():
    """清掉 HTTP 代理环境变量。

    部分 App 会在手机端架本地代理、把片源 URL 重写成本机局域网地址
    （http://192.168.x.x:端口/）再推过来。解码器读取 http_proxy 这类
    环境变量后会改走代理，局域网地址就拉不到了。投屏目标都在局域网内，
    代理帮不上忙，统一清掉。
    """
    keys = [k for k in list(os.environ)
            if k.lower().endswith('_proxy') or k.lower() in ('all_proxy',)]
    cleared = []
    for k in keys:
        v = os.environ.get(k)
        if v:
            cleared.append('%s=%s' % (k, v))
        try:
            del os.environ[k]
        except Exception:
            pass
    os.environ['NO_PROXY'] = '*'
    os.environ['no_proxy'] = '*'
    return cleared


def _setup_media_backend(backend):
    """选播放引擎，必须在 QApplication 创建前设置。

    ffmpeg : 格式广，支持 HLS(m3u8)
    windows: Media Foundation 原生管道，能吃系统 HEVC/杜比视界扩展和硬件解码，
             但不支持 m3u8
    """
    b = (backend or os.environ.get('QT_MEDIA_BACKEND') or 'ffmpeg').strip().lower()
    if b not in ('ffmpeg', 'windows'):
        b = 'ffmpeg'
    os.environ['QT_MEDIA_BACKEND'] = b
    return b


def main():
    _install_crash_handler()
    ap = argparse.ArgumentParser(description='森投屏接收端 - DLNA/AirPlay 投屏接收')
    ap.add_argument('--name', default=DEFAULT_DEVICE_NAME, help='设备显示名')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT, help='HTTP 控制端口')
    ap.add_argument('--no-airplay', action='store_true', help='禁用 AirPlay 被发现')
    ap.add_argument('--backend', default=None, choices=['ffmpeg', 'windows'],
                    help='播放引擎: ffmpeg(默认,格式广含m3u8) / '
                         'windows(Media Foundation 原生管道,可用系统 HEVC/杜比视界扩展+硬件解码)')
    ap.add_argument('--no-splash', action='store_true',
                    help='跳过开屏动画（默认本来就不显示，除非你在外观里开过）')
    ap.add_argument('--no-shortcut', action='store_true',
                    help='启动时不自动在桌面创建快捷方式')
    args = ap.parse_args()
    backend = _setup_media_backend(args.backend)
    cleared = _disable_lan_proxy()

    app = QApplication(sys.argv)
    _icon = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         'receiver', 'assets', 'icon.ico'))
    if os.path.exists(_icon):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(_icon))
    ip = get_local_ip()
    if ip == '127.0.0.1':
        QMessageBox.warning(
            None, '网络提示',
            '未检测到局域网 IP，手机将无法发现本设备。请连接 Wi-Fi 或有线网络后重试。')

    state = RendererState()
    bridge = PlayerBridge(state)

    window = None

    def log_func(msg):
        if window is not None:
            window.append_log(msg)
        else:
            print(msg)

    nets = {'stack': None, 'airplay': None, 'airplay_server': None}
    watcher = None
    active_ip = ip

    def start_net(current_ip):
        """建 DLNA + AirPlay 全套服务并同步给 GUI。

        必须先 stop_net() 再建新的：Windows 的 SO_REUSEADDR 允许同端口重复 bind
        且不报错，残留的旧监听会抢走连接，手机就连不上了。
        """
        stop_net()  # 先彻底关闭旧的（含初始那个只 bind 未启动的 stack）
        st = DlnaStack(current_ip, args.port, args.name, state, log=log_func)
        nets['stack'] = st
        if window is not None:
            window.stack = st
            window.set_ip_display(current_ip)
            # 热切换后恢复用户选的清晰度策略（新栈默认是标准模式）
            if getattr(window, 'tv_mode', False):
                st.set_tv_mode(True)
        st.start()
        log_func('[DLNA] 控制服务已启动: http://%s:%d/device.xml' % (current_ip, args.port))
        if not args.no_airplay:
            try:
                from receiver.airplay.mdns import AirPlayResponder
                apr = AirPlayResponder(current_ip, args.name)
                apr.start()
                nets['airplay'] = apr
            except Exception as e:
                log_func('[AirPlay] mDNS 未启用: %s' % e)
            try:
                from receiver.airplay.server import AirPlayServer
                srv = AirPlayServer(current_ip, 7000, state, log=log_func)
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                nets['airplay_server'] = srv
                log_func('[AirPlay] 视频控制服务已启动: http://%s:7000/' % current_ip)
            except Exception as e:
                log_func('[AirPlay] 视频服务未启用: %s' % e)

    def stop_net():
        for key, method in (('stack', 'stop'), ('airplay', 'shutdown'),
                            ('airplay_server', 'shutdown')):
            obj = nets.get(key)
            if obj:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                nets[key] = None

    def restart_net(new_ip):
        """热切换 IP（手动按钮与自动监控共用）：停旧服务、用新 IP 重建。"""
        nonlocal active_ip
        if new_ip == active_ip:
            log_func('已是 IP %s，无需切换' % new_ip)
            if watcher is not None:
                watcher.set_current(new_ip)
            return
        log_func('正在切换网络 IP: %s ...' % new_ip)
        stop_net()
        start_net(new_ip)
        active_ip = new_ip
        if watcher is not None:
            watcher.set_current(new_ip)
        log_func('已切换并重启投屏服务，当前 IP=%s' % new_ip)

    # DlnaStack 一构造就 bind+listen 了，必须登记进 nets，
    # 让 start_net 建新栈前先关掉它，否则 8200 残留双监听
    stack = DlnaStack(ip, args.port, args.name, state, log=log_func)
    nets['stack'] = stack
    window = MainWindow(stack, bridge, {'ip': ip, 'port': args.port},
                        restart_callback=restart_net)

    # 开屏动画：默认关，用户在「外观」里开了才播
    if not args.no_splash:
        try:
            from receiver.splash import run_splash
            from receiver.appearance import load as load_appearance
            cfg = load_appearance()
            if cfg.get('splash_enabled'):
                run_splash(app, cfg, _icon, log=lambda m: None)
        except Exception as e:
            print('[开屏] 未启用: %s' % e)

    window.show()
    window.ip_auto_switch.connect(lambda new_ip: restart_net(new_ip))
    log_func('[播放器] 引擎: %s%s' % (
        backend, '（Media Foundation 原生管道，可用系统 HEVC/杜比视界扩展与硬件解码。'
                 '注意：该引擎不支持 HLS/m3u8，若投屏 App 推来的是 m3u8 请换 ffmpeg 引擎）'
        if backend == 'windows' else '（FFmpeg，格式覆盖广，支持 m3u8/HLS —— '
                                     '多数国产 App 投屏推的就是 m3u8，优先用这个）'))
    if cleared:
        log_func('[网络] 已清空 HTTP 代理环境变量（%s），避免拉不到手机侧局域网片源'
                 % ', '.join(cleared[:4]))
    start_net(ip)

    # 桌面图标：跑起来就顺手建一个（已存在则不动），下次直接双击进 GUI
    if not args.no_shortcut:
        def _ensure_shortcut():
            try:
                from receiver.shortcut import ensure_desktop_shortcut
                p = ensure_desktop_shortcut()
                if p:
                    log_func('[桌面] 已生成快捷方式: %s（以后双击它就能直接打开）' % p)
            except Exception:
                pass
        threading.Thread(target=_ensure_shortcut, daemon=True).start()

    # 运行中"最佳投屏 IP"变了（开关 VPN / 切 Wi-Fi / 插网线）就自动热切换
    watcher = NetWatcher(
        on_change=lambda new_ip: window.ip_auto_switch.emit(new_ip),
        interval=5, log=log_func)
    watcher.set_current(ip)
    watcher.start()
    best_ip, best_desc = get_best_local_ip()
    log_func('[网络] 已自动选择真实网卡: %s (%s)，并开启运行时自动监控'
             % (best_ip, best_desc))
    window.set_net_status('自动选网: %s' % best_desc)

    # 后台检查防火墙规则，若缺失则明确提示用户点「一键修复网络】
    def _firewall_hint():
        try:
            from receiver.firewall import check_cast_rules
            if not check_cast_rules():
                log_func(
                    '[提示] 未检测到 Windows 防火墙入站规则，手机可能无法主动搜索到本设备。'
                    '请点击工具栏「一键修复网络(扫不到时点)」，在 UAC 弹窗点“是”，'
                    '然后重启本软件。')
        except Exception:
            pass
    threading.Thread(target=_firewall_hint, daemon=True).start()

    rc = app.exec()
    if watcher is not None:
        watcher.stop()
    stop_net()
    sys.exit(rc)


if __name__ == '__main__':
    main()
