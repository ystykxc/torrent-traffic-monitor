"""SQLite 存储层：单文件 traffic.db，WAL 模式，每次操作新建连接。

表结构与职责：
- hourly：小时桶，写入时冗余 day / week / month / year 四个字符串键；
  日/周/月/年全部从这一层聚合，一份数据出所有报表，天然对得上账。
- samples：实时速率采样（AVG 聚合，短期保留），只供速率曲线。
- traffic_samples：流量统计采样点（累计计数器差值），短窗口流量图用。
- rollup_1m / rollup_1d：由 rollup.run_once 幂等物化的分层聚合，保留 90 天。
- downloaders / users / sessions / app_settings / audit_log：配置、账户、
  会话、运行参数与审计事件。
- 下载器密码以 enc:v1: 密文存储，密钥来自 SECRET_KEY 或 data/.secret_key。

init_db() 兼容旧库：自动补齐颜色列、速率专用基线列、会话绑定列、
app_settings 与审计表，并一次性迁移历史数据、加密明文密码、作废旧长期会话。
速率瞬时状态放内存 _live 不写库；配色按「上传暖 / 下载冷」顺序分配，
只对从未手动改色的系统默认色做幂等迁移，用户自定义配色永远保留。
"""
import colorsys
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import crypto, log, timeutil

_DB_FILE = None

# 速率线程的瞬时状态（在线 / 速率 / 错误 / extra）全部放内存，
# 不再每 0.1 秒 UPDATE downloader_state。downloader_state 只由流量线程维护
# 累计基线，两个采集线程彻底不再争同一个 SQLite 写锁，也消除 set_offline
# 互相覆盖在线状态的竞态。代价：容器重启后到首轮采集之间状态为 unknown，
# 而首轮采集在 0.1~10 秒内必然到达，可接受。
_live = {}
_live_lock = threading.Lock()

# 三处 MIN(ts) 全表扫描合并成一次查询 + TTL 缓存。
# MIN 只会随新数据保持不变/变大，cleanup 删掉最老数据后才需要重算，
# 因此缓存 30 秒并在 cleanup / rollup 后主动失效即可，绝不会读脏。
_bounds_cache = {"ts": 0.0, "data": None}
_bounds_lock = threading.Lock()
_BOUNDS_TTL = 30.0


