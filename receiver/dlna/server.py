import base64
import http.server
import re
import socketserver
import threading
import urllib.request
import uuid as _uuid
from xml.sax.saxutils import escape

from . import device
from . import services
from . import ssdp

# 最小的 1x1 透明 PNG（设备图标兜底，DLNA 控制点不展示也无关紧要）
ICON_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

# 每个服务的动作 + 参数 + 状态变量。
# argumentList 必须是真的：早期版本是空壳，严格控制点拉完 SCPD 会判设备不可用，
# 直接不进投屏列表（"连上了却不显示设备"多半是这个）。
SERVICE_SPECS = {
    'ConnectionManager': {
        'actions': [
            ('GetProtocolInfo', [('Source', 'out', 'SourceProtocolInfo'),
                                 ('Sink', 'out', 'SinkProtocolInfo')]),
            ('GetCurrentConnectionIDs', [('ConnectionIDs', 'out', 'CurrentConnectionIDs')]),
            ('GetCurrentConnectionInfo',
             [('ConnectionID', 'in', 'A_ARG_TYPE_ConnectionID'),
              ('RcsID', 'out', 'A_ARG_TYPE_RcsID'),
              ('AVTransportID', 'out', 'A_ARG_TYPE_AVTransportID'),
              ('ProtocolInfo', 'out', 'A_ARG_TYPE_ProtocolInfo'),
              ('PeerConnectionManager', 'out', 'A_ARG_TYPE_ConnectionManager'),
              ('PeerConnectionID', 'out', 'A_ARG_TYPE_ConnectionID'),
              ('Direction', 'out', 'A_ARG_TYPE_Direction'),
              ('Status', 'out', 'A_ARG_TYPE_ConnectionStatus')]),
        ],
        'state_vars': [('SourceProtocolInfo', 'string'), ('SinkProtocolInfo', 'string'),
                       ('CurrentConnectionIDs', 'string'),
                       ('A_ARG_TYPE_ConnectionID', 'i4'), ('A_ARG_TYPE_RcsID', 'i4'),
                       ('A_ARG_TYPE_AVTransportID', 'i4'),
                       ('A_ARG_TYPE_ProtocolInfo', 'string'),
                       ('A_ARG_TYPE_ConnectionManager', 'string'),
                       ('A_ARG_TYPE_Direction', 'string'),
                       ('A_ARG_TYPE_ConnectionStatus', 'string')],
    },
    'AVTransport': {
        'actions': [
            ('SetAVTransportURI', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                   ('CurrentURI', 'in', 'AVTransportURI'),
                                   ('CurrentURIMetaData', 'in', 'AVTransportURIMetaData')]),
            ('Play', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                      ('Speed', 'in', 'TransportPlaySpeed')]),
            ('Pause', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID')]),
            ('Stop', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID')]),
            ('Seek', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                      ('Unit', 'in', 'A_ARG_TYPE_SeekMode'),
                      ('Target', 'in', 'A_ARG_TYPE_SeekTarget')]),
            ('SetPlayMode', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('NewPlayMode', 'in', 'CurrentPlayMode')]),
            ('GetTransportInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                  ('CurrentTransportState', 'out', 'TransportState'),
                                  ('CurrentTransportStatus', 'out', 'TransportStatus'),
                                  ('CurrentSpeed', 'out', 'TransportPlaySpeed')]),
            ('GetPositionInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                 ('Track', 'out', 'CurrentTrack'),
                                 ('TrackDuration', 'out', 'CurrentTrackDuration'),
                                 ('TrackMetaData', 'out', 'CurrentTrackMetaData'),
                                 ('TrackURI', 'out', 'CurrentTrackURI'),
                                 ('RelTime', 'out', 'RelativeTimePosition'),
                                 ('AbsTime', 'out', 'AbsoluteTimePosition'),
                                 ('RelCount', 'out', 'RelativeCounterPosition'),
                                 ('AbsCount', 'out', 'AbsoluteCounterPosition')]),
            ('GetMediaInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                              ('NrTracks', 'out', 'NumberOfTracks'),
                              ('MediaDuration', 'out', 'CurrentMediaDuration'),
                              ('CurrentURI', 'out', 'AVTransportURI'),
                              ('CurrentURIMetaData', 'out', 'AVTransportURIMetaData'),
                              ('NextURI', 'out', 'NextAVTransportURI'),
                              ('NextURIMetaData', 'out', 'NextAVTransportURIMetaData'),
                              ('PlayMedium', 'out', 'PlaybackStorageMedium'),
                              ('RecordMedium', 'out', 'RecordStorageMedium'),
                              ('WriteStatus', 'out', 'RecordMediumWriteStatus')]),
            ('GetDeviceCapabilities', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                       ('PlayMedia', 'out', 'PossiblePlaybackStorageMedia'),
                                       ('RecMedia', 'out', 'PossibleRecordStorageMedia'),
                                       ('RecQualityModes', 'out', 'PossibleRecordQualityModes')]),
            ('GetTransportSettings', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                      ('PlayMode', 'out', 'CurrentPlayMode'),
                                      ('RecQualityMode', 'out', 'CurrentRecordQualityMode')]),
        ],
        'state_vars': [('TransportState', 'string'), ('TransportStatus', 'string'),
                       ('TransportPlaySpeed', 'string'), ('CurrentPlayMode', 'string'),
                       ('CurrentRecordQualityMode', 'string'), ('NumberOfTracks', 'ui4'),
                       ('CurrentTrack', 'ui4'), ('CurrentTrackDuration', 'string'),
                       ('CurrentMediaDuration', 'string'), ('CurrentTrackMetaData', 'string'),
                       ('CurrentTrackURI', 'string'), ('AVTransportURI', 'string'),
                       ('AVTransportURIMetaData', 'string'), ('NextAVTransportURI', 'string'),
                       ('NextAVTransportURIMetaData', 'string'),
                       ('RelativeTimePosition', 'string'), ('AbsoluteTimePosition', 'string'),
                       ('RelativeCounterPosition', 'i4'), ('AbsoluteCounterPosition', 'i4'),
                       ('PlaybackStorageMedium', 'string'), ('RecordStorageMedium', 'string'),
                       ('RecordMediumWriteStatus', 'string'),
                       ('PossiblePlaybackStorageMedia', 'string'),
                       ('PossibleRecordStorageMedia', 'string'),
                       ('PossibleRecordQualityModes', 'string'),
                       ('A_ARG_TYPE_InstanceID', 'ui4'), ('A_ARG_TYPE_SeekMode', 'string'),
                       ('A_ARG_TYPE_SeekTarget', 'string')],
    },
    'RenderingControl': {
        'actions': [
            ('GetVolume', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                           ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                           ('CurrentVolume', 'out', 'Volume')]),
            ('SetVolume', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                           ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                           ('DesiredVolume', 'in', 'Volume')]),
            ('GetMute', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                         ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                         ('CurrentMute', 'out', 'Mute')]),
            ('SetMute', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                         ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                         ('DesiredMute', 'in', 'Mute')]),
            ('GetVolumeDB', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                             ('CurrentVolume', 'out', 'VolumeDB')]),
            ('SetVolumeDB', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                             ('DesiredVolume', 'in', 'VolumeDB')]),
        ],
        'state_vars': [('Volume', 'ui2'), ('Mute', 'boolean'), ('VolumeDB', 'i2'),
                       ('A_ARG_TYPE_InstanceID', 'ui4'), ('A_ARG_TYPE_Channel', 'string')],
    },
}


