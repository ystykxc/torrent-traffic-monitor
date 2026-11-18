"""应用配置：环境变量优先，其次 config.json，运行时以数据库设置为准。

采样分两套独立参数：实时速率（poll_interval，默认 5 秒）与流量统计
（traffic_interval，默认 1 分钟），各自采集、各自落库。
安全与可观测性参数集中在 SECURITY 字典，均可通过环境变量覆盖。
"""
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
DEFAULT_CONFIG = os.environ.get("CONFIG_FILE", os.path.join(ROOT_DIR, "config.json"))

# 采样间隔拆成「实时速率」与「流量统计」两套，各自独立设置、
# 各自独立采集、各自独立落库，互不干扰。改动持久化到 SQLite，重启后仍生效。
#
# 实时速率：沿用预设档位，并在 0.2 秒与 1 秒之间补上 0.5 秒。
# 配置键沿用 poll_interval（兼容旧 config.json / 环境变量 / 数据库设置）。
RATE_POLL_CHOICES = (0.1, 0.2, 0.5, 1, 3, 5, 10)
RATE_POLL_LABELS = {
    0.1: "0.1 秒", 0.2: "0.2 秒", 0.5: "0.5 秒", 1: "1 秒",
    3: "3 秒", 5: "5 秒", 10: "10 秒",
}
# 流量统计：5 秒 / 10 秒 / 30 秒 / 1 分钟 / 5 分钟 / 10 分钟 / 30 分钟。
TRAFFIC_POLL_CHOICES = (5, 10, 30, 60, 300, 600, 1800)
TRAFFIC_POLL_LABELS = {
    5: "5 秒", 10: "10 秒", 30: "30 秒", 60: "1 分钟",
    300: "5 分钟", 600: "10 分钟", 1800: "30 分钟",
}
# 默认采样率：实时速率 5 秒、流量统计 1 分钟。
DEFAULT_RATE_POLL = 5
DEFAULT_TRAFFIC_POLL = 60

# 兼容旧代码 / 部署脚本中的引用名
POLL_INTERVAL_CHOICES = RATE_POLL_CHOICES
POLL_INTERVAL_LABELS = RATE_POLL_LABELS

LIVE_SPAN_CHOICES = (30, 60, 180, 300, 600, 1800)
LIVE_SPAN_LABELS = {
    30: "30 秒", 60: "1 分钟", 180: "3 分钟",
    300: "5 分钟", 600: "10 分钟", 1800: "30 分钟",
}
DEFAULT_LIVE_SPAN = 300