def _hsl_hex(h, s, l):
    """HSL -> #RRGGBB（标准库，无外部依赖）。"""
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# 每个下载器默认分配一对（上传色, 下载色）；汇总固定用下面两个色。
#
# 配色原则：旧板两个方向都用 i*36 连续递增，用户实际的前 5 个
# 下载器只拿到 0/36/72/108/144°，挤在半圈里 —— 这正是「同为上传的颜色接近、
# 容易混淆」的根因。改用 OKLab 感知色差 farthest-point 数值寻优出的色相
# 序列 HUE_SEQ（前 5 个直接铺满整个色环），下载色在同序列基础上整体旋转
# DN_PHASE 度，让上传组与下载组在色环上完全错开、不互相撞色。相位同样由
# 寻优确定：主判据是「前 5 台 × 2 方向共 10 条线整体最小两两 ΔE 最大」，
# 它同时约束了同为上传的组内、同为下载的组内与跨方向，深浅两套主题都验证。
# 量化结果（相对旧板，深色 / 浅色）：同为上传 +221% / +218%，同为下载
# +39% / +39%，10 线整体 +73% / +69%，全 20 线整体 +60%，且更远离汇总色。
HUE_SEQ = [174, 294, 240, 60, 354, 120, 216, 273, 45, 324]
DN_PHASE = 30
# 的系统默认色（HUE_SEQ 生成）。起改由用户指定配色，这份旧板
# 只用于一次性迁移时识别「仍是 系统默认、未被手动改过」的下载器。
LEGACY_PALETTE_V16 = [
    (_hsl_hex(h, .70, .60), _hsl_hex(h + DN_PHASE, .68, .56))
    for h in HUE_SEQ
]
# 用户提供的参考配色，逐点从截图的 5 组上传/下载色块精确取色
# （核心区中位数，三种采样法交叉校验）。顺序＝下载器 sort_order 前 5 台，
# 即图片里自上而下的 qb / tr / tr1 / qb1 / tr2。大小写统一为小写 hex。
USER_PALETTE_V25 = [
    ("#f46c6a", "#419dff"),   # qb 上传珊瑚红 / 下载亮蓝
    ("#e7a33a", "#65c337"),   # tr 上传琥珀橙 / 下载草绿
    ("#d78970", "#892be2"),   # tr1 上传赭棕 / 下载亮紫
    ("#fab6b7", "#9fcfff"),   # qb1 上传浅粉 / 下载浅蓝
    ("#f7d0a8", "#b1e19c"),   # tr2 上传浅杏 / 下载浅绿
]
# 直接采用 PT Nexus（sqing33/PTNexus 流量统计页 InfoView.vue）源码里的
# 默认色板精确值，而不是 从截图逐点取色得到的近似值 —— 后者与标准色有
# ±2~3 的误差。源码逻辑为「上传一组暖色 / 下载一组冷色，按下载器顺序
# index % len 固定分配」，5 台以内自动分配区分度极高。前 5 组与 PT Nexus
# 逐值完全一致（统一转小写存储，界面展示时再统一大写）；第 6~10 组沿用
# 同一「上传暖 / 下载冷 + 色相铺开」原则续写协调色，避免 那套高饱和
# HSL 寻优色与前 5 组风格割裂，保证 10 台也齐全、两两不重复。
PTNEXUS_PALETTE_V27 = [
    ("#f56c6c", "#409eff"),   # 1 上传珊瑚红 / 下载亮蓝 (PT Nexus #F56C6C / #409EFF)
    ("#e6a23c", "#67c23a"),   # 2 上传琥珀橙 / 下载草绿 (PT Nexus #E6A23C / #67C23A)
    ("#d98a6f", "#8a2be2"),   # 3 上传赭棕 / 下载亮紫 (PT Nexus #D98A6F / #8A2BE2)
    ("#fab6b6", "#a0cfff"),   # 4 上传浅粉 / 下载浅蓝 (PT Nexus #FAB6B6 / #A0CFFF)
    ("#f7d0a3", "#b3e19d"),   # 5 上传浅杏 / 下载浅绿 (PT Nexus #F7D0A3 / #B3E19D)
    ("#e8794b", "#2bb3c0"),   # 6 上传橙红 / 下载青蓝 (风格延续)
    ("#c9a227", "#5b8ff9"),   # 7 上传金黄 / 下载霁蓝 (风格延续)
    ("#b05c7d", "#9270ca"),   # 8 上传玫红 / 下载堇紫 (风格延续)
    ("#d98f4f", "#48bb78"),   # 9 上传琥珀 / 下载竹绿 (风格延续)
    ("#c96f5a", "#7aa7e8"),   # 10 上传砖红 / 下载湖蓝 (风格延续)
]
PALETTE = PTNEXUS_PALETTE_V27
# 的旧系统默认色，仅用于一次性迁移时识别「仍是系统默认、未被手动改过」
LEGACY_PALETTE = [
    (_hsl_hex(i * 36, .70, .60), _hsl_hex(i * 36 + 168, .68, .56))
    for i in range(10)
]
SUMMARY_UP = "#fb923c"
SUMMARY_DOWN = "#38bdf8"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def configure(data_dir):
    global _DB_FILE
    os.makedirs(data_dir, exist_ok=True)
    _DB_FILE = os.path.join(data_dir, "traffic.db")
    crypto.configure(data_dir)      # 准备下载器密码加密密钥


@contextmanager
def conn():
    if _DB_FILE is None:
        raise RuntimeError("db.configure() 尚未调用")
    c = sqlite3.connect(_DB_FILE, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    # 内存优化：每次请求都新建连接，默认 page cache 约 2MB/连接，
    # 并发时就是十几 MB 的瞬时峰值。收紧到 512KB 并禁用 mmap，削平峰值分配，
    # 让 allocator 不必把堆扩到高位后长期占着不还。
    c.execute("PRAGMA cache_size=-512")
    c.execute("PRAGMA mmap_size=0")
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
    name        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK(type IN ('qb','tr')),
    url         TEXT NOT NULL,
    username    TEXT NOT NULL DEFAULT '',
    password    TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    color_up    TEXT NOT NULL DEFAULT '',
    color_down  TEXT NOT NULL DEFAULT '',
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
    -- 实时速率采样与流量统计采样各自独立的累计计数器基线，互不覆盖
    rate_last_dl_total  INTEGER,
    rate_last_up_total  INTEGER,
    rate_last_ts        REAL
);

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

