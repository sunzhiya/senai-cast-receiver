"""开屏动画。

默认不启用（appearance.DEFAULT['splash_enabled'] = False），
用户在「外观」里开了并选好素材才会出现。

素材规则：
    图片  -> 作为开屏背景铺满（按窗口比例缩放）
    gif   -> 当动图循环播
    不填  -> 用蓝紫渐变背景 + 应用图标缩放淡入 + 标题淡入 + 底部进度条
"""
import os

from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve,
                          QRect, QSize)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap, QMovie
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication


class SplashScreen(QWidget):
    """无边框开屏窗口：背景 + 图标 + 标题 + 进度条，带淡入缩放动画。"""

    W, H = 620, 400

    def __init__(self, cfg, icon_path=''):
        super().__init__()
        self.cfg = cfg or {}
        self._bg_pixmap = None
        self._movie = None
        self._step = 0

        img = (cfg.get('splash_image') or '').strip()
        self._load_bg(img)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self._center()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 28)
        lay.addStretch(2)

        # 图标：静态图或 gif
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(150, 150)
        if self._movie is not None:
            self.icon_label.setMovie(self._movie)
        else:
            pm = QPixmap(icon_path)
            if not pm.isNull():
                self.icon_label.setPixmap(pm.scaled(
                    130, 130, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title = QLabel(cfg.get('splash_title') or '')
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet('color:#ffffff; background:transparent;')
        lay.addWidget(self.title)

        self.sub = QLabel(cfg.get('splash_subtitle') or '')
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f2 = QFont()
        f2.setPointSize(10)
        self.sub.setFont(f2)
        self.sub.setStyleSheet('color:#cfd8ff; background:transparent;')
        lay.addWidget(self.sub)

        lay.addStretch(3)

        self.bar_bg = QWidget()
        self.bar_bg.setFixedSize(320, 4)
        self.bar_bg.setStyleSheet('background:rgba(255,255,255,0.18); border-radius:2px;')
        lay.addWidget(self.bar_bg, 0, Qt.AlignmentFlag.AlignHCenter)

        self.bar = QWidget(self.bar_bg)
        self.bar.setGeometry(0, 0, 0, 4)
        self.bar.setStyleSheet('background:#7c9cff; border-radius:2px;')

        # 图标缩放淡入
        self._anim_icon = QPropertyAnimation(self.icon_label, b'geometry')
        self._anim_icon.setDuration(700)
        self._anim_icon.setEasingCurve(QEasingCurve.Type.OutCubic)
        r = self.icon_label.geometry()
        self._anim_icon.setStartValue(QRect(r.center().x() - 40, r.center().y() - 40, 80, 80))
        self._anim_icon.setEndValue(r)

        self._anim_win = QPropertyAnimation(self, b'windowOpacity')
        self._anim_win.setDuration(450)
        self._anim_win.setStartValue(0.0)
        self._anim_win.setEndValue(1.0)

    # ---------------- 背景 ----------------
    def _load_bg(self, img):
        if not img or not os.path.exists(img):
            return
        if img.lower().endswith('.gif'):
            m = QMovie(img)
            if m.isValid():
                self._movie = m
        else:
            pm = QPixmap(img)
            if not pm.isNull():
                self._bg_pixmap = pm

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._bg_pixmap is not None:
            pm = self._bg_pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - pm.width()) // 2
            y = (self.height() - pm.height()) // 2
            p.drawPixmap(x, y, pm)
            p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        else:
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0.0, QColor('#1b1f3b'))
            g.setColorAt(0.55, QColor('#3a2a6b'))
            g.setColorAt(1.0, QColor('#11142a'))
            p.fillRect(self.rect(), g)
        super().paintEvent(ev)

    def _center(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        self.move(g.center().x() - self.W // 2, g.center().y() - self.H // 2)

    # ---------------- 播放 ----------------
    def start(self):
        if self._movie is not None:
            self._movie.start()
        self._anim_icon.start()
        self._anim_win.start()

        total = max(600, int(self.cfg.get('splash_ms') or 1800))
        self._steps = max(1, total // 40)
        self._step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.show()

    def _tick(self):
        self._step += 1
        pct = min(1.0, self._step / float(self._steps))
        self.bar.setFixedWidth(int(self.bar_bg.width() * pct))
        if self._step >= self._steps:
            self._timer.stop()
            self.close_sig = True

    @property
    def finished(self):
        return getattr(self, 'close_sig', False)

    def stop(self):
        try:
            if self._movie is not None:
                self._movie.stop()
        except Exception:
            pass
        try:
            self._timer.stop()
        except Exception:
            pass
        self.close()


def run_splash(app, cfg, icon_path='', log=print):
    """显示开屏并在其结束后返回。未开启就直接返回 None。"""
    if not (cfg or {}).get('splash_enabled'):
        return None
    sp = SplashScreen(cfg, icon_path)
    sp.start()
    total = max(600, int(cfg.get('splash_ms') or 1800))
    deadline = total + 400
    from PyQt6.QtCore import QElapsedTimer
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < deadline:
        app.processEvents()
        if sp.finished:
            break
        import time
        time.sleep(0.016)
    sp.stop()
    return sp
