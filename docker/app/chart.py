"""统一图表数据：12 档时间范围 × 速率/流量，返回「汇总 + 每个下载器」的多系列。

数据源按窗口跨度自动路由到单张表，避免混表 UNION 与重复全表扫描：
- 速率 (metric=rate)：采样类范围（实时 / 1 / 6 / 12 小时）取 samples 做 AVG；
  自然周期短窗口同样取 samples，长窗口取 hourly 按小时整数倍分桶，目标
  120 点、下限 24、上限 180，保证周期刚开始也有足够数据点。
- 流量 (metric=traffic)：采样类范围取 traffic_samples 的累计差值（SUM），
  raw 保留期不足时自动切到 rollup_1m；自然周期取 hourly，今日/昨日按小时、
  周/上周/本月/上月按天、本年按月。「全部」按数据库跨度自适应为自然日 /
  月 / 季度 / 年桶，按自然日历边界切分。
- rollup_1m / rollup_1d 由后台任务幂等物化，db.bounds() 缓存时间边界，
  分桶预算先算硬上界；offset 横向平移不改变桶数，最多回看 30 个窗口。

所有系列一次性返回，前端只发一个请求即可画任意组合的折线/柱状图。响应附带
window{start,end,label}、offset / max_offset / bucket_count / at_latest，供
拖动区间文字与「回到最新」使用；停用下载器不出现在 series 中。

统计口径恒为「累计计数器单调差值」（见 docs/流量统计口径深度解析.md）：
流量只来自差值，速率只画曲线、绝不累加；中间漏采空桶线性插值填补，
头尾无数据的桶保持空白。所有展示数值四舍五入保留两位小数。
"""
import bisect
import calendar
import math
import time
from datetime import timedelta

from . import db, timeutil

# (窗口秒数, 旧版桶秒数)；起采样类桶宽统一按 CHART_POINTS 等分，第二项仅保留兼容。
# 24h 从滚动采样窗口改为「今日」自然日（按小时取 hourly），不再属于这一类。
RATE_RANGES = {
    "1h": (3600, 60),
    "6h": (21600, 300),
    "12h": (43200, 600),
}
# 新增 yesterday / lastweek / lastmonth，分别紧跟 24h(今日) / week(本月) /
# month(本月) 之后。24h 是历史内部 key，界面文案与取值逻辑都是「今日」。
# 末尾新增「全部」，覆盖数据库中所有已采集数据（最早采样/小时桶 → 当前时刻）
ALL_RANGES = ("live", "1h", "6h", "12h", "24h", "yesterday",
              "week", "lastweek", "month", "lastmonth", "year", "all")
METRICS = ("rate", "traffic")
# CHART_POINTS 是「流量柱状图」采样类范围（live / 1h / 6h / 12h）的**最多**
# 等分桶数。起桶数还会按「流量统计采样间隔」收敛（可能少于 12），
# 保证绘制点不比流量统计采样点更密；速率折线图自 起不走这个常量。
CHART_POINTS = 12
# 速率折线最多给多少个数据点（桌面每点 3~5px）。前端 targetPoints('rate')
# 的上限与此处保持一致。
RATE_MAX_POINTS = 180
# 速率图自适应粒度（参考 sqing33/PTNexus resolveTimeRange / GetSpeedChartData）。
# 长窗口目标点数 120；任何 rate 窗口的点数下限 24（周期刚开始也不能只剩 1 个点）；
# 跨度 ≤48h 用 samples 细粒度、>48h 用 hourly 粗粒度（ptnexus 的「近细远粗」）。
RATE_TARGET_POINTS = 120
RATE_MIN_POINTS = 24
RATE_FINE_SPAN = 48 * 3600

# 速率折线「绘制点密度」—— 每个绘制点覆盖的秒数按窗口跨度
# 分段线性插值。锚点由用户明确指定：
# 1h (3600s) → 2s/点 （至少 2 秒一个绘制点 ⇒ 1800 点）
# 6h (21600s) → 15s/点 （至少 15 秒一个绘制点 ⇒ 1440 点）
# 24h (86400s) → 60s/点 （昨日/今日至少 1 分钟一个绘制点 ⇒ 1440 点）
# 之间的跨度（如 12h）按比例插值（12h → 30s/点 ⇒ 1440 点）。
# 后端按此「给足」绘制点（不再受旧的 RATE_MAX_POINTS=180 限制）；前端
# app.js 的 targetPoints('rate') 再按「1 像素最多 1 点」把点数收敛到绘图区
# 像素宽度——算出 1 像素挤了多个点就降密度，保证 1 像素最多 1 个绘制点。
RATE_DENSITY_ANCHORS = ((3600, 2), (21600, 15), (86400, 60))
# 给足点后的绝对上限：防止极端跨度（如刚好落在 fine 分支的长自然周期）
# 把点数撑到 memory/JSON 都吃不消；前端仍会再按像素宽度收敛一次。
RATE_STEP_MAX_POINTS = 2000


def _rate_target_step(span):
    """按窗口跨度（秒）线性插值出「目标绘制点间隔」（秒，恒 >=1）。

    短于 1h 时按比例向 1s 收敛；超过 24h 保持 60s（更长窗口另由 hourly
    粗粒度分支处理，本函数只作用于 samples 细粒度窗口）。返回值不要求是
    采样间隔的整数倍：采样稀疏造成的空桶由 _fill_rate_gaps() 线性插值补点，
    从而「绘制点」始终给足、曲线保持密集。
    """
    s = max(1, int(span))
    a = RATE_DENSITY_ANCHORS
    if s <= a[0][0]:
        return max(1, min(a[0][1], round(a[0][1] * s / a[0][0])))
    for i in range(len(a) - 1):
        x0, y0 = a[i]
        x1, y1 = a[i + 1]
        if s <= x1:
            return max(1, round(y0 + (y1 - y0) * (s - x0) / (x1 - x0)))
    return a[-1][1]