-- 流量统计采样点（独立表）。流量统计线程按自己的间隔写入累计计数器
-- 差值；流量统计卡片的短窗口（1/6/12 小时）只 SUM 这张表，密度与「流量统计
-- 采样间隔」设置严格一致。samples 表自此只存实时速率（dl_inc/up_inc 恒为 0，
-- 升级前已写入的历史 inc 保留，供 UNION 查询平滑衔接，不丢旧数据）。
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

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    username        TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    must_change     INTEGER NOT NULL DEFAULT 1,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT PRIMARY KEY,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    -- 会话绑定 UA 指纹 / IP 段，滑动续期与最大生命周期
    ua_hash         TEXT NOT NULL DEFAULT '',
    ip_net          TEXT NOT NULL DEFAULT '',
    last_seen       INTEGER NOT NULL DEFAULT 0,
    max_expires_at  INTEGER NOT NULL DEFAULT 0
);

-- 运行时可调参数（采样间隔、实时窗口等），改动持久化，重启不丢
CREATE TABLE IF NOT EXISTS app_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

-- 自动 rollup 分层物化表。采集只写 traffic_samples(raw) 与
-- hourly(1h)，后台 rollup.run_once() 幂等生成 1m / 1d 两层，查询按窗口
-- 跨度只选一张表，彻底删掉 UNION ALL 与近细远粗的混合分支。
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

-- 审计日志。登录 / 账号变更 / 下载器增删改 / 连接测试目标 /
-- 采集参数变更全部留痕，容器重启后仍可回溯。
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL NOT NULL,
    event           TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT '',
    ip              TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


def norm_color(value, fallback=None):
    """只接受 #RRGGBB，防止把任意字符串写进页面样式。"""
    s = str(value or "").strip()
    return s.lower() if _HEX.fullmatch(s) else fallback


