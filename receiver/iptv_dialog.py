# iptv对话框，输入m3u8地址或者选m3u文件，然后丢给播放器
import os

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton,
                             QComboBox, QFileDialog, QMessageBox, QTextEdit)

# 几个现成的公开频道列表，点开就能拉
PRESET_LISTS = [
    ('全部频道', 'https://iptv-org.github.io/iptv/index.m3u'),
    ('中国', 'https://iptv-org.github.io/iptv/countries/cn.m3u'),
    ('新闻', 'https://iptv-org.github.io/iptv/categories/news.m3u'),
    ('体育', 'https://iptv-org.github.io/iptv/categories/sports.m3u'),
    ('动漫', 'https://iptv-org.github.io/iptv/categories/animation.m3u'),
]


class IptvDialog(QDialog):
    """输入一个流地址 或者 拉个m3u列表挑频道，交给播放器放。"""

    def __init__(self, parent, play_cb):
        super().__init__(parent)
        self.play_cb = play_cb   # (url, title) 这样调
        self.setWindowTitle('IPTV 电视')
        self.resize(560, 380)

        v = QVBoxLayout(self)

        # 直接输流地址
        v.addWidget(QLabel('流地址（m3u8 / ts / mp4 直链）:'))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText('例如 https://xxx.m3u8')
        v.addWidget(self.url_edit)

        h1 = QHBoxLayout()
        b_play = QPushButton('播放这个地址')
        b_play.clicked.connect(self._play_url)
        b_m3u = QPushButton('打开 m3u 文件')
        b_m3u.clicked.connect(self._load_m3u_file)
        h1.addWidget(b_play)
        h1.addWidget(b_m3u)
        h1.addStretch()
        v.addLayout(h1)

        # 拉在线列表
        v.addWidget(QLabel('或者拉在线频道列表:'))
        h2 = QHBoxLayout()
        self.list_combo = QComboBox()
        for name, url in PRESET_LISTS:
            self.list_combo.addItem(name, url)
        b_fetch = QPushButton('拉取')
        b_fetch.clicked.connect(self._fetch_list)
        h2.addWidget(self.list_combo, 1)
        h2.addWidget(b_fetch)
        v.addLayout(h2)

        # 拉下来的频道显示在这，点一下就能复制
        self.chan_box = QTextEdit()
        self.chan_box.setReadOnly(True)
        self.chan_box.setMaximumHeight(140)
        self.chan_box.setPlaceholderText('拉取列表后，频道会显示在这里，点一下复制地址')
        v.addWidget(self.chan_box)

        b_ok = QPushButton('知道了')
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton('取消')
        b_cancel.clicked.connect(self.reject)
        hh = QHBoxLayout()
        hh.addStretch()
        hh.addWidget(b_ok)
        hh.addWidget(b_cancel)
        v.addLayout(hh)

    def _play_url(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, '没填', '先填个地址再点')
            return
        self.play_cb(url, 'IPTV')
        self.accept()

    def _load_m3u_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选个 m3u 文件', '', 'M3U 文件 (*.m3u *.m3u8);;所有文件 (*.*)')
        if not path:
            return
        from .iptv import IptvList
        lst = IptvList.from_file(path)
        self._show_channels(lst.channels)

    def _fetch_list(self):
        url = self.list_combo.currentData()
        if not url:
            return
        self.chan_box.clear()
        self.chan_box.setPlainText('拉取中...')
        # 同步拉，慢就慢，不折腾线程了
        from .iptv import IptvList
        lst = IptvList.from_url(url)
        self._show_channels(lst.channels)

    def _show_channels(self, channels):
        if not channels:
            self.chan_box.setPlainText('没拉到频道，列表可能有问题')
            return
        lines = []
        for i, c in enumerate(channels[:80]):
            tag = c.group or '未分组'
            lines.append('[%s] %s' % (tag, c.name or c.url[:40]))
            lines.append('  ' + c.url)
        text = '\n'.join(lines)
        self.chan_box.setPlainText(text)
        self.chan_box.selectAll()
