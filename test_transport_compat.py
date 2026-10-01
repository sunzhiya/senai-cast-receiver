# -*- coding: utf-8 -*-
"""针对 Dart 系控制点的状态机兼容性测试。

这类控制点（Flutter 应用常用开源 Dart UPnP 库）与部分自研 UPnP 栈
在状态枚举上不一致，需要用它们常见的 User-Agent 单独覆盖：

  - 只搜 ST: upnp:rootdevice，按 serviceId 定位服务，解析 device.xml
  - 动作只用 SetAVTransportURI / GetPositionInfo / Stop 三个，
    不订阅 RenderingControl / ConnectionManager
  - 进度只解析 RelTime（不读 TrackDuration）
  - 状态枚举只认 STOPPED / PLAYING / PAUSED_PLAYBACK，不认 TRANSITIONING
  - 靠 GENA 事件（LastChange 里的 <TransportState>）判断状态，不轮询

因此接收端要按 UA 走三态；下面验证这条路径，外加非 Dart UA
仍按标准回 TRANSITIONING 的对照。
"""
import http.server
import socketserver
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, '.')

from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState

PORT = 8312
BASE = 'http://127.0.0.1:%d' % PORT
# 这类控制点常见的 User-Agent
DART_UA = 'Dart/3.6 (dart:io)'
NS = '{urn:schemas-upnp-org:device-1-0}'
SNS = '{urn:schemas-upnp-org:service-1-0}'

events = []


