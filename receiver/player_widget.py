# -*- coding: utf-8 -*-
"""投屏播放组件，基于 Qt6 Multimedia。"""
import os

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QEvent, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QMediaMetaData
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QWidget, QStackedLayout, QLabel

try:
    import numpy as np
except Exception:
    np = None

# 画质档：(亮度偏移, 对比度, 饱和度, 锐化强度)
PRESETS = {
    '原画': (0, 1.00, 1.00, 0.00),
    '生动': (6, 1.10, 1.28, 0.35),
    '影院': (-4, 1.12, 1.08, 0.15),
    '锐利': (2, 1.06, 1.05, 0.80),
    '柔和': (4, 0.96, 1.12, 0.00),
}

# 音效档：(增益倍数, 等响度补偿强度)
AUDIO_PRESETS = {
    '原声': (1.00, 0.00),
    '杜比风格·宽阔': (1.18, 0.60),
    '影院氛围': (1.10, 0.40),
    '人声清晰': (1.06, 0.25),
    '夜间·轻柔': (0.85, 0.85),
}

ERR_NAMES = {
    0: '无错误',
    1: '资源不可用(解码器缺失/地址无效)',
    2: '格式不支持',
    3: '网络错误',
    4: '无权限',
}

STATUS_NAMES = {
    0: 'NoMedia', 1: 'LoadingMedia', 2: 'LoadedMedia', 3: 'Stalled',
    4: 'Buffering', 5: 'Buffered', 6: 'EndOfMedia', 7: 'InvalidMedia',
}


