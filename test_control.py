# -*- coding: utf-8 -*-
"""双向控制与状态回传回归测试。

覆盖本轮新增的 5 项能力：
  1) GENA 事件订阅 + 状态回推（手机能看到电脑端 暂停/继续/停止）
  2) 手机 Pause/Play SOAP -> 播放器回调真的被触发
  3) 手机拖动进度条 Seek -> 解析成毫秒并回调
  4) GetPositionInfo 返回真实进度（手机进度条会动）
  5) 电视模式：device.xml 型号变更 + Sink 声明 HD/4K + 立即重新宣告
"""
import http.server
import socketserver
import sys
import threading
import time
import urllib.request

from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState

PORT = 8311
received = []          # 收到的 NOTIFY 事件体
fired = {}             # 各回调是否触发


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """模拟手机端的 GENA 事件接收端点。"""

    def log_message(self, fmt, *args):
        pass

    def do_NOTIFY(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(n).decode('utf-8', 'ignore') if n else ''
        received.append(body)
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()


def free_port():
    s = socketserver.TCPServer(('127.0.0.1', 0), CallbackHandler)
    p = s.server_address[1]
    s.server_close()
    return p


def soap_post(port, service, action, args=''):
    body = ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><u:%s xmlns:u="urn:schemas-upnp-org:service:%s:1">%s</u:%s>'
            '</s:Body></s:Envelope>' % (action, service, args, action))
    req = urllib.request.Request(
        'http://127.0.0.1:%d/upnp/control/%s' % (port, service),
        data=body.encode('utf-8'),
        headers={'Content-Type': 'text/xml; charset="utf-8"',
                 'SOAPACTION': '"urn:schemas-upnp-org:service:%s:1#%s"' % (service, action)})
    return urllib.request.urlopen(req, timeout=5).read().decode('utf-8', 'ignore')


def subscribe(port, service, callback, sid=None):
    """原始 SUBSCRIBE（urllib 不支持）。sid 非空时模拟"续订"请求。"""
    import socket
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    head = ('SUBSCRIBE /upnp/event/%s HTTP/1.1\r\n'
            'HOST: 127.0.0.1:%d\r\n' % (service, port))
    if sid:
        head += 'SID: %s\r\n' % sid
    else:
        head += ('CALLBACK: <%s>\r\nNT: upnp:event\r\n' % callback)
    head += 'TIMEOUT: Second-1800\r\nContent-Length: 0\r\n\r\n'
    s.sendall(head.encode())
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return data.decode('utf-8', 'ignore')


