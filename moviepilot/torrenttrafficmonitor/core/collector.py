"""后台采集：单线程、两条节奏取数。

v1.0.3 起把「实时速率」与「流量统计」的采样节奏拆开，但仍是同一条线程、
同一份客户端缓存，一次 fetch 同时服务两个目的：

  · 实时速率节奏：固定 5 秒（constants.RATE_POLL_INTERVAL），不外显设置。
    每轮对每台启用的下载器 fetch 快照，只更新内存实时态（在线状态 /
    瞬时上传下载速率 / extra），供下载器卡片与详情弹窗展示；不写任何
    历史表、不参与流量累加。
  · 流量统计节奏：按配置页「采样间隔」（默认 1 分钟，可调）记账。仅在
    到达记账点的那一轮，用「累计计数器单调差值」写 traffic_samples +
    hourly 小时桶；中间的实时速率轮次一律不记账。

因为累计计数器是单调累计值，跨多个 5 秒实时轮次才记一次账也不会丢流量：
差值 = 本次累计值 − 上次记账时的累计值，恰好覆盖整段采样间隔。

统计口径：流量 = 相邻两次记账的累计计数器单调差值，仅此一种来源；
瞬时速率 dl_rate/up_rate 只是派生展示量，绝不参与累加。
作为 MoviePilot 插件运行时，前端固定间隔轮询取数，不依赖 SSE 推流；
独立部署时的内存裁剪、SSRF 校验与可观测性指标一并精简。
"""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import constants, db, log, rollup
from .clients import make_client

MAX_ONE_TICK = 1 << 40  # 单周期 1 TiB 视为异常跳变，丢弃并重建基线


def _increment(total, previous):
    """只用累计计数器差值。任何拿不到可信差值的情况都记 0，绝不估算。

    返回 (增量, 事件标记)：
      ok      正常差值
      no_base 首次采集或基线缺失：只建立基线，本轮不计流量
      reset   计数器回退（下载器重启 / 统计清零）：以新值重建基线，本轮不计流量
      spike   异常跳变：丢弃，本轮不计流量
      missing 本轮没拿到累计值：沿用旧基线，本轮不计流量
    """
    if total is None:
        return 0, "missing"
    if previous is None:
        return 0, "no_base"
    delta = int(total) - int(previous)
    if delta < 0:
        return 0, "reset"
    if delta > MAX_ONE_TICK:
        return 0, "spike"
    return delta, "ok"


