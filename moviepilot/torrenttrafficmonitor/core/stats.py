"""统计查询：所有粒度都从同一张 hourly 表聚合，保证报表之间不会对不上账。"""
import time
from datetime import timedelta

from . import db, timeutil

# 顶部 4 张汇总卡片的下拉档数（含当前周期本身）：
# 今日 + 往前 30 天、本周 + 往前 26 周、本月 + 往前 12 个月、本年 + 往前 5 年。
PERIOD_COUNTS = {"day": 31, "week": 27, "month": 13, "year": 6}


def _wall_ts(dt):
    """local_dt 用 UTC 对象承载本地墙上时间，减偏移才是真实 Unix 秒。"""
    return dt.timestamp() - timeutil.OFFSET


def _ym_add(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    y, m0 = divmod(idx, 12)
    return y, m0 + 1


def _day_start(year, month, day):
    from datetime import datetime, timezone
    return datetime(year, month, day, tzinfo=timezone.utc)


PERIOD_UNITS = ("day", "week", "month", "year")
PERIOD_COLS = {"day": "day", "week": "week", "month": "month", "year": "year"}


def _period_item(unit, i, local, today, monday):
    # 生成第 i 个（0=当前周期）历史周期的元数据，纯计算、不含流量数据。
    # period_series（卡片）与 period_page（无限下滑清单）共用同一套命名 / 日期 /
    # key 规则，保证两处完全一致；key 对应 hourly 表的 day/week/month/year 列。
    if unit == "day":
        d = today - timedelta(days=i)
        label = "今日" if i == 0 else ("昨日" if i == 1 else "%d 天前" % i)
        return {"offset": i, "label": label, "date": d.strftime("%m-%d"),
                "key": d.strftime("%Y-%m-%d"),
                "start": _wall_ts(d), "end": _wall_ts(d + timedelta(days=1))}
    if unit == "week":
        m = monday - timedelta(days=7 * i)
        label = "本周" if i == 0 else ("上周" if i == 1 else "%d 周前" % i)
        return {"offset": i, "label": label,
                "date": m.strftime("%m-%d") + "~" + (m + timedelta(days=6)).strftime("%m-%d"),
                "key": m.strftime("%Y-%m-%d"),
                "start": _wall_ts(m), "end": _wall_ts(m + timedelta(days=7))}
    if unit == "month":
        y, mo = _ym_add(local.year, local.month, -i)
        d = _day_start(y, mo, 1)
        ny, nm = _ym_add(y, mo, 1)
        label = "本月" if i == 0 else ("上月" if i == 1 else "%d 个月前" % i)
        return {"offset": i, "label": label, "date": "%04d-%02d" % (y, mo),
                "key": "%04d-%02d" % (y, mo),
                "start": _wall_ts(d), "end": _wall_ts(_day_start(ny, nm, 1))}
    y = local.year - i
    d = _day_start(y, 1, 1)
    label = "本年" if i == 0 else ("去年" if i == 1 else "%d 年前" % i)
    return {"offset": i, "label": label, "date": str(y), "key": str(y),
            "start": _wall_ts(d), "end": _wall_ts(_day_start(y + 1, 1, 1))}


def _period_sums(units=None):
    # 一次 GROUP BY 拿到「所有有数据的历史周期」的上传/下载合计。
    # 结果只含数据库里真实出现过的 key（很小、有限），没有数据的周期自然取 0。
    cols = [(u, PERIOD_COLS[u]) for u in (units or PERIOD_UNITS)]
    with db.conn() as c:
        sums = {}
        for unit, col in cols:
            # 停用下载器的历史流量不计入展示（重新启用后自然回归）
            rows = c.execute(
                "SELECT %s AS k, SUM(dl_bytes) AS dl, SUM(up_bytes) AS up "
                "FROM hourly WHERE downloader_id IN "
                "(SELECT id FROM downloaders WHERE enabled=1) "
                "GROUP BY %s" % (col, col)).fetchall()
            sums[unit] = {r["k"]: (int(r["up"] or 0), int(r["dl"] or 0)) for r in rows}
    return sums


def period_series(now_ts=None, counts=None):
    """顶部 4 张卡片用的「历史周期」上传/下载合计。

    和 overview 的今日/本周/本月/本年共用 hourly 表里的 day / week / month /
    year 四个字符串键，因此 offset=0 的结果与总览卡片完全一致，不会两处对不上账。
    返回 {unit: [{offset,label,date,key,start,end,up,dl}, ...]}。
    """
    now = now_ts or time.time()
    counts = dict(PERIOD_COUNTS, **(counts or {}))
    local = timeutil.local_dt(now)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=local.weekday())

    specs = {u: [_period_item(u, i, local, today, monday)
                 for i in range(counts[u])] for u in PERIOD_UNITS}
    sums = _period_sums()
    for unit, items in specs.items():
        for it in items:
            up, dl = sums[unit].get(it["key"], (0, 0))
            it["up"], it["dl"] = up, dl
    return specs