def main():
    cb_port = free_port()
    httpd = socketserver.TCPServer(('127.0.0.1', cb_port), CallbackHandler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    state = RendererState()
    state.on_pause = lambda: fired.__setitem__('pause', True)
    state.on_resume = lambda: fired.__setitem__('resume', True)
    state.on_seek = lambda ms: fired.__setitem__('seek', ms)
    state.position_provider = lambda: (65000, 600000)
    state.on_play = lambda uri, t: fired.__setitem__('play', uri)

    logs = []
    stack = DlnaStack('127.0.0.1', PORT, 'CtrlTest', state, log=logs.append)
    stack.start()
    time.sleep(0.3)

    ok = True

    def check(name, cond, extra=''):
        nonlocal ok
        print('     %-42s %s %s' % (name, 'PASS' if cond else 'FAIL', extra))
        if not cond:
            ok = False

    print('[1] GENA 事件订阅')
    resp = subscribe(PORT, 'AVTransport', 'http://127.0.0.1:%d/cb' % cb_port)
    check('SUBSCRIBE 返回 200 + SID', '200' in resp and 'SID' in resp.upper(),
          resp.splitlines()[0] if resp else '')
    time.sleep(0.4)
    check('订阅后收到 SEQ=0 初始事件', len(received) >= 1, '收到 %d 条' % len(received))

    # 续订：手机在超时前会带 SID 再 SUBSCRIBE 一次，必须回 200 而不是 412，
    # 否则 1800s 后订阅失效、手机上状态再也不更新。
    import re as _re
    m = _re.search(r'SID:\s*(\S+)', resp, _re.I)
    sid = m.group(1) if m else ''
    renew = subscribe(PORT, 'AVTransport', None, sid=sid)
    check('订阅续订(带SID)返回 200', '200' in renew and sid[:8] in renew,
          renew.splitlines()[0] if renew else '')

    print('[2] 电脑端状态变化 -> 回推手机')
    received.clear()
    state.set_transport('PAUSED_PLAYBACK')
    time.sleep(0.5)
    hit = any('PAUSED_PLAYBACK' in b for b in received)
    check('暂停状态已推给手机(TransportState)', hit,
          ('最近事件: %s' % received[-1][:120]) if received else '未收到任何事件')

    received.clear()
    state.set_transport('PLAYING')
    time.sleep(0.5)
    check('继续播放状态已推给手机', any('PLAYING' in b for b in received))

    print('[3] 手机端 SOAP 指令 -> 播放器回调')
    soap_post(PORT, 'AVTransport', 'SetAVTransportURI',
              '<InstanceID>0</InstanceID><CurrentURI>http://x/a.mp4</CurrentURI>'
              '<CurrentURIMetaData>&lt;dc:title&gt;测试&lt;/dc:title&gt;</CurrentURIMetaData>')
    soap_post(PORT, 'AVTransport', 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')
    check('Play -> 播放回调触发', fired.get('play') == 'http://x/a.mp4')
    soap_post(PORT, 'AVTransport', 'Pause', '<InstanceID>0</InstanceID>')
    check('Pause -> 暂停回调触发', fired.get('pause') is True)
    soap_post(PORT, 'AVTransport', 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')
    check('Play(继续) -> 继续回调触发', fired.get('resume') is True)

    print('[4] 拖动进度条 Seek')
    soap_post(PORT, 'AVTransport', 'Seek',
              '<InstanceID>0</InstanceID><Unit>REL_TIME</Unit><Target>00:01:30</Target>')
    check('Seek 00:01:30 解析为 90000ms 并回调', fired.get('seek') == 90000,
          '实际=%s' % fired.get('seek'))

    print('[5] GetPositionInfo 返回真实进度')
    out = soap_post(PORT, 'AVTransport', 'GetPositionInfo', '<InstanceID>0</InstanceID>')
    check('RelTime=00:01:05(65s)', '<RelTime>00:01:05</RelTime>' in out, out[:160])
    check('TrackDuration=00:10:00(600s)', '<TrackDuration>00:10:00</TrackDuration>' in out)

    print('[6] 电视模式（争取更高码率）')
    xml = urllib.request.urlopen(
        'http://127.0.0.1:%d/device.xml' % PORT, timeout=5).read().decode('utf-8')
    check('默认型号=CastReceiver', '<modelName>CastReceiver</modelName>' in xml)
    before = soap_post(PORT, 'ConnectionManager', 'GetProtocolInfo', '')
    stack.set_tv_mode(True)
    time.sleep(0.2)
    xml2 = urllib.request.urlopen(
        'http://127.0.0.1:%d/device.xml' % PORT, timeout=5).read().decode('utf-8')
    check('电视模式型号变为 4K Smart TV', '4K Smart TV' in xml2)
    after = soap_post(PORT, 'ConnectionManager', 'GetProtocolInfo', '')
    check('Sink 新增 HD/4K 声明', 'AVC_MP4_HP_HD_AAC' in after and 'HEVC_MP4_UHD' in after)
    check('SCPD/基础格式未被破坏', 'video/mp4' in after and len(after) > len(before))
    stack.set_tv_mode(False)
    time.sleep(0.2)
    xml3 = urllib.request.urlopen(
        'http://127.0.0.1:%d/device.xml' % PORT, timeout=5).read().decode('utf-8')
    check('可切回标准模式', 'CastReceiver' in xml3)

    stack.stop()
    httpd.shutdown()
    print('\n%s' % ('全部控制/回传测试通过' if ok else '存在失败项，见上'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
