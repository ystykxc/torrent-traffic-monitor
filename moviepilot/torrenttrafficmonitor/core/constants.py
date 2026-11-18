"""下载器流量统计插件的常量：采样档位、时间范围、调色板。

本文件由独立部署版 config.py / db.py 中的常量精简而来，去掉了环境变量、
安全加固参数与账户相关配置——插件运行参数全部由 MoviePilot 插件配置页管理。
v1.0.2 删除「实时速率」卡片、实时速率采样设置与「实时」窗口；
v1.0.3 起采集拆成两条节奏：流量统计按配置页的「采样间隔」（默认 1 分钟）
记账，下载器实时速率 / 在线状态按固定 5 秒（RATE_POLL_INTERVAL）刷新内存态，
后者不写入配置页、不提供任何外显设置，也不写历史表。
"""
import colorsys

# ---------------- 采样档位 ----------------
TRAFFIC_POLL_CHOICES = (5, 10, 30, 60, 300, 600, 1800)
TRAFFIC_POLL_LABELS = {
    5: "5 秒", 10: "10 秒", 30: "30 秒", 60: "1 分钟",
    300: "5 分钟", 600: "10 分钟", 1800: "30 分钟",
}
DEFAULT_TRAFFIC_POLL = 60          # 配置页「采样间隔」默认值 = 1 分钟

# 下载器实时速率 / 在线状态的固定采样间隔（5 秒）。仅供采集线程刷新内存实时态
# 使用：不外显到配置页、不写 samples / traffic_samples 历史表、不画实时曲线。
RATE_POLL_INTERVAL = 5

# 图表构建仍保留的兼容默认值（实时速率曲线已不再调用，仅 chart.build 形参需要）
CHART_LIVE_SPAN = 300
CHART_POLL_INTERVAL = 60

DEFAULT_REQUEST_TIMEOUT = 5
DEFAULT_SAMPLE_RETENTION_DAYS = 7
DEFAULT_TZ_OFFSET = 8


def in_choices(value, choices):
    """预设档位匹配：用容差比较，避免 0.1 / 0.2 / 0.5 这类浮点值与 JSON 往返后不等。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return any(abs(v - float(c)) < 1e-9 for c in choices)


# ---------------- 流量统计卡片可选时间范围 ----------------
# 与前端 TRAFFIC_RANGE_ORDER 完全一致（流量统计卡片不含「实时」）。
# 这份清单同时用于「通知」功能的多项选择列表。
TRAFFIC_RANGES = [
    {"value": "1h", "label": "1小时"},
    {"value": "6h", "label": "6小时"},
    {"value": "12h", "label": "12小时"},
    {"value": "24h", "label": "今日"},
    {"value": "yesterday", "label": "昨日"},
    {"value": "week", "label": "本周"},
    {"value": "lastweek", "label": "上周"},
    {"value": "month", "label": "本月"},
    {"value": "lastmonth", "label": "上月"},
    {"value": "year", "label": "本年"},
    {"value": "all", "label": "全部"},
]
TRAFFIC_RANGE_VALUES = tuple(x["value"] for x in TRAFFIC_RANGES)
TRAFFIC_RANGE_LABELS = {x["value"]: x["label"] for x in TRAFFIC_RANGES}

ALL_RANGES = ("live", "1h", "6h", "12h", "24h", "yesterday",
              "week", "lastweek", "month", "lastmonth", "year", "all")

# ---------------- 调色板 ----------------
def _hsl_hex(h, s, l):
    """HSL -> #RRGGBB（标准库，无外部依赖）。"""
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


HUE_SEQ = [174, 294, 240, 60, 354, 120, 216, 273, 45, 324]
DN_PHASE = 30

# 采用 PT Nexus 流量统计页的默认色板精确值：上传一组暖色 / 下载一组冷色，
# 按下载器顺序固定分配，前 5 组区分度极高。
PTNEXUS_PALETTE = [
    ("#f56c6c", "#409eff"),
    ("#e6a23c", "#67c23a"),
    ("#d98a6f", "#8a2be2"),
    ("#fab6b6", "#a0cfff"),
    ("#f7d0a3", "#b3e19d"),
    ("#e8794b", "#2bb3c0"),
    ("#c9a227", "#5b8ff9"),
    ("#b05c7d", "#9270ca"),
    ("#d98f4f", "#48bb78"),
    ("#c96f5a", "#7aa7e8"),
]
PALETTE = PTNEXUS_PALETTE
SUMMARY_UP = "#fb923c"
SUMMARY_DOWN = "#38bdf8"

# 默认通知配置（v1.0.5：首次安装即开启通知）
# 新装插件未保存过任何配置时直接使用这份默认值：每天 22:40 推送一次，
# 默认统计「今日 / 昨日 / 本周 / 本月」四个时间范围。
DEFAULT_NOTIFY = {
    "enabled": True,
    "cron": "40 22 * * *",
    "ranges": ["24h", "yesterday", "week", "month"],
    "channel": None,
}