def period_page(unit, start=0, count=10, now_ts=None):
    # 顶部卡片「历史周期数据」清单的无限分页。返回 [start, start+count)
    # 的周期条目。超出数据库采集起始的更早周期仍然生成条目（数据为 0），
    # 因此前端可以一直向下滑出更早的历史周期，不设最早下限。
    if unit not in PERIOD_UNITS:
        raise ValueError("不支持的周期单位")
    now = now_ts or time.time()
    local = timeutil.local_dt(now)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=local.weekday())
    sums = _period_sums([unit])[unit]
    items = []
    for i in range(start, start + count):
        meta = _period_item(unit, i, local, today, monday)
        up, dl = sums.get(meta["key"], (0, 0))
        items.append({"offset": i, "label": meta["label"], "date": meta["date"],
                      "up": up, "dl": dl})
    return items


def period_totals(now_ts=None):
    """每个下载器的 今日 / 本周 / 本月 / 本年 / 有记录以来 累计。"""
    now = now_ts or time.time()
    m = timeutil.hour_meta(timeutil.floor_hour(now))
    sql = """
        SELECT downloader_id,
               SUM(CASE WHEN day=?   THEN dl_bytes ELSE 0 END) AS day_dl,
               SUM(CASE WHEN day=?   THEN up_bytes ELSE 0 END) AS day_up,
               SUM(CASE WHEN week=?  THEN dl_bytes ELSE 0 END) AS week_dl,
               SUM(CASE WHEN week=?  THEN up_bytes ELSE 0 END) AS week_up,
               SUM(CASE WHEN month=? THEN dl_bytes ELSE 0 END) AS month_dl,
               SUM(CASE WHEN month=? THEN up_bytes ELSE 0 END) AS month_up,
               SUM(CASE WHEN year=?  THEN dl_bytes ELSE 0 END) AS year_dl,
               SUM(CASE WHEN year=?  THEN up_bytes ELSE 0 END) AS year_up,
               SUM(dl_bytes) AS all_dl,
               SUM(up_bytes) AS all_up
        FROM hourly WHERE downloader_id IN (SELECT id FROM downloaders WHERE enabled=1)
        GROUP BY downloader_id
    """
    args = (m["day"], m["day"], m["week"], m["week"],
            m["month"], m["month"], m["year"], m["year"])
    with db.conn() as c:
        return {r["downloader_id"]: dict(r) for r in c.execute(sql, args).fetchall()}


def query_stats(granularity, start_ts, end_ts, downloader_id=None):
    """按粒度返回完整的（含空桶补零）时间序列，并附带每个下载器的分项。"""
    if granularity not in timeutil.GRANULARITIES:
        raise ValueError("不支持的统计粒度")
    start_ts, end_ts = float(start_ts), float(end_ts)
    if end_ts <= start_ts:
        raise ValueError("结束时间必须大于开始时间")

    keys = timeutil.generate_keys(granularity, start_ts, end_ts)
    if not keys:
        return {"granularity": granularity, "items": [], "summary": {"dl": 0, "up": 0, "total": 0}}
    col = timeutil.GRAN_COLUMN[granularity]

    sql = (f"SELECT {col} AS k, downloader_id, SUM(dl_bytes) AS dl, SUM(up_bytes) AS up "
           f"FROM hourly WHERE {col} BETWEEN ? AND ? ")
    args = [keys[0], keys[-1]]
    if downloader_id:
        sql += "AND downloader_id=? "
        args.append(int(downloader_id))
    sql += "GROUP BY k, downloader_id ORDER BY k"

    with db.conn() as c:
        rows = c.execute(sql, args).fetchall()

    buckets = {
        k: {"key": k, "label": timeutil.label_of(k, granularity),
            "dl": 0, "up": 0, "total": 0, "by_downloader": {}}
        for k in keys
    }
    for r in rows:
        b = buckets.get(r["k"])
        if b is None:
            continue
        dl, up = int(r["dl"] or 0), int(r["up"] or 0)
        b["dl"] += dl
        b["up"] += up
        b["total"] += dl + up
        b["by_downloader"][str(r["downloader_id"])] = {"dl": dl, "up": up}

    items = [buckets[k] for k in keys]
    return {
        "granularity": granularity,
        "start": start_ts,
        "end": end_ts,
        "items": items,
        "summary": {
            "dl": sum(i["dl"] for i in items),
            "up": sum(i["up"] for i in items),
            "total": sum(i["total"] for i in items),
        },
    }


# 实时速率曲线数据接口 realtime() 已随 v1.0.2 的实时速率卡片一并删除：
# 该接口依赖 samples 速率采样表，插件已不再写入该表。
