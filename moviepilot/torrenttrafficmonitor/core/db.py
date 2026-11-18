"""SQLite 存储层（MoviePilot 插件版）。

与独立部署版相比的差异：
- 删除 users / sessions / audit_log 三张表与账户、会话、审计逻辑。
- 下载器连接信息（地址、账号、密码）不再入库、不再加密落盘；每轮采集前
  由插件从 MoviePilot 已接入的下载器配置实时读取（set_provider）。
- 本地 downloaders 表只保存插件自己的状态：稳定标识 dkey、曲线颜色、
  启用停用开关、排序、以及「宿主中已移除」标记。
- 统计口径、小时桶分摊、rollup、边界缓存全部沿用原实现，未作改动。

表结构：
- downloaders        下载器本地状态（颜色 / 启用 / 顺序 / dkey）
- downloader_state   流量统计累计计数器基线
- samples            兼容旧库保留（v1.0.2 起实时速率采集删除，不再写入/读取）
- traffic_samples    流量统计采样点（累计计数器差值）
- hourly             小时桶，冗余 day/week/month/year 四个字符串键
- rollup_1m/1d       后台幂等物化的分层聚合
- app_settings       运行参数（采样间隔、通知配置）
"""
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import constants, log, timeutil
from .constants import PALETTE, SUMMARY_DOWN, SUMMARY_UP  # noqa: F401 供 chart 使用

_DB_FILE = None

# 下载器来源（由插件主类注入）。返回一个 list[dict]，每项至少含：
#   dkey / name / type('qb'|'tr') / url / username / password /
#   mp_enabled / default / info(完整原始配置)
_provider = None
_merged = None
_merged_at = 0.0
_merged_lock = threading.Lock()
_MERGED_TTL = 20.0

# 采集的瞬时状态放在内存，不写库，避免与流量记账抢 SQLite 写锁。
_live = {}
_live_lock = threading.Lock()

_bounds_cache = {"ts": 0.0, "data": None}
_bounds_lock = threading.Lock()
_BOUNDS_TTL = 30.0

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def set_provider(fn):
    """注入「读取 MoviePilot 已接入下载器」的函数，并立即失效合并缓存。"""
    global _provider, _merged, _merged_at
    _provider = fn
    with _merged_lock:
        _merged, _merged_at = None, 0.0


def configure(data_dir):
    global _DB_FILE
    os.makedirs(data_dir, exist_ok=True)
    _DB_FILE = os.path.join(data_dir, "traffic.db")