class Collector:
    def __init__(self, cfg):
        self.interval = cfg["traffic_interval"]       # 流量统计记账间隔（配置页「采样间隔」，默认 1 分钟）
        # 实时速率 / 在线状态的刷新节奏：固定 5 秒，不来自配置页、不外显设置
        self.rate_interval = float(cfg.get("rate_interval") or constants.RATE_POLL_INTERVAL)
        self.timeout = cfg["request_timeout"]
        self.retention = cfg["sample_retention_days"]
        self._clients = {}                            # id -> (sig, client)
        self._client_lock = threading.Lock()
        self.stop_event = threading.Event()
        self._wake = threading.Event()
        self.thread = threading.Thread(target=self._loop,
                                       name="collector", daemon=True)
        self.last_tick = 0
        self.ticks = 0                                # 实时刷新轮次（每 5 秒）
        self.traffic_ticks = 0                        # 流量记账轮次（每采样间隔）
        self.last_error = None
        self.fail_counts = {}
        self.total_failures = 0
        self._last_rollup = 0.0
        self._last_traffic_ts = 0.0                   # 上次流量记账时间
        self.started_at = time.time()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self._wake.set()
        self.thread.join(timeout=self.timeout + 2)

    def set_traffic_interval(self, seconds):
        """「设置」里改「采样间隔」（流量统计记账间隔）：运行时立即生效，无需重启。
        实时速率节奏固定 5 秒，不受此值影响。"""
        try:
            self.interval = max(5.0, float(seconds))
        except (TypeError, ValueError):
            pass
        self._wake.set()

    # 兼容旧调用名
    def set_interval(self, seconds):
        self.set_traffic_interval(seconds)

    def _loop(self):
        last_cleanup = 0
        while not self.stop_event.is_set():
            t0 = time.time()
            try:
                self.tick()
                self.last_tick = time.time()
                self.ticks += 1
                self.last_error = None
            except Exception as exc:  # 保证采集线程永不因单轮异常退出
                self.last_error = str(exc)
                traceback.print_exc()
            now = time.time()
            # 每小时跑一次自动 rollup（traffic_samples -> 1m / hourly -> 1d）
            if now - self._last_rollup > 3600:
                try:
                    rollup.run_once(now)
                    db.invalidate_bounds()
                except Exception:
                    traceback.print_exc()
                self._last_rollup = now
            if now - last_cleanup > 3600:
                try:
                    db.cleanup_samples(self.retention)
                except Exception:
                    traceback.print_exc()
                last_cleanup = now
            # 心跳按实时速率节奏（固定 5 秒）：下载器卡片的瞬时速率 / 在线状态
            # 每 5 秒刷新一次；流量记账点由 tick() 按采样间隔自行判定。
            self._wake.wait(max(0.01, self.rate_interval - (time.time() - t0)))
            self._wake.clear()

    def tick(self):
        now = time.time()
        # 是否到达流量统计记账点：首轮立即建基线；此后每隔 self.interval 记一次账。
        # 0.5 秒容差避免 5 秒心跳与整间隔边界微抖动导致漏记一轮。
        do_traffic = (self._last_traffic_ts <= 0
                      or now - self._last_traffic_ts >= self.interval - 0.5)
        for d in db.list_downloaders(enabled_only=True):
            try:
                self.poll(d, do_traffic)
            except Exception as exc:
                # 失败只写内存实时态，不抢 SQLite 写锁
                db.mark_offline(d["id"], str(exc))
                self._note_fail(d["id"], exc)
                traceback.print_exc()
        if do_traffic:
            self._last_traffic_ts = now
            self.traffic_ticks += 1

    def _note_fail(self, did, exc):
        self.fail_counts[did] = self.fail_counts.get(did, 0) + 1
        self.total_failures += 1
        log.warn("collector.poll_failed", downloader_id=did, error=str(exc)[:200])

    def _client_for(self, d):
        """按连接签名复用客户端实例（登录态 / qB rid 缓存）。"""
        sig = (d["type"], d["url"], d["username"], d["password"])
        with self._client_lock:
            cached = self._clients.get(d["id"])
            if cached and cached[0] == sig:
                return cached[1]
            client = make_client(d, self.timeout)
            self._clients[d["id"]] = (sig, client)
            return client

    def poll(self, d, do_traffic=True):
        """一次取数：始终刷新内存实时态；仅记账轮按累计计数器差值记账。"""
        client = self._client_for(d)
        try:
            s = client.fetch()
        except Exception as exc:
            db.mark_offline(d["id"], str(exc))
            self._note_fail(d["id"], exc)
            with self._client_lock:
                self._clients.pop(d["id"], None)
            return

        now = time.time()
        extra = dict(s.get("extra") or {})
        # 实时速率 / 在线状态：每 5 秒刷新，供下载器卡片与详情弹窗展示（纯内存）
        db.update_live(d["id"], status="online", error=None, traffic_error=None,
                       last_seen=int(now), dl_rate=s["dl_rate"],
                       up_rate=s["up_rate"], extra=extra)

        if not do_traffic:
            return

        st = db.get_state(d["id"])
        prev_ts = st["last_ts"] if st else None
        # dt 只用于确定「本次覆盖的时间区间」以便分摊到小时桶，不参与流量计算。
        # prev_ts 是上次记账时间，跨多个 5 秒实时轮次的累计增量一次性记账，不丢流量。
        span_hint = (now - prev_ts) if prev_ts else float(self.interval)
        span_hint = max(1.0, min(span_hint, 3600.0))
        start_ts = prev_ts if prev_ts else now - span_hint

        dl_inc, ev_dl = _increment(s.get("dl_total"), st["last_dl_total"] if st else None)
        up_inc, ev_up = _increment(s.get("up_total"), st["last_up_total"] if st else None)
        s = dict(s)
        s["extra"] = dict(s.get("extra") or {})
        s["extra"]["counter_event"] = ev_dl if ev_dl != "ok" else ev_up
        db.record_traffic_sample(d["id"], now, start_ts, s, dl_inc, up_inc)

    def test(self, payload, allow_private=None):
        """用临时客户端抓一次，不写库。"""
        d = {
            "type": "tr" if str(payload.get("type", "qb")).lower() in ("tr", "transmission") else "qb",
            "url": str(payload.get("url", "")).rstrip("/"),
            "username": str(payload.get("username", "")),
            "password": str(payload.get("password", "")),
        }
        s = make_client(d, self.timeout).fetch()
        return {
            "ok": True,
            "dl_rate": s["dl_rate"],
            "up_rate": s["up_rate"],
            "dl_total": s.get("dl_total"),
            "up_total": s.get("up_total"),
            "extra": s.get("extra", {}),
        }

    def detail(self, d):
        """详情弹窗：复用采集客户端（登录态 / session id）按需抓一次详情。"""
        return self._client_for(d).detail()

    def detail_many(self, downloaders):
        """汇总详情：并发抓多台详情，单台失败只标记该台，不影响其他台。"""
        def one(d):
            try:
                return (d, self._client_for(d).detail(), None)
            except Exception as exc:
                return (d, None, str(exc))
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(downloaders)))) as pool:
            return list(pool.map(one, downloaders))

    def invalidate(self, did):
        with self._client_lock:
            self._clients.pop(did, None)
        self.fail_counts.pop(did, None)

    def metrics(self):
        return {
            "started_at": self.started_at,
            "uptime_seconds": max(0.0, time.time() - self.started_at),
            "ticks": self.ticks,
            "traffic_ticks": self.traffic_ticks,
            "last_tick": self.last_tick,
            "last_error": self.last_error,
            "interval": self.interval,
            "rate_interval": self.rate_interval,
            "total_failures": self.total_failures,
            "failures": dict(self.fail_counts),
        }
