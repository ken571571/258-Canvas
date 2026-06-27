"""网络层安全 —— SSRF 防护、内网地址拦截"""

import ipaddress
import socket
import logging

log = logging.getLogger("canvas571.security")

# ——— 禁止访问的内网和云 metadata 地址 ———
BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),   # 云 metadata (AWS/GCP/Azure)
    ipaddress.ip_network("127.0.0.0/8"),       # 环回段 (除 127.0.0.1 外全部拦截)
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
    ipaddress.ip_network("0.0.0.0/8"),         # 当前网络
    ipaddress.ip_network("100.64.0.0/10"),     # CGNAT / AWS
    ipaddress.ip_network("198.18.0.0/15"),     # 基准测试
    # IPv6 私有地址
    ipaddress.ip_network("fc00::/7"),          # IPv6 唯一本地地址 (ULA)
    ipaddress.ip_network("fe80::/10"),         # IPv6 链路本地地址
    ipaddress.ip_network("fd00::/8"),          # IPv6 ULA 别名段
    ipaddress.ip_network("::1/128"),           # IPv6 环回（除显式 ::1 外）
    # IPv6 映射 IPv4 地址（如 ::ffff:10.0.0.1 会绕过纯 IPv4 阻止列表）
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),      # IPv4-embedded IPv6 (NAT64 / RFC 6052)
    ipaddress.ip_network("::ffff:0.0.0.0/96"), # IPv4-translated IPv6 (RFC 2765)
]


# RFC 1918 内网段（允许局域网部署时放行）
_LAN_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def is_blocked_host(host: str, allow_lan: bool = False, allow_localhost: bool = True) -> bool:
    """检查主机名/IP 是否在禁止列表内（SSRF 防护）。

    localhost 和 127.0.0.1 默认允许（常见单机部署）。
    allow_localhost=False 时禁止 localhost（用于下载远程 ComfyUI 媒体等场景防止重定向探测内网）。
    内网地址默认拒绝（防止探测内网服务），allow_lan=True 时放行。
    云 metadata 地址始终拒绝（防止信息泄露）。

    Args:
        host: 主机名或 IP 地址
        allow_lan: True 时允许 RFC 1918 内网地址（用于 ComfyUI 多机部署等场景）
        allow_localhost: False 时禁止 localhost/127.0.0.1/::1（默认 True 保持向后兼容）
    """
    if allow_localhost and host.lower() in ("localhost", "127.0.0.1", "::1"):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(host))
        except Exception:
            log.warning(f"主机名无法解析（SSRF 拦截）: {host}")
            return True
    # IPv6 映射 IPv4 地址（如 ::ffff:10.0.0.1）— 提前提取 IPv4 部分，用 IPv4 网段检查
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        ipv4_addr = addr.ipv4_mapped
        if ipv4_addr:
            if ipv4_addr.is_loopback:
                return False  # ::ffff:127.0.0.1 等同于 127.0.0.1，放行
            for net in BLOCKED_NETWORKS:
                if isinstance(net, ipaddress.IPv4Network) and ipv4_addr in net:
                    if allow_lan and any(ipv4_addr in lan_net for lan_net in _LAN_NETWORKS):
                        continue
                    return True
            return False  # IPv4 不在阻止列表 → 放行
    for net in BLOCKED_NETWORKS:
        if addr in net:
            # allow_lan 模式放行 RFC 1918 内网段
            if allow_lan and any(addr in lan_net for lan_net in _LAN_NETWORKS):
                continue
            return True
    return False


def validate_safe_url(url: str) -> bool:
    """验证 URL 的主机名是否安全（非内网、非 metadata）。

    返回 True 表示安全可访问，False 表示被拦截。
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        return not is_blocked_host(hostname)
    except Exception:
        return False


async def async_validate_safe_url(url: str) -> bool:
    """异步版 validate_safe_url — DNS 解析不阻塞事件循环。

    在异步上下文中优先使用此函数。
    """
    from urllib.parse import urlparse
    import asyncio
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        return not await async_is_blocked_host(hostname)
    except Exception:
        return False


async def async_is_blocked_host(host: str, allow_lan: bool = False, allow_localhost: bool = True) -> bool:
    """异步版 is_blocked_host — DNS 解析在线程池中执行。

    避免同步 socket.gethostbyname() 阻塞事件循环。

    Args:
        host: 主机名或 IP 地址
        allow_lan: True 时允许 RFC 1918 内网地址
        allow_localhost: False 时禁止 localhost/127.0.0.1/::1
    """
    if allow_localhost and host.lower() in ("localhost", "127.0.0.1", "::1"):
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            ip_str = await loop.run_in_executor(None, socket.gethostbyname, host)
            addr = ipaddress.ip_address(ip_str)
        except Exception:
            log.warning(f"主机名无法解析（SSRF 拦截）: {host}")
            return True
    # IPv6 映射 IPv4 地址（如 ::ffff:10.0.0.1）— 提前提取 IPv4 部分，用 IPv4 网段检查
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        ipv4_addr = addr.ipv4_mapped
        if ipv4_addr:
            if ipv4_addr.is_loopback:
                return False  # ::ffff:127.0.0.1 等同于 127.0.0.1，放行
            for net in BLOCKED_NETWORKS:
                if isinstance(net, ipaddress.IPv4Network) and ipv4_addr in net:
                    if allow_lan and any(ipv4_addr in lan_net for lan_net in _LAN_NETWORKS):
                        continue
                    return True
            return False  # IPv4 不在阻止列表 → 放行
    for net in BLOCKED_NETWORKS:
        if addr in net:
            # allow_lan 模式放行 RFC 1918 内网段
            if allow_lan and any(addr in lan_net for lan_net in _LAN_NETWORKS):
                continue
            return True
    return False
