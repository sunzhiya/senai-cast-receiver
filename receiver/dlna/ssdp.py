import socket
import struct
import threading
import time
from email.utils import formatdate

from . import DEVICE_UUID

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

MSEARCH_TARGETS = [
    "upnp:rootdevice",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-upnp-org:service:AVTransport:1",
    "urn:schemas-upnp-org:service:RenderingControl:1",
    "urn:schemas-upnp-org:service:ConnectionManager:1",
    "uuid:" + DEVICE_UUID,
]

# 华为私有发现目标：华为手机/平板会同时搜索这些，响应后能提高被识别概率。
HUAWEI_TARGETS = [
    "urn:schemas-huawei-com:device:ManageableDevice:1",
    "urn:schemas-huawei-com:device:GenericDevice:1",
    "urn:schemas-huawei-com:service:NetworkSyncService:1",
    "urn:www-huawei-com:service:NetworkSyncService:1",
]

# 增强响应：对 rootdevice 搜索同时附送 MediaRenderer + AVTransport，
# 很多手机控制点会忽略单独的 rootdevice，需要看到具体服务才展示。
RESPONSE_BUNDLE = {
    "upnp:rootdevice": ["upnp:rootdevice", "urn:schemas-upnp-org:device:MediaRenderer:1"],
    "urn:schemas-upnp-org:device:MediaRenderer:1": ["urn:schemas-upnp-org:device:MediaRenderer:1", "urn:schemas-upnp-org:service:AVTransport:1"],
    "urn:schemas-upnp-org:service:AVTransport:1": ["urn:schemas-upnp-org:service:AVTransport:1"],
}

SERVER_STR = "Linux/5.10 UPnP/1.0 DLNADOC/1.50 SenAICastReceiver/1.0"


