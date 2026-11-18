"""账户认证与会话。

- 密码：PBKDF2-HMAC-SHA256 + 随机盐，默认 600000 轮（OWASP 2023）；哈希串自带
  轮数，旧轮数哈希在登录成功后透明升级。
- 会话：30 天滑动续期 + 90 天绝对生命周期上限，绑定 UA 指纹与 IP 网段
  （IPv4 /24、IPv6 /48）；换浏览器 / 换网段 / UA 变化要求重新登录，
  升级时一次性作废旧长期会话。
- 登录限速：连续失败临时锁定 1 分钟；只有来源 IP 落在 TRUSTED_PROXIES
  可信代理网段时才采信 X-Forwarded-For 最后一跳，否则一律用 remote_addr。
- 首次部署：BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD 环境变量直接建强账号且
  must_change=0，消除 admin/admin 竞速窗口；未配置时回落默认账号 + 强制改密。

所有审计事件同步写结构化日志与 audit_log 表。
"""
import base64
import hashlib
import hmac
import ipaddress
import secrets
import time
from threading import Lock

from flask import request

from . import config, db, log

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
MAX_FAILS = 5
BLOCK_SECONDS = 60

_fail_lock = Lock()
_fails = {}


# ---------------- 密码哈希 ----------------

def _rounds():
    return config.SECURITY["pbkdf2_rounds"]


def _b64(b):
    return base64.b64encode(b).decode()


def _unb64(s):
    return base64.b64decode(s)


def hash_password(pw, rounds=None):
    r = int(rounds or _rounds())
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), salt, r)
    # 格式带轮数，便于旧哈希识别与透明升级
    return "pbkdf2$%d$%s$%s" % (r, _b64(salt), _b64(dk))


def _parse_hash(stored):
    parts = str(stored or "").split("$")
    try:
        if parts[0] != "pbkdf2":
            return None
        if len(parts) == 3:            # 及以前：pbkdf2$salt$dk，固定 120000 轮
            return 120000, _unb64(parts[1]), _unb64(parts[2])
        if len(parts) == 4:            # pbkdf2$rounds$salt$dk
            return int(parts[1]), _unb64(parts[2]), _unb64(parts[3])
    except Exception:
        return None
    return None


def verify_password(pw, stored):
    p = _parse_hash(stored)
    if not p:
        return False
    rounds, salt, expect = p
    got = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), salt, rounds)
    return hmac.compare_digest(got, expect)


def needs_upgrade(stored):
    p = _parse_hash(stored)
    return bool(p and p[0] < _rounds())


# ---------------- 客户端识别 ----------------

def client_ip():
    """反代下的真实客户端 IP。

    绝不盲目信任 X-Forwarded-For：只有 request.remote_addr 属于
    TRUSTED_PROXIES（环境变量配置的 CIDR 列表）时，才取 XFF 的最后一跳
    （紧邻可信代理、由代理追加、攻击者无法伪造的那一跳）。否则一律用
    remote_addr。这样既修好了「所有外部用户共享同一个限速计数器」，
    又不会因盲目信任 XFF 而被伪造头绕过限速。
    """
    remote = request.remote_addr or "?"
    trusted = config.SECURITY["trusted_proxies"]
    if trusted:
        try:
            addr = ipaddress.ip_address(remote)
            if any(addr in net for net in trusted):
                xff = request.headers.get("X-Forwarded-For", "")
                if xff:
                    last = xff.split(",")[-1].strip()
                    if last:
                        return last[:64]
        except ValueError:
            pass
    return remote


def _ip():                             # 兼容旧调用名
    return client_ip()


def _ua_hash():
    return hashlib.sha256(request.headers.get("User-Agent", "").encode("utf-8")).hexdigest()[:32]


def _ip_net(ip):
    """IPv4 归到 /24、IPv6 归到 /48：跨网段变化才要求重新登录，

    同一局域网 / 移动网络内 IP 漂移不会误踢，跨网段（换城市、换出口）才失效。"""
    try:
        addr = ipaddress.ip_address(ip)
        mask = 24 if addr.version == 4 else 48
        return str(ipaddress.ip_network("%s/%d" % (addr, mask), strict=False))
    except ValueError:
        return str(ip)[:64]


# ---------------- 登录限速 ----------------

def _sweep_fails(now):
    for ip, (_n, until) in list(_fails.items()):
        if until and now > until:
            _fails.pop(ip, None)
    if len(_fails) > 256:
        _fails.clear()


def _blocked():
    with _fail_lock:
        now = time.time()
        _sweep_fails(now)
        _n, until = _fails.get(client_ip(), (0, 0))
        return now < until


def _note_fail():
    now = time.time()
    with _fail_lock:
        _sweep_fails(now)
        ip = client_ip()
        n, until = _fails.get(ip, (0, 0))
        n = 0 if now > until else n
        n += 1
        _fails[ip] = (n, now + BLOCK_SECONDS if n >= MAX_FAILS else 0)


def _clear_fail():
    with _fail_lock:
        _fails.pop(client_ip(), None)


# ---------------- 账户初始化 ----------------

