"""定期通知：每个时间范围渲染成一张「下载器 / 上传 / 下载」纯文本表格。

汇总规则（v1.0.1）：所有勾选的时间范围合并进**一条**通知，各范围之间用
分隔线区分，不再按范围逐条发送。

单个时间范围的模板（保留 v1.0.6 带表头表格，仅调整横线与圆点）：
    {时间范围名称}流量统计（{自然时间段或日期}）

    +------------+---------------+-------------+
    | 下载器     |     上传      |    下载     |
    +------------+---------------+-------------+
    | 合计       |  🟢↑ 1.01 TB  | 🔴↓ 2.56 TB |
    | QB-01      |  🟢↑ 8.10 GB  | 🔴↓ 40.00 GB|
    +------------+---------------+-------------+

本次相对 v1.0.6 仅两点调整（其余排版一律不变）：
- 段间分隔横线由 12 格改为 24 格（与 v1.0.27 一致）。
- 红绿点换位并加文本方向箭头：上传由 🔴 改 🟢 并紧跟向上箭头 ↑（🟢↑），下载由 🟢 改
  🔴 并紧跟向下箭头 ↓（🔴↓）。
v1.0.30：合计行首列「合计」改为居中对齐。
v1.0.31：合计行居中的填充空格改用 NBSP（U+00A0），因为微信把通知渲染为
  Markdown 表格、会 trim 普通空格，NBSP 不被 trim 才能在微信里真正居中。
v1.0.32：微信把表头居中、数据行左对齐，导致「合计」中心仍比表头「下载器」
  偏左约 2 个 NBSP 宽；合计行首列在此基础上再右偏 2 格，视觉上与表头对齐。

通知是纯文本、没有表格语法，因此用「按显示宽度补齐 + ASCII 边框」画出表格：
中文与 emoji 按 2 格计算宽度、数值列右对齐，列间用 | 明确隔开（不再用制表符，
很多客户端会把 \\t 吞掉导致整行粘在一起）。数据口径直接复用
chart.build(metric="traffic")，与页面上的流量统计卡片完全一致。
"""
import unicodedata

from . import chart, constants, timeutil

# 单条通知里不同时间范围之间的分隔线：24 格（与 v1.0.27 一致）
SECTION_LINE = "─"
SECTION_LINE_COLS = 24
SECTION_SEPARATOR = "\n\n" + SECTION_LINE * SECTION_LINE_COLS + "\n\n"

# ---------------- 表格版式 ----------------
# 表头依次为：下载器、上传、下载（纯文字）
TABLE_HEADER = ("下载器", "上传", "下载")
# 数据行里上传 / 下载数值前：上传=🟢 + 向上箭头↑（🟢↑），下载=🔴 + 向下箭头↓（🔴↓）
# 相对 v1.0.6（上传🔴/下载🟢）红绿点换位，并各跟一个纯文本方向箭头。
ICON_UP = "🟢"
ICON_DOWN = "🔴"
LABEL_UP = "↑"
LABEL_DOWN = "↓"
# 表格边框字符（与 Windows 命令行里输出的 +---+ 表格一致，任何字体都能显示）
BORDER_H = "-"
BORDER_V = "|"
BORDER_C = "+"
# 不加宽度的零宽字符（emoji 变体选择符 / 组合符），算宽度时跳过
_ZERO_WIDTH = ("\ufe0e", "\ufe0f", "\u200b", "\u200c", "\u200d", "\u2060")
# 不换行空格：微信把通知渲染成 Markdown 表格时会 trim 单元格首尾的普通空格，
# 但 NBSP 不会被 trim，故用它填充「合计」的居中空格才能在微信里真正生效。
NBSP = "\u00a0"


def fmt_bytes(n):
    """与前端 fmtBytes 完全一致：1024 进制、两位小数，单位 B/KB/MB/GB/TB/PB。"""
    n = float(n or 0)
    if n < 1024:
        return "%d B" % round(n)
    units = ["KB", "MB", "GB", "TB", "PB"]
    v, i = n, -1
    while True:
        v /= 1024.0
        i += 1
        if not (v >= 1024 and i < len(units) - 1):
            break
    return "%.2f %s" % (v, units[i])


