"""自动 rollup：分层物化聚合，让图表查询按窗口跨度只路由到一张表。

避免同一个窗口同时照顾 samples / traffic_samples / hourly 而做 UNION 混表、
多次 MIN(ts) 全表扫描与近细远粗混合分支。分层如下：

 traffic_samples (raw，明细，保留 7 天)
   │ run_once 幂等聚合
   ▼
 rollup_1m (1 分钟桶，保留 90 天)  ← 中等窗口 / raw 过期时的单表数据源
   │
   ▼
 rollup_1d (1 天桶)                ← 长窗口数据源

run_once 由后台定时任务触发，按水位增量聚合、可重复执行；status() 回报各层
水位。聚合口径与 hourly 完全一致（累计计数器差值求和），90 天以上的
rollup 数据自动清理。hourly 本身就是分层里的 1h 层。
"""
import math
import time

from . import db, log

ROLLUP_1M_RETENTION_DAYS = 90


def _water(c, kind, default=0.0):
    r = c.execute("SELECT value FROM rollup_state WHERE kind=?", (kind,)).fetchone()
    return float(r["value"]) if r else default


def _set_water(c, kind, value):
    c.execute(
        "INSERT INTO rollup_state(kind,value,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(kind) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (kind, float(value), int(time.time())),
    )


def run_once(now=None):
    """幂等跑一轮分层聚合。返回本次写入的 1m 桶数 / 1d 桶数。"""
    now = now or time.time()
    n1m = n1d = 0
    with db.conn() as c:
        # ---- raw -> rollup_1m：只处理已经结束的完整分钟 ----
        water = _water(c, "1m", 0.0)
        # 水位按分钟向下对齐，保证「跨水位边界的那一分钟」被完整重算
        water = math.floor(water / 60.0) * 60.0
        last_complete = math.floor((now - 60.0) / 60.0) * 60.0
        if last_complete > water:
            rows = c.execute(
                "SELECT downloader_id, CAST(ts/60 AS INTEGER)*60 AS m, "
                "SUM(dl_inc) AS dl, SUM(up_inc) AS up "
                "FROM traffic_samples WHERE ts>=? AND ts<? "
                "GROUP BY downloader_id, m",
                (water, last_complete + 60.0),
            ).fetchall()
            for r in rows:
                c.execute(
                    "INSERT INTO rollup_1m(downloader_id,minute_ts,dl_bytes,up_bytes) "
                    "VALUES (?,?,?,?) ON CONFLICT(downloader_id,minute_ts) DO UPDATE SET "
                    "dl_bytes=excluded.dl_bytes, up_bytes=excluded.up_bytes",
                    (r["downloader_id"], r["m"], int(r["dl"] or 0), int(r["up"] or 0)),
                )
                n1m += 1
            _set_water(c, "1m", last_complete + 60.0)

        # ---- hourly -> rollup_1d：按 day 全量重算，口径与顶部卡片一致 ----
        rows = c.execute(
            "SELECT downloader_id, day, SUM(dl_bytes) AS dl, SUM(up_bytes) AS up "
            "FROM hourly GROUP BY downloader_id, day"
        ).fetchall()
        for r in rows:
            c.execute(
                "INSERT INTO rollup_1d(downloader_id,day,dl_bytes,up_bytes) "
                "VALUES (?,?,?,?) ON CONFLICT(downloader_id,day) DO UPDATE SET "
                "dl_bytes=excluded.dl_bytes, up_bytes=excluded.up_bytes",
                (r["downloader_id"], r["day"], int(r["dl"] or 0), int(r["up"] or 0)),
            )
            n1d += 1
        _set_water(c, "1d", now)

        # ---- 清理过期的 1m 桶（1d 与 hourly 永久保留）----
        cutoff = now - ROLLUP_1M_RETENTION_DAYS * 86400
        c.execute("DELETE FROM rollup_1m WHERE minute_ts < ?", (cutoff,))

    if n1m or n1d:
        log.info("rollup.done", buckets_1m=n1m, buckets_1d=n1d)
    return {"buckets_1m": n1m, "buckets_1d": n1d}


def status():
    """供 /api/metrics 暴露 rollup 健康度。"""
    try:
        with db.conn() as c:
            w1m = _water(c, "1m", 0.0)
            w1d = _water(c, "1d", 0.0)
            c1m = c.execute("SELECT COUNT(*) FROM rollup_1m").fetchone()[0]
            c1d = c.execute("SELECT COUNT(*) FROM rollup_1d").fetchone()[0]
        return {"water_1m": w1m, "water_1d": w1d,
                "rows_1m": c1m, "rows_1d": c1d}
    except Exception as exc:
        log.warn("rollup.status_failed", error=str(exc))
        return {}