def bootstrap():
    """无账户时创建账号。

    优先用 BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD 建立强账号且 must_change=0，
    容器一启动就没有「默认 admin/admin 等人抢」的窗口。未配置时保持
    原行为（默认账号 + 强制改密）并打印告警，兼容既有部署习惯。
    """
    if db.count_users():
        return
    bu = config.SECURITY["bootstrap_username"]
    bp = config.SECURITY["bootstrap_password"]
    if bu and bp:
        if 2 <= len(bu) <= 32 and len(bp) >= 6 and bu.lower() != DEFAULT_USERNAME:
            db.create_user(bu, hash_password(bp), 0)
            log.info("auth.bootstrap_from_env", username=bu)
            print("[auth] 已用 BOOTSTRAP_USERNAME 建立账号「%s」"
                  "（无需强制改密，无默认账号竞速窗口）" % bu, flush=True)
            return
        print("[auth] BOOTSTRAP_USERNAME/PASSWORD 不合法（账号 2~32 位且不能为 admin、"
              "密码至少 6 位），回落默认账号", flush=True)
    db.create_user(DEFAULT_USERNAME, hash_password(DEFAULT_PASSWORD), 1)
    print("[auth] 已创建默认账号 admin / admin（首次登录必须修改账号与密码）。"
          "公网部署强烈建议改用 BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD 环境变量",
          flush=True)


# ---------------- 会话 ----------------

def token_from_request():
    h = request.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.headers.get("X-Auth-Token", "").strip()


def login(username, password):
    if _blocked():
        return None, "尝试次数过多，请 1 分钟后再试"
    u = db.get_user()
    ok_name = u and hmac.compare_digest(str(username or "").strip(), u["username"])
    if not ok_name or not verify_password(password or "", u["password_hash"]):
        _note_fail()
        db.audit("login.failed", actor=str(username or "")[:64], ip=client_ip())
        return None, "账号或密码错误"
    _clear_fail()
    # 旧轮数哈希登录成功后透明升级
    if needs_upgrade(u["password_hash"]):
        db.update_user(u["username"], hash_password(password or ""), u["must_change"])
        log.info("auth.hash_upgraded", rounds=_rounds())
    token = secrets.token_urlsafe(32)
    now = time.time()
    ttl = config.SECURITY["session_ttl_days"] * 86400
    max_life = config.SECURITY["session_max_lifetime_days"] * 86400
    bind = config.SECURITY["session_bind"]
    db.create_session(
        token, now + ttl,
        ua_hash=_ua_hash() if bind else "",
        ip_net=_ip_net(client_ip()) if bind else "",
        max_expires_at=now + max_life,
    )
    db.audit("login.success", actor=u["username"], ip=client_ip())
    return {"token": token, "username": u["username"],
            "must_change": bool(u["must_change"])}, None


def current_session():
    token = token_from_request()
    if not token:
        return None
    s = db.get_session(token)
    if not s:
        return None
    now = time.time()
    if (float(s["expires_at"]) < now or
            (s["max_expires_at"] and float(s["max_expires_at"]) < now)):
        db.delete_session(token)
        return None
    # 绑定校验（UA 指纹 / IP 段变化时要求重新登录）。
    # 只拒绝本次请求，**绝不删除会话**：否则任何一个拿到/猜到 token 的人拿
    # 不同 UA 打一次请求，就能把合法用户的会话直接踢下线（会话销毁型 DoS）；
    # 用户换浏览器、换网络或反代 XFF 抖动也会被迫反复重新登录。会话只由
    # 过期清理与主动 logout 删除。
    if config.SECURITY["session_bind"]:
        if ((s["ua_hash"] and s["ua_hash"] != _ua_hash()) or
                (s["ip_net"] and s["ip_net"] != _ip_net(client_ip()))):
            db.audit("session.rejected", actor=s.get("username", ""), ip=client_ip())
            return None
    # 滑动续期：每半个 TTL 才写一次库，避免每个 API 请求都触发 SQLite 写事务
    ttl = config.SECURITY["session_ttl_days"] * 86400
    if now - float(s["last_seen"] or 0) > ttl / 2:
        db.touch_session(token, now + ttl, now)
    return s


def logout():
    token = token_from_request()
    if token:
        db.delete_session(token)
        db.audit("logout", ip=client_ip())


def setup(new_username, new_password):
    """首次登录强制修改账号与密码：两者都不能仍是 admin。"""
    u = db.get_user()
    if not u:
        return "账号不存在"
    if not u["must_change"]:
        return "已完成初始化，请使用「账户设置」修改"
    name = str(new_username or "").strip()
    pw = str(new_password or "")
    if len(name) < 2 or len(name) > 32:
        return "新账号长度需为 2~32 个字符"
    if name.lower() == DEFAULT_USERNAME:
        return "新账号不能仍为 admin，请更换"
    if len(pw) < 6 or len(pw) > 128:
        return "新密码长度需为 6~128 个字符"
    if pw == DEFAULT_PASSWORD:
        return "新密码不能仍为 admin，请更换"
    db.update_user(name, hash_password(pw), 0)
    db.audit("auth.setup", actor=name, ip=client_ip())
    return None


def change(old_password, new_username, new_password):
    """后续修改账号/密码，需验证原密码；账号或密码留空表示保持原值。"""
    u = db.get_user()
    if not u or not verify_password(old_password or "", u["password_hash"]):
        db.audit("auth.change_failed", ip=client_ip())
        return "原密码错误"
    name = str(new_username or "").strip() or u["username"]
    pw = str(new_password or "")
    if len(name) < 2 or len(name) > 32:
        return "账号长度需为 2~32 个字符"
    if pw and (len(pw) < 6 or len(pw) > 128):
        return "新密码长度需为 6~128 个字符"
    db.update_user(name, hash_password(pw) if pw else u["password_hash"], 0)
    db.audit("auth.change", actor=name, ip=client_ip())
    return None