def _build_scpd(service):
    """按服务规范生成带完整参数与状态变量的 SCPD XML。"""
    spec = SERVICE_SPECS[service]
    actions = []
    for name, args in spec['actions']:
        if args:
            arg_xml = ''.join(
                '<argument><name>%s</name><direction>%s</direction>'
                '<relatedStateVariable>%s</relatedStateVariable></argument>'
                % (n, d, sv) for n, d, sv in args)
            actions.append('<action><name>%s</name><argumentList>%s</argumentList></action>'
                           % (name, arg_xml))
        else:
            actions.append('<action><name>%s</name><argumentList/></action>' % name)
    state_vars = ''.join(
        '<stateVariable sendEvents="no"><name>%s</name><dataType>%s</dataType></stateVariable>'
        % (n, t) for n, t in spec['state_vars'])
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<scpd xmlns="urn:schemas-upnp-org:service-1-0">'
            '<specVersion><major>1</major><minor>0</minor></specVersion>'
            '<actionList>%s</actionList>'
            '<serviceStateTable>%s</serviceStateTable>'
            '</scpd>' % (''.join(actions), state_vars))


SCPD = {svc: _build_scpd(svc) for svc in SERVICE_SPECS}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 记录 IP + UA，看到 [HTTP] 手机IP GET /device.xml 200 就说明发现成功
        try:
            ip = self.client_address[0] if self.client_address else '?'
            self.server.log('[HTTP] %s %s' % (ip, fmt % args))
        except Exception:
            pass

    def _send(self, code, body, content_type='text/xml; charset="utf-8"', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Server', 'SenAICastReceiver/1.0')
        self.send_header('Cache-Control', 'no-cache')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        ip = self.client_address[0] if self.client_address else '?'
        ua = self.headers.get('User-Agent', '') if self.headers else ''
        # 不同 App 的 UPnP 栈对状态机取值要求不一样，按 UA 自适应
        # （见 services.RendererState.detect_control_point）
        try:
            self.server.state.detect_control_point(ua)
        except Exception:
            pass
        # 详细诊断：手机每次拉取都记录 IP + UA；device.xml 额外记录完整请求头
        if self.path == '/device.xml':
            self.server.log('[HTTP] %s GET /device.xml (User-Agent: %s)' % (ip, ua))
            if not getattr(self.server, '_diag_http_dumped', False):
                self.server._diag_http_dumped = True
                hdr = '\n'.join('%s: %s' % (k, v) for k, v in self.headers.items())
                self.server.log('[HTTP][诊断] /device.xml 完整请求头:\n%s' % hdr)
            self._send(200, device.device_description(
                self.server.app_ip, self.server.app_port, self.server.app_name,
                tv_mode=getattr(self.server, 'tv_mode', False)))
            return
        if self.path.startswith('/upnp/scpd/'):
            for key, xml in SCPD.items():
                if key in self.path:
                    self._send(200, xml)
                    return
            self._send(404, '<error>no scpd</error>')
            return
        if self.path == '/icon.png':
            self._send(200, ICON_PNG, content_type='image/png')
            return
        self._send(404, '<error>not found</error>')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(length) if length else b''
        if self.path.startswith('/upnp/control/'):
            # 按 UA 选状态机策略
            try:
                if self.server.state.detect_control_point(
                        self.headers.get('User-Agent', '')):
                    self.server.log(
                        '[兼容] 识别控制点: %s -> %s'
                        % (self.server.state.control_point,
                           '标准状态机(含 TRANSITIONING)'
                           if self.server.state.use_transitioning
                           else '三态(STOPPED/PLAYING/PAUSED_PLAYBACK)'))
            except Exception:
                pass
            action, params = services.parse_soap(body)
            if action is None:
                self._send(500, services._soap_fault('Client', 'Bad SOAP'), extra={'EXT': ''})
                return
            code, resp, _ = self.server.state.handle(self.path, action, params)
            self._send(code, resp, extra={'EXT': ''})
            summary = params.get('CurrentURI', '')[:90]
            self.server.log('[DLNA] 收到指令 %s %s' % (action, summary))
            return
        self._send(404, '<error>not found</error>')

    def do_SUBSCRIBE(self):
        """记下手机的 CALLBACK 地址，之后状态变化往这儿推。

        以前只回 200+SID 从不推事件，手机永远看不到电脑端的播放状态。
        """
        service = self._service_from_path(self.path)
        cb = self.headers.get('CALLBACK', '') or ''
        timeout_hdr = self.headers.get('TIMEOUT', '') or 'Second-1800'
        # 续订：控制点超时前会带 SID 再 SUBSCRIBE（这次没有 CALLBACK）。
        # 回 412 的话订阅会在 1800s 后失效，表现为投屏看久了手机状态就不更新了。
        sid_hdr = self.headers.get('SID', '') or ''
        notifier = getattr(self.server, 'notifier', None)
        if sid_hdr and notifier is not None:
            if sid_hdr in notifier._subs:
                notifier.refresh(sid_hdr, timeout_hdr)
                self._send(200, '', extra={'SID': sid_hdr, 'TIMEOUT': timeout_hdr,
                                           'SERVER': ssdp.SERVER_STR})
                self.server.log('[DLNA] 事件订阅续订 SID=%s...' % sid_hdr[:20])
                return
            self._send(412, '', extra={'SID': '', 'TIMEOUT': timeout_hdr})
            return
        m = re.search(r'<(http://[^>]+)>', cb)
        if not m or not service:
            self._send(412, '', extra={'SID': '', 'TIMEOUT': timeout_hdr})
            return
        callback = m.group(1)
        sid = self.server.notifier.subscribe(service, callback, timeout_hdr)
        self._send(200, '', extra={
            'SID': sid, 'TIMEOUT': timeout_hdr, 'SERVER': ssdp.SERVER_STR})
        self.server.log('[DLNA] 事件订阅 %s <- %s (SID=%s)'
                        % (service.split(':')[-2] if ':' in service else service,
                           callback, sid[:20] + '...'))
        # SEQ=0 初始事件：推送当前完整状态（GENA 规范要求）
        self.server.notifier.push_initial(service)

    def do_UNSUBSCRIBE(self):
        sid = self.headers.get('SID', '') or ''
        if sid:
            self.server.notifier.unsubscribe(sid)
        self._send(200, '')

    @staticmethod
    def _service_from_path(path):
        if 'AVTransport' in path:
            return 'AVTransport'
        if 'RenderingControl' in path:
            return 'RenderingControl'
        if 'ConnectionManager' in path:
            return 'ConnectionManager'
        return None

    def do_NOTIFY(self):
        # 控制点推送状态事件，直接确认即可
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length:
            try:
                self.rfile.read(length)
            except Exception:
                pass
        self._send(200, '')


class _NotifyRequest(urllib.request.Request):
    """事件必须用 NOTIFY 发。

    urllib 一带 data 就自动走 POST，而 UPnP 规范要求 NOTIFY；
    实测控制点收到 POST 直接回 501 丢事件 —— "状态推不回手机"就栽在这。
    """

    def get_method(self):
        return 'NOTIFY'


class EventNotifier:
    """状态变化时向所有订阅者推 LastChange。

    手机发 Pause/Play/Stop -> 我们执行 -> set_transport 触发 -> 这里 NOTIFY 出去。
    电脑端 GUI 的暂停/继续/停止走同一条路。
    """

    def __init__(self, state, log=print):
        self.state = state
        self.log = log
        self._subs = {}   # sid -> (service, callback_url, timeout)
        self._seq = {}    # sid -> int
        # 关掉系统代理：CALLBACK 是局域网手机，走代理会被 sing-tun 之类劫持
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))

    def subscribe(self, service, callback, timeout):
        sid = 'uuid:%s' % _uuid.uuid4()
        self._subs[sid] = (service, callback, timeout)
        self._seq[sid] = 0
        return sid

    def unsubscribe(self, sid):
        self._subs.pop(sid, None)
        self._seq.pop(sid, None)

    def refresh(self, sid, timeout):
        """订阅续订：更新超时（并防止因字典被替换导致续订丢失）。"""
        if sid in self._subs:
            svc, cb, _old = self._subs[sid]
            self._subs[sid] = (svc, cb, timeout)

    def _lastchange_body(self, service, props):
        ns = 'urn:schemas-upnp-org:metadata-1-0/%s/' % service
        inner = ''.join('<%s val="%s"/>' % (k, escape(str(v)))
                        for k, v in props.items())
        last = ('<Event xmlns="%s"><InstanceID val="0">%s</InstanceID></Event>'
                % (ns, inner))
        return ('<?xml version="1.0" encoding="utf-8"?>'
                '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
                '<e:property><LastChange>%s</LastChange></e:property>'
                '</e:propertyset>' % escape(last))

    def push_initial(self, service):
        """订阅建立后的 SEQ=0 初始事件。"""
        if service == 'AVTransport':
            props = {'TransportState': self.state.transport_state,
                     'TransportStatus': 'OK',
                     'CurrentTrackURI': self.state.current_uri,
                     'NumberOfTracks': '1'}
        elif service == 'RenderingControl':
            props = {'Volume': str(self.state.volume),
                     'Mute': str(self.state.mute)}
        else:
            return
        self._post(service, props, initial=True)

    def notify_state(self, state=None):
        """传输状态变化回调：向 AVTransport 订阅者推送新状态。"""
        st = state or self.state
        self._post('AVTransport',
                   {'TransportState': st.transport_state,
                    'TransportStatus': 'OK',
                    'CurrentTrackURI': st.current_uri})

    def notify_volume(self, state=None):
        """音量/静音变化回调：向 RenderingControl 订阅者推送。"""
        st = state or self.state
        self._post('RenderingControl',
                   {'Volume': str(st.volume), 'Mute': str(st.mute)})

    def _post(self, service, props, initial=False):
        if not self._subs:
            return
        body = self._lastchange_body(service, props)
        threading.Thread(target=self._post_async,
                         args=(service, body, initial), daemon=True).start()

    def _post_async(self, service, body, initial):
        for sid, (svc, callback, _to) in list(self._subs.items()):
            if svc != service:
                continue
            seq = self._seq.get(sid, 0)
            if not initial:
                self._seq[sid] = seq + 1
            req = _NotifyRequest(
                callback, data=body.encode('utf-8'),
                headers={'Content-Type': 'text/xml; charset="utf-8"',
                         'NT': 'upnp:event', 'NTS': 'upnp:propchange',
                         'SID': sid, 'SEQ': str(seq)})
            try:
                self._opener.open(req, timeout=3).read()
                self.log('[事件] 已推送 %s -> %s (SEQ=%d)'
                         % (service, callback, seq))
            except Exception as e:
                self.log('[事件] 推送失败 %s: %s' % (callback, e))


class DlnaServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DlnaStack:
    """把 HTTP 控制服务与 SSDP 发现打包成一个可启动/停止的栈。"""

    def __init__(self, ip, port, name, state, log=print):
        self.ip = ip
        self.port = port
        self.name = name
        self.state = state
        self.log = log
        self.http = DlnaServer(('0.0.0.0', port), _Handler)
        self.http.app_ip = ip
        self.http.app_port = port
        self.http.app_name = name
        self.http.state = state
        self.http.log = log
        # 电视模式：把型号报成 4K 电视，争取更高码率（成不成看 App）
        self.tv_mode = False
        self.http.tv_mode = False
        self.ssdp = ssdp.SSDPServer(ip, port, name, log=log)
        self.notifier = EventNotifier(state, log=log)
        # 得挂到 http server 上：do_SUBSCRIBE 走 self.server.notifier，
        # 漏了这行手机一订阅就 AttributeError
        self.http.notifier = self.notifier
        state.on_transport_change = self._on_transport_change
        state.on_volume_change = self._on_volume_change
        self._thread = None

    def _on_transport_change(self, state):
        try:
            self.notifier.notify_state(state)
        except Exception:
            pass

    def _on_volume_change(self, state):
        try:
            self.notifier.notify_volume(state)
        except Exception:
            pass

    def set_tv_mode(self, on):
        """切换电视模式：改设备描述中的型号标识 + 立即重新宣告，让手机重新协商。"""
        self.tv_mode = bool(on)
        self.http.tv_mode = bool(on)
        try:
            self.state.tv_mode = bool(on)
        except Exception:
            pass
        try:
            self.ssdp.announce()
        except Exception:
            pass
        return self.tv_mode

    def start(self):
        self._thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self._thread.start()
        self.ssdp.start()
        self.log('[DLNA] 控制服务已启动: http://%s:%d/device.xml' % (self.ip, self.port))

    def stop(self):
        try:
            # 仅当真正启动过 serve_forever 才 shutdown：未启动时 shutdown() 会
            # 永久阻塞在 __is_shut_down.wait()（该事件只有 serve_forever 退出时才设置），
            # 会让程序卡死。初始那个只 bind 未启动的 stack 就属于这种情况。
            if self._thread is not None:
                self.http.shutdown()
        except Exception:
            pass
        try:
            # 关键：必须真正关闭监听 socket，否则旧 socket 会一直占着 8200，
            # 与新 stack 形成"双监听"（Windows SO_REUSEADDR 不报错），
            # 手机连接被分给无人 accept 的旧 socket -> 永远收不到响应。
            self.http.server_close()
        except Exception:
            pass
        self._thread = None
        self.ssdp.shutdown()
