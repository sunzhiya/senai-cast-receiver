from PyQt6.QtCore import QObject, pyqtSignal


class PlayerBridge(QObject):
    """把 DLNA 后台线程里的播放事件，安全地桥接到 Qt 主线程的 GUI。"""

    playRequested = pyqtSignal(str, str)   # (uri, title)
    stopRequested = pyqtSignal()
    pauseRequested = pyqtSignal()          # 手机/电脑端请求暂停（DLNA SOAP Pause）
    resumeRequested = pyqtSignal()         # 请求继续播放
    volumeRequested = pyqtSignal(int)
    muteRequested = pyqtSignal(int)
    # 手机拖动进度条 -> SOAP Seek -> 转成毫秒交给播放器（须回主线程执行）
    seekRequested = pyqtSignal(object)

    def __init__(self, state):
        super().__init__()
        self.state = state
        state.on_play = lambda uri, title: self.playRequested.emit(uri, title)
        state.on_stop = lambda: self.stopRequested.emit()
        state.on_pause = lambda: self.pauseRequested.emit()
        state.on_resume = lambda: self.resumeRequested.emit()
        state.on_volume = lambda v: self.volumeRequested.emit(v)
        state.on_mute = lambda m: self.muteRequested.emit(m)
        state.on_seek = lambda ms: self.seekRequested.emit(ms)