def disp_width(text):
    """字符串的显示宽度：东亚全角字符与 emoji 记 2 格，其余记 1 格。"""
    w = 0
    for ch in str(text):
        if ch in _ZERO_WIDTH or unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad_cell(text, width, align="left", pad=" ", left_bias=0):
    """把单元格补空格到指定显示宽度（left / right / center 三种对齐）。

    pad 可指定填充字符：默认普通空格；合计行首列传 NBSP，避免微信 Markdown
    表格渲染时把居中空格 trim 掉。
    left_bias：center 对齐时额外往右偏移的填充格数（用于补偿微信把表头居中、
    数据左对齐导致的合计与表头中心错位）。
    """
    s = str(text)
    gap = max(0, width - disp_width(s))
    if align == "right":
        return pad * gap + s
    if align == "center":
        left = min(gap, gap // 2 + left_bias)
        return pad * left + s + pad * (gap - left)
    return s + pad * gap


def render_table(rows):
    """把二维数组（首行为表头）渲染成带 ASCII 边框、按显示宽度对齐的纯文本表格。

    形如：
        +--------+----------+----------+
        | 下载器 |   上传   |   下载   |
        +--------+----------+----------+
        | 合计   | 🔴 1 TB  | 🟢 2 TB  |
        +--------+----------+----------+

    用 | 与 +- 显式画线，不依赖制表符，任何客户端都不会把列粘成一行。
    """
    rows = [list(r) for r in rows if r]
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max(disp_width(r[i]) for r in rows) for i in range(ncol)]
    # 表头：首列左对齐、数值列居中；数据行：首列左对齐、数值列右对齐（数字对齐）
    head_align = ["left"] + ["center"] * (ncol - 1)
    body_align = ["left"] + ["right"] * (ncol - 1)
    # v1.0.30：合计行（表头下第一行）首列「合计」居中对齐，数值列仍右对齐不变
    total_align = ["center"] + ["right"] * (ncol - 1)
    border = BORDER_C + BORDER_C.join(BORDER_H * (w + 2) for w in widths) + BORDER_C

    lines = [border]
    for idx, r in enumerate(rows):
        if idx == 0:
            aligns = head_align
        elif idx == 1:
            aligns = total_align
        else:
            aligns = body_align
        # 合计行首列用 NBSP 填充居中：微信 Markdown 表格会 trim 普通空格，
        # 但 NBSP 会保留，这样「合计」在微信里才真正居中；其余单元格不变。
        cells = []
        for i in range(ncol):
            if idx == 1 and i == 0:
                # 合计行首列：NBSP 填充 + 右偏 2 格。微信把第一列渲染成 Markdown
                # 表格时表头居中、数据左对齐，实测「合计」中心比表头「下载器」偏左
                # 约 2 个 NBSP 宽，故在居中基础上再右偏 2 格使其视觉对齐表头。
                cells.append(pad_cell(r[i], widths[i], aligns[i], pad=NBSP, left_bias=2))
            else:
                cells.append(pad_cell(r[i], widths[i], aligns[i]))
        lines.append(BORDER_V + BORDER_V.join(" " + c + " " for c in cells) + BORDER_V)
        if idx == 0:
            lines.append(border)       # 表头与数据的分隔线
    lines.append(border)               # 表格底边
    return "\n".join(lines)


def describe_range(range_key, start, end):
    """把窗口 [start, end) 备注成具体的自然时间段或者日期。"""
    s = timeutil.local_dt(start)
    # end 是右开边界，取最后一秒所在的墙上时间
    e = timeutil.local_dt(max(start, end - 1))
    if range_key in ("24h", "yesterday"):
        return s.strftime("%Y-%m-%d")
    if range_key in ("month", "lastmonth"):
        return s.strftime("%Y-%m")
    if range_key == "year":
        return s.strftime("%Y")
    if range_key in ("week", "lastweek", "all"):
        return "%s ~ %s" % (s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))
    # 1小时 / 6小时 / 12小时：精确到分钟的起止时间段
    if s.strftime("%Y-%m-%d") == e.strftime("%Y-%m-%d"):
        return "%s ~ %s" % (s.strftime("%Y-%m-%d %H:%M"), e.strftime("%H:%M"))
    return "%s ~ %s" % (s.strftime("%Y-%m-%d %H:%M"), e.strftime("%Y-%m-%d %H:%M"))


