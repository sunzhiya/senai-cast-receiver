import socket
import ctypes

DEFAULT_DEVICE_NAME = "森投屏接收端"
DEFAULT_PORT = 8200
DISCOVER_INTERVAL = 30

_VPN_KEYWORDS = (
    "vpn", "tap", "wireguard", "openvpn", "zerotier", "tailscale",
    "cloudflare", "warp", "tunnel", "虚拟", "vmware", "virtualbox",
    "docker", "wsl", "hyper-v", "vethernet", "loopback", "ras",
    "point-to-point", "pptp", "l2tp", "sstp", "anyconnect", "cisco",
)
_PHYS_KEYWORDS = (
    "realtek", "intel", "qualcomm", "atheros", "broadcom", "mediatek",
    "802.11", "wi-fi", "wireless", "ethernet", "以太网", "无线", "pci",
    "gbe", "net", "network",
)


def _enum_adapters():
    try:
        iphlpapi = ctypes.windll.iphlpapi
    except Exception:
        return []

    MAX_ADAPTER_NAME_LENGTH = 256
    MAX_ADAPTER_DESCRIPTION_LENGTH = 128
    MAX_ADAPTER_ADDRESS_LENGTH = 8

    class IP_ADDR_STRING(ctypes.Structure):
        pass

    IP_ADDR_STRING._fields_ = [
        ("Next", ctypes.POINTER(IP_ADDR_STRING)),
        ("IpAddress", ctypes.c_char * 16),
        ("IpMask", ctypes.c_char * 16),
        ("Context", ctypes.c_ulong),
    ]

    class IP_ADAPTER_INFO(ctypes.Structure):
        pass

    IP_ADAPTER_INFO._fields_ = [
        ("Next", ctypes.POINTER(IP_ADAPTER_INFO)),
        ("ComboIndex", ctypes.c_ulong),
        ("AdapterName", ctypes.c_char * (MAX_ADAPTER_NAME_LENGTH + 4)),
        ("Description", ctypes.c_char * (MAX_ADAPTER_DESCRIPTION_LENGTH + 4)),
        ("AddressLength", ctypes.c_ulong),
        ("Address", ctypes.c_ubyte * MAX_ADAPTER_ADDRESS_LENGTH),
        ("Index", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("DhcpEnabled", ctypes.c_ulong),
        ("CurrentIpAddress", ctypes.POINTER(IP_ADDR_STRING)),
        ("IpAddressList", IP_ADDR_STRING),
    ]

    buflen = ctypes.c_ulong(4096)
    buf = ctypes.create_string_buffer(buflen.value)
    ret = iphlpapi.GetAdaptersInfo(buf, ctypes.byref(buflen))
    if ret == 111:
        buf = ctypes.create_string_buffer(buflen.value)
        ret = iphlpapi.GetAdaptersInfo(buf, ctypes.byref(buflen))
    if ret != 0:
        return []

    result = []
    info = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO))
    while info:
        desc = info.contents.Description.decode("mbcs", "ignore")
        addr = info.contents.IpAddressList
        while True:
            ip = addr.IpAddress.decode("ascii", "ignore").strip()
            if ip and ip != "0.0.0.0":
                result.append((ip, desc, info.contents.Type))
            if not addr.Next:
                break
            addr = addr.Next.contents
        if not info.contents.Next:
            break
        info = info.contents.Next
    return result


def _is_private(ip):
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def _score(ip, desc, typ):
    d = (desc or "").lower()
    if typ == 24:
        return -100
    if any(k in d for k in _VPN_KEYWORDS):
        return -50
    if typ == 131:
        return -50
    s = 0
    if _is_private(ip):
        s += 1
    if typ in (6, 71):
        s += 2
    if any(k in d for k in _PHYS_KEYWORDS):
        s += 1
    return s


def list_local_ips():
    raw = _enum_adapters()
    out = []
    for ip, desc, typ in raw:
        if ip.startswith("127.") or ip.startswith("169.254"):
            continue
        out.append((ip, desc or "未知网卡"))
    if not out:
        out.append(("127.0.0.1", "回环(未检测到可用网卡)"))
    return out


def get_best_local_ip():
    raw = _enum_adapters()
    best, best_score, best_desc = None, -999, ""
    for ip, desc, typ in raw:
        if ip.startswith("127.") or ip.startswith("169.254"):
            continue
        sc = _score(ip, desc, typ)
        if sc > best_score:
            best_score, best, best_desc = sc, ip, desc
    if best and best_score >= 0:
        return best, (best_desc or "未知网卡")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0], "默认路由出口"
    except OSError:
        return "127.0.0.1", "未检测到可用局域网网卡"
    finally:
        s.close()


def get_local_ip():
    return get_best_local_ip()[0]
