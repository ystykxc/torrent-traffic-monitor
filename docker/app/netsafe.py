"""统一 URL 目标安全校验：防 SSRF / 云元数据探测 / 下载器凭据外泄。

「测试连接」与「新增下载器」接受任意 URL 并由服务端用 urllib 发起请求，
若不加校验会形成「已登录用户 → 让服务端主动连内网」的探测跳板。

两级校验：
- assert_client_target()：轻量版，采集线程每轮都过一遍（不做 DNS 解析，
  避免高频档位下反复解析域名），只封禁非 http/https 与非法的字面量 IP。
- assert_safe_target()：完整版，测试连接 / 新增下载器时调用，解析目标全部
  A/AAAA 记录，逐条拒绝环回 / 链路本地（含 169.254.169.254）/ 保留 /
  组播 / 未指定地址；默认还禁止私网地址，除非 ALLOW_PRIVATE_TARGETS 显式放行。

本项目是家用内网工具，下载器几乎都在 192.168.x / 10.x，故默认允许私网；
环回、链路本地与元数据地址任何情况下都不放行。same_target() 用于判断
测试时 URL 是否被改动，防止把已存密码 POST 到新地址。
"""
import ipaddress
import socket
import urllib.parse

from . import config


def _forbidden_literal(ip):
    """任何配置下都禁止的地址类别（与是否允许私网无关）。"""
    return (ip.is_loopback or ip.is_link_local or ip.is_reserved or
            ip.is_multicast or ip.is_unspecified)


def assert_client_target(url):
    """采集线程入口：只校验 scheme 与字面量 IP，不做 DNS 解析。

    数据库里已保存的下载器地址属于「管理员显式授权」，这里只堵死明显的
    危险形态（file:///etc/passwd、http://127.0.0.1:...、云元数据地址）。
    """
    p = urllib.parse.urlsplit(str(url or ""))
    if p.scheme not in ("http", "https"):
        raise ValueError("下载器地址只允许 http / https")
    host = p.hostname or ""
    if not host:
        raise ValueError("下载器地址缺少主机")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return str(url)                       # 域名：交给下面完整版按需解析
    if _forbidden_literal(ip):
        raise ValueError("禁止访问环回 / 链路本地 / 保留地址")
    return str(url)


def assert_safe_target(url, allow_private=None):
    """测试连接 / 新增下载器入口：解析全部 A/AAAA 记录后逐条校验。

    allow_private=None 时读配置 ALLOW_PRIVATE_TARGETS（默认 True，家用内网）。
    解析失败直接拒绝，避免让 urllib 带着异常字符串回显形成探测通道。
    """
    p = urllib.parse.urlsplit(str(url or ""))
    if p.scheme not in ("http", "https"):
        raise ValueError("只允许 http / https")
    host = p.hostname or ""
    if not host:
        raise ValueError("URL 缺少主机")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError:
        raise ValueError("URL 端口不合法")

    allow = (config.SECURITY["allow_private_targets"]
             if allow_private is None else bool(allow_private))
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        raise ValueError("目标主机无法解析")

    seen = set()
    for info in infos:
        raw = info[4][0]
        if raw in seen:
            continue
        seen.add(raw)
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            raise ValueError("目标地址无法解析")
        if _forbidden_literal(ip) or (not allow and ip.is_private):
            raise ValueError("目标地址被安全策略拒绝")
    if not seen:
        raise ValueError("目标主机无可用地址")
    return p.geturl()


def same_target(a, b):
    """规范化后比较两个 URL 是否指向同一目标（判断测试时 URL 是否被改动）。"""
    def norm(u):
        try:
            p = urllib.parse.urlsplit(str(u or "").rstrip("/"))
            return (p.scheme.lower(), (p.hostname or "").lower(), p.port,
                    p.path.rstrip("/"))
        except ValueError:
            return None
    return norm(a) is not None and norm(a) == norm(b)
