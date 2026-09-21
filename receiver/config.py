import socket
import ctypes

DEFAULT_DEVICE_NAME = "森投屏接收端"
DEFAULT_PORT = 8200
DISCOVER_INTERVAL = 30  # 秒，SSDP 周期宣告间隔

# 识别「应排除」的虚拟/隧道/VPN 网卡关键字（Description 命中即严重降权）
_VPN_KEYWORDS = (
    "vpn", "tap", "wireguard", "openvpn", "zerotier", "tailscale",
    "cloudflare", "warp", "tunnel", "虚拟", "vmware", "virtualbox",
    "docker", "wsl", "hyper-v", "vethernet", "loopback", "ras",
    "point-to-point", "pptp", "l2tp", "sstp", "anyconnect", "cisco",
)
# 物理网卡加分关键字（真实 Wi-Fi / 以太网）
_PHYS_KEYWORDS = (
    "realtek", "intel", "qualcomm", "atheros", "broadcom", "mediatek",
    "802.11", "wi-fi", "wireless", "ethernet", "以太网", "无线", "pci",
    "gbe", "net", "network",
)


def _enum_adapters():
    """返回 [(ip, description, if_type), ...] 所有非回环 IPv4 地址。

    直接调用 Windows IPHLPAPI 枚举网卡，不依赖路由表，因此不受 VPN
    抢占默认网关/默认路由的影响。
    """
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
    if ret == 111:  # ERROR_BUFFER_OVERFLOW
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
    """越高越优先作为投屏地址。VPN/虚拟网卡被打成负分。"""
    d = (desc or "").lower()
    if typ == 24:  # 软件回环
        return -100
    if any(k in d for k in _VPN_KEYWORDS):
        return -50
    if typ == 131:  # 隧道接口（多数 VPN / 6to4）
        return -50
    s = 0
    if _is_private(ip):
        s += 1
    if typ in (6, 71):  # 以太网 / Wi-Fi
        s += 2
    if any(k in d for k in _PHYS_KEYWORDS):
        s += 1
    return s


def list_local_ips():
    """返回所有可作为投屏地址的 (ip, 网卡描述)，供 GUI 下拉手动选择。"""
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
    """返回 (ip, 网卡描述)，已自动排除 VPN/虚拟网卡选择真实网卡。

    优先级：物理 Wi-Fi/以太网 > 普通私有地址 >（被严重降权的 VPN/隧道）。
    仅在枚举完全失败时才回退到 connect(8.8.8.8) 出口探测。
    """
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
    # 兜底：旧式出口探测（仅在枚举失败时）
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0], "默认路由出口"
    except OSError:
        return "127.0.0.1", "未检测到可用局域网网卡"
    finally:
        s.close()


def get_local_ip():
    """获取本机在局域网中的真实 IP（排除 VPN/虚拟网卡）。见 get_best_local_ip。"""
    return get_best_local_ip()[0]
