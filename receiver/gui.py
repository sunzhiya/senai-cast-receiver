import io
import json
import os
import socket
import subprocess
import sys
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QTimer
from PyQt6.QtGui import QDesktopServices, QPixmap, QIcon, QAction
from PyQt6.QtWidgets import (QMainWindow, QToolBar, QLabel, QPushButton,
                             QSlider, QTextEdit, QDockWidget, QLineEdit,
                             QMessageBox, QComboBox, QDialog, QVBoxLayout,
                             QHBoxLayout, QApplication, QCheckBox, QSpinBox,
                             QFileDialog, QColorDialog, QGroupBox, QFormLayout,
                             QSystemTrayIcon, QMenu, QWidget)
from .player_widget import CastPlayer
from .player import PlayerBridge
from .config import list_local_ips
from .island import IslandBar

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_TEST_URL = 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4'


class MainWindow(QMainWindow):
    ip_auto_switch = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, stack, bridge, info, restart_callback=None):
        super().__init__()
        self.log_signal.connect(self._do_append_log)
        self.stack = stack
        self.bridge = bridge
        self.info = info
        self.restart_callback = restart_callback
        self.setWindowTitle('森投屏接收端')
        self.resize(960, 620)
        icon = os.path.abspath(os.path.join(HERE, 'assets', 'icon.ico'))
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self._fs_geo = None

        self.player = CastPlayer(self, log=self.append_log)
        self.player.playerStatus.connect(self.append_log)
        self.player.playerError.connect(self.append_log)
        self.setCentralWidget(self.player)

        self._build_toolbar()
        self._build_tools()
        self._build_dock()
        self._connect()
        self._apply_saved_appearance()
        self._start_stat_timer()
        self._build_tray()

    def _build_tray(self):
        self._tray = None
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            icon_path = os.path.abspath(os.path.join(HERE, 'assets', 'icon.ico'))
            icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip('森投屏接收端 — 正在接收投屏')

            menu = QMenu()
            act_show = QAction('显示窗口', self)
            act_show.triggered.connect(self._restore_from_tray)
            act_pause = QAction('暂停 / 继续', self)
            act_pause.triggered.connect(self._toggle_pause)
            act_quit = QAction('退出（真正结束）', self)
            act_quit.triggered.connect(self._quit_app)
            menu.addAction(act_show)
            menu.addAction(act_pause)
            menu.addSeparator()
            menu.addAction(act_quit)
            tray.setContextMenu(menu)
            tray.activated.connect(self._on_tray_activated)
            tray.show()
            self._tray = tray
            self.append_log('[托盘] 已驻留系统托盘，关窗口不退出，投屏继续接收')
        except Exception as e:
            self.append_log('[托盘] 不可用: %s' % e)

    def _on_tray_activated(self, reason):
        try:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self._restore_from_tray()
        except Exception:
            pass

    def _restore_from_tray(self):
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _minimize_to_tray(self):
        if getattr(self, '_tray', None) is None:
            self.showMinimized()
            self.append_log('系统托盘不可用，已最小化到任务栏')
            return
        self.hide()
        self.append_log('[托盘] 已收进托盘，后台继续接收投屏')

    def _quit_app(self):
        self._really_quit = True
        self.close()

    def closeEvent(self, event):
        if getattr(self, '_really_quit', False):
            if getattr(self, '_tray', None) is not None:
                self._tray.hide()
            event.accept()
            return
        if getattr(self, '_tray', None) is None:
            event.accept()
            return
        event.ignore()
        self.hide()
        try:
            self._tray.showMessage(
                '森投屏接收端',
                '已收进托盘继续接收投屏。双击托盘图标可恢复窗口。',
                QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass
        self.append_log('[托盘] 窗口已隐藏，继续在后台接收投屏')

    def _build_toolbar(self):
        self.main_tb = None
        self.name_edit = QLineEdit(self.stack.http.app_name)
        self.name_edit.setFixedWidth(180)
        self.name_edit.editingFinished.connect(self._rename)

        self.ip_combo = QComboBox()
        self.ip_combo.setMinimumWidth(160)
        self._fill_ip_combo()

        self.state_label = QLabel('状态: 空闲')
        self.net_status = QLabel('自动选网: 开启')
        self.net_status.setStyleSheet('color:#39ff88; font-weight:bold;')

        self.btn_pause = QPushButton('暂停')
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop = QPushButton('停止')
        self.btn_stop.clicked.connect(self.player.stop)
        self.btn_self = QPushButton('自测')
        self.btn_self.clicked.connect(lambda: self.on_play(SELF_TEST_URL, '自测视频'))

        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.valueChanged.connect(self._on_vol_slider)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.player.available_presets())
        self.preset_combo.setCurrentText('原画')
        self.preset_combo.currentTextChanged.connect(self._apply_preset)

        self.audio_combo = QComboBox()
        self.audio_combo.addItems(self.player.available_audio_presets())
        self.audio_combo.setCurrentText('原声')
        self.audio_combo.currentTextChanged.connect(self._apply_audio_preset)

        self.btn_dolby = QPushButton('杜比/高清检测')
        self.btn_dolby.clicked.connect(self.open_dolby_check)

        self.out_combo = QComboBox()
        self.out_combo.setFixedWidth(190)
        self.out_combo.setToolTip('投屏声音输出到哪个设备（耳机/扬声器/显示器等）')
        self._fill_output_combo()
        self.out_combo.currentTextChanged.connect(self._apply_output_device)

        self.btn_look = QPushButton('外观')
        self.btn_look.clicked.connect(self.open_appearance)

        self.btn_about = QPushButton('关于')
        self.btn_about.setToolTip('版本信息、赞赏、联系与支持、皮肤定制')
        self.btn_about.clicked.connect(self.open_about)

        self.res_label = QLabel('码流: —')

        self.btn_full = QPushButton('全屏')
        self.btn_full.clicked.connect(self._toggle_fullscreen)

        self.btn_min = QPushButton('最小化')
        self.btn_min.clicked.connect(self._minimize_to_tray)

        self.btn_quit = QPushButton('退出')
        self.btn_quit.clicked.connect(self._quit_app)

        self.island = IslandBar(self)
        self.island.vol.valueChanged.connect(self._on_vol_slider)
        self.vol.valueChanged.connect(self.island.vol.setValue)
        self._island_guard = QTimer(self)
        self._island_guard.setInterval(350)
        self._island_guard.timeout.connect(self.island.guard)
        self._island_guard.start()

        self._build_progress()

    def _build_progress(self):
        from PyQt6.QtWidgets import QFrame
        container = QFrame()
        self.progress_bar = container
        h = QHBoxLayout()
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

        self.btn_play_toggle = QPushButton('▶')
        self.btn_play_toggle.setFixedSize(30, 26)
        self.btn_play_toggle.setToolTip('播放 / 暂停（空格）')
        self.btn_play_toggle.clicked.connect(self._toggle_pause)
        h.addWidget(self.btn_play_toggle)

        self.btn_stop2 = QPushButton('■')
        self.btn_stop2.setFixedSize(30, 26)
        self.btn_stop2.setToolTip('停止')
        self.btn_stop2.clicked.connect(self.player.stop)
        h.addWidget(self.btn_stop2)

        self.pos_label = QLabel('00:00:00')
        self.pos_label.setMinimumWidth(70)
        h.addWidget(self.pos_label)

        self.prog = QSlider(Qt.Orientation.Horizontal)
        self.prog.setRange(0, 10000)
        self.prog.setValue(0)
        self.prog.setMinimumWidth(320)
        self.prog.sliderMoved.connect(self._on_slider_moved)
        self.prog.sliderReleased.connect(self._on_slider_released)
        self.prog.valueChanged.connect(self._on_slider_changed)
        h.addWidget(self.prog, 1)

        self.dur_label = QLabel('00:00:00')
        self.dur_label.setMinimumWidth(70)
        h.addWidget(self.dur_label)

        self.vol2 = QSlider(Qt.Orientation.Horizontal)
        self.vol2.setRange(0, 100)
        self.vol2.setValue(100)
        self.vol2.setFixedWidth(90)
        self.vol2.setToolTip('音量')
        self.vol2.valueChanged.connect(self.player.set_volume)
        h.addWidget(self.vol2)

        container.setLayout(h)
        container.setFixedHeight(42)
        container.setStyleSheet(
            'QFrame { background:#0e0e0e; }'
            'QSlider::groove:horizontal { height:6px; background:#333; border-radius:3px; }'
            'QSlider::sub-page:horizontal { background:#2e7d32; border-radius:3px; }'
            'QSlider::handle:horizontal { width:14px; margin:-5px 0; '
            'background:#e0e0e0; border-radius:7px; }'
            'QPushButton { background:#2a2a2a; color:#e8e8e8; border:1px solid #444; '
            'border-radius:4px; }'
            'QPushButton:hover { background:#3a3a3a; }')
        pb = QToolBar('progress', self)
        pb.setMovable(False)
        pb.setFloatable(False)
        pb.setFixedHeight(46)
        pb.addWidget(container)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, pb)
        pb.show()

    def _fill_output_combo(self):
        self.out_combo.blockSignals(True)
        self.out_combo.clear()
        try:
            devs = self.player.list_output_devices()
        except Exception:
            devs = []
        self.out_combo.addItem('系统默认', None)
        for desc, dev in devs:
            self.out_combo.addItem(desc, dev)
        cur = self.player.current_output_description()
        if cur:
            idx = self.out_combo.findText(cur)
            if idx >= 0:
                self.out_combo.setCurrentIndex(idx)
        self.out_combo.blockSignals(False)

    def _apply_output_device(self, _text=None):
        dev = self.out_combo.currentData()
        if self.player.set_output_device(dev):
            name = self.out_combo.currentText()
            self.append_log('[音频] 输出设备已切到: %s' % name)

    def _build_tools(self):
        self.tools_tb = None
        self.btn_shortcut = QPushButton('创建桌面快捷方式')
        self.btn_shortcut.clicked.connect(self._make_shortcut)
        self.btn_miracast = QPushButton('打开无线显示(华为镜像/Miracast)')
        self.btn_miracast.clicked.connect(self._open_wireless_display)
        self.btn_apply_ip = QPushButton('应用并切换IP')
        self.btn_apply_ip.clicked.connect(self._apply_ip)
        self.btn_fix = QPushButton('一键修复网络(扫不到时点)')
        self.btn_fix.clicked.connect(self._fix_network)
        self.btn_conn = QPushButton('手机连通性自检')
        self.btn_conn.clicked.connect(self.open_connect_check)
        self.btn_adapt = QPushButton('特殊软件适配')
        self.btn_adapt.setToolTip('某个 App 扫不到 / 播不了 / 控制不灵？把安装包发 QQ 1218563952')
        self.btn_adapt.clicked.connect(self.open_adapt_help)
        self.btn_iptv = QPushButton('IPTV 电视')
        self.btn_iptv.setToolTip('拉 m3u/m3u8 电视流，或打开 iptv-org 官方列表')
        self.btn_iptv.clicked.connect(self.open_iptv)
        self.btn_huawei = QPushButton('华为多屏协同')
        self.btn_huawei.setToolTip('检测 Miracast 组件 + 一键调起系统「投影到此电脑」')
        self.btn_huawei.clicked.connect(self.open_huawei)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['跟随手机', '电视模式(争取1080P/4K)'])
        self.quality_combo.setCurrentIndex(0)
        self.quality_combo.setFixedWidth(170)
        self.quality_combo.setToolTip(
            'DLNA 投屏的清晰度由手机端 App 选择的片源决定，接收端无法凭空把 720P 变 4K。\n'
            '「电视模式」会：①把设备型号声明为 4K 智能电视；'
            '②在 GetProtocolInfo 中声明 HD/4K 解码能力；③立即重新宣告让手机重新协商。')
        self.quality_combo.currentIndexChanged.connect(self._apply_quality_mode)
        self.tv_mode = False

    def _fix_network(self):
        import ctypes
        from .msix import is_packaged
        if is_packaged():
            QMessageBox.information(
                self, '网络提示（商店版）',
                '微软商店版由系统自动放行本程序的局域网入站端口（8200 / 1900），'
                '不需要手动加防火墙规则。\n\n'
                '如果手机扫不到设备，多半是系统 SSDP Discovery 服务占着 1900 端口。'
                '这个需要管理员权限，商店版无法代劳，请手动操作：\n\n'
                '1. Win+R 输入 services.msc\n'
                '2. 找到 "SSDP Discovery" 服务 → 停止\n'
                '3. 重启本软件\n\n'
                '（该服务重启电脑后会自动恢复，不影响上网）')
            self.append_log('[网络] 商店版：防火墙由系统自动放行；'
                            '若需释放 1900 端口请手动停止 SSDP Discovery 服务')
            return
        script = os.path.abspath(os.path.join(HERE, '..', 'fix_network.py'))
        if not os.path.exists(script):
            QMessageBox.warning(self, '文件缺失', '未找到 fix_network.py: %s' % script)
            return
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', sys.executable, '"%s"' % script, None, 1)
        except Exception as e:
            QMessageBox.warning(self, '提权失败', '无法启动修复: %s' % e)
            return
        if ret <= 32:
            QMessageBox.warning(
                self, '提权被拒',
                '未能以管理员身份运行修复脚本(错误码 %d)。\n可手动操作：以管理员运行 cmd，'
                '执行 `net stop ssdpsrv`，再重启本软件；或右键 fix_network.py '
                '“以管理员身份运行”。' % ret)
        else:
            QMessageBox.information(
                self, '已发起修复',
                '已请求管理员权限，请在弹出的 UAC 窗口点“是”。\n'
                '修复脚本会停止系统 SSDPSRV 服务并加防火墙规则；完成后请【重启本软件】，'
                '手机即可主动搜到本设备。')

    def open_huawei(self):
        from . import huawei as _hw
        report = _hw.build_report()
        for ln in report:
            self.append_log('[华为] ' + ln)

        if _hw.miracast_available():
            self.append_log('[华为] 系统支持 Miracast。已帮你打开「投影到此电脑」，'
                            '手机下拉菜单点「无线投屏 / 多屏协同」选这台电脑即可。')
            _hw.open_miracast_settings()
            if _hw.open_connect_app():
                self.append_log('[华为] 同时启动了 Windows「连接」应用等待手机接入。')
        else:
            QMessageBox.information(
                self, '华为多屏协同',
                '<b>这台电脑还没装 Miracast 接收组件</b>（「无线显示器」）。\n\n'
                '去 微软商店 搜「无线显示器 / Wireless Display」装一个，装完重启软件，'
                '然后华为手机下拉菜单点「无线投屏 / 多屏协同」选本机就能投。\n\n'
                '华为 HiSuite 和微软 Your Phone 是闭源客户端，本软件不重复实现它们的协议；'
                '投屏请走上面系统 Miracast 这条路。')

    def _netstat_port(self, port):
        listening = False
        remotes = []
        nlisteners = 0
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            raw = subprocess.run(
                ['netstat', '-ano'], capture_output=True, timeout=10,
                startupinfo=si, stdin=subprocess.DEVNULL).stdout or b''
            out = raw.decode('utf-8', errors='ignore')
            for line in out.splitlines():
                if (':%d' % port) not in line:
                    continue
                up = line.upper()
                parts = line.split()
                if 'LISTENING' in up:
                    nlisteners += 1
                    listening = True
                    continue
                if ('ESTABLISHED' in up or 'CLOSE_WAIT' in up or 'TIME_WAIT' in up
                        or 'LAST_ACK' in up or 'FIN_WAIT' in up):
                    if len(parts) >= 4:
                        remote = parts[2]
                        rip = remote.rsplit(':', 1)[0]
                        if rip and not rip.startswith('127.') and rip != '0.0.0.0':
                            st = ('已连接' if 'ESTABLISHED' in up
                                  else ('已连后断开' if 'CLOSE_WAIT' in up else '连接中'))
                            if rip not in [r[0] for r in remotes]:
                                remotes.append((rip, st))
        except Exception:
            pass
        return listening, remotes, nlisteners

    def open_adapt_help(self):
        QMessageBox.information(
            self, '特殊软件适配',
            '<b>某个 App 扫不到 / 连上不出画面 / 不能暂停拖进度？</b><br><br>'
            '多半是它的投屏实现和我们的默认行为对不上（状态机枚举、协议头、'
            '片源地址被重写等），拿到安装包针对性改最快。<br><br>'
            '<b>把安装包发给 QQ：1218563952</b><br>'
            '直接发 .apk 即可，附一句现象（扫不到 / 不出画面 / 不能暂停 / '
            '进度不回传 / 画质或音效不对）。<br><br>'
            '适配好了会通过 QQ 回复你，并放进后续版本。<br><br>'
            '<span style="color:#666">可以先自己试：换「系统解码」快捷方式启动、'
            '点「一键修复网络」后重启、在手机 App 里手动切清晰度。</span>')

    def open_iptv(self):
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        from .iptv import IptvList
        dlg = QDialog(self)
        dlg.setWindowTitle('IPTV 电视接收')
        dlg.resize(540, 480)
        v = QVBoxLayout(dlg)

        v.addWidget(QLabel('<b>IPTV 电视接收</b>'))
        v.addWidget(QLabel('支持 m3u/m3u8 列表文件、单条流地址(m3u8/ts/mp4)，'
                           '或下方官方默认列表。'))

        url_edit = QLineEdit()
        url_edit.setPlaceholderText('m3u 列表文件或流地址 (http/https/udp/rtp)')
        v.addWidget(url_edit)

        h = QHBoxLayout()
        b_file = QPushButton('选择 m3u 文件...')
        b_url = QPushButton('打开流/列表')
        b_def = QPushButton('默认列表(iptv-org)')
        b_cn = QPushButton('中文频道列表')
        h.addWidget(b_file)
        h.addWidget(b_url)
        h.addWidget(b_def)
        h.addWidget(b_cn)
        v.addLayout(h)

        status_lbl = QLabel('')
        v.addWidget(status_lbl)

        lst = QListWidget()
        lst.setFixedHeight(200)
        v.addWidget(lst)

        import threading as _th
        iptv_obj = [None]

        def play_channel(name, url):
            self.player.play_src(url, 'IPTV: %s' % name)
            self.state_label.setText('状态: 播放中 - IPTV')
            self.append_log('[IPTV] 播放频道: %s -> %s' % (name, url[:100]))

        def fill_list(obj):
            lst.clear()
            ch = []
            for i, c in enumerate(obj.channels):
                label = c.name or ('频道%d' % i)
                if c.group:
                    label = '[%s] %s' % (c.group, label)
                ch.append((label, c.url))
            for label, _u in ch[:1000]:
                lst.addItem(QListWidgetItem(label))
            iptv_obj[0] = ch
            status_lbl.setText('<span style="color:#2e7d32">已加载 %d 个频道</span>'
                               % len(ch))

        def on_select(idx):
            if 0 <= idx < len(iptv_obj[0]):
                label, url = iptv_obj[0][idx]
                play_channel(label, url)

        lst.currentRowChanged.connect(on_select)

        def do_file():
            path, _ = QFileDialog.getOpenFileName(
                dlg, '选择 m3u 列表', '', '*.m3u;*.m3u8;*.txt')
            if not path:
                return
            obj = IptvList.from_file(path)
            status_lbl.setText('正在解析...')
            dlg.show()
            self._do_fill_iptv(obj, lst, fill_list, status_lbl)

        def do_url():
            u = url_edit.text().strip()
            if not u:
                return
            if u.lower().startswith(('http://', 'https://')) and \
                    u.split('?')[0].lower().endswith(('.m3u', '.m3u8')):
                status_lbl.setText('正在加载列表...')
                def fetch():
                    obj = IptvList.from_url(u)
                    self._do_fill_iptv(obj, lst, fill_list, status_lbl)
                _th.Thread(target=fetch, daemon=True).start()
            else:
                play_channel('单条流', u)

        def do_default():
            u = 'https://iptv-org.github.io/iptv/index.m3u'
            status_lbl.setText('正在加载默认列表(iptv-org)...')
            def fetch():
                obj = IptvList.from_url(u)
                self._do_fill_iptv(obj, lst, fill_list, status_lbl)
            _th.Thread(target=fetch, daemon=True).start()

        def do_cn():
            u = 'https://iptv-org.github.io/iptv/languages/zho.m3u'
            status_lbl.setText('正在加载中文频道列表...')
            def fetch():
                obj = IptvList.from_url(u)
                self._do_fill_iptv(obj, lst, fill_list, status_lbl)
            _th.Thread(target=fetch, daemon=True).start()

        b_file.clicked.connect(do_file)
        b_url.clicked.connect(do_url)
        b_def.clicked.connect(do_default)
        b_cn.clicked.connect(do_cn)

        h2 = QHBoxLayout()
        b_cancel = QPushButton('关闭')
        b_cancel.clicked.connect(dlg.reject)
        h2.addStretch()
        h2.addWidget(b_cancel)
        v.addLayout(h2)

        dlg.exec()

    def _do_fill_iptv(self, obj, lst, fill_list, status_lbl):
        def _apply():
            fill_list(obj)
            status_lbl.setText('<span style="color:#2e7d32">已加载 %d 个频道</span>'
                               % len(obj.channels))
            self.append_log('[IPTV] 列表加载完成: %d 个频道' % len(obj.channels))
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, _apply)

    def open_connect_check(self):
        ip = self.stack.http.app_ip
        port = self.stack.http.app_port
        url = 'http://%s:%d/device.xml' % (ip, port)

        copied = '（已复制到剪贴板）'
        try:
            QApplication.clipboard().setText(url)
        except Exception:
            copied = '（复制失败，请手动记录）'

        listening, remotes, nlisteners = self._netstat_port(port)
        dup = (' [!]监听数异常(应为1，说明旧栈未释放，请重启软件)'
               if nlisteners > 1 else '')
        if listening and remotes:
            local_detail = ('本机自检: 服务监听中 [OK](监听数=%d%s)；已检测到外部设备连入 -> %s'
                            % (nlisteners, dup,
                               '、'.join('%s(%s)' % (ip, st) for ip, st in remotes[:5])))
        elif listening:
            local_detail = ('本机自检: 服务监听中 [OK](监听数=%d%s)（尚未检测到外部设备连入，'
                            '请确认手机 App 已点过投屏）' % (nlisteners, dup))
        else:
            local_detail = ('本机自检: 未检测到端口 %d 监听 [X] —— 服务未启动或被占用，'
                            '请重启本软件' % port)

        dlg = QDialog(self)
        dlg.setWindowTitle('手机连通性自检')
        dlg.resize(420, 480)
        v = QVBoxLayout(dlg)

        v.addWidget(QLabel('<b>本机连接地址</b> (手机需访问此地址):'))
        url_label = QLineEdit(url)
        url_label.setReadOnly(True)
        url_label.selectAll()
        v.addWidget(url_label)
        v.addWidget(QLabel('<span style="color:#2e7d32">%s</span>' % copied))

        qr_label = QLabel('', dlg)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            from qrcode import make as qrcode_make
            img = qrcode_make(url)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            pm = QPixmap()
            pm.loadFromData(buf.getvalue())
            qr_label.setPixmap(pm.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio))
        except Exception:
            qr_label.setText('（二维码库不可用，请手动输入上方地址）')
        v.addWidget(qr_label)

        v.addWidget(QLabel('<b>步骤</b>：用手机浏览器(Chrome/系统浏览器)扫描上方二维码，'
                          '或手动打开该地址。'))
        v.addWidget(QLabel('<span style="color:#1565c0">%s</span>' % local_detail))

        result = QLabel()
        result.setWordWrap(True)
        result.setText(
            '【判定】\n'
            '① 若上方显示「已检测到外部设备连入」 <b>网络完全正常</b>，手机已连上本机，'
            '问题在手机 App 不认这台设备：换 乐播投屏 / BubbleUPnP / VLC 试；'
            '确认用的是<b>视频 App 内「投屏/TV」按钮</b>而非系统「无线投屏/Miracast」；'
            '鸿蒙给该 App 开「附近的设备」权限。\n\n'
            '② 手机浏览器<b>能打开</b>上面的地址  网络通，同样按①排查 App 层。\n\n'
            '③ 手机浏览器<b>打不开/超时</b>，且上方<b>没</b>检测到外部连入  才是网络被掐：'
            '电脑插<b>网线</b>连路由器（多数隔离只限无线互访）；'
            '登录路由器关「AP 隔离/无线用户隔离/WLAN 隔离」；临时关 VPN 再试。\n\n'
            '注：本机「连自己」会超时是 TUN 类 VPN（sing-tun）劫持回环流量所致，'
            '不代表手机连不上。')
        v.addWidget(result)

        h = QHBoxLayout()
        btn_copy = QPushButton('再复制一次')
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(url))
        btn_ok = QPushButton('知道了')
        btn_ok.clicked.connect(dlg.accept)
        h.addWidget(btn_copy)
        h.addWidget(btn_ok)
        v.addLayout(h)

        self.append_log('[自检] 连接地址已生成: %s | %s' % (url, local_detail))
        dlg.exec()

    def _fill_ip_combo(self):
        self.ip_combo.clear()
        cur = self.info.get('ip')
        found = False
        for ip_addr, desc in list_local_ips():
            self.ip_combo.addItem('%s  (%s)' % (ip_addr, desc), ip_addr)
            if ip_addr == cur:
                found = True
        if not found and cur:
            self.ip_combo.insertItem(0, '%s  (当前)' % cur, cur)
        idx = self.ip_combo.findData(cur)
        if idx >= 0:
            self.ip_combo.setCurrentIndex(idx)

    def set_ip_display(self, ip):
        self.info['ip'] = ip
        self._fill_ip_combo()

    def set_net_status(self, text):
        self.net_status.setText(text)

    def _apply_ip(self):
        ip = self.ip_combo.currentData()
        if not ip:
            return
        if ip == self.info.get('ip'):
            self.append_log('当前已是 IP %s，无需切换' % ip)
            return
        if self.restart_callback:
            self.append_log('正在切换到网络 IP %s ...' % ip)
            self.restart_callback(ip)
        else:
            self.append_log('IP 切换回调未设置，请重启软件后重试')

    def open_about(self):
        try:
            from .about import build_about
            dlg = build_about(self,
                              on_appearance=self.open_appearance)
            dlg.exec()
        except Exception as e:
            self.append_log('关于窗口打开失败: %s' % e)

    def _apply_theme(self, name):
        if not name:
            return
        from . import theme as _theme
        try:
            colors = _theme.get(name)
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(_theme.stylesheet(colors))
            self.setStyleSheet(_theme.stylesheet(colors))
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setStyleSheet(_theme.progress_stylesheet(colors))
            from .appearance import load as load_cfg, save as save_cfg
            cfg = load_cfg()
            cfg['theme'] = name
            save_cfg(cfg)
            self.append_log('外观: 主题已切到「%s」' % name)
        except Exception as e:
            self.append_log('主题切换失败: %s' % e)

    def _open_custom_theme(self, parent_dlg):
        from . import theme as _theme
        from PyQt6.QtGui import QColor
        dlg = QDialog(parent_dlg)
        dlg.setWindowTitle('自定义主题')
        dlg.resize(420, 320)
        v = QVBoxLayout(dlg)

        name_edit = QLineEdit('我的主题')
        v.addWidget(QLabel('主题名称:'))
        v.addWidget(name_edit)

        edits = {}
        for key, label in (('accent', '强调色（进度条/高亮）'),
                           ('bg', '界面底色'),
                           ('fg', '文字色'),
                           ('panel', '工具栏底色')):
            v.addWidget(QLabel(label))
            e = QLineEdit(_theme.get(_theme.DEFAULT_THEME)[key])
            edits[key] = e
            v.addWidget(e)

        def pick(target):
            c = QColorDialog.getColor(QColor(target.text()), dlg)
            if c.isValid():
                target.setText(c.name())

        for key in ('accent', 'bg', 'fg', 'panel'):
            b = QPushButton('选色: %s' % key)
            b.clicked.connect(lambda _c=False, k=key: pick(edits[k]))
            v.addWidget(b)

        def do_save():
            nm = name_edit.text().strip()
            if not nm:
                QMessageBox.warning(dlg, '名称为空', '给主题起个名字')
                return
            colors = {k: edits[k].text().strip() or '#000000'
                      for k in ('accent', 'bg', 'fg', 'panel')}
            if _theme.save_custom(nm, colors):
                self._apply_theme(nm)
                if hasattr(self, 'theme_combo'):
                    self.theme_combo.blockSignals(True)
                    self.theme_combo.clear()
                    self.theme_combo.addItems(_theme.all_names())
                    i = self.theme_combo.findText(nm)
                    if i >= 0:
                        self.theme_combo.setCurrentIndex(i)
                    self.theme_combo.blockSignals(False)
                self.append_log('外观: 已保存自定义主题「%s」' % nm)
                dlg.accept()
            else:
                QMessageBox.warning(dlg, '保存失败', '主题写入失败，检查目录权限。')

        h = QHBoxLayout()
        b_save = QPushButton('保存并应用')
        b_save.clicked.connect(do_save)
        b_cancel = QPushButton('取消')
        b_cancel.clicked.connect(dlg.reject)
        h.addWidget(b_save)
        h.addWidget(b_cancel)
        v.addLayout(h)
        dlg.exec()

    def _delete_custom_theme(self, parent_dlg):
        from . import theme as _theme
        cur = self.theme_combo.currentText() if hasattr(self, 'theme_combo') else ''
        if cur in _theme.BUILTIN:
            QMessageBox.information(parent_dlg, '内置主题',
                                    '「%s」是内置主题，删不掉。' % cur)
            return
        if _theme.delete_custom(cur):
            self.theme_combo.blockSignals(True)
            self.theme_combo.clear()
            self.theme_combo.addItems(_theme.all_names())
            self.theme_combo.setCurrentIndex(0)
            self.theme_combo.blockSignals(False)
            self._apply_theme(self.theme_combo.currentText())
            self.append_log('外观: 已删除自定义主题「%s」' % cur)

    def _make_shortcut(self):
        from .msix import is_packaged
        if is_packaged():
            QMessageBox.information(
                self, '商店版说明',
                '微软商店版由系统自动创建开始菜单入口，可直接搜索「森投屏接收端」启动。\n\n'
                '需要桌面图标的话，在开始菜单里右键图标 → 「固定到任务栏」或'
                '「发送到 → 桌面快捷方式」即可。')
            self.append_log('[快捷方式] 商店版：入口在开始菜单，桌面图标请自行固定')
            return
        try:
            from .shortcut import install_default
            paths = install_default()
            self.append_log('桌面快捷方式已创建:\n  %s' % paths[0])
            QMessageBox.information(
                self, '完成',
                '已创建唯一桌面快捷方式：\n\n'
                '森投屏接收端 (系统解码·杜比) —— 系统 Media Foundation 管道，'
                '可调用你已装的 HEVC/AV1/VP9 扩展与硬件解码；'
                '若系统装了 Dolby Access，音效也会自动生效。\n\n'
                '旧的 ffmpeg 快捷方式已自动清理。\n\n%s' % paths[0])
        except Exception as e:
            self.append_log('创建快捷方式失败: %s' % e)
            QMessageBox.warning(self, '失败', '创建快捷方式失败: %s' % e)

    def _open_wireless_display(self):
        QDesktopServices.openUrl(QUrl('ms-settings:project'))
        self.append_log(
            '已打开「投影到此电脑」设置页。请先安装“无线显示”可选功能并设为“随处可用”，'
            '再打开“无线显示”应用等待连接；随后在华为手机下拉菜单点“无线投屏/多屏协同”'
            '选择本机即可镜像（系统级 Miracast，非 App 内视频投屏）。')

    def _build_dock(self):
        dock = QDockWidget('日志', self)
        self.log_dock = dock
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        dock.setWidget(self.log)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        dock.setMaximumHeight(130)
        dock.setMinimumHeight(80)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.append_log('就绪。手机与电脑需在同一局域网(Wi-Fi/有线)。')

    def _connect(self):
        self.bridge.playRequested.connect(self.on_play)
        self.bridge.stopRequested.connect(self.on_stop)
        self.bridge.volumeRequested.connect(self._on_volume)
        self.bridge.muteRequested.connect(self.player.set_muted)
        self.bridge.pauseRequested.connect(self._on_remote_pause)
        self.bridge.resumeRequested.connect(self._on_remote_resume)
        self.bridge.seekRequested.connect(self._on_remote_seek)
        self.player.playbackChanged.connect(self._on_playback_changed)
        self.player.fullscreenToggle.connect(self._toggle_fullscreen)
        st = getattr(self.bridge, 'state', None)
        if st is not None:
            st.position_provider = lambda: (self.player.position_ms(),
                                            self.player.duration_ms())

    def _toggle_pause(self):
        if self.player.is_playing():
            self.player.pause()
            self._notify_remote_state('PAUSED')
            self.state_label.setText('状态: 已暂停(电脑控制)')
            self.append_log('[控制] 电脑端请求暂停')
        else:
            self.player.resume()
            self._notify_remote_state('PLAYING')
            self.state_label.setText('状态: 播放中')
            self.append_log('[控制] 电脑端请求继续')

    def _notify_remote_state(self, transport):
        st = getattr(self.bridge, 'state', None)
        if st is None:
            return
        try:
            st.set_transport(transport)
        except Exception:
            pass

    def _on_remote_pause(self):
        self.player.pause()
        self.state_label.setText('状态: 已暂停(手机控制)')
        self.append_log('[控制] 手机端请求暂停 -> 已暂停')

    def _on_remote_resume(self):
        self.player.resume()
        self.state_label.setText('状态: 播放中')
        self.append_log('[控制] 手机端请求继续 -> 已继续')

    def _on_remote_seek(self, ms):
        dur = self.player.duration_ms()
        if dur <= 0:
            self.append_log('[控制] 手机端请求跳转 %d ms —— 当前片源无总时长（直播流），无法拖动'
                            % ms)
            return
        if self.player.seek(ms):
            self.append_log('[控制] 手机端拖动进度 -> 跳转到 %s' % self._fmt_clock(ms))
            self._notify_remote_seek(ms)
        else:
            self.append_log('[控制] 手机端跳转失败（片源可能不支持拖动）: %s ms' % ms)

    def _on_playback_changed(self, name):
        st = getattr(self.bridge, 'state', None)
        mapping = {'PLAYING': 'PLAYING', 'PAUSED': 'PAUSED_PLAYBACK',
                   'STOPPED': 'STOPPED'}
        transport = mapping.get(name, 'STOPPED')
        if st is not None:
            st.set_transport(transport)
        if name == 'PLAYING':
            self.state_label.setText('状态: 播放中')
            self.btn_pause.setText('暂停')
            self.btn_play_toggle.setText('⏸')
        elif name == 'PAUSED':
            self.state_label.setText('状态: 已暂停')
            self.btn_pause.setText('继续')
            self.btn_play_toggle.setText('▶')
        else:
            self.state_label.setText('状态: 空闲')
            self.btn_pause.setText('暂停')
            self.btn_play_toggle.setText('▶')
        self.append_log('[状态] %s -> 已同步给手机(TransportState=%s)'
                        % (name, transport))

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.show()
            self.btn_full.setText('全屏')
            if self._fs_geo is not None:
                self.setGeometry(self._fs_geo)
            self._island_show()
            self.append_log('已退出全屏')
        else:
            self._fs_geo = self.geometry()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.hide()
            self.btn_full.setText('退出全屏')
            self.showFullScreen()
            self._island_auto_hide()
            self.append_log('已全屏（Esc / 双击画面 / 再点一次按钮可退出）')

    def keyPressEvent(self, event):
        try:
            if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
                self._toggle_fullscreen()
                return
            if event.key() == Qt.Key.Key_F11:
                self._toggle_fullscreen()
                return
            if event.key() == Qt.Key.Key_Space:
                if self.player.is_playing():
                    self.player.pause()
                else:
                    self.player.resume()
                return
            if event.key() == Qt.Key.Key_Left:
                self._seek_rel(-5000)
                return
            if event.key() == Qt.Key.Key_Right:
                self._seek_rel(5000)
                return
            if event.key() == Qt.Key.Key_Home:
                self._seek_start()
                return
            if event.key() == Qt.Key.Key_End:
                self._seek_end()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def _start_stat_timer(self):
        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(1000)
        self._stat_timer.timeout.connect(self._refresh_stat)
        self._stat_timer.start()
        self._slider_pressed = False

    @staticmethod
    def _fmt_clock(ms):
        try:
            s = max(0, int(ms // 1000))
        except Exception:
            s = 0
        h, rem = divmod(s, 3600)
        m, s = divmod(rem, 60)
        return '%02d:%02d:%02d' % (h, m, s)

    def _refresh_progress(self):
        if getattr(self, '_slider_pressed', False):
            return
        try:
            pos = self.player.position_ms()
            dur = self.player.duration_ms()
        except Exception:
            return
        if self.player.is_live():
            self.pos_label.setText(self._fmt_clock(pos))
            self.dur_label.setText('直播')
            self.prog.setEnabled(False)
            self.prog.setValue(0)
            return
        self.pos_label.setText(self._fmt_clock(pos))
        self.dur_label.setText(self._fmt_clock(dur))
        if dur > 0:
            self.prog.setEnabled(True)
            pct = min(10000, int(pos * 10000 / dur))
            if not self.prog.isSliderDown():
                self.prog.setValue(pct)

    def _on_slider_changed(self, val):
        if not getattr(self, '_slider_pressed', False) and not self.prog.isSliderDown():
            return
        dur = self.player.duration_ms()
        if dur <= 0:
            return
        pos = dur * (val / 10000.0)
        self.pos_label.setText(self._fmt_clock(pos))

    def _on_slider_moved(self, val):
        self._slider_pressed = True
        self._on_slider_changed(val)

    def _on_slider_released(self):
        self._slider_pressed = False
        val = self.prog.value()
        dur = self.player.duration_ms()
        if dur <= 0:
            return
        ms = int(dur * (val / 10000.0))
        if self.player.seek(ms):
            self.append_log('[控制] 电脑端拖动进度 -> 跳转到 %s' % self._fmt_clock(ms))
            self._notify_remote_seek(ms)
        else:
            self.append_log('[控制] 电脑端拖动失败（片源不支持跳转）')

    def _notify_remote_seek(self, ms):
        st = getattr(self.bridge, 'state', None)
        if st is None:
            return
        try:
            st._parse_time(ms)
        except Exception:
            pass
        try:
            st.set_transport(st.transport_state)
        except Exception:
            pass

    def _seek_rel(self, delta_ms):
        dur = self.player.duration_ms()
        if dur <= 0:
            return
        cur = self.player.position_ms()
        ms = max(0, min(dur, cur + delta_ms))
        if self.player.seek(ms):
            self.append_log('[控制] 电脑端 %s %d ms -> %s' % (
                '+' if delta_ms > 0 else '-', abs(delta_ms), self._fmt_clock(ms)))
            self._notify_remote_seek(ms)

    def _seek_start(self):
        if self.player.seek(0):
            self.append_log('[控制] 电脑端跳到开头')

    def _seek_end(self):
        dur = self.player.duration_ms()
        if dur > 0 and self.player.seek(max(0, dur - 5000)):
            self.append_log('[控制] 电脑端跳到结尾前 5s')

    def _refresh_stat(self):
        self._refresh_progress()
        try:
            info = self.player.meta_summary()
        except Exception:
            return
        res = info.get('res')
        if not res:
            return
        parts = [res]
        tag = info.get('tag')
        if tag:
            parts.append(tag)
        if info.get('fps'):
            parts.append(info['fps'])
        if info.get('bitrate'):
            parts.append(info['bitrate'])
        text = '  码流: ' + ' · '.join(parts)
        if self.res_label.text() != text:
            self.res_label.setText(text)

    def _apply_preset(self, name):
        if name == '原画':
            self.player.set_enhance(False)
            self.append_log('画质: 原画（已关闭增强，最省 CPU）')
        else:
            ok = self.player.set_enhance(True, name)
            self.append_log('画质: %s（帧级增强%s）'
                            % (name, '已开启' if ok else '开启失败，保持原画'))

    def _apply_quality_mode(self, idx):
        tv = bool(idx)
        self.tv_mode = tv
        try:
            self.stack.set_tv_mode(tv)
        except Exception as e:
            self.append_log('清晰度策略切换失败: %s' % e)
            return
        if tv:
            self.append_log(
                '清晰度策略: 电视模式 —— 已把设备型号声明为 4K 智能电视、'
                '并在 GetProtocolInfo 中声明 HD/4K 解码能力，同时重新宣告。'
                '请让手机重新搜索/重连一次投屏。注意：最终清晰度仍由手机端 App 决定。')
        else:
            self.append_log('清晰度策略: 跟随手机（恢复标准接收端标识）')

    def _apply_audio_preset(self, name):
        gain = self.player.set_audio_preset(name)
        self.append_log('音效: %s（增益 x%.2f%s）'
                        % (name, gain,
                           '' if name == '原声' else '，低音量时自动补偿层次'))

    def open_dolby_check(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('杜比 / 高清解码检测')
        dlg.resize(640, 520)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel('<b>正在检测系统组件…</b>'))
        dlg.show()
        QApplication.processEvents()

        try:
            from .dolby import build_report, advice_text
            report = build_report()
        except Exception as e:
            QMessageBox.warning(self, '检测失败', '无法完成检测: %s' % e)
            dlg.close()
            return

        while v.count():
            item = v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        v.addWidget(QLabel(
            '杜比是授权技术，软件自己解不了。<br>'
            '这里只是查一下系统装没装杜比组件——装了，并且用 windows 解码引擎，'
            '系统的杜比/HDR/硬解就会直接作用在播放上。'))

        for line in report['lines']:
            lab = QLabel(line)
            lab.setWordWrap(True)
            v.addWidget(lab)

        for title, status, desc, link in report['items']:
            box = QLabel('<b>%s</b> — %s<br><span style="color:#555">%s</span>'
                         % (title, status, desc))
            box.setWordWrap(True)
            v.addWidget(box)
            btn = QPushButton('打开商店/设置：%s' % title)
            btn.clicked.connect(lambda _c=False, u=link: QDesktopServices.openUrl(QUrl(u)))
            v.addWidget(btn)

        tips = QLabel('<b>可执行建议</b><br>' + '<br>'.join(
            '• %s' % t for t in advice_text(report)))
        tips.setWordWrap(True)
        v.addWidget(tips)

        btn_ok = QPushButton('知道了')
        btn_ok.clicked.connect(dlg.accept)
        v.addWidget(btn_ok)
        self.append_log('[杜比检测] %s' % ' / '.join(report['lines']))
        dlg.exec()

    def _apply_saved_appearance(self):
        from .appearance import load as load_cfg
        self.cfg = load_cfg()
        self.player.set_background(self.cfg.get('bg_image', ''),
                                   self.cfg.get('bg_color', '#000000'))
        try:
            from . import theme as _theme
            name = self.cfg.get('theme') or _theme.DEFAULT_THEME
            colors = _theme.get(name)
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(_theme.stylesheet(colors))
            self.setStyleSheet(_theme.stylesheet(colors))
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setStyleSheet(_theme.progress_stylesheet(colors))
        except Exception:
            pass
        try:
            self.island.reposition()
            self.island.fade_in()
        except Exception:
            pass
        if self.cfg.get('dlss_enabled') and self._dlss_supported():
            self.append_log('[DLSS] 超分已启用（驱动层 RTX Video Super Resolution）')

    def open_appearance(self):
        from .appearance import load as load_cfg, save as save_cfg
        from . import theme as _theme
        cfg = load_cfg()
        dlg = QDialog(self)
        dlg.setWindowTitle('外观设置')
        dlg.resize(560, 600)
        v = QVBoxLayout(dlg)

        g0 = QGroupBox('界面主题（皮肤）')
        f0 = QFormLayout(g0)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(_theme.all_names())
        cur_theme = cfg.get('theme') or _theme.DEFAULT_THEME
        idx = self.theme_combo.findText(cur_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.setToolTip('换整套界面配色，立即生效')
        self.theme_combo.currentTextChanged.connect(self._apply_theme)
        f0.addRow('主题:', self.theme_combo)

        row0 = QHBoxLayout()
        b_new = QPushButton('自定义配色...')
        b_new.clicked.connect(lambda: self._open_custom_theme(dlg))
        row0.addWidget(b_new)
        b_del = QPushButton('删除自定义')
        b_del.clicked.connect(lambda: self._delete_custom_theme(dlg))
        row0.addWidget(b_del)
        row0.addStretch()
        w0 = QWidget()
        w0.setLayout(row0)
        f0.addRow('', w0)
        v.addWidget(g0)

        g1 = QGroupBox('开屏动画（默认关闭，需要就自己开并配素材）')
        f1 = QFormLayout(g1)
        cb = QCheckBox('启用开屏动画')
        cb.setChecked(bool(cfg.get('splash_enabled')))
        f1.addRow(cb)

        img_edit = QLineEdit(cfg.get('splash_image') or '')
        img_edit.setPlaceholderText('不选就用默认渐变背景；选 gif 会当动图播')
        row = QHBoxLayout()
        row.addWidget(img_edit, 1)
        b_img = QPushButton('选择图片')
        b_clr = QPushButton('清除')
        row.addWidget(b_img)
        row.addWidget(b_clr)
        w = QWidget()
        w.setLayout(row)
        f1.addRow('开屏背景:', w)

        t_edit = QLineEdit(cfg.get('splash_title') or '')
        s_edit = QLineEdit(cfg.get('splash_subtitle') or '')
        f1.addRow('标题:', t_edit)
        f1.addRow('副标题:', s_edit)

        ms = QSpinBox()
        ms.setRange(600, 8000)
        ms.setSingleStep(100)
        ms.setSuffix(' ms')
        ms.setValue(int(cfg.get('splash_ms') or 1800))
        f1.addRow('停留时长:', ms)
        v.addWidget(g1)

        g2 = QGroupBox('播放器背景')
        f2 = QFormLayout(g2)
        bg_edit = QLineEdit(cfg.get('bg_image') or '')
        bg_edit.setPlaceholderText('没播视频时显示；不选就用下方纯色')
        row2 = QHBoxLayout()
        row2.addWidget(bg_edit, 1)
        b_bg = QPushButton('选择图片')
        b_bgclr = QPushButton('清除')
        row2.addWidget(b_bg)
        row2.addWidget(b_bgclr)
        w2 = QWidget()
        w2.setLayout(row2)
        f2.addRow('背景图:', w2)

        col_edit = QLineEdit(cfg.get('bg_color') or '#000000')
        row3 = QHBoxLayout()
        row3.addWidget(col_edit, 1)
        b_col = QPushButton('选颜色')
        row3.addWidget(b_col)
        w3 = QWidget()
        w3.setLayout(row3)
        f2.addRow('背景色:', w3)
        v.addWidget(g2)

        def pick(target):
            path, _ = QFileDialog.getOpenFileName(
                dlg, '选择图片', '',
                '图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*.*)')
            if path:
                target.setText(path)

        b_img.clicked.connect(lambda: pick(img_edit))
        b_bg.clicked.connect(lambda: pick(bg_edit))
        b_clr.clicked.connect(lambda: img_edit.setText(''))
        b_bgclr.clicked.connect(lambda: bg_edit.setText(''))

        def pick_color():
            from PyQt6.QtGui import QColor
            c = QColorDialog.getColor(QColor(col_edit.text() or '#000000'), dlg)
            if c.isValid():
                col_edit.setText(c.name())
        b_col.clicked.connect(pick_color)

        b_preview = QPushButton('预览开屏动画')

        def preview():
            tmp = dict(cfg)
            tmp.update({'splash_enabled': True,
                        'splash_image': img_edit.text().strip(),
                        'splash_title': t_edit.text().strip(),
                        'splash_subtitle': s_edit.text().strip(),
                        'splash_ms': ms.value()})
            from .splash import run_splash
            icon = os.path.abspath(os.path.join(HERE, 'assets', 'icon.ico'))
            run_splash(QApplication.instance(), tmp, icon, log=self.append_log)
        b_preview.clicked.connect(preview)

        h = QHBoxLayout()
        b_save = QPushButton('保存')
        b_reset = QPushButton('恢复默认')
        b_cancel = QPushButton('取消')
        h.addWidget(b_save)
        h.addWidget(b_reset)
        h.addWidget(b_cancel)
        v.addStretch(1)
        v.addLayout(h)
        v.addWidget(b_preview)

        def do_save():
            new = dict(cfg)
            new.update({'splash_enabled': cb.isChecked(),
                        'splash_image': img_edit.text().strip(),
                        'splash_title': t_edit.text().strip(),
                        'splash_subtitle': s_edit.text().strip(),
                        'splash_ms': ms.value(),
                        'bg_image': bg_edit.text().strip(),
                        'bg_color': col_edit.text().strip() or '#000000'})
            if hasattr(self, 'theme_combo'):
                new['theme'] = self.theme_combo.currentText()
            if save_cfg(new):
                self.cfg = new
                self.player.set_background(new['bg_image'], new['bg_color'])
                self.append_log('外观已保存：开屏%s，背景%s，主题%s'
                                % ('开' if new['splash_enabled'] else '关',
                                   new['bg_image'] or new['bg_color'],
                                   new.get('theme', '经典黑')))
                dlg.accept()
            else:
                QMessageBox.warning(self, '保存失败', '外观设置写入失败，请检查目录权限。')

        def do_reset():
            from .appearance import DEFAULT
            for k, val in DEFAULT.items():
                cfg[k] = val
            cb.setChecked(cfg['splash_enabled'])
            img_edit.setText(cfg['splash_image'])
            t_edit.setText(cfg['splash_title'])
            s_edit.setText(cfg['splash_subtitle'])
            ms.setValue(cfg['splash_ms'])
            bg_edit.setText(cfg['bg_image'])
            col_edit.setText(cfg['bg_color'])

        b_save.clicked.connect(do_save)
        b_reset.clicked.connect(do_reset)
        b_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _on_vol_slider(self, v):
        if hasattr(self, 'vol2'):
            self.vol2.blockSignals(True)
            self.vol2.setValue(v)
            self.vol2.blockSignals(False)
        self.player.set_volume(v)

    def _on_volume(self, v):
        self.vol.blockSignals(True)
        self.vol.setValue(v)
        self.vol.blockSignals(False)
        if hasattr(self, 'vol2'):
            self.vol2.blockSignals(True)
            self.vol2.setValue(v)
            self.vol2.blockSignals(False)
        self.player.set_volume(v)

    def _rename(self):
        new_name = self.name_edit.text().strip() or '森投屏接收端'
        self.stack.http.app_name = new_name
        self.stack.ssdp.name = new_name
        self.append_log('设备名已改为: %s（新推送的设备将以此名被发现）' % new_name)

    def on_play(self, uri, title):
        self.player.play_src(uri, title)
        self.state_label.setText('状态: 播放中' + (' - ' + title if title else ''))
        self.append_log('播放: %s | %s' % (title or '(无标题)', uri[:120]))
        self._island_auto_hide()

    def on_stop(self):
        self.player.stop()
        self.state_label.setText('状态: 空闲')
        self.append_log('停止')
        self._island_show()

    def _island_auto_hide(self):
        try:
            if getattr(self, 'island', None) is not None:
                self.island.set_compact(True)
                self.island.fade_in()
            if getattr(self, 'progress_bar', None) is not None:
                self.progress_bar.hide()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)
        except Exception:
            pass

    def _island_show(self):
        try:
            self.unsetCursor()
            if getattr(self, 'island', None) is not None:
                self.island.set_compact(False)
                self.island.reposition()
                self.island.fade_in()
            if getattr(self, 'progress_bar', None) is not None:
                self.progress_bar.show()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.show()
        except Exception:
            pass

    def bring_to_front(self):
        try:
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
            self.raise_()
            self.activateWindow()
            if getattr(self, 'island', None) is not None:
                self.island.show_at_top()
        except Exception:
            pass

    def enterEvent(self, ev):
        try:
            if getattr(self, 'island', None) is not None and self.player.is_playing():
                self.island.set_compact(False)
                self.island.reposition()
                self.island.fade_in()
                self.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        try:
            if getattr(self, 'island', None) is not None and self.player.is_playing():
                if not self.island.underMouse():
                    self.island.set_compact(True)
                self.setCursor(Qt.CursorShape.BlankCursor)
        except Exception:
            pass
        super().leaveEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        try:
            if getattr(self, 'island', None) is not None:
                self.island.reposition()
        except Exception:
            pass

    def moveEvent(self, ev):
        super().moveEvent(ev)
        try:
            if getattr(self, 'island', None) is not None and self.island.isVisible():
                self.island.reposition()
        except Exception:
            pass

    def hideEvent(self, ev):
        try:
            if getattr(self, 'island', None) is not None:
                self.island.hide()
        except Exception:
            pass
        super().hideEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        try:
            if getattr(self, 'island', None) is not None:
                self.island.show_at_top()
                from PyQt6.QtCore import QTimer as _T
                _T.singleShot(120, self.island.show_at_top)
        except Exception:
            pass

    def changeEvent(self, ev):
        from PyQt6.QtCore import QEvent
        try:
            if ev.type() == QEvent.Type.ActivationChange:
                if self.isActiveWindow():
                    if getattr(self, 'island', None) is not None:
                        self.island.show_at_top()
                        from PyQt6.QtCore import QTimer as _T
                        _T.singleShot(150, self.island.reposition)
            elif ev.type() == QEvent.Type.WindowStateChange:
                if getattr(self, 'island', None) is not None:
                    if self.isMinimized():
                        self.island.hide()
                    else:
                        self.island.show_at_top()
        except Exception:
            pass
        super().changeEvent(ev)

    def populate_more_menu(self, menu):
        def add_action(text, slot, enabled=True):
            a = menu.addAction(text)
            a.setEnabled(enabled)
            a.triggered.connect(lambda _c=False, s=slot: s())
            return a

        add_action('自测播放', lambda: self.on_play(SELF_TEST_URL, '自测视频'))

        m_pic = menu.addMenu('画质')
        for name in self.player.available_presets():
            a = m_pic.addAction(name)
            a.triggered.connect(lambda _c=False, n=name: self._apply_preset(n))

        m_audio = menu.addMenu('音效')
        for name in self.player.available_audio_presets():
            a = m_audio.addAction(name)
            a.triggered.connect(lambda _c=False, n=name: self._apply_audio_preset(n))

        m_out = menu.addMenu('音频输出')
        for i in range(self.out_combo.count()):
            a = m_out.addAction(self.out_combo.itemText(i))
            a.triggered.connect(
                lambda _c=False, idx=i: (self.out_combo.setCurrentIndex(idx),
                                         self._apply_output_device()))

        m_quality = menu.addMenu('清晰度策略')
        for i in range(self.quality_combo.count()):
            a = m_quality.addAction(self.quality_combo.itemText(i))
            a.triggered.connect(
                lambda _c=False, idx=i: self.quality_combo.setCurrentIndex(idx))

        m_net = menu.addMenu('网络 / 设备')
        for i in range(self.ip_combo.count()):
            a = m_net.addAction('切换到 ' + self.ip_combo.itemText(i))
            a.triggered.connect(
                lambda _c=False, idx=i: (self.ip_combo.setCurrentIndex(idx),
                                         self._apply_ip()))
        add2 = m_net.addAction('一键修复网络')
        add2.triggered.connect(self._fix_network)
        add3 = m_net.addAction('手机连通性自检')
        add3.triggered.connect(self.open_connect_check)
        add4 = m_net.addAction('修改设备名')
        add4.triggered.connect(self._ask_rename)

        menu.addSeparator()
        add_action('IPTV 电视', self.open_iptv)
        add_action('华为多屏协同', self.open_huawei)
        add_action('杜比 / 高清检测', self.open_dolby_check)
        add_action('特殊软件适配', self.open_adapt_help)

        if self._dlss_supported():
            a = menu.addAction('DLSS 5 超分（当前：%s）'
                               % ('开' if self.cfg.get('dlss_enabled') else '关'))
            a.triggered.connect(self._toggle_dlss)

        menu.addSeparator()
        add_action('外观设置', self.open_appearance)
        add_action('启动与性能', self.open_startup_settings)
        add_action('创建桌面快捷方式', self._make_shortcut)
        add_action('关于', self.open_about)

        menu.addSeparator()
        add_action('全屏', self._toggle_fullscreen)
        add_action('最小化到托盘', self._minimize_to_tray)
        add_action('退出程序', self._quit_app)

    def _ask_rename(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, '设备名', '手机上将显示的名称：', text=self.stack.http.app_name)
        if ok and name.strip():
            self.stack.http.app_name = name.strip()
            self.stack.ssdp.name = name.strip()
            self.append_log('设备名已改为: %s' % name.strip())

    def _dlss_supported(self):
        try:
            from . import dlss
            return dlss.is_supported()
        except Exception:
            return False

    def _toggle_dlss(self):
        try:
            from . import dlss
            from .appearance import save as save_cfg
            cur = bool(self.cfg.get('dlss_enabled'))
            new = not cur
            self.cfg['dlss_enabled'] = new
            save_cfg(self.cfg)
            if new:
                self.append_log('[DLSS] 已开启超分（%s）。视频超分依赖 NVIDIA 驱动的 '
                                'RTX Video Super Resolution，请在 NVIDIA 控制面板中'
                                '把「RTX 视频增强」设为开启。' % dlss.description())
                dlss.open_nvidia_control_panel()
            else:
                self.append_log('[DLSS] 已关闭超分')
        except Exception as e:
            self.append_log('DLSS 切换失败: %s' % e)

    def open_startup_settings(self):
        from PyQt6.QtWidgets import QCheckBox, QGroupBox, QFormLayout, QWidget as _W
        from . import autostart
        dlg = QDialog(self)
        dlg.setWindowTitle('启动与性能')
        dlg.resize(460, 300)
        v = QVBoxLayout(dlg)

        g = QGroupBox('开机启动')
        f = QFormLayout(g)
        cb_boot = QCheckBox('开机自动启动')
        cb_boot.setChecked(autostart.is_enabled())
        f.addRow(cb_boot)

        cb_silent = QCheckBox('静默启动（不显示主窗口，直接进托盘）')
        cmd = autostart.current_command()
        cb_silent.setChecked('--silent' in cmd)
        cb_silent.setEnabled(autostart.silent_supported())
        if not autostart.silent_supported():
            cb_silent.setToolTip('商店版由系统托管启动入口，暂不支持静默参数')
        f.addRow(cb_silent)
        v.addWidget(g)

        g2 = QGroupBox('GPU 超分')
        f2 = QFormLayout(g2)
        if self._dlss_supported():
            cb_dlss = QCheckBox('启用 DLSS 5 超分')
            cb_dlss.setChecked(bool(self.cfg.get('dlss_enabled')))
            f2.addRow(cb_dlss)
            info = QLabel('检测到 NVIDIA 显卡，超分走驱动层 RTX Video Super Resolution。')
            info.setWordWrap(True)
            f2.addRow(info)
        else:
            f2.addRow(QLabel('当前设备不支持，已隐藏相关选项。'))
            cb_dlss = None
        v.addWidget(g2)

        h = QHBoxLayout()
        b_ok = QPushButton('保存')
        b_cancel = QPushButton('取消')
        h.addStretch()
        h.addWidget(b_ok)
        h.addWidget(b_cancel)
        v.addLayout(h)

        def do_save():
            want = cb_boot.isChecked()
            silent = cb_silent.isChecked() and autostart.silent_supported()
            if want:
                ok, msg = autostart.enable(silent)
                if ok:
                    self.append_log('[启动] 已设置开机自启%s: %s'
                                    % ('（静默）' if silent else '', msg))
                else:
                    QMessageBox.warning(dlg, '设置失败', msg)
                    return
            else:
                ok, msg = autostart.disable()
                if ok:
                    self.append_log('[启动] 已取消开机自启')
                else:
                    QMessageBox.warning(dlg, '取消失败', msg)
                    return
            if cb_dlss is not None:
                from .appearance import save as save_cfg
                self.cfg['dlss_enabled'] = cb_dlss.isChecked()
                save_cfg(self.cfg)
            dlg.accept()

        b_ok.clicked.connect(do_save)
        b_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _do_append_log(self, msg):
        try:
            if getattr(self, 'log', None) is None:
                print(msg)
                return
            self.log.append(msg)
            sb = self.log.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())
        except Exception:
            try:
                print(msg)
            except Exception:
                pass

    def append_log(self, msg):
        try:
            self.log_signal.emit(msg)
        except Exception:
            self._do_append_log(msg)