class CastPlayer(QWidget):
    """解码 + 显示 + 音量 + 画质增强，双模式：原生 QVideoWidget 或逐帧 numpy 处理。"""

    playerError = pyqtSignal(str)
    playerStatus = pyqtSignal(str)
    playbackChanged = pyqtSignal(str)
    fullscreenToggle = pyqtSignal()

    def __init__(self, parent=None, log=print):
        super().__init__(parent)
        self.log = log
        self._title = ''

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(1.0)

        # 0=原生 QVideoWidget（CPU 省），1=逐帧 numpy 处理画到 QLabel
        self._video = QVideoWidget()
        self._video.setStyleSheet('background:#000')
        self._canvas = QLabel()
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._canvas.setStyleSheet('background:#000')
        self._stack = QStackedLayout(self)
        self._stack.addWidget(self._video)
        self._stack.addWidget(self._canvas)
        self._stack.setCurrentWidget(self._video)

        self._player.setVideoOutput(self._video)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.playbackStateChanged.connect(self._on_state)

        # 双击画面 → 请求切全屏
        self._video.installEventFilter(self)
        self._canvas.installEventFilter(self)

        self._enhance_on = False
        self._params = PRESETS['原画']
        self._sink = None

        # 音效：base_vol 是用户设的 0-100，最终音量 = base_vol × 增益 × 等响度补偿
        self._base_vol = 100
        self._audio_params = AUDIO_PRESETS['原声']
        self._audio_preset = '原声'

    # ---------- 播放控制 ----------
    def play_src(self, uri, title=''):
        self._title = title or ''
        self.log('[播放器] 载入: %s' % uri[:120])
        self._player.setSource(QUrl(uri))
        self._player.play()

    def stop(self):
        self._player.stop()
        self._player.setSource(QUrl())
        self._canvas.setPixmap(QPixmap())

    def pause(self):
        self._player.pause()

    def resume(self):
        self._player.play()

    def set_volume(self, v):
        try:
            self._base_vol = max(0, min(100, int(v)))
        except Exception:
            self._base_vol = 100
        self._apply_audio()

    def set_muted(self, m):
        try:
            self._audio.setMuted(bool(m))
        except Exception:
            pass

    # ---------- 背景 ----------
    def set_background(self, image='', color='#000000'):
        try:
            if image and os.path.exists(image):
                p = image.replace('\\', '/')
                bg = 'border-image: url("%s") 0 0 0 0 stretch stretch;' % p
            else:
                bg = 'background:%s;' % (color or '#000000')
            self._video.setStyleSheet(bg)
            self._canvas.setStyleSheet(bg)
            self.setStyleSheet('background:%s;' % (color or '#000000'))
            return True
        except Exception:
            return False

    # ---------- 音效 ----------
    def available_audio_presets(self):
        return list(AUDIO_PRESETS.keys())

    def set_audio_preset(self, name):
        self._audio_preset = name if name in AUDIO_PRESETS else '原声'
        self._audio_params = AUDIO_PRESETS[self._audio_preset]
        self._apply_audio()
        return self._audio_params[0]

    def _apply_audio(self):
        """等响度补偿：音量越小补得越多，近似 Fletcher-Munson 曲线。"""
        gain, loud = self._audio_params
        v = self._base_vol / 100.0
        eff = v * gain
        if loud > 0:
            eff = eff * (1.0 + loud * (1.0 - v) * 0.8)
        try:
            self._audio.setVolume(max(0.0, min(1.0, eff)))
        except Exception:
            pass

    # ---------- 进度 ----------
    def position_ms(self):
        try:
            return int(self._player.position())
        except Exception:
            return 0

    def duration_ms(self):
        try:
            return int(self._player.duration())
        except Exception:
            return 0

    def seek(self, ms):
        try:
            self._player.setPosition(int(ms))
            return True
        except Exception as e:
            self.log('[播放器] 跳转失败: %s' % e)
            return False

    def is_playing(self):
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ---------- 画质增强 ----------
    def available_presets(self):
        return list(PRESETS.keys())

    def set_enhance(self, on, preset='生动'):
        """开/关帧级增强。失败自动回退原画，不影响播放。"""
        if np is None and on:
            self.log('[画质增强] numpy 不可用，保持原画')
            return False
        try:
            if on:
                self._params = PRESETS.get(preset, PRESETS['生动'])
                if self._sink is None:
                    self._sink = QVideoSink(self)
                    self._sink.videoFrameChanged.connect(self._on_frame)
                self._player.setVideoSink(self._sink)
                self._stack.setCurrentWidget(self._canvas)
            else:
                self._player.setVideoOutput(self._video)
                self._stack.setCurrentWidget(self._video)
            self._enhance_on = bool(on)
            return True
        except Exception as e:
            self._enhance_on = False
            try:
                self._player.setVideoOutput(self._video)
                self._stack.setCurrentWidget(self._video)
            except Exception:
                pass
            self.log('[画质增强] 不可用，回退原画: %s' % e)
            return False

    def _on_frame(self, frame):
        if not self._enhance_on:
            return
        try:
            img = frame.toImage()
            if img.isNull():
                return
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            w, h = img.width(), img.height()
            if w <= 0 or h <= 0:
                return
            bits = img.bits()
            bits.setsize(h * w * 3)
            arr = np.frombuffer(bits, np.uint8).reshape(h, w, 3)
            out = self._process(arr)
            qimg = QImage(out.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            self._canvas.setPixmap(QPixmap.fromImage(qimg.copy()))
        except Exception:
            pass

    def _process(self, arr):
        """亮度 → 对比度 → 饱和度 → 非锐化掩蔽锐化。"""
        b, c, s, sh = self._params
        f = arr.astype(np.float32)
        if c != 1.0:
            f = (f - 128.0) * c + 128.0
        if b:
            f += float(b)
        if s != 1.0:
            luma = (f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114)
            f = luma[..., None] + (f - luma[..., None]) * s
        out = np.clip(f, 0, 255)
        if sh > 0 and _shape_ok(out):
            p = out
            blur = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
                    p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] +
                    p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0
            core = p[1:-1, 1:-1] + (p[1:-1, 1:-1] - blur) * (sh * 2.0)
            out[1:-1, 1:-1] = np.clip(core, 0, 255)
        return out.astype(np.uint8)

    # ---------- 状态上报 ----------
    @staticmethod
    def _enum_val(e):
        try:
            return int(e.value)
        except Exception:
            try:
                return int(e)
            except Exception:
                return None

    def _on_error(self, err, msg):
        code = self._enum_val(err)
        name = ERR_NAMES.get(code, str(err))
        text = '播放错误: %s | %s' % (name, msg or '')
        self.log('[播放器] %s' % text)
        self.playerError.emit(text)

    def _on_status(self, st):
        code = self._enum_val(st)
        text = '状态: %s' % STATUS_NAMES.get(code, str(st))
        if code == 2:
            res = self.resolution_text()
            if res:
                text += ' (分辨率 %s)' % res
        self.playerStatus.emit(text)

    def _on_playback_state(self, st):
        try:
            if st == QMediaPlayer.PlaybackState.PlayingState:
                name = 'PLAYING'
            elif st == QMediaPlayer.PlaybackState.PausedState:
                name = 'PAUSED'
            else:
                name = 'STOPPED'
        except Exception:
            return
        self.playbackChanged.emit(name)

    def _on_state(self, st):
        if st == QMediaPlayer.PlaybackState.PlayingState:
            self.playerStatus.emit('状态: 播放中')

    def resolution_text(self):
        try:
            md = self._player.metaData()
            v = md.value(QMediaMetaData.Key.VideoResolution)
            if v is not None:
                return '%dx%d' % (v.width(), v.height())
        except Exception:
            pass
        return None

    @staticmethod
    def resolution_tag(res):
        if not res or 'x' not in res:
            return ''
        try:
            _w, h = (int(x) for x in res.split('x'))
        except Exception:
            return ''
        if h >= 2000:
            return '4K'
        if h >= 1400:
            return '2K'
        if h >= 1000:
            return '1080P'
        if h >= 700:
            return '720P'
        if h >= 480:
            return '480P'
        return 'SD'

    def meta_summary(self):
        out = {}
        try:
            md = self._player.metaData()
        except Exception:
            return out

        def _get(key_name):
            key = getattr(QMediaMetaData.Key, key_name, None)
            if key is None:
                return None
            try:
                return md.value(key)
            except Exception:
                return None

        res = _get('VideoResolution')
        if res is not None:
            try:
                out['res'] = '%dx%d' % (res.width(), res.height())
                out['tag'] = self.resolution_tag(out['res'])
            except Exception:
                pass
        br = _get('VideoBitRate')
        if br:
            try:
                out['bitrate'] = '%d kbps' % int(int(br) / 1000)
            except Exception:
                pass
        fr = _get('VideoFrameRate')
        if fr:
            try:
                out['fps'] = '%.0f fps' % float(fr)
            except Exception:
                pass
        for name in ('VideoCodec', 'AudioCodec'):
            c = _get(name)
            if c:
                out['codec' if name == 'VideoCodec' else 'acodec'] = str(c)
        return out

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonDblClick:
            self.fullscreenToggle.emit()
            return True
        return super().eventFilter(obj, ev)

    def backend_name(self):
        return os.environ.get('QT_MEDIA_BACKEND', 'ffmpeg(默认)')


def _shape_ok(arr):
    return arr.shape[0] > 3 and arr.shape[1] > 3
