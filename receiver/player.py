from PyQt6.QtCore import QObject, pyqtSignal


class PlayerBridge(QObject):

    playRequested = pyqtSignal(str, str)
    stopRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    resumeRequested = pyqtSignal()
    volumeRequested = pyqtSignal(int)
    muteRequested = pyqtSignal(int)
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