def init_db():
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        # 旧库补齐「实时速率采样」独立基线列。流量统计继续使用原有的
        # last_dl_total / last_up_total / last_ts（旧值正好衔接，不丢基线），
        # 实时速率改用 rate_last_* 单独记账，两个采集线程互不覆盖。
        scols = {r["name"] for r in c.execute("PRAGMA table_info(downloader_state)")}
        for _col, _decl in (("rate_last_dl_total", "INTEGER"),
                            ("rate_last_up_total", "INTEGER"),
                            ("rate_last_ts", "REAL")):
            if _col not in scols:
                c.execute("ALTER TABLE downloader_state ADD COLUMN %s %s" % (_col, _decl))

        # ---- 旧库补齐会话绑定 / 滑动续期列 ----
        ucols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)")}
        for _col, _decl in (("ua_hash", "TEXT NOT NULL DEFAULT ''"),
                            ("ip_net", "TEXT NOT NULL DEFAULT ''"),
                            ("last_seen", "INTEGER NOT NULL DEFAULT 0"),
                            ("max_expires_at", "INTEGER NOT NULL DEFAULT 0")):
            if _col not in ucols:
                c.execute("ALTER TABLE sessions ADD COLUMN %s %s" % (_col, _decl))
        # 升级前的旧会话是「10 年有效期、不绑定 UA/IP」的长期通行证，
        # 直接作废旧会话、强制所有设备重新登录一次，从根上收回权限。
        c.execute("DELETE FROM sessions WHERE max_expires_at<=0 OR max_expires_at<expires_at")

        # ---- 一次性把升级前 samples 里的历史 inc 迁进 traffic_samples ----
        # 短窗口流量图靠 UNION ALL traffic_samples + samples 兼容旧数据，
        # 混表语义不同且随历史量线性变慢。迁移后 chart.py 只读一张 traffic_samples，
        # 既不丢旧数据，也把 UNION ALL 彻底删掉。幂等标记保证只跑一次。
        done = c.execute("SELECT value FROM app_settings WHERE key='legacy_inc_v35'").fetchone()
        if not done:
            cur = c.execute(
                "INSERT INTO traffic_samples (downloader_id,ts,dl_inc,up_inc) "
                "SELECT s.downloader_id, s.ts, s.dl_inc, s.up_inc FROM samples s "
                "WHERE (s.dl_inc <> 0 OR s.up_inc <> 0) AND NOT EXISTS "
                "(SELECT 1 FROM traffic_samples t WHERE t.downloader_id=s.downloader_id "
                " AND t.ts=s.ts)"
            )
            c.execute("INSERT INTO app_settings(key,value) VALUES('legacy_inc_v35','1') "
                      "ON CONFLICT(key) DO UPDATE SET value='1'")
            if cur.rowcount and cur.rowcount > 0:
                print(f"[db] 已把 {cur.rowcount} 条 samples 历史流量采样迁入 "
                      "traffic_samples（删除 UNION ALL 兼容分支）", flush=True)

        # ---- 把库里残留的明文下载器密码一次性改写成密文 ----
        # encrypt 对已加密值原样返回，因此即使标记丢失、重复执行也幂等。
        enc_rows = c.execute("SELECT id,password FROM downloaders").fetchall()
        enc_n = 0
        for r in enc_rows:
            raw = str(r["password"] or "")
            if raw and not crypto.is_encrypted(raw):
                c.execute("UPDATE downloaders SET password=? WHERE id=?",
                          (crypto.encrypt(raw), r["id"]))
                enc_n += 1
        if enc_n:
            print(f"[db] 已加密 {enc_n} 个下载器的明文密码", flush=True)

        # ---- 密钥来源变更后的历史密文统一到当前主密钥 ----
        # 例如「先默认启动（.secret_key 加密）→ 后来补上 SECRET_KEY」，
        # crypto.decrypt 已能用回退密钥解开；这里再一次性 rekey，
        # 让库里最终只保留当前主密钥的密文，长期不依赖回退链。
        rekey_n = 0
        for r in enc_rows:
            new_val = crypto.rekey(r["password"])
            if new_val is not None:
                c.execute("UPDATE downloaders SET password=? WHERE id=?",
                          (new_val, r["id"]))
                rekey_n += 1
        if rekey_n:
            print(f"[db] 已用当前主密钥重加密 {rekey_n} 个历史下载器密码", flush=True)

        cols = {r["name"] for r in c.execute("PRAGMA table_info(downloaders)")}
        if "color_up" not in cols or "color_down" not in cols:
            if "color_up" not in cols:
                c.execute("ALTER TABLE downloaders ADD COLUMN color_up TEXT NOT NULL DEFAULT ''")
            if "color_down" not in cols:
                c.execute("ALTER TABLE downloaders ADD COLUMN color_down TEXT NOT NULL DEFAULT ''")
            rows = c.execute("SELECT id FROM downloaders ORDER BY sort_order, id").fetchall()
            for i, r in enumerate(rows):
                up, down = PALETTE[i % len(PALETTE)]
                c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                          (up, down, r["id"]))
            print(f"[db] 已为 {len(rows)} 个已有下载器分配默认曲线颜色", flush=True)
        # 修补历史遗留的空颜色
        empty = c.execute("SELECT id FROM downloaders WHERE color_up='' OR color_down='' "
                          "ORDER BY sort_order, id").fetchall()
        for i, r in enumerate(empty):
            up, down = PALETTE[i % len(PALETTE)]
            c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                      (up, down, r["id"]))

        # 把「仍是 旧系统默认色」的下载器一次性迁移到新色板。
        # 只替换完整命中旧板某一对的记录：用户手动改过任意一色（或用调色板
        # 自定义过）就被视为自定义配色，原样保留，绝不被覆盖。用 app_settings
        # 打标记保证幂等 —— 升级重启、反复 init_db 都只迁移一次，之后新增 /
        # 重排 / 一键重分配都直接使用新板。历史流量数据完全不受影响。
        done = c.execute("SELECT value FROM app_settings WHERE key='palette_v16'").fetchone()
        if not done:
            legacy = {(u.lower(), d.lower()) for u, d in LEGACY_PALETTE}
            rows = c.execute(
                "SELECT id,color_up,color_down FROM downloaders ORDER BY sort_order, id"
            ).fetchall()
            migrated = 0
            for i, r in enumerate(rows):
                key = (str(r["color_up"] or "").lower(), str(r["color_down"] or "").lower())
                if key in legacy:
                    up, down = PALETTE[i % len(PALETTE)]
                    c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                              (up, down, r["id"]))
                    migrated += 1
            c.execute(
                "INSERT INTO app_settings(key,value) VALUES('palette_v16','1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            if migrated:
                print(f"[db] 已把 {migrated} 个旧默认配色的下载器迁移到新高区分度色板",
                      flush=True)

        # 把「仍是 系统默认色」的下载器按 sort_order 顺序一次性
        # 迁移到用户指定的参考配色（前 5 台）。同样只替换完整命中旧板某一对
        # 的记录，手动改过任意一色的视为自定义配色、原样保留；palette_v25
        # 标记保证幂等 —— 升级重启、反复 init_db 都只迁移一次。历史流量数据
        # 完全不受影响。
        done25 = c.execute("SELECT value FROM app_settings WHERE key='palette_v25'").fetchone()
        if not done25:
            legacy25 = {(u.lower(), d.lower()) for u, d in LEGACY_PALETTE_V16}
            rows25 = c.execute(
                "SELECT id,color_up,color_down FROM downloaders ORDER BY sort_order, id"
            ).fetchall()
            migrated25 = 0
            for i, r in enumerate(rows25):
                key25 = (str(r["color_up"] or "").lower(), str(r["color_down"] or "").lower())
                if key25 in legacy25:
                    up25, down25 = PALETTE[i % len(PALETTE)]
                    c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                              (up25, down25, r["id"]))
                    migrated25 += 1
            c.execute(
                "INSERT INTO app_settings(key,value) VALUES('palette_v25','1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            if migrated25:
                print(f"[db] 已把 {migrated25} 个系统默认配色迁移到用户指定参考配色",
                      flush=True)

        # 把「仍是 截图取色 / HSL 系统默认色」的下载器按
        # sort_order 顺序一次性迁移到 PT Nexus 精确色板。只替换完整命中
        # 旧系统板某一对的记录；用户手动改过任意一色（含通过 hex / RGB
        # 数值框自定义）的视为自定义配色，原样保留。palette_v27 标记保证
        # 幂等 —— 升级重启、反复 init_db 都只迁移一次。历史流量数据不变。
        done27 = c.execute("SELECT value FROM app_settings WHERE key='palette_v27'").fetchone()
        if not done27:
            legacy27 = {(u.lower(), d.lower()) for u, d in (LEGACY_PALETTE_V16 + USER_PALETTE_V25)}
            rows27 = c.execute(
                "SELECT id,color_up,color_down FROM downloaders ORDER BY sort_order, id"
            ).fetchall()
            migrated27 = 0
            for i, r in enumerate(rows27):
                key27 = (str(r["color_up"] or "").lower(), str(r["color_down"] or "").lower())
                if key27 in legacy27:
                    up27, down27 = PALETTE[i % len(PALETTE)]
                    c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                              (up27, down27, r["id"]))
                    migrated27 += 1
            c.execute(
                "INSERT INTO app_settings(key,value) VALUES('palette_v27','1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            if migrated27:
                print(f"[db] 已把 {migrated27} 个旧默认配色的下载器迁移到 PT Nexus 精确色板",
                      flush=True)


def next_palette_index():
    """与 PT Nexus 一致 —— 按当前下载器数量顺序取下一组（index % len）。

    新增第 n 台时正好拿到色板第 n 组，5 台以内自动分配区分度最高；
    超过色板长度时从头循环。不再「找第一组没被占用的色」，避免删除 /
    重排 / 手动改色后新下载器跳到不相邻的色组。"""
    with conn() as c:
        count = c.execute("SELECT COUNT(*) FROM downloaders").fetchone()[0]
    return count % len(PALETTE)


def import_initial(downloaders):
    """首次启动把 config.json 的下载器导入数据库；之后以数据库为准。"""
    if not downloaders:
        return
    with conn() as c:
        n = c.execute("SELECT COUNT(*) FROM downloaders").fetchone()[0]
        if n:
            return
        now = int(time.time())
        for i, d in enumerate(downloaders):
            up, down = PALETTE[i % len(PALETTE)]
            c.execute(
                "INSERT INTO downloaders "
                "(name,type,url,username,password,enabled,sort_order,color_up,color_down,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(d.get("name") or f"下载器{i+1}"),
                    "tr" if str(d.get("type", "qb")).lower() in ("tr", "transmission") else "qb",
                    str(d.get("url", "")).rstrip("/"),
                    str(d.get("username", "")),
                    crypto.encrypt(str(d.get("password", ""))),   # 密文入库
                    1 if d.get("enabled", True) else 0,
                    i,
                    norm_color(d.get("color_up"), up),
                    norm_color(d.get("color_down"), down),
                    now,
                ),
            )
        print(f"[db] 已从 config.json 导入 {len(downloaders)} 个下载器", flush=True)