def _wall_ts(dt):
    """local_dt 返回的是「用 UTC 对象承载的本地墙上时间」，减偏移得真实 Unix 秒。"""
    return dt.timestamp() - timeutil.OFFSET


def _shift_months(dt, delta):
    """按整月平移，日超出目标月天数时收敛到该月最后一天。"""
    idx = dt.year * 12 + (dt.month - 1) + delta
    y, m0 = divmod(idx, 12)
    m = m0 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def _day0(local, delta=0):
    return (local + timedelta(days=delta)).replace(
        hour=0, minute=0, second=0, microsecond=0)


def _monday0(local):
    return _day0(local, -local.weekday())


def _month0(local, delta=0):
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _shift_months(first, delta) if delta else first


def _period_bounds(range_key, local):
    """速率图自然周期窗口 [start, end)，返回「UTC 对象承载的本地墙上时间」。

    今日 / 本周 / 本月 / 本年：起点为周期首日 0 点，终点为**当前时刻** ——
    绝不把还没发生的未来时间画进图里。
    昨日 / 上周 / 上月：完整过去周期，终点为该周期的右边界。
    """
    if range_key == "24h":
        return _day0(local), local
    if range_key == "yesterday":
        return _day0(local, -1), _day0(local)
    if range_key == "week":
        return _monday0(local), local
    if range_key == "lastweek":
        m = _monday0(local)
        return m - timedelta(days=7), m
    if range_key == "month":
        return _month0(local), local
    if range_key == "lastmonth":
        first = _month0(local)
        return _shift_months(first, -1), first
    # year
    return local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), local


def _traffic_period(range_key, local):
    """流量图自然周期窗口：返回 (起点 dt, 桶数 n, 单位 unit)。

    保持 的自然周期口径不变，只补齐三个新范围：
      昨日 = 24 个小时桶、上周 = 7 个日桶、上月 = 上月实际天数的日桶。
    """
    if range_key == "24h":
        return _day0(local), local.hour + 1, "hour"
    if range_key == "yesterday":
        return _day0(local, -1), 24, "hour"
    if range_key == "week":
        return _monday0(local), local.weekday() + 1, "day"
    if range_key == "lastweek":
        return _monday0(local) - timedelta(days=7), 7, "day"
    if range_key == "month":
        return _month0(local), local.day, "day"
    if range_key == "lastmonth":
        first = _month0(local)
        lm = _shift_months(first, -1)
        return lm, (first - lm).days, "day"
    # year
    return (local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            local.month, "month")


