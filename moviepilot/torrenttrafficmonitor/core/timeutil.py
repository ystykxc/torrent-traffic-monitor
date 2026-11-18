"""时间与统计桶工具。

统一约定：数据库里存的 ts 都是真实 Unix 时间戳（秒）。所有小时 / 日 / 周 /
月 / 年边界按 TZ_OFFSET（默认东八区）换算成本地墙上时间后再切分，容器里
不需要装 tzdata，也不受宿主机时区影响。中国无夏令时，固定偏移足够可靠。
"""
from datetime import datetime, timedelta, timezone
import os

try:
    TZ_OFFSET = int(os.environ.get("TZ_OFFSET", "8"))
except ValueError:
    TZ_OFFSET = 8
OFFSET = TZ_OFFSET * 3600


def configure(offset_hours):
    """由 main 在启动时按 config.json 显式设置，避免各处读取不一致。"""
    global TZ_OFFSET, OFFSET
    TZ_OFFSET = int(offset_hours)
    OFFSET = TZ_OFFSET * 3600
    os.environ["TZ_OFFSET"] = str(TZ_OFFSET)

GRANULARITIES = ("hour", "day", "week", "month", "year")
GRAN_COLUMN = {
    "hour": "hour_ts",
    "day": "day",
    "week": "week",
    "month": "month",
    "year": "year",
}


def local_dt(ts):
    """把 Unix 时间戳转成本地墙上时间（用 UTC 对象承载，只取字段）。"""
    return datetime.fromtimestamp(float(ts) + OFFSET, tz=timezone.utc)


def floor_hour(ts):
    """返回 ts 所在本地小时的起点（真实 Unix 秒）。"""
    return (int(float(ts) + OFFSET) // 3600) * 3600 - OFFSET


def hour_meta(hour_ts):
    """小时桶对应的日/周/月/年字符串键。周以周一为一周起点。"""
    dt = local_dt(hour_ts)
    monday = dt - timedelta(days=dt.weekday())
    return {
        "day": dt.strftime("%Y-%m-%d"),
        "week": monday.strftime("%Y-%m-%d"),
        "month": dt.strftime("%Y-%m"),
        "year": dt.strftime("%Y"),
    }


def key_of(ts, granularity):
    """任意时刻归属的分组键。hour 返回 int，其余返回 str。"""
    h = floor_hour(ts)
    if granularity == "hour":
        return h
    return hour_meta(h)[granularity]


def _start_of_day(ts):
    return local_dt(ts).replace(hour=0, minute=0, second=0, microsecond=0)


def generate_keys(granularity, start_ts, end_ts, limit=2000):
    """生成 [start_ts, end_ts] 覆盖到的完整分组键序列（含空桶），用于图表补零。"""
    keys = []
    if granularity == "hour":
        cur, stop = floor_hour(start_ts), floor_hour(end_ts)
        while cur <= stop and len(keys) < limit:
            keys.append(cur)
            cur += 3600
        return keys

    cur = _start_of_day(start_ts)
    stop = _start_of_day(end_ts)

    if granularity == "week":
        cur -= timedelta(days=cur.weekday())
        while cur <= stop and len(keys) < limit:
            keys.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=7)
    elif granularity == "month":
        cur = cur.replace(day=1)
        while cur <= stop and len(keys) < limit:
            keys.append(cur.strftime("%Y-%m"))
            cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1)
    elif granularity == "year":
        cur = cur.replace(month=1, day=1)
        while cur <= stop and len(keys) < limit:
            keys.append(cur.strftime("%Y"))
            cur = cur.replace(year=cur.year + 1)
    else:  # day
        while cur <= stop and len(keys) < limit:
            keys.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
    return keys


def label_of(key, granularity):
    """给分组键生成短标签。"""
    if granularity == "hour":
        return local_dt(key).strftime("%m-%d %H:00")
    if granularity == "day":
        return str(key)[5:]
    if granularity == "week":
        return str(key)[5:] + " 周"
    return str(key)


def range_for(granularity, now_ts):
    """各粒度的默认查询范围（真实 Unix 秒）。"""
    spans = {
        "hour": 48 * 3600,
        "day": 30 * 86400,
        "week": 26 * 7 * 86400,
        "month": 730 * 86400,
        "year": 10 * 365 * 86400,
    }
    return now_ts - spans.get(granularity, 30 * 86400), now_ts
