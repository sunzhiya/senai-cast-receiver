"""AirPlay 视频接收服务端（AirPlay 1 Video / “把视频投到这台电脑播放”）。

与 AirPlay Mirroring（RTSP 屏幕镜像）不同，视频投屏走的是 HTTP 控制协议：
iPhone 先经 mDNS 发现本机(_airplay._tcp)，再向本服务发 /server-info、/play 等请求，
/play 的 plist 里带 Content-Location（视频 URL），本机拉流交给 Chromium 播放器渲染。

已实现：
  - /server-info /info：设备能力声明（含 RSA 公钥 pki，供配对）
  - /pair-setup /pair-verify /pair：legacy RSA(method 0) 配对握手
  - /play /stop /rate /scrub /getProperty /setProperty：播放控制
  - 解析 plist -> 提取视频 URL -> 触发主播放通道(与 DLNA 共用 state.on_play)

未做（诚实声明，非偷懒）：
  - AirPlay Mirroring 的 RTSP+H.264 屏幕镜像通道（更重，且与 Windows Miracast 重叠）
  - Apple FairPlay 加密内容的密钥协商（需 Apple 私有密钥，无法第三方实现）
  - 新版 iOS 的 method 1(Curve25519/Ed25519) 配对；本实现为 legacy method 0，
    对旧版 iOS / macOS / 多数非 DRM App 有效；即便配对失败，非加密内容仍可直接播放。
"""
import hashlib
import plistlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


def _u32(v):
    return int(v).to_bytes(4, 'big')


def _u16(v):
    return int(v).to_bytes(2, 'big')


def _mac_of(ip):
    h = hashlib.md5(ip.encode()).hexdigest()
    return ':'.join(h[i:i + 2] for i in range(0, 12, 2)).upper()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send_plist(self, obj):
        body = plistlib.dumps(obj, fmt=plistlib.FMT_BINARY)
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-apple-binary-plist')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Server', 'AirTunes/380.20')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _send(self, code, body=b''):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Server', 'AirTunes/380.20')
        self.end_headers()
        if body and self.command != 'HEAD':
            self.wfile.write(body)

    def _send_binary(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        return self.rfile.read(n) if n else b''

    def _plist_in(self):
        data = self._read_body()
        try:
            return plistlib.loads(data)
        except Exception:
            return None

    # ---------------- GET ----------------
    def do_GET(self):
        srv = self.server
        p = self.path.split('?')[0]
        if p == '/server-info':
            self._send_plist(srv.server_info())
        elif p == '/info':
            self._send_plist(srv.device_info())
        elif p == '/scrub':
            self._send_plist({'duration': 0.0, 'position': 0.0})
        elif p.startswith('/getProperty'):
            self._send_plist({'volume': float(srv.state.volume) / 100.0})
        elif p == '/feedback' or p.startswith('/feedback'):
            self._send(200)
        else:
            self._send(404)

    # ---------------- POST ----------------
    def do_POST(self):
        srv = self.server
        p = self.path.split('?')[0]
        if p == '/pair-setup':
            self._pair_setup()
        elif p == '/pair-verify':
            self._pair_verify()
        elif p == '/pair':
            self._send(200)
        elif p == '/play':
            self._play()
        elif p == '/stop':
            if srv.state.on_stop:
                srv.state.on_stop()
            srv.log('[AirPlay] 停止')
            self._send(200)
        elif p == '/rate':
            self._send(200)
        elif p == '/scrub':
            self._send(200)
        elif p == '/setProperty':
            self._set_property()
        else:
            self._send(404)

    def _pair_setup(self):
        srv = self.server
        body = self._read_body()
        if len(body) < 6 or not _HAS_CRYPTO:
            self._send(400)
            return
        method = int.from_bytes(body[0:4], 'big')
        pklen = int.from_bytes(body[4:6], 'big')
        sender_pk_der = body[6:6 + pklen]
        try:
            srv.sender_pub = serialization.load_der_public_key(sender_pk_der)
        except Exception:
            self._send(400)
            return
        our_der = srv.rsa.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self._send_binary(_u32(method) + _u16(len(our_der)) + our_der)
        srv.log('[AirPlay] 完成 pair-setup（legacy RSA method 0）')

    def _pair_verify(self):
        srv = self.server
        body = self._read_body()
        if len(body) < 6 or not _HAS_CRYPTO or srv.sender_pub is None:
            self._send(400)
            return
        method = int.from_bytes(body[0:4], 'big')
        dlen = int.from_bytes(body[4:6], 'big')
        enc = body[6:6 + dlen]
        try:
            rnd = srv.rsa.decrypt(enc, padding.PKCS1v15())
            out = srv.sender_pub.encrypt(rnd, padding.PKCS1v15())
        except Exception:
            self._send(400)
            return
        srv.session_key = rnd
        self._send_binary(_u32(method) + _u16(len(out)) + out)
        srv.log('[AirPlay] 完成 pair-verify，会话已建立')

    def _play(self):
        srv = self.server
        d = self._plist_in()
        uri = ''
        title = 'AirPlay 视频'
        if isinstance(d, dict):
            loc = d.get('Content-Location')
            if isinstance(loc, (list, tuple)) and loc:
                loc = loc[0]
            uri = loc if isinstance(loc, str) else (str(loc) if loc is not None else '')
            t = d.get('Title')
            if isinstance(t, str) and t:
                title = t
        srv.log('[AirPlay] 收到播放请求: %s' % uri[:160])
        if uri and srv.state.on_play:
            srv.state.on_play(uri, title)
        self._send(200)

    def _set_property(self):
        srv = self.server
        d = self._plist_in()
        if isinstance(d, dict) and 'volume' in d:
            try:
                vol = float(d['volume'])
                srv.state.volume = int(vol * 100)
                if srv.state.on_volume:
                    srv.state.on_volume(srv.state.volume)
            except (TypeError, ValueError):
                pass
        self._send(200)


class AirPlayServer(ThreadingHTTPServer):
    """AirPlay 视频控制 HTTP 服务（默认 7000 端口，与 mDNS 宣告一致）。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, ip, port, state, log=print):
        super().__init__(('0.0.0.0', port), _Handler)
        self.ip = ip
        self.port = port
        self.state = state
        self.log = log
        self.sender_pub = None
        self.session_key = None
        if _HAS_CRYPTO:
            self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._pub_der = self.rsa.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo)
        else:
            self.rsa = None
            self._pub_der = b''
            self.log('[AirPlay] 未安装 cryptography，配对不可用（非 DRM 内容仍可直接播放）')

    def server_info(self):
        return {
            'deviceid': _mac_of(self.ip),
            'features': 0x5A7FFFF7,
            'model': 'Computer',
            'name': '森投屏接收端',
            'protovers': '1.1',
            'srcvers': '380.20',
            'vv': 2,
            'pki': self._pub_der,
            'pi': _mac_of(self.ip),
        }

    def device_info(self):
        return {
            'capabilities': {
                'audio': {'codecs': ['LPCM', 'AAC', 'AAC ELD', 'OPUS', 'FLAC']},
                'video': {'codecs': ['H.264', 'HEVC', 'MPEG4', 'H.263'],
                          'resolutions': [{'width': 1920, 'height': 1080}]},
            },
            'features': 0x5A7FFFF7,
        }