class CbHandler(http.server.BaseHTTPRequestHandler):
    """模拟手机端 GENA 接收端点。"""

    def log_message(self, *a):
        pass

    def do_NOTIFY(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        events.append(self.rfile.read(n).decode('utf-8', 'ignore') if n else '')
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()


def get(url, ua=DART_UA, timeout=5):
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def soap(service_type, control_url, action, inner='', ua=DART_UA):
    env = ('<?xml version="1.0"?>'
           '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
           '<s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
           % (action, service_type, inner, action))
    req = urllib.request.Request(
        BASE + control_url, data=env.encode('utf-8'),
        headers={'Content-Type': 'text/xml; charset="utf-8"',
                 'User-Agent': ua,
                 'SOAPACTION': '"%s#%s"' % (service_type, action)})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode('utf-8', 'ignore')


def main():
    cb = socketserver.TCPServer(('127.0.0.1', 0), CbHandler)
    cb.allow_reuse_address = True
    cb_port = cb.server_address[1]
    threading.Thread(target=cb.serve_forever, daemon=True).start()

    state = RendererState()
    state.position_provider = lambda: (75000, 900000)
    stack = DlnaStack('127.0.0.1', PORT, 'JiongTest', state, log=lambda m: None)
    stack.start()
    ok = True

    def check(name, cond, extra=''):
        nonlocal ok
        print('     %-46s %s %s' % (name, 'PASS' if cond else 'FAIL', extra))
        if not cond:
            ok = False

    try:
        print('[1] device.xml（Dart UA）解析所需字段')
        root = ET.fromstring(get(BASE + '/device.xml'))
        dev = root.find(NS + 'device')
        check('deviceType = MediaRenderer:1',
              dev.find(NS + 'deviceType').text ==
              'urn:schemas-upnp-org:device:MediaRenderer:1')
        for f in ('friendlyName', 'modelName'):
            check('含 %s' % f, dev.find(NS + f) is not None)
        svcs = {}
        for s in dev.find(NS + 'serviceList'):
            svcs[s.find(NS + 'serviceId').text] = {
                'type': s.find(NS + 'serviceType').text,
                'control': s.find(NS + 'controlURL').text,
                'event': s.find(NS + 'eventSubURL').text,
                'scpd': s.find(NS + 'SCPDURL').text,
            }
        av_id = 'urn:upnp-org:serviceId:AVTransport'
        check('按 serviceId 能定位到 AVTransport（它唯一的入口）', av_id in svcs)
        av = svcs[av_id]
        check('AVTransport 有 controlURL/eventSubURL/SCPDURL',
              all(av[k] for k in ('control', 'event', 'scpd')))

        print('[2] SCPD（Dart 控制点会下载并解析动作列表）')
        scpd = ET.fromstring(get(BASE + av['scpd']))
        acts = [a.find(SNS + 'name').text for a in scpd.find(SNS + 'actionList')]
        for need in ('SetAVTransportURI', 'GetPositionInfo', 'Stop', 'Play', 'Pause'):
            check('SCPD 含 %s' % need, need in acts)

        print('[3] GetPositionInfo -> 只解析 RelTime')
        out = soap(av['type'], av['control'], 'GetPositionInfo', '<InstanceID>0</InstanceID>')
        vals = {}
        for el in ET.fromstring(out).iter():
            vals[el.tag.split('}')[-1]] = el.text
        check('RelTime = 00:01:15（真实进度 75s）', vals.get('RelTime') == '00:01:15',
              str(vals.get('RelTime')))

        print('[4] 状态机：绝不能回 TRANSITIONING（其枚举只有三值）')
        soap(av['type'], av['control'], 'SetAVTransportURI',
             '<InstanceID>0</InstanceID><CurrentURI>http://x/v.mp4</CurrentURI>'
             '<CurrentURIMetaData></CurrentURIMetaData>')
        st = state.transport_state
        check('SetAVTransportURI 后 = STOPPED（非 TRANSITIONING）', st == 'STOPPED', st)
        check('已识别控制点为 Dart', state.use_transitioning is False,
              state.control_point)

        def tstate():
            r = soap(av['type'], av['control'], 'GetTransportInfo', '<InstanceID>0</InstanceID>')
            d = {}
            for el in ET.fromstring(r).iter():
                d[el.tag.split('}')[-1]] = el.text
            return d.get('CurrentTransportState')

        soap(av['type'], av['control'], 'Play', '<InstanceID>0</InstanceID><Speed>1</Speed>')
        check('Play 后 = PLAYING', tstate() == 'PLAYING')
        soap(av['type'], av['control'], 'Pause', '<InstanceID>0</InstanceID>')
        check('Pause 后 = PAUSED_PLAYBACK', tstate() == 'PAUSED_PLAYBACK')
        soap(av['type'], av['control'], 'Stop', '<InstanceID>0</InstanceID>')
        check('Stop 后 = STOPPED', tstate() == 'STOPPED')

        print('[5] GENA 事件：它靠事件而非轮询判断状态')
        import socket as _s
        sk = _s.create_connection(('127.0.0.1', PORT), timeout=5)
        sk.sendall(('SUBSCRIBE %s HTTP/1.1\r\nHOST: 127.0.0.1:%d\r\n'
                    'CALLBACK: <http://127.0.0.1:%d/cb>\r\nNT: upnp:event\r\n'
                    'TIMEOUT: Second-1800\r\nUser-Agent: %s\r\n'
                    'Content-Length: 0\r\n\r\n'
                    % (av['event'], PORT, cb_port, DART_UA)).encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            c = sk.recv(4096)
            if not c:
                break
            buf += c
        sk.close()
        check('SUBSCRIBE 回 200 + SID', b'200' in buf and b'SID' in buf.upper(),
              buf.decode('utf-8', 'ignore').splitlines()[0])
        time.sleep(0.5)
        check('收到 SEQ=0 初始事件', len(events) >= 1, '收到 %d 条' % len(events))

        events.clear()
        state.set_transport('PLAYING')
        time.sleep(0.6)
        # Dart 控制点解析的是 LastChange 解包后的 <TransportState val="..."/>
        hit = any('TransportState' in e and 'PLAYING' in e for e in events)
        check('事件体含 <TransportState val="PLAYING"/>', hit,
              (events[-1][:150] if events else '未收到事件'))
        events.clear()
        state.set_transport('PAUSED_PLAYBACK')
        time.sleep(0.6)
        check('暂停事件含 PAUSED_PLAYBACK',
              any('PAUSED_PLAYBACK' in e for e in events))

        print('[6] 对照：非 Dart 控制点仍走标准状态机（含 TRANSITIONING）')
        stack.state.detect_control_point('Ktor client')
        check('非 Dart UA -> 启用 TRANSITIONING', state.use_transitioning is True)
        soap(av['type'], av['control'], 'SetAVTransportURI',
             '<InstanceID>0</InstanceID><CurrentURI>http://x/v2.mp4</CurrentURI>'
             '<CurrentURIMetaData></CurrentURIMetaData>', ua='Ktor client')
        check('该控制点下 SetAVTransportURI = TRANSITIONING',
              state.transport_state == 'TRANSITIONING', state.transport_state)

        print('\n%s' % ('Dart 控制点状态机兼容性测试通过'
                        if ok else '存在失败项，见上'))
        return 0 if ok else 1
    finally:
        stack.stop()
        cb.shutdown()


if __name__ == '__main__':
    sys.exit(main())