# ---------- 账户与会话 ----------

def count_users():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_user():
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=1").fetchone()
        return dict(r) if r else None


def create_user(username, password_hash, must_change=1):
    with conn() as c:
        c.execute("DELETE FROM users")
        c.execute("INSERT INTO users (id,username,password_hash,must_change,updated_at) "
                  "VALUES (1,?,?,?,?)", (username, password_hash, int(must_change), int(time.time())))


def update_user(username, password_hash, must_change):
    with conn() as c:
        c.execute("UPDATE users SET username=?,password_hash=?,must_change=?,updated_at=? WHERE id=1",
                  (username, password_hash, int(must_change), int(time.time())))


def reset_auth():
    """忘记密码时用：清空账户与所有会话，下次启动重建默认账号。"""
    with conn() as c:
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM users")


def create_session(token, expires_at, ua_hash="", ip_net="", max_expires_at=None):
    """新建会话时一并记下 UA 指纹 / IP 段与最大生命周期上限。"""
    now = int(time.time())
    with conn() as c:
        c.execute(
            "INSERT INTO sessions "
            "(token,created_at,expires_at,ua_hash,ip_net,last_seen,max_expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (token, now, int(expires_at), ua_hash or "", ip_net or "", now,
             int(max_expires_at or expires_at)),
        )


