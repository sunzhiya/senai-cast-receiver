import io
import json
import os
import socket
import subprocess
import sys
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QTimer
from PyQt6.QtGui import QDesktopServices, QPixmap, QIcon
from PyQt6.QtWidgets import (QMainWindow, QToolBar, QLabel, QPushButton,
                             QSlider, QTextEdit, QDockWidget, QLineEdit,
                             QMessageBox, QComboBox, QDialog, QVBoxLayout,
                             QHBoxLayout, QApplication, QCheckBox, QSpinBox,
                             QFileDialog, QColorDialog, QGroupBox, QFormLayout)
from .player_widget import CastPlayer
from .player import PlayerBridge
from .config import list_local_ips

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_TEST_URL = 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4'


class MainWindow(QMainWindow):
    # 自动网络监控触发的 IP 切换信号（工作线程 -> 主线程安全桥接）
    ip_auto_switch = pyqtSignal(str)
    # 日志信号：工作线程只 emit，写控件交给主线程槽。
    # 跨线程直接 append 日志会被吞（以前"手机连上了却没 [HTTP] 日志"就是这么丢的）
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
        # 全屏前保存的窗口几何，退出全屏时恢复
        self._fs_geo = None

        # 播放器用 Qt6 Multimedia。QWebEngineView 自带的 Chromium 未编译
        # H.264/AAC，投 mp4 会直接解码失败，所以换成 Qt 媒体管线。
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

    def _build_toolbar(self):
        tb = QToolBar('main', self)
        self.main_tb = tb
        self.addToolBar(tb)
        tb.addWidget(QLabel('设备名:'))
        self.name_edit = QLineEdit(self.stack.http.app_name)
        self.name_edit.setFixedWidth(180)
        self.name_edit.editingFinished.connect(self._rename)
        tb.addWidget(self.name_edit)
        tb.addWidget(QLabel('  端口:%d' % self.info['port']))
        tb.addWidget(QLabel('  本机IP:'))
        self.ip_combo = QComboBox()
        self.ip_combo.setMinimumWidth(160)
        self._fill_ip_combo()
        tb.addWidget(self.ip_combo)
        self.state_label = QLabel('状态: 空闲')
        tb.addWidget(self.state_label)
        self.net_status = QLabel('自动选网: 开启')
        self.net_status.setStyleSheet('color:#2e7d32; font-weight:bold;')
        tb.addWidget(self.net_status)

        self.btn_pause = QPushButton('暂停')
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop = QPushButton('停止')
        self.btn_stop.clicked.connect(self.player.stop)
        self.btn_self = QPushButton('自测')
        self.btn_self.clicked.connect(lambda: self.on_play(SELF_TEST_URL, '自测视频'))
        tb.addWidget(self.btn_pause)
        tb.addWidget(self.btn_stop)
        tb.addWidget(self.btn_self)

        tb.addWidget(QLabel('音量'))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(120)
        self.vol.valueChanged.connect(self.player.set_volume)
        tb.addWidget(self.vol)

        tb.addWidget(QLabel('  画质:'))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.player.available_presets())
        self.preset_combo.setCurrentText('原画')
        self.preset_combo.setFixedWidth(90)
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        tb.addWidget(self.preset_combo)

        tb.addWidget(QLabel('  音效:'))
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(self.player.available_audio_presets())
        self.audio_combo.setCurrentText('原声')
        self.audio_combo.setFixedWidth(110)
        self.audio_combo.currentTextChanged.connect(self._apply_audio_preset)
        tb.addWidget(self.audio_combo)

        self.btn_dolby = QPushButton('杜比/高清检测')
        self.btn_dolby.clicked.connect(self.open_dolby_check)
        tb.addWidget(self.btn_dolby)

        self.btn_look = QPushButton('外观')
        self.btn_look.clicked.connect(self.open_appearance)
        tb.addWidget(self.btn_look)

        # 真实码流信息（分辨率/帧率/码率）。分辨率由手机端片源决定，
        # 接收端变不出 4K，只能如实显示 + 增强。
        self.res_label = QLabel('  码流: —')
        tb.addWidget(self.res_label)

        self.btn_full = QPushButton('全屏')
        self.btn_full.clicked.connect(self._toggle_fullscreen)
        tb.addWidget(self.btn_full)

        # 进度条放窗口底部固定行：电脑端可拖动，键盘 ←/→ 也能跳
        # （用 QFrame 包一层塞进 QToolBar，避免 QSlider 直接放工具行被挤没）
        self._build_progress()

    def _build_progress(self):
        from PyQt6.QtWidgets import QFrame
        container = QFrame()
        self.progress_bar = container
        h = QHBoxLayout()
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(8)

        self.pos_label = QLabel('00:00:00')
        self.pos_label.setMinimumWidth(70)
        h.addWidget(self.pos_label)

        self.prog = QSlider(Qt.Orientation.Horizontal)
        self.prog.setRange(0, 10000)   # 百分比 ×100，分辨率够用
        self.prog.setValue(0)
        self.prog.setMinimumWidth(320)
        self.prog.sliderMoved.connect(self._on_slider_moved)
        self.prog.sliderReleased.connect(self._on_slider_released)
        self.prog.valueChanged.connect(self._on_slider_changed)
        h.addWidget(self.prog, 1)

        self.dur_label = QLabel('00:00:00')
        self.dur_label.setMinimumWidth(70)
        h.addWidget(self.dur_label)

        container.setLayout(h)
        container.setStyleSheet(
            'QFrame { background:#0e0e0e; }'
            'QSlider::groove:horizontal { height:6px; background:#333; border-radius:3px; }'
            'QSlider::sub-page:horizontal { background:#2e7d32; border-radius:3px; }'
            'QSlider::handle:horizontal { width:14px; margin:-5px 0; '
            'background:#e0e0e0; border-radius:7px; }')
        pb = QToolBar('progress', self)
        pb.setMovable(False)
        pb.addWidget(container)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, pb)

    def _build_tools(self):
        tb = QToolBar('tools', self)
        self.tools_tb = tb
        self.addToolBar(tb)
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
        self.btn_huawei.setToolTip('检测 Miracast 组件 + 一键调起系统「投影到此电脑」（华为手机多屏协同走系统 Miracast，本软件不重新实现该协议）')
        self.btn_huawei.clicked.connect(self.open_huawei)
        tb.addWidget(self.btn_shortcut)
        tb.addWidget(self.btn_miracast)
        tb.addWidget(self.btn_apply_ip)
        tb.addWidget(self.btn_fix)
        tb.addWidget(self.btn_conn)
        tb.addWidget(self.btn_adapt)
        tb.addWidget(self.btn_iptv)
        tb.addWidget(self.btn_huawei)

        # 电视模式：把型号报成 4K 电视并声明 HD/4K 解码能力，诱导部分 App 推高码率。
        # 成不成看 App，最终还是手机说了算。
        tb.addWidget(QLabel('  清晰度策略:'))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['跟随手机', '电视模式(争取1080P/4K)'])
        self.quality_combo.setCurrentIndex(0)
        self.quality_combo.setFixedWidth(170)
        self.quality_combo.setToolTip(
            'DLNA 投屏的清晰度由手机端 App 选择的片源决定，接收端无法凭空把 720P 变 4K。\n'
            '「电视模式」会：①把设备型号声明为 4K 智能电视；'
            '②在 GetProtocolInfo 中声明 HD/4K 解码能力；③立即重新宣告让手机重新协商。\n'
            '对部分 App 有效、不保证全部生效；若仍不变，请在手机 App 内手动切清晰度。')
        self.quality_combo.currentIndexChanged.connect(self._apply_quality_mode)
        tb.addWidget(self.quality_combo)
        self.tv_mode = False

    def _fix_network(self):
        """提权运行 fix_network.py：停系统 SSDPSRV 释放 1900 + 加防火墙规则。"""
        import ctypes
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

    # ---------------- IPTV ----------------
    def open_iptv(self):
        from .iptv_dialog import IptvDialog
        dlg = IptvDialog(self, play_cb=self._play_iptv_url)
        dlg.exec()

    def _play_iptv_url(self, url, title):
        self.on_play(url, title or 'IPTV')

    # ---------------- 华为 / 安卓投屏（系统 Miracast 引导） ----------------
    def open_huawei(self):
        """华为手机投到电脑实际走系统 Miracast，这里帮检测 + 一键调起。"""
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
        """netstat 查端口监听与外部连入，返回 (listening, remotes, nlisteners)。"""
        listening = False
        remotes = []
        nlisteners = 0
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            raw = subprocess.run(
                ['netstat', '-ano'], capture_output=True, timeout=10,
                startupinfo=si, stdin=subprocess.DEVNULL).stdout or b''
            # netstat 中文 Windows 输出 GBK，按 utf-8 忽略解码，ASCII 信息不受影响
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
        """某个 App 对不上时的求助入口：把 apk 发过来针对性适配。"""
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
        """IPTV 电视：输入 m3u/m3u8 列表或单条流地址，或加载官方默认列表。"""
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
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
        """跨线程安全：用 signal 把结果投递回主线程再填列表。"""
        def _apply():
            fill_list(obj)
            status_lbl.setText('<span style="color:#2e7d32">已加载 %d 个频道</span>'
                               % len(obj.channels))
            self.append_log('[IPTV] 列表加载完成: %d 个频道' % len(obj.channels))
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, _apply)

    def open_connect_check(self):
        """自检：手机浏览器直连 device.xml，区分「路由器隔离」还是「App 不认」。"""
        ip = self.stack.http.app_ip
        port = self.stack.http.app_port
        url = 'http://%s:%d/device.xml' % (ip, port)

        copied = '（已复制到剪贴板）'
        try:
            QApplication.clipboard().setText(url)
        except Exception:
            copied = '（复制失败，请手动记录）'

        # 不能靠「本机连本机 IP」来自检：TUN 类 VPN（sing-tun 等）会劫持回环流量，
        # 导致本机连自己也会超时/10061，结果不准。看 netstat 里有没有外部设备连进来才准。
        listening, remotes, nlisteners = self._netstat_port(port)
        # 监听数必须=1。>1 说明旧栈 socket 没释放（Windows SO_REUSEADDR 允许重复 bind
        # 且不报错），连接会被分给没人 accept 的 socket，手机就一直收不到响应。
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

        # 二维码（缺库就隐藏）
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
        """由 main 在热切换 IP 后调用，刷新下拉与 info。"""
        self.info['ip'] = ip
        self._fill_ip_combo()

    def set_net_status(self, text):
        """更新“自动选网”状态标签，让用户清楚当前自动选中的真实网卡。"""
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

    def _make_shortcut(self):
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
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.append_log('就绪。手机与电脑需在同一局域网(Wi-Fi/有线)。')

    def _connect(self):
        self.bridge.playRequested.connect(self.on_play)
        self.bridge.stopRequested.connect(self.on_stop)
        self.bridge.volumeRequested.connect(self._on_volume)
        self.bridge.muteRequested.connect(self.player.set_muted)
        # 手机端 暂停/继续/拖进度条 -> 播放器真的跟着动
        # （以前只改状态机没动播放器，手机上点了暂停电脑还在放）
        self.bridge.pauseRequested.connect(self._on_remote_pause)
        self.bridge.resumeRequested.connect(self._on_remote_resume)
        self.bridge.seekRequested.connect(self._on_remote_seek)
        # 播放器状态 -> DLNA TransportState -> GENA 推给手机
        self.player.playbackChanged.connect(self._on_playback_changed)
        self.player.fullscreenToggle.connect(self._toggle_fullscreen)
        # 让 SOAP GetPositionInfo 能拿到真实进度，手机进度条才会动
        st = getattr(self.bridge, 'state', None)
        if st is not None:
            st.position_provider = lambda: (self.player.position_ms(),
                                            self.player.duration_ms())

    def _toggle_pause(self):
        """暂停/继续共用一个按钮：按状态切换，并回推给手机。"""
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
        """电脑端暂停/继续后，把新状态同步给手机（GENA NOTIFY）。"""
        st = getattr(self.bridge, 'state', None)
        if st is None:
            return
        try:
            st.set_transport(transport)
        except Exception:
            pass

    # ---------------- 双向控制：手机 -> 电脑 ----------------
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
            # 直播流（IPTV/K线等）没有总时长，物理上无法 seek，
            # 不是代码 bug，是片源本身不可拖
            self.append_log('[控制] 手机端请求跳转 %d ms —— 当前片源无总时长（直播流），无法拖动'
                            % ms)
            return
        if self.player.seek(ms):
            self.append_log('[控制] 手机端拖动进度 -> 跳转到 %s' % self._fmt_clock(ms))
            self._notify_remote_seek(ms)
        else:
            self.append_log('[控制] 手机端跳转失败（片源可能不支持拖动）: %s ms' % ms)

    # ---------------- 双向控制：电脑 -> 手机 ----------------
    def _on_playback_changed(self, name):
        """播放器状态变化 -> DLNA TransportState -> GENA NOTIFY 推给手机。"""
        st = getattr(self.bridge, 'state', None)
        mapping = {'PLAYING': 'PLAYING', 'PAUSED': 'PAUSED_PLAYBACK',
                   'STOPPED': 'STOPPED'}
        transport = mapping.get(name, 'STOPPED')
        if st is not None:
            st.set_transport(transport)
        if name == 'PLAYING':
            self.state_label.setText('状态: 播放中')
            self.btn_pause.setText('暂停')
        elif name == 'PAUSED':
            self.state_label.setText('状态: 已暂停')
            self.btn_pause.setText('继续')
        else:
            self.state_label.setText('状态: 空闲')
            self.btn_pause.setText('暂停')
        self.append_log('[状态] %s -> 已同步给手机(TransportState=%s)'
                        % (name, transport))

    # ---------------- 全屏 ----------------
    def _toggle_fullscreen(self):
        """全屏/退出全屏：隐藏工具栏与日志，最大化画面；Esc 或双击可退出。"""
        if self.isFullScreen():
            self.showNormal()
            self.main_tb.show()
            self.tools_tb.show()
            self.progress_bar.show()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.show()
            self.btn_full.setText('全屏')
            if self._fs_geo is not None:
                self.setGeometry(self._fs_geo)
            self.append_log('已退出全屏')
        else:
            self._fs_geo = self.geometry()
            self.main_tb.hide()
            self.tools_tb.hide()
            self.progress_bar.hide()
            if getattr(self, 'log_dock', None) is not None:
                self.log_dock.hide()
            self.btn_full.setText('退出全屏')
            self.showFullScreen()
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

    # ---------------- 码流信息显示 ----------------
    def _start_stat_timer(self):
        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(1000)
        self._stat_timer.timeout.connect(self._refresh_stat)
        self._stat_timer.start()
        self._slider_pressed = False   # 用户正在拖进度条期间暂停自动更新

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
        """每秒把播放位置推进度条与时间标签。"""
        if getattr(self, '_slider_pressed', False):
            return
        try:
            pos = self.player.position_ms()
            dur = self.player.duration_ms()
        except Exception:
            return
        if self.player.is_live():
            # 直播流没有总时长，进度条不可拖，只显示位置 + 「直播」
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
        # 拖动中只更新显示，不动播放器
        if not getattr(self, '_slider_pressed', False) and not self.prog.isSliderDown():
            return
        dur = self.player.duration_ms()
        if dur <= 0:
            return
        pos = dur * (val / 10000.0)
        self.pos_label.setText(self._fmt_clock(pos))

    def _on_slider_moved(self, val):
        """手指按住拖动时标记 pressed，防止 _refresh_progress 把位置弹回去。"""
        self._slider_pressed = True
        self._on_slider_changed(val)

    def _on_slider_released(self):
        """松手 → 真正 setPosition，并回推给手机。"""
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
        """电脑端 seek 后同步给手机（走 DLNA SOAP Seek，手机进度条也跟着跳）。"""
        st = getattr(self.bridge, 'state', None)
        if st is None:
            return
        try:
            st._parse_time(ms)  # 仅触发校验，不改动
        except Exception:
            pass
        # 通过 GENA 状态推送 + GetPositionInfo 刷新：手机侧下次轮询/事件时就会看到新位置
        try:
            st.set_transport(st.transport_state)  # 触发一次 NOTIFY 让手机刷新位置
        except Exception:
            pass

    def _seek_rel(self, delta_ms):
        """相对跳转（键盘 ←/→）。"""
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
        """切换画质预设：'原画' 关闭帧级增强（最流畅），其余开启真实帧处理。"""
        if name == '原画':
            self.player.set_enhance(False)
            self.append_log('画质: 原画（已关闭增强，最省 CPU）')
        else:
            ok = self.player.set_enhance(True, name)
            self.append_log('画质: %s（帧级增强%s）'
                            % (name, '已开启' if ok else '开启失败，保持原画'))

    def _apply_quality_mode(self, idx):
        """切换清晰度策略（电视模式 = 声明 4K 电视 + HD/4K 解码能力 + 重新宣告）。"""
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
        """切换音效档位（真实作用于音量映射：增益 + 等响度补偿）。"""
        gain = self.player.set_audio_preset(name)
        self.append_log('音效: %s（增益 x%.2f%s）'
                        % (name, gain,
                           '' if name == '原声' else '，低音量时自动补偿层次'))

    def open_dolby_check(self):
        """杜比 / 高清解码能力检测：如实告诉用户哪些是系统级能力、怎么开。"""
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

        # 重绘（检测完再填内容）
        while v.count():
            item = v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        v.addWidget(QLabel(
            '<b>边界说明</b>：杜比全景声 / 杜比视界是<b>授权技术</b>，'
            '第三方播放器无法凭空实现其解码。本软件做的是：检测系统是否已装杜比组件，'
            '并在 <code>--backend windows</code> 下走 Media Foundation 原生管道，'
            '让<b>系统级</b>杜比/HEVC/硬件解码自动作用于本播放；'
            '另外提供真实的帧级画质增强与等响度音效补偿。'))

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

    # ---------------- 外观：开屏动画 + 自定义背景 ----------------
    def _apply_saved_appearance(self):
        from .appearance import load as load_cfg
        self.cfg = load_cfg()
        self.player.set_background(self.cfg.get('bg_image', ''),
                                   self.cfg.get('bg_color', '#000000'))

    def open_appearance(self):
        from .appearance import load as load_cfg, save as save_cfg
        cfg = load_cfg()
        dlg = QDialog(self)
        dlg.setWindowTitle('外观设置')
        dlg.resize(560, 560)
        v = QVBoxLayout(dlg)

        # 开屏动画
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

        # 背景
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
            if save_cfg(new):
                self.cfg = new
                self.player.set_background(new['bg_image'], new['bg_color'])
                self.append_log('外观已保存：开屏%s，背景%s'
                                % ('开' if new['splash_enabled'] else '关',
                                   new['bg_image'] or new['bg_color']))
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

    def _on_volume(self, v):
        self.vol.blockSignals(True)
        self.vol.setValue(v)
        self.vol.blockSignals(False)
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

    def on_stop(self):
        self.player.stop()
        self.state_label.setText('状态: 空闲')
        self.append_log('停止')

    def _do_append_log(self, msg):
        """主线程槽：真正写日志控件（含自滚到底）。"""
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
        """线程安全日志入口：任何线程调用都安全，经 Qt 队列投递到主线程。"""
        try:
            self.log_signal.emit(msg)
        except Exception:
            self._do_append_log(msg)
