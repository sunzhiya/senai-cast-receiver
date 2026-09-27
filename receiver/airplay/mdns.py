"""AirPlay 被发现（mDNS/DNS-SD）轻量 responder。

说明：本模块让本机作为 AirPlay 设备出现在 iPhone / 部分小众投屏 App 的列表里
（即"能被扫到"）。由于 Apple 的 FairPlay 视频流加密需要私有密钥，完整的 AirPlay
*视频解码*不在开源范围内——本软件的主投屏通道是 DLNA（覆盖爱优腾/B站等绝大多数
App）。这里只提供"被发现 + 架构可插拔"，真要接 AirPlay 视频后续再补 RTSP 层。
"""
import hashlib
import socket
import struct
import threading
import time

MDNS_ADDR = "224.0.0.251"
MDNS_PORT = 5353


def _enc_name(name):
    out = b''
    for label in name.split('.'):
        if label:
            out += bytes([len(label)]) + label.encode('utf-8')
    return out + b'\x00'


def _read_name(data, off):
    labels = []
    while off < len(data):
        length = data[off]
        if length == 0:
            off += 1
            break
        if (length & 0xC0) == 0xC0:  # 压缩指针
            off += 2
            break
        off += 1
        labels.append(data[off:off + length].decode('utf-8', 'ignore'))
        off += length
    return '.'.join(labels), off


class AirPlayResponder(threading.Thread):
    def __init__(self, ip, name, port=7000, log=print):
        super().__init__(daemon=True)
        self.ip = ip
        self.name = name
        self.port = port
        self.log = log
        self._stop = threading.Event()
        self.sock = None
        self.mac = self._fake_mac(ip)

    def _fake_mac(self, ip):
        h = hashlib.md5(ip.encode()).hexdigest()
        return ':'.join(h[i:i + 2] for i in range(0, 12, 2)).upper()

    def _txt(self):
        fields = [
            'deviceid=' + self.mac,
            'features=0x5A7FFFF7',
            'model=Computer',
            'name=' + self.name,
            'protovers=1.1',
            'srcvers=380.20',
            'vv=2',
        ]
        out = b''
        for f in fields:
            b = f.encode('utf-8')
            out += bytes([len(b)]) + b
        return out

    def _setup(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', MDNS_PORT))
        mreq = struct.pack('4sl', socket.inet_aton(MDNS_ADDR), socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        self.sock.settimeout(1.0)
        self.log('[AirPlay] mDNS responder 已启动（设备可在 AirPlay 列表出现）')

    def _build(self, qid, qname, qtype):
        services = {'_airplay._tcp.local': '._airplay._tcp.local',
                    '_raop._tcp.local': '._raop._tcp.local'}
        if qname not in services:
            return None
        srv_name = self.name + services[qname]
        target = self.name + '.local'
        answers = b''
        # PTR
        pn = _enc_name(srv_name)
        answers += _enc_name(qname) + struct.pack('>HHIH', 12, 1, 4500, len(pn)) + pn
        # SRV
        srv_rdata = struct.pack('>HHH', 0, 0, self.port) + _enc_name(target)
        answers += _enc_name(srv_name) + struct.pack('>HHIH', 33, 1, 120, len(srv_rdata)) + srv_rdata
        # TXT
        txt = self._txt()
        answers += _enc_name(srv_name) + struct.pack('>HHIH', 16, 1, 4500, len(txt)) + txt
        # A
        ardata = socket.inet_aton(self.ip)
        answers += _enc_name(target) + struct.pack('>HHIH', 1, 1, 120, 4) + ardata
        header = struct.pack('>HHHHHH', qid, 0x8400, 1, 4, 0, 0)
        question = _enc_name(qname) + struct.pack('>HH', qtype, 1)
        return header + question + answers

    def _advertise(self):
        for svc in ('_airplay._tcp.local', '_raop._tcp.local'):
            pkt = self._build(0, svc, 12)
            if pkt:
                try:
                    self.sock.sendto(pkt, (MDNS_ADDR, MDNS_PORT))
                except OSError:
                    pass

    def _handle_query(self, data, addr):
        if len(data) < 12:
            return
        qid, flags, qd = struct.unpack('>HHH', data[:6])
        if flags & 0x8000:
            return
        off = 12
        for _ in range(qd):
            qname, off = _read_name(data, off)
            if off + 4 > len(data):
                return
            qtype, _ = struct.unpack('>HH', data[off:off + 4])
            off += 4
            if qname in ('_airplay._tcp.local', '_raop._tcp.local'):
                resp = self._build(qid, qname, qtype)
                if resp:
                    try:
                        self.sock.sendto(resp, (MDNS_ADDR, MDNS_PORT))
                    except OSError:
                        pass

    def run(self):
        try:
            self._setup()
        except OSError as e:
            self.log('[AirPlay] 无法启动 mDNS(%s)，已跳过（不影响 DLNA 投屏）' % e)
            return
        self._advertise()
        last = time.time()
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
                self._handle_query(data, addr)
            except socket.timeout:
                pass
            except OSError:
                pass
            if time.time() - last > 2:
                self._advertise()
                last = time.time()

    def shutdown(self):
        self._stop.set()