def build_section(range_key, cfg):
    """生成单个时间范围的一段通知文字：标题 + 空行 + 三列表格。"""
    data = chart.build(
        range_key, "traffic",
        live_span=constants.CHART_LIVE_SPAN,
        poll_interval=constants.CHART_POLL_INTERVAL,
        traffic_interval=cfg.get("traffic_interval", constants.DEFAULT_TRAFFIC_POLL),
        offset=0,
    )
    w = data["window"]
    label = constants.TRAFFIC_RANGE_LABELS.get(range_key, range_key)
    period = describe_range(range_key, w["start"], w["end"])

    up_total = int(data["summary"].get("up") or 0)
    down_total = int(data["summary"].get("down") or 0)

    # 表头 → 合计行 → 各下载器行（0 流量也照常列出，顺序与卡片一致）
    # 数值前：上传=🟢↑、下载=🔴↓（圆点后紧跟文本箭头，箭头后再空格接数值）
    def cell(icon, arrow, value):
        return "%s%s %s" % (icon, arrow, fmt_bytes(value))

    rows = [list(TABLE_HEADER)]
    rows.append([
        "合计",
        cell(ICON_UP, LABEL_UP, up_total),
        cell(ICON_DOWN, LABEL_DOWN, down_total),
    ])
    for s in data["series"]:
        if s["id"] == 0:
            continue
        up = sum(v or 0 for v in s["up"])
        down = sum(v or 0 for v in s["down"])
        rows.append([
            s["name"],
            cell(ICON_UP, LABEL_UP, up),
            cell(ICON_DOWN, LABEL_DOWN, down),
        ])

    return "%s流量统计（%s）\n\n%s" % (label, period, render_table(rows))


def build_message(ranges, cfg):
    """把所有选中的时间范围汇总进一条通知，返回 (title, text)。

    各时间范围之间用 SECTION_SEPARATOR 分隔，每段内部是一张独立表格。
    """
    sections = []
    for key in ranges:
        if key not in constants.TRAFFIC_RANGE_VALUES:
            continue
        try:
            sections.append(build_section(key, cfg))
        except Exception as exc:
            label = constants.TRAFFIC_RANGE_LABELS.get(key, key)
            sections.append("%s流量统计\n数据读取失败：%s" % (label, str(exc)[:120]))
    if not sections:
        return ("下载器流量统计", "没有可统计的时间范围")
    return ("下载器流量统计", SECTION_SEPARATOR.join(sections))


def build_messages(ranges, cfg):
    """兼容旧调用签名：返回仅含一条汇总通知的列表 [(title, text)]。

    v1.0.1 起不再「一个时间范围一条通知」；_send_notify / notify/test / preview
    都只发出这一条，宿主消息中心里就是一条完整的汇总消息。
    """
    return [build_message(ranges, cfg)]


def normalize_ranges(value):
    """把配置里的多选值规范成合法的时间范围列表，保持前端展示顺序。"""
    if isinstance(value, str):
        value = [x for x in value.replace("，", ",").split(",") if x.strip()]
    if not isinstance(value, (list, tuple)):
        return []
    seen, out = set(), []
    for x in value:
        k = str(x).strip()
        if k in constants.TRAFFIC_RANGE_VALUES and k not in seen:
            seen.add(k)
            out.append(k)
    # 按 TRAFFIC_RANGES 的固定顺序输出，保证通知顺序稳定
    order = {k: i for i, k in enumerate(constants.TRAFFIC_RANGE_VALUES)}
    return sorted(out, key=lambda k: order[k])


def validate_cron(expr):
    """校验五位 cron 表达式，返回规范化字符串；非法时抛 ValueError。"""
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        raise ValueError("cron 必须是 5 位表达式（分 时 日 月 周），例如：40 22 * * *")
    # 交给 APScheduler 做权威校验（MoviePilot 宿主必然自带）
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger.from_crontab(" ".join(parts))
    except Exception as exc:
        raise ValueError("cron 表达式不合法：%s" % exc)
    return " ".join(parts)