class SSDPServer(threading.Thread):
    """SSDP 发现：周期 NOTIFY 宣告 + 响应 M-SEARCH（绑不上 1900 就降级为只宣告）。"""

    def __init__(self, ip, port, name, log=print, interval=30):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.name = name
        self.log = log
        self.interval = interval
        self._stop = threading.Event()
        self.can_respond = False
        self._listen_sock = None
        self._notify_sock = None

    def _location(self):
        return "http://%s:%d/device.xml" % (self.ip, self.port)

    def _usn(self, nt):
        if nt == "upnp:rootdevice":
            return "uuid:%s::upnp:rootdevice" % DEVICE_UUID
        if nt == "uuid:" + DEVICE_UUID:
            return "uuid:%s" % DEVICE_UUID
        return "uuid:%s::%s" % (DEVICE_UUID, nt)

    def _build_notify(self, nt):
        lines = [
            "NOTIFY * HTTP/1.1",
            "HOST: %s:%d" % (SSDP_ADDR, SSDP_PORT),
            "CACHE-CONTROL: max-age=1800",
            # DATE 是 UPnP 规范推荐头，部分严格控制点（含自研 SSDP 栈的 App）会校验
            "DATE: %s" % formatdate(usegmt=True),
            "LOCATION: %s" % self._location(),
            "NT: %s" % nt,
            "NTS: ssdp:alive",
            "SERVER: %s" % SERVER_STR,
            "USN: %s" % self._usn(nt),
            "",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8")

    def _build_response(self, nt):
        # DATE 头部分严格控制点会校验
        lines = [
            "HTTP/1.1 200 OK",
            "CACHE-CONTROL: max-age=1800",
            "DATE: %s" % formatdate(usegmt=True),
            "EXT:",
            "LOCATION: %s" % self._location(),
            "SERVER: %s" % SERVER_STR,
            "ST: %s" % nt,
            "USN: %s" % self._usn(nt),
            "BOOTID.UPNP.ORG: 1",
            "CONFIGID.UPNP.ORG: 1",
            "",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8")

    def _build_byebye(self, nt):
        lines = [
            "NOTIFY * HTTP/1.1",
            "HOST: %s:%d" % (SSDP_ADDR, SSDP_PORT),
            "NT: %s" % nt,
            "NTS: ssdp:byebye",
            "USN: %s" % self._usn(nt),
            "",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8")

    def _setup_listen(self):
        """绑 1900 响应 M-SEARCH。Windows 的 SSDPSRV 常占着 1900，绑不上就降级为只宣告。"""
        # 先绑具体 IP（响应源地址精确为真实网卡，不被 VPN 抢），失败再退通配。
        # 两种情况都绑 1900，让响应源端口=1900 —— 多数安卓/鸿蒙控制点
        # 会丢弃源端口不是 1900 的响应（以前"收到响应却不拉 device.xml"就栽在这）。
        hosts = [self.ip, ""]
        for host in hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, SSDP_PORT))
                mreq = struct.pack("4sL", socket.inet_aton(SSDP_ADDR), socket.INADDR_ANY)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                sock.settimeout(1.0)
                self._listen_sock = sock
                self.can_respond = True
                self.log("[SSDP] 已绑定 1900 端口(host=%s)，可主动响应手机搜索(M-SEARCH)，"
                         "响应将从此 socket 发出（源端口=1900）" % host)
                return
            except OSError as e:
                self.log("[SSDP] 绑定 1900 于 %s 失败: %s" % (host or '<通配>', e))
        self.can_respond = False
        self.log("[SSDP] 无法绑定 1900（很可能被系统 SSDP 服务占用）。已降级为仅 NOTIFY 宣告。"
                 "若手机仍扫不到，请在界面点「一键修复网络」停止系统 SSDP 服务后重启本软件。")

    def _setup_notify(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 4))
        # 绑具体 IP 并指定组播出口网卡，NOTIFY 才不会从 VPN 虚拟网卡溜出去
        try:
            sock.bind((self.ip, 0))
        except OSError:
            pass
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(self.ip))
        except OSError:
            pass
        self._notify_sock = sock

    def _send_notify_all(self):
        if not self._notify_sock:
            return
        for nt in MSEARCH_TARGETS:
            try:
                self._notify_sock.sendto(self._build_notify(nt), (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass

    def _send_byebye(self):
        if not self._notify_sock:
            return
        for nt in MSEARCH_TARGETS:
            try:
                self._notify_sock.sendto(self._build_byebye(nt), (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass

    def _handle_search(self, data, addr):
        text = data.decode("utf-8", "ignore")
        if not text.startswith("M-SEARCH"):
            return
        st = None
        for line in text.split("\r\n"):
            if line.lower().startswith("st:"):
                st = line.split(":", 1)[1].strip()
        # 详细诊断：首条 M-SEARCH 全文，确认手机到底发了什么
        if not getattr(self, '_diag_msearch_dumped', False):
            self._diag_msearch_dumped = True
            self.log("[SSDP][诊断] 收到原始 M-SEARCH(来自%s):\n%s" % (addr, text.strip()))
        self.log("[SSDP] 收到来自 %s 的 M-SEARCH, ST=%s" % (addr, st or '(空)'))
        if st is None:
            return
        # 有些小众 App 搜 "MediaRenderer"（不带版本号）或带关键字的 ST
        st_l = (st or "").lower()
        if st == "ssdp:all":
            targets = list(dict.fromkeys(MSEARCH_TARGETS + HUAWEI_TARGETS))
        elif st in MSEARCH_TARGETS:
            targets = RESPONSE_BUNDLE.get(st, [st])
        elif st in HUAWEI_TARGETS:
            targets = [st]
        elif any(k in st_l for k in ("mediarenderer", "avtransport",
                                       "renderingcontrol", "connectionmanager",
                                       "rootdevice", "huawei")):
            targets = ["urn:schemas-upnp-org:device:MediaRenderer:1"]
        else:
            self.log("[SSDP][诊断] 未匹配的 ST=%s，已忽略本次搜索" % st)
            return
        # 响应必须从绑 1900 的监听 socket 发出（源端口=1900），
        # 否则多数安卓/鸿蒙控制点直接丢弃
        send_sock = self._listen_sock if (self._listen_sock and self.can_respond) else self._notify_sock
        src = None
        try:
            src = send_sock.getsockname()
        except Exception:
            pass
        if not getattr(self, '_diag_resp_dumped', False):
            self._diag_resp_dumped = True
            sample = self._build_response(targets[0]).decode("utf-8", "ignore")
            self.log("[SSDP][诊断] 即将发出的响应样例(源地址=%s):\n%s" % (src, sample))
        self.log("[SSDP][诊断] 响应源地址=%s, LOCATION=%s, 目标数=%d"
                 % (src, self._location(), len(targets)))
        sent = 0
        for nt in targets:
            try:
                send_sock.sendto(self._build_response(nt), addr)
                sent += 1
            except OSError as e:
                self.log("[SSDP] 单播响应 %s 失败: %s" % (addr, e))
        # 部分控制点只认 NOTIFY 宣告不处理单播响应，补发一次提高展示率
        try:
            send_sock.sendto(self._build_notify(
                "urn:schemas-upnp-org:device:MediaRenderer:1"), addr)
            sent += 1
        except OSError:
            pass
        # AP 隔离绕过：组播一份，路由器会泛洪给所有客户端，
        # 避免 PC手机单播被路由器隔离拦掉
        mc_sent = 0
        if self._notify_sock:
            for nt in targets:
                try:
                    self._notify_sock.sendto(self._build_response(nt), (SSDP_ADDR, SSDP_PORT))
                    mc_sent += 1
                except OSError:
                    pass
            try:
                self._notify_sock.sendto(
                    self._build_notify("urn:schemas-upnp-org:device:MediaRenderer:1"),
                    (SSDP_ADDR, SSDP_PORT))
                mc_sent += 1
            except OSError:
                pass
        self.log("[SSDP] 已向 %s 回复 单播%d + 组播%d 条响应(组播用于绕过AP隔离)"
                 % (addr, sent, mc_sent))

    def run(self):
        self._setup_notify()
        self._setup_listen()
        # 启动自检：源端口必须是 1900
        src = None
        try:
            src = self._listen_sock.getsockname() if self._listen_sock else None
        except Exception:
            pass
        self.log("[SSDP][诊断] 启动完成: 本机IP=%s HTTP端口=%d 设备名=%s 可主动响应=%s "
                 "响应源端口=%s LOCATION=%s" % (self.ip, self.port, self.name,
                                            self.can_respond, src, self._location()))
        self._send_notify_all()  # 启动立即宣告一次，缩短手机发现延迟
        last = time.time()
        # 前 2 分钟高频宣告（每 3 秒），覆盖手机 App 刚打开时的瞬时扫描
        fast_until = time.time() + 120
        while not self._stop.is_set():
            if self.can_respond and self._listen_sock:
                try:
                    data, addr = self._listen_sock.recvfrom(1024)
                    self._handle_search(data, addr)
                except socket.timeout:
                    pass
                except OSError:
                    pass
            now = time.time()
            interval = 3 if now < fast_until else self.interval
            if now - last >= interval:
                self._send_notify_all()
                last = now
            time.sleep(0.2)

    def announce(self):
        """立即重新宣告一次（切换电视模式/设备名后调用，让手机重新拉 device.xml）。"""
        self._send_notify_all()

    def shutdown(self):
        self._stop.set()
        self._send_byebye()
