import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QDesktopServices, QIcon
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QTabWidget, QWidget,
                             QScrollArea, QFrame, QLineEdit, QCheckBox)

HERE = os.path.dirname(os.path.abspath(__file__))
DONATE_IMG = os.path.join(HERE, 'assets', 'donate.jpg')
ICON_IMG = os.path.join(HERE, 'assets', 'icon.ico')

QQ = '1218563952'
GITHUB = 'https://github.com/sunzhiya/senai-cast-receiver'
ISSUES = 'https://github.com/sunzhiya/senai-cast-receiver/issues'
PRIVACY = 'https://raw.githubusercontent.com/sunzhiya/senai-cast-receiver/main/PRIVACY.md'
VERSION = '1.3.0'


def _pkg_version():
    try:
        from .msix import package_version
        return package_version() or VERSION
    except Exception:
        return VERSION


VERSION = _pkg_version()


def _open(url):
    try:
        QDesktopServices.openUrl(QUrl(url))
    except Exception:
        pass


def _copy(text, parent=None):
    try:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        if parent is not None:
            parent.append_log('[关于] 已复制: %s' % text)
    except Exception:
        pass


def _link(label, url, parent=None):
    lab = QLabel('<a href="%s" style="color:#3f8cff;">%s</a>' % (url, label))
    lab.setOpenExternalLinks(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    return lab


def build_about(parent, on_theme=None, on_appearance=None):
    from .msix import is_packaged
    store = is_packaged()

    dlg = QDialog(parent)
    dlg.setWindowTitle('关于 森投屏接收端')
    dlg.resize(640, 560)
    v = QVBoxLayout(dlg)

    head = QHBoxLayout()
    if os.path.exists(ICON_IMG):
        ico = QLabel()
        pix = QPixmap(ICON_IMG).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        ico.setPixmap(pix)
        head.addWidget(ico)
    info = QLabel(
        '<div style="font-size:16px;"><b>森投屏接收端</b> v%s</div>'
        '<div style="color:#888;">Windows 上的 DLNA / AirPlay / IPTV 投屏接收端</div>'
        % VERSION)
    info.setTextFormat(Qt.TextFormat.RichText)
    head.addWidget(info)
    head.addStretch()
    v.addLayout(head)

    tabs = QTabWidget()
    v.addWidget(tabs)

    tab_donate = QWidget()
    td = QVBoxLayout(tab_donate)
    if store:
        td.addWidget(QLabel(
            '<div style="line-height:150%%;">'
            '这版是从微软商店装的。<br><br>'
            '想支持的话，商店里点个好评、GitHub 上点个 Star，都算。<br>'
            '扫码请我喝瓶水也行，随意。'
            '</div>'))
    else:
        td.addWidget(QLabel(
            '<div style="line-height:150%%;">'
            '给不给都不影响功能，全都能用。<br><br>'
            '有事找我：<b>QQ %s</b>（备注「投屏」），或者 GitHub 提 Issue。'
            '</div>' % QQ))
    if os.path.exists(DONATE_IMG):
        pm = QPixmap(DONATE_IMG).scaled(280, 280,
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
        lab = QLabel()
        lab.setPixmap(pm)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        td.addWidget(lab, 0, Qt.AlignmentFlag.AlignCenter)
        td.addWidget(QLabel('微信扫一扫，金额随意'),
                     0, Qt.AlignmentFlag.AlignCenter)
    td.addStretch()

    b_copy = QPushButton('复制 QQ 号')
    b_copy.clicked.connect(lambda: _copy(QQ, parent))
    row = QHBoxLayout()
    row.addWidget(b_copy)
    row.addStretch()
    td.addLayout(row)
    tabs.addTab(tab_donate, '赞赏')

    tab_help = QWidget()
    th = QVBoxLayout(tab_help)

    def add_block(title, rows):
        th.addWidget(QLabel('<b>%s</b>' % title))
        for label, value, action in rows:
            r = QHBoxLayout()
            lb = QLabel(value)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            r.addWidget(lb)
            if action == 'link':
                r.addWidget(_link('打开', value, parent))
            elif action == 'copy':
                b = QPushButton('复制')
                b.clicked.connect(lambda _c=False, v=value: _copy(v, parent))
                r.addWidget(b)
            r.addStretch()
            th.addLayout(r)
        th.addSpacing(10)

    add_block('出问题了', [
        ('提 Issue', ISSUES, 'link'),
        ('QQ', QQ, 'copy'),
    ])
    add_block('要我适配新 App', [
        ('发我', QQ, 'copy'),
    ])
    add_block('其它', [
        ('项目主页', GITHUB, 'link'),
        ('隐私政策', PRIVACY, 'link'),
    ])

    info2 = QTextEdit()
    info2.setReadOnly(True)
    info2.setPlainText(
        '先自查这几条：\n'
        '1. 手机和电脑得在同一个 Wi-Fi（或同一个有线网），路由器别开 AP 隔离\n'
        '2. 用 App 里的「投屏 / TV」按钮，不是系统自带的「无线投屏」\n'
        '3. 鸿蒙要给那个 App「附近设备」权限\n'
        '4. 扫不到先点「一键修复网络」，点完重启软件\n\n'
        '还是不行，点「手机连通性自检」，手机浏览器能打开那个地址，'
        '说明网是通的，问题在那个 App 上。把 App 名和现象发我。')
    info2.setMinimumHeight(150)
    th.addWidget(QLabel('<b>排查顺序</b>'))
    th.addWidget(info2)
    th.addStretch()
    tabs.addTab(tab_help, '联系与支持')

    tab_skin = QWidget()
    ts = QVBoxLayout(tab_skin)
    ts.addWidget(QLabel(
        '<div style="line-height:150%%;">'
        '主题、背景图、开屏动画都在「外观」里改，改完立刻生效，不用重启。<br><br>'
        '自带 6 套：经典黑 / 深邃蓝 / 暗夜紫 / 暖阳橙 / 青瓷绿 / 樱粉。<br>'
        '也能自己配色存成预设。<br><br>'
        '想要别的皮肤、想改图标或开屏，<b>QQ %s</b> 找我，做得出来的都给你做。'
        '</div>' % QQ))
    b_skin = QPushButton('打开「外观」设置')
    b_skin.clicked.connect(lambda: (on_appearance() if on_appearance else None))
    ts.addWidget(b_skin)
    ts.addSpacing(12)
    ts.addWidget(QLabel('<b>新 App 适配</b>'))
    ts.addWidget(QLabel(
        '把 .apk 发我 QQ %s，说一句哪里不对（扫不到、没画面、暂停没反应、'
        '进度不动、声音不对）。' % QQ))
    ts.addStretch()
    tabs.addTab(tab_skin, '皮肤与定制')

    foot = QHBoxLayout()
    b_privacy = QPushButton('隐私政策')
    b_privacy.clicked.connect(lambda: _open(PRIVACY))
    b_github = QPushButton('GitHub')
    b_github.clicked.connect(lambda: _open(GITHUB))
    b_close = QPushButton('关闭')
    b_close.clicked.connect(dlg.accept)
    foot.addWidget(b_privacy)
    foot.addWidget(b_github)
    foot.addStretch()
    foot.addWidget(b_close)
    v.addLayout(foot)

    return dlg