def get_session(token):
    with conn() as c:
        r = c.execute(
            "SELECT s.token, s.created_at, s.expires_at, s.ua_hash, s.ip_net, "
            "s.last_seen, s.max_expires_at, u.username, u.must_change "
            "FROM sessions s JOIN users u ON u.id=1 WHERE s.token=?",
            (token,),
        ).fetchone()
        return dict(r) if r else None


def touch_session(token, new_expires, now_ts):
    """滑动续期，但绝不超过 max_expires_at（绝对生命周期上限）。"""
    with conn() as c:
        c.execute(
            "UPDATE sessions SET last_seen=?, "
            "expires_at=MAX(expires_at, MIN(max_expires_at, ?)) "
            "WHERE token=? AND max_expires_at>0",
            (int(now_ts), int(new_expires), token),
        )


def count_sessions():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def delete_session(token):
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def delete_sessions():
    with conn() as c:
        c.execute("DELETE FROM sessions")


def delete_other_sessions(keep_token):
    """改密码后踢掉其他设备，当前浏览器保持登录。"""
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token<>?", (keep_token,))


# ---------- 运行时可调参数 ----------

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


# ---------- 下载器配置 ----------

def list_downloaders(enabled_only=False, public=False):
    sql = "SELECT * FROM downloaders"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY sort_order, id"
    with conn() as c:
        rows = [dict(r) for r in c.execute(sql).fetchall()]
    for r in rows:
        r["color_up"] = norm_color(r.get("color_up"), SUMMARY_UP)
        r["color_down"] = norm_color(r.get("color_down"), SUMMARY_DOWN)
        # 库里是密文，读出来时透明解密供采集器登录使用；
        # public=True 只回显 has_password，密码本身绝不出现在 API 响应里。
        r["password"] = crypto.decrypt(r.get("password"))
        if public:
            r["has_password"] = bool(r.pop("password", ""))
    return rows


def get_downloader(did):
    with conn() as c:
        r = c.execute("SELECT * FROM downloaders WHERE id=?", (did,)).fetchone()
        d = dict(r) if r else None
    if d:
        d["password"] = crypto.decrypt(d.get("password"))
    return d


def save_downloader(payload, did=None):
    # 没显式传 sort_order 时：新增排到末尾，编辑保持原位（配置页表单不再带顺序字段）
    raw_order = payload.get("sort_order", None)
    if raw_order in (None, ""):
        if did is None:
            with conn() as c:
                sort_order = c.execute("SELECT COUNT(*) FROM downloaders").fetchone()[0]
        else:
            sort_order = int((get_downloader(did) or {}).get("sort_order") or 0)
    else:
        sort_order = int(raw_order or 0)
    base = [
        str(payload.get("name") or "未命名"),
        "tr" if str(payload.get("type", "qb")).lower() in ("tr", "transmission") else "qb",
        str(payload.get("url", "")).rstrip("/"),
        str(payload.get("username", "")),
        crypto.encrypt(str(payload.get("password", ""))),   # 密文入库
        1 if payload.get("enabled", True) else 0,
        sort_order,
    ]
    if did is None:
        idx = next_palette_index()
        color_up = norm_color(payload.get("color_up"), PALETTE[idx][0])
        color_down = norm_color(payload.get("color_down"), PALETTE[idx][1])
        with conn() as c:
            cur = c.execute(
                "INSERT INTO downloaders "
                "(name,type,url,username,password,enabled,sort_order,color_up,color_down,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                base + [color_up, color_down, int(time.time())],
            )
            return cur.lastrowid
    cur = get_downloader(did) or {}
    color_up = norm_color(payload.get("color_up"), norm_color(cur.get("color_up"), SUMMARY_UP))
    color_down = norm_color(payload.get("color_down"), norm_color(cur.get("color_down"), SUMMARY_DOWN))
    with conn() as c:
        # 密码留空表示保持不变
        if not base[4]:
            c.execute(
                "UPDATE downloaders SET name=?,type=?,url=?,username=?,enabled=?,sort_order=?,"
                "color_up=?,color_down=? WHERE id=?",
                [base[0], base[1], base[2], base[3], base[5], base[6], color_up, color_down, did],
            )
        else:
            c.execute(
                "UPDATE downloaders SET name=?,type=?,url=?,username=?,password=?,enabled=?,sort_order=?,"
                "color_up=?,color_down=? WHERE id=?",
                base + [color_up, color_down, did],
            )
        return did


