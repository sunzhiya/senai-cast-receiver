"""AirPlay 视频服务端无界面自测：验证 /server-info 与 /play 真的能触发播放回调。

运行：python test_airplay.py
"""
import http.client
import plistlib
import threading
import time

from receiver.dlna.services import RendererState
from receiver.airplay.server import AirPlayServer


def main():
    state = RendererState()
    events = []
    state.on_play = lambda uri, title: events.append(('play', uri, title))
    state.on_stop = lambda: events.append(('stop',))

    srv = AirPlayServer('127.0.0.1', 7100, state, log=print)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)

    conn = http.client.HTTPConnection('127.0.0.1', 7100, timeout=3)

    # 1) /server-info
    conn.request('GET', '/server-info')
    r = conn.getresponse()
    info = plistlib.loads(r.read())
    assert info.get('deviceid'), 'deviceid 缺失'
    assert info.get('pki'), 'pki(公钥) 缺失'
    print('[OK] /server-info deviceid=%s features=%s' % (info['deviceid'], hex(info['features'])))

    # 2) /info
    conn.request('GET', '/info')
    r = conn.getresponse()
    di = plistlib.loads(r.read())
    assert 'capabilities' in di, 'capabilities 缺失'
    print('[OK] /info 含 video 能力: %s' % ('video' in di['capabilities']))

    # 3) /play (plist 带 Content-Location)
    body = plistlib.dumps(
        {'Content-Location': 'http://example.com/v.m3u8', 'Title': '测试片'},
        fmt=plistlib.FMT_BINARY)
    conn.request('POST', '/play', body,
                 {'Content-Type': 'application/x-apple-binary-plist'})
    r = conn.getresponse()
    r.read()
    time.sleep(0.2)
    assert events and events[0][0] == 'play' and events[0][1] == 'http://example.com/v.m3u8', events
    print('[OK] /play 触发 on_play: %s / %s' % (events[0][1], events[0][2]))

    # 4) /stop
    conn.request('POST', '/stop')
    r = conn.getresponse()
    r.read()
    time.sleep(0.1)
    assert events[-1][0] == 'stop', events
    print('[OK] /stop 触发 on_stop')

    srv.shutdown()
    print('全部 AirPlay 视频服务端测试通过')


if __name__ == '__main__':
    main()