def in_choices(value, choices):
    """预设档位匹配：用容差比较，避免 0.1 / 0.2 / 0.5 这类浮点值与 JSON 往返后不等。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return any(abs(v - float(c)) < 1e-9 for c in choices)


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 安全加固与可观测性配置（全部可用环境变量覆盖，未设置时取安全默认值）
# 这些值在模块导入时解析一次；容器启动前由 compose / docker run 注入即可。
# ---------------------------------------------------------------------------
def _bool_env(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _parse_cidrs(raw):
    """把逗号分隔的 CIDR / IP 列表解析成 ip_network 列表。"""
    import ipaddress
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            print(f"[config] 忽略无法解析的可信代理网段: {part}", flush=True)
    return out


SECURITY = {
    # 首次部署直接用环境变量建立强账号，从根上消除 admin/admin 竞速窗口。
    # 两个都设置才生效；只设置一个仍回落到默认账号 + 强制改密。
    "bootstrap_username": os.environ.get("BOOTSTRAP_USERNAME", "").strip(),
    "bootstrap_password": os.environ.get("BOOTSTRAP_PASSWORD", ""),
    # 只有来源 IP 落在这些网段内，才信任 X-Forwarded-For 的最后一跳。
    # 留空 = 不信任任何代理，一律用 remote_addr（杜绝伪造 XFF 绕过限速）。
    "trusted_proxies": _parse_cidrs(os.environ.get("TRUSTED_PROXIES", "")),
    # 会话有效期（滑动续期步长）/ 最大生命周期 / 是否绑定 UA 与 IP 段。
    "session_ttl_days": max(1, _int_env("SESSION_TTL_DAYS", 30)),
    "session_max_lifetime_days": max(1, _int_env("SESSION_MAX_LIFETIME_DAYS", 90)),
    "session_bind": _bool_env("SESSION_BIND", True),
    # PBKDF2 轮数（OWASP 2023 建议 600000）。
    "pbkdf2_rounds": max(100_000, _int_env("PBKDF2_ROUNDS", 600_000)),
    # 下载器密码加密密钥。留空则在 data 目录自动生成 .secret_key（权限 600）。
    "secret_key": os.environ.get("SECRET_KEY", ""),
    # 是否允许连接内网私有地址。本项目是家用内网工具，下载器几乎都在内网，
    # 默认允许；但环回 / 链路本地（含 169.254.169.254 云元数据）/ 保留地址一律禁止。
    "allow_private_targets": _bool_env("ALLOW_PRIVATE_TARGETS", True),
    # 全局限流（每个 key 在窗口内的请求数上限）。默认 180/分钟，
    # 严格路径（/api/chart、连接测试）取其一半 = 90/分钟 —— 高频采样档位
    # （0.1 秒）下 SSE 推流被节流到 1 秒、chart 最多 60 次/分钟，留出余量。
    "rate_limit": max(10, _int_env("RATE_LIMIT", 180)),
    "rate_limit_window": 60,
    # 可观测性 / 推流开关
    "sse_enabled": _bool_env("SSE_ENABLED", True),
    "audit_enabled": _bool_env("AUDIT_ENABLED", True),
    "metrics_enabled": _bool_env("METRICS_ENABLED", True),
}


def load():
    cfg = {
        "poll_interval": DEFAULT_RATE_POLL,        # 实时速率采样间隔（秒）
        "traffic_interval": DEFAULT_TRAFFIC_POLL,  # 流量统计采样间隔（秒，新增）
        "live_span": DEFAULT_LIVE_SPAN,
        "request_timeout": 5,
        "sample_retention_days": 7,
        "tz_offset": 8,
        "data_dir": "/app/data",
        "http_port": 8080,
        "downloaders": [],
    }
    if os.path.isfile(DEFAULT_CONFIG):
        try:
            with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except (OSError, ValueError) as exc:
            print(f"[config] 读取 {DEFAULT_CONFIG} 失败，使用默认配置: {exc}", flush=True)

    cfg["poll_interval"] = _float_env("POLL_INTERVAL", cfg["poll_interval"])
    cfg["traffic_interval"] = _int_env("TRAFFIC_INTERVAL", cfg["traffic_interval"])
    cfg["live_span"] = _int_env("LIVE_SPAN", cfg["live_span"])
    cfg["request_timeout"] = _int_env("REQUEST_TIMEOUT", cfg["request_timeout"])
    cfg["sample_retention_days"] = _int_env("SAMPLE_RETENTION_DAYS", cfg["sample_retention_days"])
    cfg["tz_offset"] = _int_env("TZ_OFFSET", cfg["tz_offset"])
    cfg["http_port"] = _int_env("HTTP_PORT", cfg["http_port"])
    cfg["data_dir"] = os.environ.get("DATA_DIR", cfg["data_dir"])

    # 实时速率下限 0.1 秒（亚秒档位）、上限 300 秒，防止误填超大值把线程饿死。
    cfg["poll_interval"] = max(0.1, min(cfg["poll_interval"], 300))
    # 流量统计下限 5 秒、上限 30 分钟（与预设档位一致）。
    cfg["traffic_interval"] = max(5, min(cfg["traffic_interval"], 1800))
    cfg["request_timeout"] = max(1, min(cfg["request_timeout"], 60))
    cfg["sample_retention_days"] = max(1, min(cfg["sample_retention_days"], 365))
    # 实时窗口只接受预设档位，非法值回落默认
    if int(cfg.get("live_span") or 0) not in LIVE_SPAN_CHOICES:
        cfg["live_span"] = DEFAULT_LIVE_SPAN
    return cfg