def reorder_downloaders(ids):
    """按给定 id 顺序重排：单个事务里把 sort_order 设为列表下标。

    忽略不存在的 id 与重复项；没出现在 ids 里的下载器保持原相对顺序排在末尾。
    返回最终生效的 id 顺序。
    """
    wanted, seen = [], set()
    for x in ids or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i not in seen:
            seen.add(i)
            wanted.append(i)
    with conn() as c:
        existing = [r["id"] for r in
                    c.execute("SELECT id FROM downloaders ORDER BY sort_order, id").fetchall()]
        eset = set(existing)
        ordered = [i for i in wanted if i in eset] + [i for i in existing if i not in seen]
        for pos, did in enumerate(ordered):
            c.execute("UPDATE downloaders SET sort_order=? WHERE id=?", (pos, did))
    return ordered


def recolor_all(shift=None):
    """「一键重新分配颜色」：按当前 sort_order 顺序把调色板依次分配给所有下载器。

    shift 为调色板轮转起点；不传时随机取一个，保证每点一次都能换一套新配色。
    只改颜色，不动流量数据 / 账户 / 其他配置。
    """
    import random
    with conn() as c:
        rows = c.execute("SELECT id FROM downloaders ORDER BY sort_order, id").fetchall()
        base = random.randrange(len(PALETTE)) if shift is None else int(shift)
        base %= len(PALETTE)
        for i, r in enumerate(rows):
            up, down = PALETTE[(i + base) % len(PALETTE)]
            c.execute("UPDATE downloaders SET color_up=?, color_down=? WHERE id=?",
                      (up, down, r["id"]))
    return {"count": len(rows), "shift": base,
            "colors": [{"up": PALETTE[(i + base) % len(PALETTE)][0],
                        "down": PALETTE[(i + base) % len(PALETTE)][1]}
                       for i in range(len(rows))]}


def delete_downloader(did):
    with conn() as c:
        c.execute("DELETE FROM downloaders WHERE id=?", (did,))
        c.execute("DELETE FROM downloader_state WHERE downloader_id=?", (did,))
        c.execute("DELETE FROM samples WHERE downloader_id=?", (did,))
        c.execute("DELETE FROM traffic_samples WHERE downloader_id=?", (did,))
        c.execute("DELETE FROM hourly WHERE downloader_id=?", (did,))


# ---------- 采集状态 ----------

def get_state(did):
    with conn() as c:
        r = c.execute("SELECT * FROM downloader_state WHERE downloader_id=?", (did,)).fetchone()
        return dict(r) if r else None


def record_rate_sample(did, now, s):
    """实时速率采样 —— **只写 samples 一张表**。

    这里每 0.1 秒还要 UPDATE downloader_state（状态 / 速率 / rate_last_*
    基线 / extra），与流量线程的写事务抢 SQLite 写锁。把这些瞬时状态全部
    搬到内存 (update_live)，downloader_state 只由流量线程维护累计基线，
    彻底消除写竞争与 0.1 秒档位下的磁盘写放大。samples 的 dl_inc / up_inc
    恒写 0；升级前旧库里的历史 inc 已由 init_db() 一次性迁进 traffic_samples。
    """
    with conn() as c:
        c.execute(
            "INSERT INTO samples (downloader_id,ts,dl_rate,up_rate,dl_inc,up_inc) VALUES (?,?,?,?,?,?)",
            (did, now, s["dl_rate"], s["up_rate"], 0, 0),
        )


