"""无界面验证 DLNA 内核：device.xml 可访问、SOAP 控制、播放回调。"""
import time
import urllib.request
import http.client
import xml.etree.ElementTree as ET

from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState

NS = 'urn:schemas-upnp-org:device-1-0'
AV = 'urn:schemas-upnp-org:service:AVTransport:1'


def _soap(action, inner):
    return ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
            % (action, AV, inner, action))


def _post(conn, action, inner):
    body = _soap(action, inner)
    conn.request('POST', '/upnp/control/AVTransport', body.encode('utf-8'),
                 {'Content-Type': 'text/xml; charset="utf-8"',
                  'SOAPACTION': '"%s#%s"' % (AV, action)})
    return conn.getresponse()


def main():
    state = RendererState()
    events = []
    state.on_play = lambda u, t: events.append(('play', u, t))
    state.on_stop = lambda: events.append(('stop',))
    stack = DlnaStack('127.0.0.1', 8299, 'TestReceiver', state, log=print)
    stack.start()
    time.sleep(0.6)

    xml = urllib.request.urlopen('http://127.0.0.1:8299/device.xml', timeout=4).read().decode()
    root = ET.fromstring(xml)
    dt = root.find('.//{%s}deviceType' % NS)
    assert dt is not None and 'MediaRenderer' in dt.text, 'deviceType 错误: %r' % dt.text
    print('[OK] device.xml 返回 MediaRenderer 描述')

    conn = http.client.HTTPConnection('127.0.0.1', 8299, timeout=4)
    meta = ('&lt;DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"&gt;'
            '&lt;item&gt;&lt;dc:title&gt;测试片&lt;/dc:title&gt;&lt;/item&gt;&lt;/DIDL-Lite&gt;')
    r = _post(conn, 'SetAVTransportURI',
              '<InstanceID>0</InstanceID>'
              '<CurrentURI>http://example.com/a.mp4</CurrentURI>'
              '<CurrentURIMetaData>%s</CurrentURIMetaData>' % meta)
    assert r.status == 200, 'SetAVTransportURI 状态 %d' % r.status
    print('[OK] SetAVTransportURI -> 200')

    r = _post(conn, 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')
    assert r.status == 200, 'Play 状态 %d' % r.status
    time.sleep(0.2)
    print('[OK] Play -> 200')

    assert events and events[0][0] == 'play', '未触发播放回调: %r' % events
    assert events[0][2] == '测试片', '标题解析错误: %r' % events[0][2]
    print('[OK] 播放回调触发，标题=%s' % events[0][2])

    r = _post(conn, 'GetTransportInfo', '<InstanceID>0</InstanceID>')
    body = r.read().decode()
    assert 'PLAYING' in body, '状态未 PLAYING: %s' % body
    print('[OK] GetTransportInfo -> PLAYING')

    r = _post(conn, 'Stop', '<InstanceID>0</InstanceID>')
    assert r.status == 200
    time.sleep(0.1)
    assert ('stop',) in events, '未触发停止回调'
    print('[OK] Stop 回调触发')

    stack.stop()
    print('\n全部 DLNA 内核测试通过')


if __name__ == '__main__':
    main()
