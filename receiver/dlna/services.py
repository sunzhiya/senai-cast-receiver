import re
import xml.etree.ElementTree as ET

from . import DEVICE_UUID


def _localname(tag):
    return tag.split('}')[-1]


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def parse_soap(body_bytes):
    try:
        root = ET.fromstring(body_bytes)
    except ET.ParseError:
        return None, {}
    body = None
    for el in root.iter():
        if _localname(el.tag) == 'Body':
            body = el
            break
    if body is None or len(body) == 0:
        return None, {}
    action_el = body[0]
    action = _localname(action_el.tag)
    params = {}
    for child in action_el:
        params[_localname(child.tag)] = child.text or ''
    return action, params


def _soap_response(service_type, action, args):
    inner = ''.join('<%s>%s</%s>' % (k, _esc(v), k) for k, v in args.items())
    return ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body>'
            '<u:%sResponse xmlns:u="%s">%s</u:%sResponse>'
            '</s:Body></s:Envelope>' % (action, service_type, inner, action))


def _soap_fault(code, desc):
    return ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><s:Fault>'
            '<faultcode>s:%s</faultcode>'
            '<faultstring>%s</faultstring>'
            '</s:Fault></s:Body></s:Envelope>' % (code, _esc(desc)))


class RendererState:

    def __init__(self):
        self.transport_state = 'STOPPED'
        self.current_uri = ''
        self.current_title = ''
        self.current_meta = ''
        self.volume = 100
        self.mute = 0
        self.on_play = None
        self.on_stop = None
        self.on_pause = None
        self.on_resume = None
        self.on_volume = None
        self.on_mute = None
        self.on_transport_change = None
        self.on_volume_change = None
        self.on_seek = None
        self.position_provider = None
        self.tv_mode = False
        self.use_transitioning = False
        self.control_point = ''

    def detect_control_point(self, ua):
        ua = (ua or '').strip()
        if not ua:
            return False
        low = ua.lower()
        if self.control_point.lower() == low:
            return False
        self.control_point = ua
        self.use_transitioning = ('dart/' not in low)
        return True

    def set_transport(self, st):
        if self.transport_state != st:
            self.transport_state = st
            if self.on_transport_change:
                try:
                    self.on_transport_change(self)
                except Exception:
                    pass

    def _parse_title(self, meta):
        if not meta:
            return ''
        m = re.search(r'<dc:title>(.*?)</dc:title>', meta, re.S | re.I)
        return m.group(1).strip() if m else ''

    def handle(self, service_path, action, params):
        if 'AVTransport' in service_path:
            return self._av_transport(action, params)
        if 'RenderingControl' in service_path:
            return self._rendering_control(action, params)
        if 'ConnectionManager' in service_path:
            return self._connection_manager(action, params)
        return 404, _soap_fault('Client', 'Unknown service'), {}

    def _fmt_ms(self, ms):
        try:
            ms = int(ms)
        except Exception:
            ms = 0
        if ms < 0:
            ms = 0
        s, msx = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return '%02d:%02d:%02d' % (h, m, s)

    @staticmethod
    def _parse_time(t):
        if not t:
            return 0
        t = str(t).strip()
        try:
            if ':' in t:
                parts = [float(x) for x in t.split(':')]
                sec = 0.0
                for p in parts:
                    sec = sec * 60 + p
                return int(sec * 1000)
            return int(float(t) * 1000)
        except Exception:
            return 0

    def _position(self):
        if self.position_provider is None:
            return 0, 0
        try:
            pos, dur = self.position_provider()
            return int(pos or 0), int(dur or 0)
        except Exception:
            return 0, 0

    def _av_transport(self, action, params):
        st = 'urn:schemas-upnp-org:service:AVTransport:1'
        if action == 'SetAVTransportURI':
            self.current_uri = params.get('CurrentURI', '')
            self.current_meta = params.get('CurrentURIMetaData', '')
            self.current_title = self._parse_title(self.current_meta) or self.current_uri
            self.set_transport('TRANSITIONING' if self.use_transitioning else 'STOPPED')
            return 200, _soap_response(st, action, {}), {}
        if action == 'GetMediaInfo':
            _pos, dur = self._position()
            return 200, _soap_response(st, action, {
                'NrTracks': '1',
                'MediaDuration': self._fmt_ms(dur),
                'CurrentURI': self.current_uri,
                'CurrentURIMetaData': self.current_meta,
                'NextURI': '',
                'NextURIMetaData': '',
                'PlayMedium': 'NONE',
                'RecordMediumWriteStatus': 'NOT_IMPLEMENTED',
            }), {}
        if action == 'GetTransportInfo':
            return 200, _soap_response(st, action, {
                'CurrentTransportState': self.transport_state,
                'CurrentTransportStatus': 'OK',
                'CurrentSpeed': '1',
            }), {}
        if action == 'GetPositionInfo':
            pos, dur = self._position()
            return 200, _soap_response(st, action, {
                'Track': '1',
                'TrackDuration': self._fmt_ms(dur),
                'TrackMetaData': self.current_meta,
                'TrackURI': self.current_uri,
                'RelTime': self._fmt_ms(pos),
                'AbsTime': self._fmt_ms(pos),
                'RelCount': '2147483647',
                'AbsCount': '2147483647',
            }), {}
        if action == 'Play':
            if self.current_uri:
                was_paused = (self.transport_state == 'PAUSED_PLAYBACK')
                self.set_transport('PLAYING')
                if was_paused and self.on_resume:
                    self.on_resume()
                elif self.on_play:
                    self.on_play(self.current_uri, self.current_title)
            return 200, _soap_response(st, action, {}), {}
        if action == 'Pause':
            self.set_transport('PAUSED_PLAYBACK')
            if self.on_pause:
                self.on_pause()
            return 200, _soap_response(st, action, {}), {}
        if action == 'Stop':
            self.set_transport('STOPPED')
            if self.on_stop:
                self.on_stop()
            return 200, _soap_response(st, action, {}), {}
        if action == 'Seek':
            unit = (params.get('Unit') or 'REL_TIME').upper()
            target = params.get('Target', '')
            if unit in ('REL_TIME', 'ABS_TIME'):
                ms = self._parse_time(target)
            else:
                ms = 0
            if ms > 0 and self.on_seek:
                try:
                    self.on_seek(ms)
                except Exception:
                    pass
            return 200, _soap_response(st, action, {}), {}
        if action == 'SetPlayMode':
            return 200, _soap_response(st, action, {}), {}
        if action == 'GetDeviceCapabilities':
            return 200, _soap_response(st, action, {
                'PlayMedia': 'NONE', 'RecMedia': 'NONE', 'RecQualityModes': 'NONE'
            }), {}
        if action == 'GetTransportSettings':
            return 200, _soap_response(st, action, {
                'PlayMode': 'NORMAL', 'RecQualityMode': 'NOT_IMPLEMENTED'
            }), {}
        return 200, _soap_response(st, action, {}), {}

    def _rendering_control(self, action, params):
        st = 'urn:schemas-upnp-org:service:RenderingControl:1'
        if action == 'GetVolume':
            return 200, _soap_response(st, action, {'CurrentVolume': str(self.volume)}), {}
        if action == 'SetVolume':
            try:
                self.volume = int(float(params.get('DesiredVolume', self.volume)))
            except ValueError:
                pass
            if self.on_volume:
                self.on_volume(self.volume)
            if self.on_volume_change:
                try:
                    self.on_volume_change(self)
                except Exception:
                    pass
            return 200, _soap_response(st, action, {}), {}
        if action == 'GetMute':
            return 200, _soap_response(st, action, {'CurrentMute': str(self.mute)}), {}
        if action == 'SetMute':
            self.mute = 1 if params.get('DesiredMute', '').lower() in ('1', 'true', 'yes') else 0
            if self.on_mute:
                self.on_mute(self.mute)
            if self.on_volume_change:
                try:
                    self.on_volume_change(self)
                except Exception:
                    pass
            return 200, _soap_response(st, action, {}), {}
        return 200, _soap_response(st, action, {}), {}

    def _connection_manager(self, action, params):
        st = 'urn:schemas-upnp-org:service:ConnectionManager:1'
        if action == 'GetProtocolInfo':
            sink = (
                'http-get:*:video/mp4:*,'
                'http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_MP_SD_AAC_LTP,'
                'http-get:*:video/mpeg:*,'
                'http-get:*:video/mpeg:DLNA.ORG_PN=MPEG_PS_NTSC,'
                'http-get:*:video/vnd.dlna.mpeg-tts:*,'
                'http-get:*:video/mp2t:*,'
                'http-get:*:video/x-matroska:*,'
                'http-get:*:video/x-msvideo:*,'
                'http-get:*:video/x-ms-wmv:*,'
                'http-get:*:video/x-flv:*,'
                'http-get:*:video/webm:*,'
                'http-get:*:video/quicktime:*,'
                'http-get:*:application/vnd.apple.mpegurl:*,'
                'http-get:*:application/x-mpegURL:*,'
                'http-get:*:application/dash+xml:*,'
                'http-get:*:audio/mpeg:*,'
                'http-get:*:audio/mp4:*,'
                'http-get:*:audio/L16:*,'
                'http-get:*:audio/x-ms-wma:*,'
                'http-get:*:image/jpeg:*,'
                'http-get:*:image/png:*'
            )
            if getattr(self, 'tv_mode', False):
                sink = (
                    'http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_HP_HD_AAC,'
                    'http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_HP_HD_AAC_LTP,'
                    'http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_MP_HD_1080i_AAC,'
                    'http-get:*:video/mp4:DLNA.ORG_PN=HEVC_MP4_UHD_HEVC_AAC,'
                    'http-get:*:video/x-matroska:DLNA.ORG_PN=HEVC_MKV_UHD_HEVC_AAC,'
                    'http-get:*:video/vnd.dlna.mpeg-tts:DLNA.ORG_PN=MPEG_TS_HD_NA,'
                ) + sink
            source = (
                'http-get:*:video/mp4:*,'
                'http-get:*:audio/mpeg:*,'
                'http-get:*:image/jpeg:*'
            )
            return 200, _soap_response(st, action, {'Source': source, 'Sink': sink}), {}
        if action == 'GetCurrentConnectionIDs':
            return 200, _soap_response(st, action, {'ConnectionIDs': '0'}), {}
        if action == 'GetCurrentConnectionInfo':
            return 200, _soap_response(st, action, {
                'RcsID': '0', 'AVTransportID': '0', 'ProtocolInfo': '',
                'PeerConnectionManager': '', 'PeerConnectionID': '-1',
                'Direction': 'Input', 'Status': 'OK',
            }), {}
        return 200, _soap_response(st, action, {}), {}