def record_traffic_sample(did, now, start_ts, s, dl_inc, up_inc):
    """流量统计采样 —— 写独立采样点 traffic_samples + 把累计计数器差值
    分摊到 hourly 小时桶，并更新「流量统计专用」基线 last_dl_total /
    last_up_total / last_ts。

    绝不写 samples，绝不触碰 dl_rate / up_rate / status / rate_last_*：
    实时速率完全由速率线程负责。统计口径沿用 —— 只用累计计数器差值，
    异常轮次记 0、保留基线、差值自愈，采样间隔变长不会丢量。
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

        # 累计计数器基线绝不能被 NULL 冲掉。用 COALESCE 只在新值非空时
        # 更新基线；计数器真正回退（新值更小但非空）会正常写入，从而在下轮
        # 以新值重建基线。
        c.execute(
            "INSERT INTO downloader_state "
            "(downloader_id,last_dl_total,last_up_total,last_ts) VALUES (?,?,?,?) "
            "ON CONFLICT(downloader_id) DO UPDATE SET "
            "last_dl_total=COALESCE(excluded.last_dl_total,downloader_state.last_dl_total),"
            "last_up_total=COALESCE(excluded.last_up_total,downloader_state.last_up_total),"
            "last_ts=excluded.last_ts",
            (did, s.get("dl_total"), s.get("up_total"), now),
        )


# ---------------- 内存实时状态 ----------------

def update_live(did, **fields):
    """速率线程写瞬时状态（纯内存，加锁，绝不碰 SQLite）。"""
    with _live_lock:
        cur = dict(_live.get(did) or {})
        cur.update(fields)
        _live[did] = cur


def mark_offline(did, message, source="rate"):
    """采集失败时记离线。

    两个线程都 db.set_offline() 写同一行，互相覆盖在线状态。改成内存
    合并：rate 线程决定 status/error/速率；traffic 线程只记 traffic_error，
    不覆盖 rate 线程刚判定的在线状态，竞态彻底消失。
    """
    msg = str(message)[:300]
    with _live_lock:
        cur = dict(_live.get(did) or {})
        cur["last_seen"] = int(time.time())
        if source == "rate":
            cur["status"] = "offline"
            cur["error"] = msg
            cur["dl_rate"] = 0
            cur["up_rate"] = 0
        else:
            cur["traffic_error"] = msg
            cur.setdefault("status", "unknown")
        _live[did] = cur


def set_offline(did, message, source="rate"):
    """兼容旧调用名（collector），语义改为写内存实时态。"""
    mark_offline(did, message, source)


def get_states():
    """对外读取：DB 累计基线 + 内存实时态合并，接口形状与 完全一致。"""
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


# ---------------- 数据源边界缓存 ----------------

def invalidate_bounds():
    with _bounds_lock:
        _bounds_cache["data"] = None
        _bounds_cache["ts"] = 0.0


def bounds(force=False):
    """一次查询拿到各数据源的时间边界，TTL 缓存，替代 每次请求三处 MIN(ts)。

    返回 dict：samples_min_ts / traffic_min_ts / hourly_min_ts /
    rollup_1m_min_ts / rollup_1m_max_ts / traffic_max_ts。
    """
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
            "samples_min_ts": mn("SELECT MIN(ts) FROM samples"),
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


# ---------------- 审计日志 ----------------

def audit(event, actor="", ip="", detail=""):
    """结构化日志 + 持久化落库双写。detail 里绝不记录密码 / token。"""
    log.info("audit." + str(event), actor=actor, ip=ip, detail=str(detail)[:300])
    try:
        with conn() as c:
            c.execute(
                "INSERT INTO audit_log(ts,event,actor,ip,detail) VALUES (?,?,?,?,?)",
                (time.time(), str(event), str(actor or ""), str(ip or ""),
                 str(detail)[:500]),
            )
            # 只保留最近 5000 条，避免无限膨胀
            c.execute("DELETE FROM audit_log WHERE id IN "
                      "(SELECT id FROM audit_log ORDER BY id DESC LIMIT -1 OFFSET 5000)")
    except Exception as exc:
        log.warn("audit.write_failed", error=str(exc))


def list_audit(limit=100):
    try:
        with conn() as c:
            rows = c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                             (max(1, min(500, int(limit))),)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def cleanup_samples(retention_days):
    cutoff = time.time() - retention_days * 86400
    with conn() as c:
        # 两张采样表按同一保留期清理（hourly / rollup_1d 是长期汇总，不清理）。
        c.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM traffic_samples WHERE ts < ?", (cutoff,))
        # 内存/磁盘优化：DELETE 不会自动收缩 WAL，截断已合并页避免
        # -wal 文件与 page cache 随清理动作长期累积。
        # TRUNCATE 在存在其他读连接时会抛
        # "database table is locked"（采集线程与 Web 请求并发时很常见），
        # 属正常并发，不能让它中断清理、也不能每轮刷一条异常栈。
        # 降级为 PASSIVE 并完全容错，清理结果（DELETE）仍照常提交。
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            try:
                c.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.OperationalError:
                pass
    invalidate_bounds()