@contextmanager
def conn():
    if _DB_FILE is None:
        raise RuntimeError("db.configure() 尚未调用")
    c = sqlite3.connect(_DB_FILE, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS downloaders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dkey        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'qb',
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    color_up    TEXT NOT NULL DEFAULT '',
    color_down  TEXT NOT NULL DEFAULT '',
    missing     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS downloader_state (
    downloader_id       INTEGER PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'unknown',
    error               TEXT,
    last_seen           INTEGER,
    dl_rate             INTEGER NOT NULL DEFAULT 0,
    up_rate             INTEGER NOT NULL DEFAULT 0,
    last_dl_total       INTEGER,
    last_up_total       INTEGER,
    last_ts             REAL,
    extra               TEXT,
    rate_last_dl_total  INTEGER,
    rate_last_up_total  INTEGER,
    rate_last_ts        REAL
);

-- 兼容独立部署版旧库：v1.0.2 已删除实时速率曲线，本表不再写入 / 读取
CREATE TABLE IF NOT EXISTS samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    downloader_id   INTEGER NOT NULL,
    ts              REAL NOT NULL,
    dl_rate         INTEGER NOT NULL,
    up_rate         INTEGER NOT NULL,
    dl_inc          INTEGER NOT NULL,
    up_inc          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_did_ts ON samples(downloader_id, ts);

CREATE TABLE IF NOT EXISTS traffic_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    downloader_id   INTEGER NOT NULL,
    ts              REAL NOT NULL,
    dl_inc          INTEGER NOT NULL,
    up_inc          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traffic_samples_did_ts ON traffic_samples(downloader_id, ts);

CREATE TABLE IF NOT EXISTS hourly (
    downloader_id   INTEGER NOT NULL,
    hour_ts         INTEGER NOT NULL,
    day             TEXT NOT NULL,
    week            TEXT NOT NULL,
    month           TEXT NOT NULL,
    year            TEXT NOT NULL,
    dl_bytes        INTEGER NOT NULL DEFAULT 0,
    up_bytes        INTEGER NOT NULL DEFAULT 0,
    samples         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (downloader_id, hour_ts)
);
CREATE INDEX IF NOT EXISTS idx_hourly_day   ON hourly(day);
CREATE INDEX IF NOT EXISTS idx_hourly_week  ON hourly(week);
CREATE INDEX IF NOT EXISTS idx_hourly_month ON hourly(month);
CREATE INDEX IF NOT EXISTS idx_hourly_year  ON hourly(year);

CREATE TABLE IF NOT EXISTS app_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rollup_1m (
    downloader_id   INTEGER NOT NULL,
    minute_ts       INTEGER NOT NULL,
    dl_bytes        INTEGER NOT NULL DEFAULT 0,
    up_bytes        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (downloader_id, minute_ts)
);
CREATE INDEX IF NOT EXISTS idx_rollup_1m_ts ON rollup_1m(minute_ts);

CREATE TABLE IF NOT EXISTS rollup_1d (
    downloader_id   INTEGER NOT NULL,
    day             TEXT NOT NULL,
    dl_bytes        INTEGER NOT NULL DEFAULT 0,
    up_bytes        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (downloader_id, day)
);
CREATE INDEX IF NOT EXISTS idx_rollup_1d_day ON rollup_1d(day);

CREATE TABLE IF NOT EXISTS rollup_state (
    kind            TEXT PRIMARY KEY,
    value           REAL NOT NULL,
    updated_at      INTEGER NOT NULL
);
"""


def norm_color(value, fallback=None):
    """只接受 #RRGGBB，防止把任意字符串写进页面样式。"""
    s = str(value or "").strip()
    return s.lower() if _HEX.fullmatch(s) else fallback


def init_db():
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        # 兼容从旧独立版迁移过来的数据库：补齐 dkey / missing 列
        cols = {r["name"] for r in c.execute("PRAGMA table_info(downloaders)")}
        if "dkey" not in cols:
            c.execute("ALTER TABLE downloaders ADD COLUMN dkey TEXT")
            c.execute("UPDATE downloaders SET dkey='legacy-'||id WHERE dkey IS NULL")
        if "missing" not in cols:
            c.execute("ALTER TABLE downloaders ADD COLUMN missing INTEGER NOT NULL DEFAULT 0")


# ---------- 下载器：从 MoviePilot 同步 + 本地状态 ----------

def sync_downloaders(force=False):
    """把宿主已接入的下载器与本地状态表合并，结果缓存 20 秒。

    宿主里新增的下载器自动建本地记录并按顺序分配颜色；宿主里移除的下载器
    只标记 missing（保留其历史流量数据，重新接入后自动恢复）；连接信息每次
    都取自宿主，绝不在本地落盘。
    """
    global _merged, _merged_at
    now = time.time()
    with _merged_lock:
        if (not force and _merged is not None
                and now - _merged_at < _MERGED_TTL):
            return _merged

    if _provider is None:
        log.warn("downloader provider not configured")
        with _merged_lock:
            return _merged or []

    try:
        remote = list(_provider() or [])
    except Exception as exc:
        log.warn("read moviepilot downloaders failed", error=str(exc)[:200])
        with _merged_lock:
            return _merged or []

    with conn() as c:
        rows = {r["dkey"]: dict(r) for r in c.execute("SELECT * FROM downloaders")}
        count = len(rows)
        seen = set()
        for item in remote:
            dkey = str(item.get("dkey") or item.get("name") or "").strip()
            if not dkey:
                continue
            seen.add(dkey)
            row = rows.get(dkey)
            if row is None:
                idx = count % len(PALETTE)
                count += 1
                c.execute(
                    "INSERT INTO downloaders "
                    "(dkey,name,type,enabled,sort_order,color_up,color_down,missing,created_at) "
                    "VALUES (?,?,?,?,?,?,?,0,?)",
                    (dkey, str(item.get("name") or dkey),
                     "tr" if str(item.get("type", "")).lower() in ("tr", "transmission") else "qb",
                     1, len(rows), PALETTE[idx][0], PALETTE[idx][1], int(time.time())),
                )
            else:
                c.execute(
                    "UPDATE downloaders SET name=?,type=?,missing=0 WHERE dkey=?",
                    (str(item.get("name") or dkey),
                     "tr" if str(item.get("type", "")).lower() in ("tr", "transmission") else "qb",
                     dkey),
                )
        # 宿主中已不存在的标记 missing（不删数据）
        for dkey in set(rows) - seen:
            c.execute("UPDATE downloaders SET missing=1 WHERE dkey=?", (dkey,))
        # 曲线颜色一律由系统自动分配：空值 / 非法值按调色板顺序补齐，
        # 用户不再需要也不允许手工设置颜色。
        ordered = c.execute("SELECT * FROM downloaders ORDER BY sort_order,id").fetchall()
        for i, r in enumerate(ordered):
            up, down = PALETTE[i % len(PALETTE)]
            if (not _HEX.match(str(r["color_up"] or ""))
                    or not _HEX.match(str(r["color_down"] or ""))):
                c.execute("UPDATE downloaders SET color_up=?,color_down=? WHERE id=?",
                          (up, down, r["id"]))
        local = {r["dkey"]: dict(r) for r in c.execute("SELECT * FROM downloaders")}

    by_key = {str(x.get("dkey") or x.get("name") or "").strip(): x for x in remote}
    merged = []
    for dkey, row in local.items():
        src = by_key.get(dkey, {})
        merged.append({
            "id": row["id"],
            "dkey": dkey,
            "name": row["name"],
            "type": row["type"],
            "enabled": int(row["enabled"]),
            "sort_order": int(row["sort_order"]),
            "color_up": norm_color(row.get("color_up"), SUMMARY_UP),
            "color_down": norm_color(row.get("color_down"), SUMMARY_DOWN),
            "missing": int(row.get("missing") or 0),
            "created_at": row["created_at"],
            # 连接信息来自宿主，不落库
            "url": str(src.get("url") or ""),
            "username": str(src.get("username") or ""),
            "password": str(src.get("password") or ""),
            "mp_enabled": bool(src.get("mp_enabled", True)),
            "default": bool(src.get("default", False)),
            "info": src.get("info") or {},
        })
    merged.sort(key=lambda x: (x["sort_order"], x["id"]))
    with _merged_lock:
        _merged, _merged_at = merged, now
    return merged


def list_downloaders(enabled_only=False, public=False):
    """返回下载器列表。public=True 时不回传顶层 password，但保留 info 完整配置。"""
    rows = [dict(x) for x in sync_downloaders()]
    if enabled_only:
        rows = [x for x in rows if x["enabled"] and not x["missing"]]
    out = []
    for x in rows:
        item = dict(x)
        pwd = item.pop("password", "")
        if public:
            item["has_password"] = bool(pwd)
        else:
            item["password"] = pwd      # 采集器 / 详情弹窗内部使用
        out.append(item)
    return out


def get_downloader(did):
    for x in sync_downloaders():
        if x["id"] == int(did):
            return dict(x)
    return None


def update_downloader_config(did, payload):
    """下载器设置只可改「启用停用」；颜色由系统自动分配，忽略传入的颜色字段。"""
    cur = get_downloader(did)
    if not cur:
        return None
    enabled = cur["enabled"]
    if "enabled" in payload:
        enabled = 1 if payload.get("enabled") else 0
    with conn() as c:
        c.execute("UPDATE downloaders SET enabled=? WHERE id=?", (enabled, int(did)))
    set_provider(_provider)             # 触发合并缓存失效
    return get_downloader(did)


def recolor_all(shift=None):
    """一键重新分配颜色：按当前顺序把调色板依次分配给所有下载器。"""
    import random
    rows = sync_downloaders(force=True)
    base = random.randrange(len(PALETTE)) if shift is None else int(shift)
    base %= len(PALETTE)
    with conn() as c:
        for i, r in enumerate(rows):
            up, down = PALETTE[(i + base) % len(PALETTE)]
            c.execute("UPDATE downloaders SET color_up=?,color_down=? WHERE id=?",
                      (up, down, r["id"]))
    set_provider(_provider)
    return {"count": len(rows), "shift": base,
            "colors": [{"up": PALETTE[(i + base) % len(PALETTE)][0],
                        "down": PALETTE[(i + base) % len(PALETTE)][1]}
                       for i in range(len(rows))]}


# ---------- 运行参数 ----------

def get_setting(key, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key, value):
    with conn() as c:
        c.execute(
            "INSERT INTO app_settings(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


# ---------- 采集状态 ----------

def get_state(did):
    with conn() as c:
        r = c.execute("SELECT * FROM downloader_state WHERE downloader_id=?", (did,)).fetchone()
        return dict(r) if r else None


def record_traffic_sample(did, now, start_ts, s, dl_inc, up_inc):
    """写 traffic_samples + 把累计计数器差值按时间比例分摊到 hourly 小时桶。

    铁律：流量只来自累计计数器的单调差值；速率只画曲线、绝不累加。
    一次采样跨越两个小时时按时间比例分摊，保证日/周/月/年报表对得上账。
    """
    with conn() as c:
        c.execute(
            "INSERT INTO traffic_samples (downloader_id,ts,dl_inc,up_inc) VALUES (?,?,?,?)",
            (did, now, dl_inc, up_inc),
        )
        span = now - start_ts
        if span > 0 and (dl_inc or up_inc):
            cur = start_ts
            while cur < now - 1e-6:
                h = timeutil.floor_hour(cur)
                seg_end = min(now, h + 3600)
                w = (seg_end - cur) / span
                meta = timeutil.hour_meta(h)
                c.execute(
                    "INSERT INTO hourly (downloader_id,hour_ts,day,week,month,year,dl_bytes,up_bytes,samples) "
                    "VALUES (?,?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(downloader_id,hour_ts) DO UPDATE SET "
                    "dl_bytes=dl_bytes+excluded.dl_bytes, "
                    "up_bytes=up_bytes+excluded.up_bytes, "
                    "samples=samples+1",
                    (did, h, meta["day"], meta["week"], meta["month"], meta["year"],
                     int(dl_inc * w), int(up_inc * w)),
                )
                cur = seg_end
        c.execute(
            "INSERT INTO downloader_state "
            "(downloader_id,last_dl_total,last_up_total,last_ts) VALUES (?,?,?,?) "
            "ON CONFLICT(downloader_id) DO UPDATE SET "
            "last_dl_total=COALESCE(excluded.last_dl_total,downloader_state.last_dl_total),"
            "last_up_total=COALESCE(excluded.last_up_total,downloader_state.last_up_total),"
            "last_ts=excluded.last_ts",
            (did, s.get("dl_total"), s.get("up_total"), now),
        )


def update_live(did, **fields):
    """采集写瞬时状态（纯内存，加锁，绝不碰 SQLite）。"""
    with _live_lock:
        cur = dict(_live.get(did) or {})
        cur.update(fields)
        _live[did] = cur


def mark_offline(did, message):
    """采集失败：标记离线并清零瞬时速率（内存态）。"""
    msg = str(message)[:300]
    with _live_lock:
        cur = dict(_live.get(did) or {})
        cur.update({"last_seen": int(time.time()), "status": "offline",
                    "error": msg, "dl_rate": 0, "up_rate": 0})
        _live[did] = cur


def get_states():
    """DB 累计基线 + 内存实时态合并。"""
    with conn() as c:
        base = {r["downloader_id"]: dict(r)
                for r in c.execute("SELECT * FROM downloader_state")}
    with _live_lock:
        live = {k: dict(v) for k, v in _live.items()}
    out = {}
    for did in set(base) | set(live):
        row = dict(base.get(did) or {})
        lv = live.get(did) or {}
        if isinstance(lv.get("extra"), dict):
            lv["extra"] = json.dumps(lv["extra"], ensure_ascii=False)
        for k in ("status", "error", "last_seen", "dl_rate", "up_rate", "extra"):
            if k in lv:
                row[k] = lv[k]
        if not row.get("error") and lv.get("traffic_error"):
            row["error"] = lv["traffic_error"]
        row.setdefault("status", "unknown")
        row.setdefault("dl_rate", 0)
        row.setdefault("up_rate", 0)
        out[did] = row
    return out


# ---------- 数据源边界缓存 ----------

def invalidate_bounds():
    with _bounds_lock:
        _bounds_cache["data"] = None
        _bounds_cache["ts"] = 0.0


def bounds(force=False):
    """一次查询拿到各数据源的时间边界，TTL 缓存。"""
    now = time.time()
    with _bounds_lock:
        if (not force and _bounds_cache["data"] is not None
                and now - _bounds_cache["ts"] < _BOUNDS_TTL):
            return dict(_bounds_cache["data"])
    with conn() as c:
        def mn(sql):
            r = c.execute(sql).fetchone()
            return r[0] if r and r[0] is not None else None
        data = {
            # 实时速率曲线（samples 表）v1.0.2 起不再写入 / 读取
            "samples_min_ts": None,
            "traffic_min_ts": mn("SELECT MIN(ts) FROM traffic_samples"),
            "traffic_max_ts": mn("SELECT MAX(ts) FROM traffic_samples"),
            "hourly_min_ts": mn("SELECT MIN(hour_ts) FROM hourly"),
            "rollup_1m_min_ts": mn("SELECT MIN(minute_ts) FROM rollup_1m"),
            "rollup_1m_max_ts": mn("SELECT MAX(minute_ts) FROM rollup_1m"),
        }
    with _bounds_lock:
        _bounds_cache["data"] = dict(data)
        _bounds_cache["ts"] = now
    return dict(data)


def cleanup_samples(retention_days):
    cutoff = time.time() - retention_days * 86400
    with conn() as c:
        c.execute("DELETE FROM traffic_samples WHERE ts < ?", (cutoff,))
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            try:
                c.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.OperationalError:
                pass
    invalidate_bounds()