def _sample_buckets(range_key, now, live_span, poll_interval, traffic_interval,
                    offset, metric, count_only=False):
    """live / 1h / 6h / 12h：滚动窗口。

    rate：桶宽＝采样间隔的整数倍，采样点给足（上限 RATE_MAX_POINTS）；
    traffic：按「流量统计采样间隔」收敛的等分桶。
    右端只取到「已完成的完整桶」，最后一个时间点不会空白 / 断尾。
    绘图点密度不得超过采样数据密度，见下方两处 max(step, pi/ti)。
    """
    # poll_interval（实时速率）允许 0.1 / 0.2 / 0.5 秒亚秒档位，图表分桶仍按
    # 整数秒对齐：亚秒档位只让采集器写库更密、桶内 AVG 更细腻；若直接把 0.1
    # 当作 step，times / spans 会变成浮点、SQL CAST 边界失准，故向上取整到 1 秒。
    pi = max(1, math.ceil(float(poll_interval or 5)))
    # traffic_interval（流量统计）是整数秒档位（5 秒 ~ 30 分钟）。
    ti = max(1, int(float(traffic_interval or 60)))
    if range_key == "live":
        span = max(30, int(live_span or 300))
    else:
        span = RATE_RANGES[range_key][0]

    if metric == "rate":
        if range_key == "live":
            # live 档保持「采样间隔整数倍 + RATE_MAX_POINTS 上限」原逻辑，
            # 与 app.js 的 1 秒刷新 / 帧平移节奏配套（天然满足）。
            k = max(1, math.ceil(span / (pi * RATE_MAX_POINTS)))
            step = min(span, pi * k)
        else:
            # 1h / 6h / 12h 按目标密度给足绘制点（1h→2s / 点、
            # 6h→15s / 点、12h→30s / 点），不再被旧的 180 点上限掐断。
            step = min(span, max(1, _rate_target_step(span)))
            # 绘制点不能比采样点更密 —— step 至少为一个实时速率
            # 采样间隔，于是 span/step ≤ 窗口内采样点数。否则采样 5 秒却按
            # 2 秒一个绘制点，多个绘制点会共用同一个采样值（_fill_rate_gaps
            # 插值后数值一致），白白增加绘图次数却不增加信息量。
            step = min(span, max(step, pi))
            if span / step > RATE_STEP_MAX_POINTS:
                step = max(step, math.ceil(span / RATE_STEP_MAX_POINTS))
        n = max(1, span // step)
    else:
        # 流量统计短窗口的采样点来自 traffic_samples（密度＝ti），
        # 绘图点按 ti 封顶、桶数按「窗口内采样数据量」收敛，不再固定 12 桶。
        if range_key == "live":
            step = max(ti, int(round(span / CHART_POINTS)) or 1)
        else:
            step = max(1, int(round(span / CHART_POINTS)))
            step = max(step, ti)
        step = min(step, span)
        n = max(1, span // step)

    if count_only:
        return n
    end_aligned = math.floor((now - offset * step) / step) * step
    start = end_aligned - n * step
    # 最新窗口把「不足一个完整桶」的尾部采样并入最后一个桶，避免
    # floor 对齐把最近 <step 秒的数据整段丢掉（图表单位不足 / 数据遗漏）。
    # 历史窗口（offset>0）不并入，否则会串进更新的窗口。
    extra = 0 if offset else max(0, int(now - end_aligned))
    end = end_aligned + extra
    buckets = []
    # 把 label 的 strftime 格式随桶带出，供 build 给折线末端刻度
    # 补「窗口右端时刻」时复用同一格式（去日期 / 时间精度完全一致）。
    lfmt = "%H:%M:%S" if step < 60 else "%H:%M"
    for i in range(n):
        ts = start + i * step
        buckets.append({
            "ts": ts, "seconds": step + (extra if i == n - 1 else 0), "key": i,
            # 统一分桶宽度单独存一份。最后一个桶的 seconds 会并入尾部
            # extra，不能直接拿它当 SQL 的 CAST 分母（n=1 时尤其会错）。
            "step": step,
            "label": timeutil.local_dt(ts).strftime(lfmt),
            "lfmt": lfmt,
        })
    return start, buckets, "samples", end


def _rate_natural_buckets(range_key, now, poll_interval, offset, samples_min_ts,
                          count_only=False):
    """速率图自然周期 —— 按「窗口跨度」自适应粒度（参考 ptnexus）。

    短窗口（跨度 ≤ RATE_FINE_SPAN 且 samples 覆盖得到）→ samples 采样点给足；
    长窗口 → hourly 表按小时整数倍分桶，目标 120 点、下限 24、上限 180。
    samples 保留期不足时自动回退 hourly，绝不画空图。
    """
    # poll_interval 允许 0.1 / 0.2 秒亚秒档位。图表分桶仍按整数秒对齐，
    # 亚秒档位只让采集器写库更密、桶内 AVG 更细腻；若直接把 0.1 当作 step，
    # times / spans 会变成浮点、SQL CAST 边界失准，故统一向上取整到 1 秒。
    pi = max(1, math.ceil(float(poll_interval or 5)))
    local = timeutil.local_dt(now)
    start_dt, end_dt = _period_bounds(range_key, local)
    start, hard_end = _wall_ts(start_dt), _wall_ts(end_dt)
    # 再向下对齐到完整桶边界：最后一个时间点必然有数据，不会断尾
    span = max(1, int(hard_end - start))

    fine = (span <= RATE_FINE_SPAN and samples_min_ts is not None
            and samples_min_ts <= start)
    if fine:
        # 今日 / 昨日（自然周期且跨度 ≤48h、samples 覆盖得到）
        # 同样按目标密度给足绘制点：昨日(24h)→60s/点 ⇒ 1440 点，满足「至少
        # 1 分钟一个绘制点」；今日按当前跨度比例插值。step 非采样间隔整数倍
        # 造成的空桶由 _fill_rate_gaps 线性插值补点。
        step = min(span, max(1, _rate_target_step(span)))
        # 细粒度分支的源是 samples，同一道判定 —— 绘制点间隔
        # 不小于实时速率采样间隔，绘制点数不超过窗口内采样点数。
        step = min(span, max(step, pi))
        if span / step > RATE_STEP_MAX_POINTS:
            step = max(step, math.ceil(span / RATE_STEP_MAX_POINTS))
        source = "samples"
    else:
        span_h = span / 3600.0
        # 目标 120 点；但不允许粗到让点数 < 24，也不允许细到 > 180 点
        step_h = max(1, min(math.ceil(span_h / RATE_TARGET_POINTS),
                            max(1, int(span_h // RATE_MIN_POINTS))))
        step_h = max(step_h, math.ceil(span_h / RATE_MAX_POINTS))
        step = step_h * 3600
        source = "hourly-span"

    # n 向上取整，让「不足一个完整桶」的尾部也拥有自己的时间点；
    # window_end 直接取硬边界（当前时刻 / 完整过去周期右边界），SQL 查到它，
    # 尾部数据不再被 floor(span/step) 丢掉（旧实现上月/本年分别漏 2h / 8h）。
    n = max(1, int(math.ceil(span / step)))
    if count_only:
        return n
    end = hard_end
    # offset 单位就是一个 X 轴刻度（桶），整体左移，窗口形状恒定
    start -= offset * step
    end -= offset * step
    buckets = []
    for i in range(n):
        ts = int(start + i * step)
        fmt = "%m-%d" if step >= 86400 else "%m-%d %H:%M"
        buckets.append({"ts": ts, "seconds": step, "key": i,
                        "label": timeutil.local_dt(ts).strftime(fmt), "lfmt": fmt})
    return start, buckets, source, end


def _traffic_natural_buckets(range_key, now, offset, count_only=False):
    """流量图自然周期：今日 / 昨日按小时、周 / 上周 / 本月 / 上月按天、本年按月。

    只补齐三个新范围，聚合键（hour_ts / day / month）与桶宽全部沿用旧口径，
    顶部汇总卡与统计口径零改动。
    """
    local = timeutil.local_dt(now)
    first0, n, unit = _traffic_period(range_key, local)
    if count_only:
        return n
    if unit == "hour":
        first = first0 - timedelta(hours=offset)
        seconds, source = 3600, "hourly-hour"
    elif unit == "day":
        first = first0 - timedelta(days=offset)
        seconds, source = 86400, "hourly-day"
    else:
        first = _shift_months(first0, -offset)
        seconds, source = 86400 * 30, "hourly-month"

    last = _shift_months(first, n - 1)
    cross_year = first.year != last.year
    buckets = []
    for i in range(n):
        if unit == "hour":
            d = first + timedelta(hours=i)
        elif unit == "day":
            d = first + timedelta(days=i)
        else:
            d = _shift_months(first, i)
        ts = int(_wall_ts(d))
        if unit == "hour":
            key, label = ts, d.strftime("%H:00")
        elif unit == "day":
            key, label = d.strftime("%Y-%m-%d"), d.strftime("%m-%d")
        else:
            key = d.strftime("%Y-%m")
            label = d.strftime("%y/%m") if cross_year else d.strftime("%m月")
        buckets.append({"ts": ts, "seconds": seconds, "key": key, "label": label})

    if unit == "hour":
        end_dt = first + timedelta(hours=n)
    elif unit == "day":
        end_dt = first + timedelta(days=n)
    else:
        end_dt = _shift_months(first, n)
    return _wall_ts(first), buckets, source, _wall_ts(end_dt)


def _all_buckets(now, offset, db_min_ts, count_only=False):
    # 「全部」—— 覆盖数据库中所有已采集数据（最早数据 → 当前时刻）。
    # 粒度按跨度自适应（小时整数倍），目标 120 点、下限 24、上限 180；
    # 用 hourly 字节 / 覆盖秒数算平均速率。前期无数据的桶保持空，
    # 不会凭空补水平线。
    # 本函数现只服务**速率卡片**的「全部」（点云给足，避免被压成 20~30
    # 个点）；流量统计卡片的「全部」改由 _all_traffic_buckets 按自然日 / 月 /
    # 季度 / 年分桶（见其注释），两卡时间轴各自独立、由前端分别渲染 / 拖动。
    first = float(db_min_ts) if db_min_ts is not None else now - 86400
    first = min(first, now - 3600)
    span = max(3600, int(now - first))
    span_h = span / 3600.0
    step_h = max(1, min(math.ceil(span_h / RATE_TARGET_POINTS),
                        max(1, int(span_h // RATE_MIN_POINTS))))
    step_h = max(step_h, math.ceil(span_h / RATE_MAX_POINTS))
    step = step_h * 3600
    # 起点直接取数据库最早数据，不再向下对齐到桶边界 —— 否则「全部」的区间
    # 文字会显示得比实际最早数据还早（例如 03-01 的数据被显示成 02-28）。
    start0 = first
    n = max(1, int(math.ceil((now - start0) / step)))
    if count_only:
        return n
    start = start0 - offset * step
    end = now - offset * step
    buckets = []
    for i in range(n):
        ts = int(start + i * step)
        fmt = "%Y-%m-%d" if step >= 86400 else "%m-%d %H:%M"
        buckets.append({"ts": ts, "seconds": step, "key": i,
                        "label": timeutil.local_dt(ts).strftime(fmt), "lfmt": fmt})
    return start, buckets, "hourly-all", end


def _all_traffic_buckets(now, offset, db_min_ts, count_only=False):
    """流量统计卡片「全部」—— 按数据库跨度的自然日历粒度分桶。

    与 _all_buckets（速率卡片「全部」，按小时整数倍自适应、最多 180 点）分开：
    用户要求「全部」的每个上传/下载柱组按**自然日 / 自然月 / 自然季度 /
    自然年**聚合，粒度由数据库覆盖的跨度决定（阈值均为「大于」严格判定）：
        默认                        -> 自然日
        数据库自然天数   > 30 天    -> 自然月
        数据库自然月数   > 24 个月  -> 自然季度
        数据库自然季度数 > 20 个    -> 自然年
    四个条件级联覆盖（跨度更大时必然同时满足更细的条件），取最粗的一档。
    于是各档点数上限恰好是 30 / 24 / 20，配合 前端柱宽可缩到 3px，
    数据点既完整又不会糊成一片。

    桶按**自然日历边界**切分（本地墙上时间，复用 _wall_ts / _shift_months），
    从数据库最早数据所在的自然单位起、到当前所在的自然单位止，逐单位一个
    桶；月 / 季度 / 年不等宽，seconds 取相邻两边界的真实差值，spans / 区间
    文字都精确。offset 单位＝一个自然单位，窗口形状（桶数 n）恒定。
    """
    first = float(db_min_ts) if db_min_ts is not None else now - 86400
    first = min(first, now - 3600)
    lf, ln = timeutil.local_dt(first), timeutil.local_dt(now)

    day0, dayn = _day0(lf), _day0(ln)          # 最早数据日 0 点 / 今天 0 点
    days = (dayn - day0).days + 1
    month0 = _month0(lf)                       # 最早数据月 1 日 0 点
    months = (ln.year - month0.year) * 12 + (ln.month - month0.month) + 1

    def q_abs(y, m):
        return y * 4 + (m - 1) // 3
    quarters = q_abs(ln.year, ln.month) - q_abs(month0.year, month0.month) + 1

    unit = "day"
    if days > 30:
        unit = "month"
    if months > 24:
        unit = "quarter"
    if quarters > 20:
        unit = "year"

    if unit == "day":
        unit0, n = day0, days
        advance = lambda d, k: d + timedelta(days=k)
    elif unit == "month":
        unit0, n = month0, months
        advance = lambda d, k: _shift_months(d, k)
    elif unit == "quarter":
        qm = (month0.month - 1) // 3 * 3 + 1   # 所在季度的首月
        unit0, n = month0.replace(month=qm), quarters
        advance = lambda d, k: _shift_months(d, 3 * k)
    else:
        unit0, n = month0.replace(month=1), ln.year - month0.year + 1
        advance = lambda d, k: _shift_months(d, 12 * k)
    n = max(1, int(n))
    if count_only:
        return n

    first_unit = advance(unit0, -offset)        # offset 单位＝一个自然单位
    buckets = []
    for i in range(n):
        d = advance(first_unit, i)
        nx = advance(first_unit, i + 1)
        ts = int(_wall_ts(d))
        seconds = max(1, int(_wall_ts(nx) - _wall_ts(d)))
        if unit == "day":
            label = d.strftime("%m-%d")
        elif unit == "month":
            label = d.strftime("%y/%m")
        elif unit == "quarter":
            label = "%02dQ%d" % (d.year % 100, (d.month - 1) // 3 + 1)
        else:
            label = d.strftime("%Y")
        buckets.append({"ts": ts, "seconds": seconds, "key": i, "label": label})
    # 起点取 first_unit、右端取第 n 个单位的边界（与 _traffic_natural_buckets
    # 「本月 / 本年」一致，右端可略超当前时刻，由 build 的 label_end 夹到 now）。
    start = int(_wall_ts(first_unit))
    window_end = int(_wall_ts(advance(first_unit, n)))
    return start, buckets, "hourly-all-natural", window_end


def _buckets(range_key, now, live_span, poll_interval, offset=0, metric="rate",
             samples_min_ts=None, db_min_ts=None, traffic_interval=60,
             count_only=False):
    """返回 (start_ts, buckets, source, window_end)；count_only=True 时只返回桶数 n。

    起按 metric 分派：
      - rate + 采样类（live / 1h / 6h / 12h）：滚动窗口，采样点给足
      - rate + 自然周期：按窗口跨度自适应粒度（详见 _rate_natural_buckets）
      - traffic + 采样类：等分桶
      - traffic + 自然周期：今日/昨日按小时、周/上周/本月/上月按天、本年按月
      - traffic + 全部：自然日 / 月 / 季度 / 年（按数据库跨度自适应）
      - rate + 全部：沿用 _all_buckets 的自适应小时桶
    offset 为往前平移的桶数，窗口桶数在平移前后保持恒定。
    底层数据不足时补零 / 保持 None，不会为凑数凭空造数据。

    count_only 让 build() 用一次「纯算术」拿到桶数即可先 clamp
    offset，随后只完整生成一次分桶；既不重复生成 buckets / labels / spans，
    也避免超大 offset 在自然周期分支里造成 datetime 年份溢出。
    """
    if range_key == "all":
        # 流量统计卡片「全部」按自然日 / 月 / 季度 / 年分桶（每个柱组
        # 一个自然单位）；速率卡片「全部」仍走 _all_buckets 的自适应小时桶，
        # 保持 「点数给足」的折线密度，不被压成 20~30 个点。
        if metric == "traffic":
            return _all_traffic_buckets(now, offset, db_min_ts, count_only)
        return _all_buckets(now, offset, db_min_ts, count_only)
    if range_key == "live" or range_key in RATE_RANGES:
        return _sample_buckets(range_key, now, live_span, poll_interval,
                               traffic_interval, offset, metric, count_only)
    if metric == "rate":
        return _rate_natural_buckets(range_key, now, poll_interval, offset,
                                     samples_min_ts, count_only)
    return _traffic_natural_buckets(range_key, now, offset, count_only)


def _fill_rate_gaps(series):
    """速率折线里「两个真实采样之间」的空桶（None）用线性插值填补。

    把桶宽缩到恰好等于采样间隔，只要采集时刻稍微抖动，某些桶就会一个采样
    都没有；前端 drawLines 遇到 null 就 flush 一段，于是折线出现「断掉的线段」。
    ptnexus 的做法是给缺失时间点填 0，但那样会画出突然掉到 0 的假谷；本项目用
    线性插值更贴合真实采集数据。

    关键修正：头部 / 尾部的空桶**不是漏采**，而是「项目还没跑到那么早 /
    那么晚」，数据库里本来就没有数据。曾把首尾缺口用最近一个真实值补齐，
    结果项目刚部署 3 天时，本周 / 本月 / 本年窗口前面几天会被最早时刻的值铺成
    一条假的水平线。这些桶必须保持 None —— 前端 drawLines 遇到 null 会跳过，
    折线自然从第一个真实采样开始，前期留白而不画线。

    - 头部缺口（首个真实采样之前）：保持 None，不画线
    - 尾部缺口（末个真实采样之后）：保持 None，不画线
    - 中间缺口（两侧都有真实采样）：线性插值，消除漏采造成的断线
    - 整条线全空：保持 None，前端照常显示「暂无采样数据」
    只改展示数组，不碰 samples / hourly，流量统计口径零影响。

    汇总线（series[0]）不再独立插值，改为在「各下载器线插值后」
    逐点重新求和。旧实现把汇总线与各下载器线各自独立插值：汇总线因「总有
    下载器写了 0 速率」而处处有值、不会被插值，个别下载器偶发漏采的桶却被
    线性插值补上速度 —— 该桶就出现「汇总 0 < 单下载器 100」，正是用户反馈
    的「5 个下载器有一个有速度，但汇总下载器的速度是 0」。重算后汇总线恒
    等于各下载器线之和；头 / 尾缺口仍保持 None，不画假水平线。
    """
    def fill(arr):
        known = [i for i, v in enumerate(arr) if v is not None]
        if len(known) < 2:
            return
        first, last = known[0], known[-1]
        for i in range(first + 1, last):
            if arr[i] is not None:
                continue
            lo = max(k for k in known if k < i)
            hi = min(k for k in known if k > i)
            a, b = arr[lo], arr[hi]
            arr[i] = round(a + (b - a) * (i - lo) / (hi - lo), 2)
    # 只插值各下载器线；汇总线留到最后按求和重建，绝不独立插值。
    for s in series:
        if s["id"] == 0:
            continue
        fill(s["up"])
        fill(s["down"])
    s0, others = series[0], series[1:]
    for key in ("up", "down"):
        arr0 = s0[key]
        for i in range(len(arr0)):
            vs = [s[key][i] for s in others if s[key][i] is not None]
            # 就地覆盖（不重新绑定列表对象），保持 build 里 sum_up /
            # sum_down 的同一引用，让后面的 summary 峰值跟着同步。全 None
            # 的点保持 None —— 头 / 尾缺口不画假水平线。
            arr0[i] = round(sum(vs), 2) if vs else None
    return series


def build(range_key, metric, live_span=300, poll_interval=5, offset=0,
          traffic_interval=60):
    """poll_interval = 实时速率采样间隔；traffic_interval = 流量统计采样间隔。"""
    if range_key not in ALL_RANGES:
        raise ValueError("不支持的时间范围：%s" % range_key)
    if metric not in METRICS:
        raise ValueError("不支持的指标：%s" % metric)
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    now = time.time()
    # 每次请求都做三处 MIN(ts) 全表扫描。合并成 db.bounds
    # 的一次查询 + 30 秒 TTL 缓存（cleanup / rollup 后主动失效），把「每次
    # /api/chart 都全表扫」降为「每分钟最多一次」，且新数据只会让下界变大，
    # 缓存绝不会读到脏的最早时间。
    b = db.bounds()
    samples_min_ts = b["samples_min_ts"]
    hourly_min_ts = b["hourly_min_ts"]
    traffic_min_ts = b["traffic_min_ts"]
    # 「全部」从数据库最早一条已采集数据起算；rollup_1m 的起点
    # 也纳入，因为它保留 90 天，比只留 7 天的 traffic_samples 更能反映
    # 「细粒度数据的最早边界」。
    _mins = [v for v in (samples_min_ts, hourly_min_ts, traffic_min_ts,
                         b.get("rollup_1m_min_ts")) if v is not None]
    db_min_ts = min(_mins) if _mins else None

    # 桶数 n 与 offset 无关。先用 count_only 的**纯算术**（不生成
    # buckets / labels / spans、不查 SQL）拿到 n 并 clamp offset，随后只完整
    # 生成一次分桶。相比 「为算 max_offset 先完整调用一次 _buckets 再
    # 正式调用一次」，重复计算彻底消除；offset 在传入分桶函数前已被限制在
    # 30*n 内，自然周期分支不会再因超大 offset 触发 datetime 年份溢出。
    n0 = _buckets(range_key, now, live_span, poll_interval, 0,
                  metric, samples_min_ts, db_min_ts, traffic_interval,
                  count_only=True)
    max_offset = 30 * int(n0)
    offset = min(offset, max_offset)
    start, buckets, source, window_end = _buckets(
        range_key, now, live_span, poll_interval, offset,
        metric, samples_min_ts, db_min_ts, traffic_interval)
    n = len(buckets)

    # 流量短窗口按「窗口跨度 + 数据边界」只选一张表。
    # raw 覆盖窗口起点 -> traffic_samples（明细，SUM 增量，口径与 一致）
    # raw 过期但 1m 层覆盖 -> rollup_1m（1 分钟桶，自动 rollup 生成）
    # 都不覆盖 -> 仍读 traffic_samples，前端照常显示空图
    # 这里是 UNION ALL traffic_samples + samples 混表，语义不同且随历史量
    # 线性变慢；升级前的历史 inc 已由 db.init_db 一次性迁入 traffic_samples，
    # 因此这里可以彻底只读一张表。
    if source == "samples" and metric == "traffic":
        if (b.get("rollup_1m_min_ts") is not None and
                (traffic_min_ts is None or traffic_min_ts > start) and
                b["rollup_1m_min_ts"] <= start):
            source = "rollup-1m"
        else:
            source = "traffic-raw"
    # 停用下载器从两张图表（图例 / 折线 / 堆叠柱 / 汇总线）完全移除；
    # idset 与 ids 均来自 dls，SQL 里停用下载器的行会被自动丢弃。
    dls = db.list_downloaders(enabled_only=True)
    ids = [d["id"] for d in dls]
    idset = set(ids)
    per = {i: {"up": [None] * n, "down": [None] * n} for i in ids}
    zero = 0 if metric == "traffic" else None

    with db.conn() as c:
        if source in ("samples", "traffic-raw", "rollup-1m"):
            step = buckets[0].get("step", buckets[0]["seconds"])
            # 每种 source 只查一张表，UNION ALL 已彻底删除。
            # samples -> 实时速率曲线（AVG 速率）
            # traffic-raw-> 流量明细（SUM 累计计数器差值）
            # rollup-1m -> raw 过期后的 1 分钟物化层（SUM 字节，自动 rollup 生成）
            if source == "samples":
                sql = ("SELECT downloader_id, CAST((ts - ?)/? AS INTEGER) AS b, "
                       "AVG(dl_rate) AS dlr, AVG(up_rate) AS upr, "
                       "0 AS dlb, 0 AS upb FROM samples "
                       "WHERE ts>=? AND ts<? GROUP BY downloader_id, b")
            elif source == "traffic-raw":
                sql = ("SELECT downloader_id, CAST((ts - ?)/? AS INTEGER) AS b, "
                       "0 AS dlr, 0 AS upr, SUM(dl_inc) AS dlb, SUM(up_inc) AS upb "
                       "FROM traffic_samples "
                       "WHERE ts>=? AND ts<? GROUP BY downloader_id, b")
            else:
                sql = ("SELECT downloader_id, CAST((minute_ts - ?)/? AS INTEGER) AS b, "
                       "0 AS dlr, 0 AS upr, SUM(dl_bytes) AS dlb, SUM(up_bytes) AS upb "
                       "FROM rollup_1m "
                       "WHERE minute_ts>=? AND minute_ts<? GROUP BY downloader_id, b")
            rows = c.execute(sql, (start, step, start, window_end)).fetchall()
            for r in rows:
                did, b = r["downloader_id"], int(r["b"] or 0)
                if did not in idset or b < 0:
                    continue
                # 不足一个完整桶的尾部采样（b==n）并入最后一个桶，不丢数据
                b = min(b, n - 1)
                if metric == "rate":
                    # AVG 聚合会产生小数位，统一四舍五入保留两位小数
                    per[did]["down"][b] = round(float(r["dlr"] or 0), 2)
                    per[did]["up"][b] = round(float(r["upr"] or 0), 2)
                else:
                    per[did]["down"][b] = int(r["dlb"] or 0)
                    per[did]["up"][b] = int(r["upb"] or 0)
        elif source in ("hourly-span", "hourly-all"):
            # 速率图长窗口 —— hourly 按「自适应小时整数倍」分桶，桶内
            # SUM(字节) / 覆盖小时数 = 平均字节/秒（与 hourly 口径一致）。
            step = buckets[0].get("step", buckets[0]["seconds"])
            rows = c.execute(
                "SELECT downloader_id, CAST((hour_ts - ?)/? AS INTEGER) AS b, "
                "SUM(dl_bytes) AS dlb, SUM(up_bytes) AS upb, COUNT(*) AS hours "
                "FROM hourly WHERE hour_ts>=? AND hour_ts<? GROUP BY downloader_id, b",
                (start, step, start, window_end),
            ).fetchall()
            for r in rows:
                did, b = r["downloader_id"], int(r["b"] or 0)
                if did not in idset or b < 0 or b >= n:
                    continue
                secs = max(3600, int(r["hours"] or 1) * 3600)
                if metric == "traffic":
                    # 「全部」的流量图按字节 SUM，与小时/日/月桶口径一致
                    per[did]["down"][b] = int(r["dlb"] or 0)
                    per[did]["up"][b] = int(r["upb"] or 0)
                else:
                    per[did]["down"][b] = round((r["dlb"] or 0) / secs, 2)
                    per[did]["up"][b] = round((r["upb"] or 0) / secs, 2)
        elif source == "hourly-all-natural":
            # 流量统计卡片「全部」—— 自然日 / 月 / 季度 / 年不等宽桶。
            # SQL 先按 hourly 表冗余的 day 列聚合（行数 = 天数 × 下载器数，
            # 远少于逐 hour_ts），再用二分把每个 day 映射到所属自然单位桶：
            # 桶 i 覆盖 [starts[i], starts[i+1]) 的日期，字典序与时间序一致。
            # stops[i] 是桶 i 的排他上界（最后一个桶取窗口右边界），防止
            # 「下一个自然单位第一天」被误并入最后一个桶。
            starts = [timeutil.local_dt(b["ts"]).strftime("%Y-%m-%d")
                      for b in buckets]
            end_day = timeutil.local_dt(window_end).strftime("%Y-%m-%d")
            stops = starts[1:] + [end_day]
            rows = c.execute(
                "SELECT day AS k, downloader_id, SUM(dl_bytes) AS dlb, "
                "SUM(up_bytes) AS upb, COUNT(*) AS hours FROM hourly "
                "WHERE hour_ts>=? AND hour_ts<? GROUP BY day, downloader_id",
                (start - 3600, window_end + 3600),
            ).fetchall()
            acc = {}
            for r in rows:
                did = r["downloader_id"]
                if did not in idset:
                    continue
                k = r["k"]
                i = bisect.bisect_right(starts, k) - 1
                if i < 0 or i >= n or k >= stops[i]:
                    continue
                slot = acc.setdefault((did, i), [0, 0, 0])
                slot[0] += int(r["dlb"] or 0)
                slot[1] += int(r["upb"] or 0)
                slot[2] += int(r["hours"] or 0)
            for (did, i), (dlb, upb, hrs) in acc.items():
                if metric == "traffic":
                    per[did]["down"][i] = dlb
                    per[did]["up"][i] = upb
                else:
                    secs = max(3600, hrs * 3600)
                    per[did]["down"][i] = round(dlb / secs, 2)
                    per[did]["up"][i] = round(upb / secs, 2)
        else:
            # 「今日 / 昨日」按 hour_ts 对齐小时桶；周 / 月按 day；年按 month 聚合。
            col = ("hour_ts" if source == "hourly-hour"
                   else "day" if source == "hourly-day" else "month")
            key_idx = {b["key"]: i for i, b in enumerate(buckets)}
            rows = c.execute(
                "SELECT %s AS k, downloader_id, SUM(dl_bytes) AS dlb, SUM(up_bytes) AS upb, "
                "COUNT(*) AS hours FROM hourly WHERE hour_ts>=? AND hour_ts<? "
                "GROUP BY k, downloader_id" % col,
                (start - 3600, window_end + 3600),
            ).fetchall()
            for r in rows:
                i, did = key_idx.get(r["k"]), r["downloader_id"]
                if i is None or did not in idset:
                    continue
                if metric == "traffic":
                    per[did]["down"][i] = int(r["dlb"] or 0)
                    per[did]["up"][i] = int(r["upb"] or 0)
                else:
                    secs = max(3600, int(r["hours"] or 1) * 3600)
                    per[did]["down"][i] = round((r["dlb"] or 0) / secs, 2)
                    per[did]["up"][i] = round((r["upb"] or 0) / secs, 2)

    sum_up, sum_down = [zero] * n, [zero] * n
    for i in range(n):
        us = [per[d]["up"][i] for d in ids if per[d]["up"][i] is not None]
        ds = [per[d]["down"][i] for d in ids if per[d]["down"][i] is not None]
        if us:
            v = sum(us)
            # 多台速率相加会产生二进制浮点噪声，汇总线同样两位小数
            sum_up[i] = round(v, 2) if metric == "rate" else v
        if ds:
            v = sum(ds)
            sum_down[i] = round(v, 2) if metric == "rate" else v

    series = [{
        "id": 0, "name": "汇总", "color_up": db.SUMMARY_UP, "color_down": db.SUMMARY_DOWN,
        "up": sum_up, "down": sum_down,
    }]
    for d in dls:
        series.append({
            "id": d["id"], "name": d["name"],
            "color_up": d["color_up"], "color_down": d["color_down"],
            "up": per[d["id"]]["up"], "down": per[d["id"]]["down"],
        })

    # 速率折线只填补中间漏采，头尾保持 None（详见 _fill_rate_gaps）
    if metric == "rate":
        series = _fill_rate_gaps(series)

    if metric == "traffic":
        summary = {"up": sum(v or 0 for v in sum_up), "down": sum(v or 0 for v in sum_down)}
    else:
        summary = {"up": max([v or 0 for v in sum_up] or [0]),
                   "down": max([v or 0 for v in sum_down] or [0])}

    # 采样类与「今日 / 昨日」（小时桶）显示到分钟；周 / 月 / 年 / 全部按天 / 月聚合
    if range_key == "all":
        fmt = "%Y-%m-%d" if buckets[0]["seconds"] >= 86400 else "%m-%d %H:%M"
    elif source in ("hourly-day", "hourly-month"):
        fmt = "%Y-%m-%d"
    else:
        fmt = "%m-%d %H:%M"
    # 把「用户选择的时间范围」与「SQL 查询右端」彻底分开。
    # 起，采样类滚动窗口（live / 1h / 6h / 12h）的 window_end 会带上
    # extra = int(now - end_aligned)（当前时刻越过最后一个对齐桶边界的余秒，
    # 0 ~ step-1），用于 SQL 把「不足一个完整桶」的最新采样并进最后一桶，
    # 不丢数据。但这段 extra 不属于用户选择的时间范围：把 rate 折线末点
    # 对齐到 window_end 后，tooltip 首末时刻跨度变成「选择范围 + extra」——
    # 实时 5 分钟档 step=5 时多 0~4 秒（now 落在整分后 2 秒即「多 2 秒」），
    # 6h(step=15) / 12h(step=30) 更是多 0~14 / 0~29 秒。用户明确要求对所有
    # 时间范围逐一核实并修复。
    # 修法：单独算「展示窗口右端」disp_end = 窗口起点 + 选择范围秒数；
    # SQL 查询右边界仍用原 window_end（含 extra），series / spans / 分桶 /
    # 聚合 / 累计计数器差值一律不动，仅调整展示端点，数值口径
    if range_key == "live":
        chosen_span = max(30, int(live_span or 300))
    elif range_key in RATE_RANGES:
        chosen_span = RATE_RANGES[range_key][0]
    else:
        # 自然周期 / 「全部」：window_end - start 本就是完整周期跨度，
        # 取整数秒消除 now 的亚秒抖动 会少 <1 秒）。
        chosen_span = int(round(window_end - start))
    disp_end = int(buckets[0]["ts"]) + chosen_span

    # 区间文字的终点改用「窗口右边界」而不是最后一个桶的起点。旧实现让
    # 「本月 / 本年 / 上月」等范围的文字少显示一整个桶（天 / 月 / 2 小时），
    # 用户据此误以为「图表展示的单位不足」。右端再夹到硬边界（当前时刻 /
    # 完整过去周期边界），不把还没发生的未来时间写进文字；拖到历史窗口时
    # window_end 已经左移，min 后自然显示历史区间。
    # 改用 disp_end（不含 extra / 亚秒），与 rate 折线末点、X 轴首尾
    # 刻度逐字对齐到「用户选择的时间范围」。
    local_now = timeutil.local_dt(now)
    if range_key in ("all", "live") or range_key in RATE_RANGES:
        hard_end = now
    else:
        hard_end = _wall_ts(_period_bounds(range_key, local_now)[1])
    label_end = min(disp_end, hard_end)
    window_label = (timeutil.local_dt(buckets[0]["ts"]).strftime(fmt) + " ~ " +
                    timeutil.local_dt(label_end).strftime(fmt))

    # 每个桶的真实起止 Unix 秒，供前端弹出菜单在短窗口显示时间段标题
    spans = [[int(b["ts"]), int(b["ts"] + b["seconds"])] for b in buckets]

    labels = [b["label"] for b in buckets]
    times = [b["ts"] for b in buckets]
    # b（用户反馈 「还是没解决」）：折线图把 n 个「桶起点」
    # 按 i/(n-1) 铺满绘图区，最右点标成 start+(n-1)*step，比窗口右端少一个
    # 桶宽 —— live/5分钟/step=5 就是「4分55秒，少5秒」。把末点对齐到
    # window.end，修好了「少一桶」。
    #
    # （用户反馈 「多几秒」）：window_end 还含 的尾部余秒
    # extra（见上方 disp_end 注释），直接拿它当末点，跨度又变成
    # 「选择范围 + extra」。现改为对齐到 disp_end = 窗口起点 + 选择范围，
    # 于是 rate 折线首末时刻严格 = [window.start, window.end] = 选择范围，
    # 既不少绘制也不多绘制，且与左上角区间文字、X 轴首尾刻度逐字对齐。
    #
    # 仅调整 rate 折线「展示用的时间轴端点标签」（times / labels 末项）：
    # series / spans / bucket_count / SQL 分桶 / 聚合 / 累计计数器差值一律
    # 不动；SQL 查询右边界仍用含 extra 的 window_end，尾部采样不丢。
    # 流量柱状图按柱组中心 + 时间段标题，本就是区间语义，traffic 保持原样。
    if metric == "rate" and n >= 2:
        lfmt = buckets[-1].get("lfmt") or "%m-%d %H:%M"
        times[-1] = disp_end
        labels[-1] = timeutil.local_dt(disp_end).strftime(lfmt)

    return {
        "range": range_key, "metric": metric,
        "labels": labels,
        "times": times,
        "spans": spans,
        "series": series, "summary": summary,
        # 横向拖动用：offset 单位为一个 X 轴刻度（桶），上限 30 个当前窗口长度
        "offset": offset, "max_offset": max_offset, "bucket_count": n,
        "at_latest": offset == 0,
        # window 表达「用户选择的时间范围」，起终点与 rate 折线首末点、
        # X 轴首尾刻度严格一致（不再含 SQL 尾桶的 extra 余秒 / 亚秒抖动）。
        "window": {"start": int(buckets[0]["ts"]), "end": disp_end,
                   "label": window_label},
        "downloaders": [{"id": d["id"], "name": d["name"],
                         "color_up": d["color_up"], "color_down": d["color_down"]} for d in dls],
    }
