from PyQt6.QtCore import Qt, QTimer, QPoint, QRect
from PyQt6.QtGui import (QPainter, QColor, QPainterPath, QPen, QFont,
                         QLinearGradient, QBrush)
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QSlider, QMenu, QApplication)


class IslandBar(QWidget):

    def __init__(self, main_window):
        super().__init__(None, Qt.WindowType.Tool
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.main = main_window
        self.setObjectName('islandBar')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._opacity = 1.0
        self._compact = False
        self._radius = 23
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._tick_fade)

        self.setFixedHeight(46)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 6, 12, 6)
        root.setSpacing(10)

        self.dot = QLabel('●')
        self.dot.setStyleSheet('color:#39ff88; font-size:13px; background:transparent;')
        root.addWidget(self.dot)

        self.name_label = QLabel('森投屏接收端')
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        self.name_label.setFont(f)
        self.name_label.setStyleSheet('color:#f2f2f7; background:transparent; letter-spacing:0.5px;')
        root.addWidget(self.name_label)

        self.state_label = QLabel('空闲')
        self.state_label.setStyleSheet('color:#9a9aa2; font-size:11px; background:transparent;')
        root.addWidget(self.state_label)

        self.stretch = QWidget()
        self.stretch.setStyleSheet('background:transparent;')
        self.stretch.setFixedWidth(1)
        root.addWidget(self.stretch, 1)

        self.ctrl = QWidget()
        self.ctrl.setStyleSheet('background:transparent;')
        ch = QHBoxLayout(self.ctrl)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)

        self.btn_play = self._icon_button('▶', '播放 / 暂停', self._toggle_play)
        self.btn_stop = self._icon_button('■', '停止', self._stop)
        ch.addWidget(self.btn_play)
        ch.addWidget(self.btn_stop)

        self.time_label = QLabel('')
        self.time_label.setStyleSheet('color:#c8c8d0; font-size:11px; background:transparent;')
        ch.addWidget(self.time_label)

        root.addWidget(self.ctrl)

        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setFixedWidth(84)
        self.vol.setStyleSheet(
            'QSlider{background:transparent;}'
            'QSlider::groove:horizontal{height:3px;background:rgba(255,255,255,60);border-radius:2px;}'
            'QSlider::sub-page:horizontal{background:rgba(255,255,255,190);border-radius:2px;}'
            'QSlider::handle:horizontal{width:9px;height:9px;margin:-3px 0;'
            'background:#ffffff;border-radius:5px;}')
        root.addWidget(self.vol)

        self.btn_more = self._icon_button('⋯', '更多', self._show_more)
        root.addWidget(self.btn_more)

        root.addSpacing(4)
        self.btn_hide = self._icon_button('—', '隐藏（收进托盘）', self._hide_to_tray)
        root.addWidget(self.btn_hide)

        self.setVisible(True)

    def _icon_button(self, text, tip, slot):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(26, 26)
        b.setStyleSheet(
            'QPushButton{background:rgba(255,255,255,24);color:#ececf2;'
            'border:none;border-radius:13px;font-size:12px;}'
            'QPushButton:hover{background:rgba(255,255,255,58);}'
            'QPushButton:pressed{background:rgba(255,255,255,90);}')
        b.clicked.connect(slot)
        return b

    def _toggle_play(self):
        self._jump_back()
        try:
            self.main._toggle_pause()
        except Exception:
            pass

    def _stop(self):
        self._jump_back()
        try:
            self.main.on_stop()
        except Exception:
            pass

    def _hide_to_tray(self):
        try:
            self.main._minimize_to_tray()
        except Exception:
            pass

    def _jump_back(self):
        try:
            self.main.bring_to_front()
        except Exception:
            pass

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._jump_back()
        super().mousePressEvent(ev)

    def enterEvent(self, ev):
        if self._compact:
            self.set_compact(False)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        try:
            if self.main is not None and self.main.player.is_playing() and not self.underMouse():
                self.set_compact(True)
        except Exception:
            pass
        super().leaveEvent(ev)

    def _show_more(self):
        m = QMenu(self)
        m.setStyleSheet(
            'QMenu{background:#1c1c22;color:#ececf2;border:1px solid rgba(255,255,255,28);'
            'border-radius:10px;padding:6px;}'
            'QMenu::item{padding:6px 22px 6px 14px;border-radius:6px;}'
            'QMenu::item:selected{background:rgba(255,255,255,32);}'
            'QMenu::separator{height:1px;background:rgba(255,255,255,22);margin:4px 8px;}')
        try:
            self.main.populate_more_menu(m)
        except Exception:
            pass
        m.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 6)))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(r.left()), float(r.top()),
                            float(r.width()), float(r.height()),
                            float(self._radius), float(self._radius))

        grad = QLinearGradient(0, float(r.top()), 0, float(r.bottom()))
        grad.setColorAt(0.0, QColor(46, 46, 56, int(222 * self._opacity)))
        grad.setColorAt(0.55, QColor(26, 26, 33, int(226 * self._opacity)))
        grad.setColorAt(1.0, QColor(16, 16, 21, int(230 * self._opacity)))
        p.fillPath(path, QBrush(grad))

        p.setPen(QPen(QColor(255, 255, 255, int(40 * self._opacity)), 1))
        p.drawPath(path)

        hl = QPainterPath()
        hl.addRoundedRect(float(r.left()) + 12, float(r.top()) + 1.0,
                          float(r.width()) - 24, float(r.height()) - 2.0,
                          float(self._radius - 2), float(self._radius - 2))
        p.setPen(QPen(QColor(255, 255, 255, int(16 * self._opacity)), 1))
        p.drawPath(hl)
        p.end()

    def _tick_fade(self):
        if self._opacity < 1.0:
            self._opacity = min(1.0, self._opacity + 0.16)
            self.update()
        if self._opacity >= 1.0:
            self._opacity = 1.0
            self._fade_timer.stop()

    def fade_in(self):
        self.setVisible(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._opacity = 0.15
        self._fade_timer.start()
        try:
            self.raise_()
        except Exception:
            pass
        self.update()

    def show_at_top(self):
        if not self._eligible():
            self.hide()
            return
        self.reposition()
        self.fade_in()

    def _eligible(self):
        mw = self.main
        if mw is None:
            return False
        return mw.isVisible() and not mw.isMinimized()

    def guard(self):
        if not self._eligible():
            if self.isVisible():
                self.hide()
            return
        if not self.isVisible():
            self.show_at_top()
            return

    def set_compact(self, on):
        if self._compact == on:
            return
        self._compact = on
        for w in (self.name_label, self.state_label, self.time_label,
                  self.vol, self.btn_stop, self.btn_more, self.btn_hide):
            w.setVisible(not on)
        self._radius = 15 if on else 23
        self.setFixedHeight(30 if on else 46)
        self.reposition()
        self.update()

    def _screen_geo(self):
        try:
            scr = self.main.screen() if self.main is not None else None
            if scr is None:
                scr = QApplication.primaryScreen()
            return scr.availableGeometry()
        except Exception:
            return None

    def reposition(self):
        mw = self.main
        try:
            if mw is None or not mw.isVisible() or mw.isMinimized():
                return
            h = 30 if self._compact else 46
            geo = self._screen_geo()
            if geo is not None:
                w = 150 if self._compact else min(560, max(460, int(geo.width() * 0.42)))
                x = geo.center().x() - w // 2
                y = geo.top() + 10
            else:
                w = 150 if self._compact else 520
                tl = mw.mapToGlobal(QPoint(0, 0))
                x = tl.x() + (mw.width() - w) // 2
                y = tl.y() + 8
            self.setFixedWidth(w)
            self.setGeometry(x, y, w, h)
            self.raise_()
            self.update()
        except Exception:
            pass

    def set_state(self, text, playing=False):
        self.state_label.setText(text)
        self.dot.setStyleSheet(
            'color:%s; font-size:13px; background:transparent;'
            % ('#39ff88' if playing else '#8a8a92'))
        self.btn_play.setText('⏸' if playing else '▶')

    def set_time(self, text):
        self.time_label.setText(text)
