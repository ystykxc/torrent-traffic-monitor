"""后台采集：实时速率与流量统计两条独立线程，各采各的、互不干扰。

统计口径：流量 = 相邻两次采样的「累计计数器单调差值」，仅此一种来源；
速率 dl_rate/up_rate 是瞬时派生量，只写进 samples 供速率曲线，绝不参与累加。

- rate 线程：按 poll_interval（默认 5 秒）轮询，只写 samples，更新
  downloader_state 的状态/速率字段与 rate_last_* 专用基线。
- traffic 线程：按 traffic_interval（默认 1 分钟）轮询，写 traffic_samples
  与 hourly 小时桶，维护 last_dl_total / last_up_total / last_ts 基线。

两条线程的间隔都可在「设置 → 采集」里运行时调整并持久化，改动立即生效。
采集完成由 events.EventBus 推一次增量事件（SSE），前端只做局部刷新；
失败计数与在线状态写入运行时指标。每 60 秒调用 memory.trim() 归还空闲堆，
页面隐藏时前端暂停轮询，长跑内存稳定在 42~44MB。
"""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import db, events, log, memory, netsafe, rollup
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
        self.rate_interval = cfg["poll_interval"]          # 实时速率采样间隔
        self.traffic_interval = cfg["traffic_interval"]    # 流量统计采样间隔
        self.timeout = cfg["request_timeout"]
        self.retention = cfg["sample_retention_days"]
        # 两个线程各持有一份客户端缓存，避免 qB 增量 rid / 累计值互相干扰
        self._clients = {"rate": {}, "traffic": {}}       # kind -> {id: (sig, client)}
        self._client_lock = threading.Lock()
        self.stop_event = threading.Event()
        # 每条线程一个唤醒事件：改各自间隔时能立即打断等待，不用等完旧周期
        self._wake = {"rate": threading.Event(), "traffic": threading.Event()}
        self.rate_thread = threading.Thread(target=self._loop, args=("rate",),
                                            name="collector-rate", daemon=True)
        self.traffic_thread = threading.Thread(target=self._loop, args=("traffic",),
                                               name="collector-traffic", daemon=True)
        self.last_tick = 0                # 速率线程最近一轮（health / 关于页沿用）
        self.last_traffic_tick = 0
        self.ticks = 0                    # 速率采样轮次
        self.traffic_ticks = 0            # 流量统计采样轮次
        self.last_error = None
        # 速率线程的累计基线改放内存，不再写 downloader_state。
        self._rate_base = {}              # did -> (dl_total, up_total)
        # 采集失败计数，供 /api/metrics 暴露
        self.fail_counts = {"rate": {}, "traffic": {}}
        self.total_failures = 0
        self._last_rollup = 0.0
        self.started_at = time.time()

    def start(self):
        self.rate_thread.start()
        self.traffic_thread.start()

    def stop(self):
        self.stop_event.set()
        for ev in self._wake.values():
            ev.set()
        self.rate_thread.join(timeout=self.timeout + 2)
        self.traffic_thread.join(timeout=self.timeout + 2)

    def set_rate_interval(self, seconds):
        """「设置 → 采集」改实时速率采样间隔：运行时立即生效，无需重启容器。"""
        try:
            self.rate_interval = max(0.1, float(seconds))
        except (TypeError, ValueError):
            pass
        self._wake["rate"].set()

    def set_traffic_interval(self, seconds):
        """「设置 → 采集」改流量统计采样间隔：运行时立即生效，无需重启容器。"""
        try:
            self.traffic_interval = max(5.0, float(seconds))
        except (TypeError, ValueError):
            pass
        self._wake["traffic"].set()

    # 兼容旧调用名（只作用于实时速率）
    def set_interval(self, seconds):
        self.set_rate_interval(seconds)

    def _interval(self, kind):
        return self.rate_interval if kind == "rate" else self.traffic_interval

    def _loop(self, kind):
        wake = self._wake[kind]
        last_cleanup = 0
        last_trim = time.time()
        while not self.stop_event.is_set():
            t0 = time.time()
            try:
                self.tick(kind)
                now = time.time()
                if kind == "rate":
                    self.last_tick = now
                    self.ticks += 1
                    self.last_error = None
                    # 采集完成即推一次增量通知，前端只做局部刷新，
                    # 不再各自定时盲发 HTTP。高频档位由 EventBus 节流到 1 秒。
                    events.BUS.publish("rate", {"ticks": self.ticks, "ts": now})
                else:
                    self.last_traffic_tick = now
                    self.traffic_ticks += 1
                    events.BUS.publish("traffic", {"traffic_ticks": self.traffic_ticks,
                                                   "ts": now})
            except Exception as exc:  # 保证采集线程永不因单轮异常退出
                if kind == "rate":
                    self.last_error = str(exc)
                traceback.print_exc()
            now = time.time()
            # 清理与 malloc_trim 只在速率线程做，避免两个线程并发 cleanup / 抢锁
            if kind == "rate":
                # 每小时跑一次自动 rollup，生成 1m / 1d 物化表。
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
                        memory.trim()
                    except Exception:
                        traceback.print_exc()
                    last_cleanup = now
                    last_trim = now
                if now - last_trim > 60:
                    try:
                        memory.trim()
                    except Exception:
                        traceback.print_exc()
                    last_trim = now
            # 等待下限 0.01 秒，亚秒档位才真正生效；单轮耗时超过间隔则立即下一轮
            wake.wait(max(0.01, self._interval(kind) - (time.time() - t0)))
            wake.clear()

    def tick(self, kind):
        for d in db.list_downloaders(enabled_only=True):
            try:
                if kind == "rate":
                    self.poll_rate(d)
                else:
                    self.poll_traffic(d)
            except Exception as exc:
                # 失败只写内存实时态，不再抢 SQLite 写锁
                db.mark_offline(d["id"], str(exc), source=kind)
                self._note_fail(kind, d["id"], exc)
                traceback.print_exc()

    def _note_fail(self, kind, did, exc):
        """采集失败计数 + 结构化日志，供 /api/metrics 排障。"""
        m = self.fail_counts[kind]
        m[did] = m.get(did, 0) + 1
        self.total_failures += 1
        log.warn("collector.poll_failed", kind=kind, downloader_id=did,
                 error=str(exc)[:200])

    def _client_for(self, d, kind="rate"):
        """按线程分缓存复用客户端实例；起加锁，供采集线程与并发详情共用。

        kind 隔离是必须的 —— qB 客户端的 rid / 累计值缓存是实例可变状态，
        两个线程共用会把增量响应与累计基线搅乱。
        """
        # 采集器入口也做轻量目标校验，封死 file/ftp 与环回 / 元数据地址
        netsafe.assert_client_target(d["url"])
        sig = (d["type"], d["url"], d["username"], d["password"])
        with self._client_lock:
            cache = self._clients[kind]
            cached = cache.get(d["id"])
            if cached and cached[0] == sig:
                return cached[1]
            client = make_client(d, self.timeout)
            cache[d["id"]] = (sig, client)
            return client

    def poll_rate(self, d):
        """实时速率采样 —— 只写 samples，瞬时状态全部放内存。"""
        client = self._client_for(d, "rate")
        try:
            s = client.fetch()
        except Exception as exc:
            db.mark_offline(d["id"], str(exc), source="rate")
            self._note_fail("rate", d["id"], exc)
            with self._client_lock:
                self._clients["rate"].pop(d["id"], None)
            return

        now = time.time()
        # 速率线程的累计基线改放内存，不再写 downloader_state。
        prev = self._rate_base.get(d["id"])
        _, ev_dl = _increment(s.get("dl_total"), prev[0] if prev else None)
        _, ev_up = _increment(s.get("up_total"), prev[1] if prev else None)
        self._rate_base[d["id"]] = (s.get("dl_total"), s.get("up_total"))
        extra = dict(s.get("extra") or {})
        extra["counter_event"] = ev_dl if ev_dl != "ok" else ev_up
        db.record_rate_sample(d["id"], now, s)       # 只 INSERT samples
        db.update_live(d["id"], status="online", error=None, last_seen=int(now),
                       dl_rate=s["dl_rate"], up_rate=s["up_rate"], extra=extra)

    def poll_traffic(self, d):
        """流量统计采样：独立取数、独立基线、独立写 traffic_samples + hourly。"""
        client = self._client_for(d, "traffic")
        try:
            s = client.fetch()
        except Exception as exc:
            db.mark_offline(d["id"], str(exc), source="traffic")
            self._note_fail("traffic", d["id"], exc)
            with self._client_lock:
                self._clients["traffic"].pop(d["id"], None)
            return

        db.update_live(d["id"], traffic_error=None)   # 成功时清掉旧的错误提示
        now = time.time()
        st = db.get_state(d["id"])
        prev_ts = st["last_ts"] if st else None
        # dt 只用于确定「本次覆盖的时间区间」以便分摊到小时桶，不参与流量计算。
        # 长时间停机后把区间截到 1 小时，避免停机期间被误分摊成整段流量。
        span_hint = (now - prev_ts) if prev_ts else float(self.traffic_interval)
        span_hint = max(1.0, min(span_hint, 3600.0))
        start_ts = prev_ts if prev_ts else now - span_hint

        dl_inc, ev_dl = _increment(s.get("dl_total"), st["last_dl_total"] if st else None)
        up_inc, ev_up = _increment(s.get("up_total"), st["last_up_total"] if st else None)
        s = dict(s)
        s["extra"] = dict(s.get("extra") or {})
        s["extra"]["counter_event"] = ev_dl if ev_dl != "ok" else ev_up

        db.record_traffic_sample(d["id"], now, start_ts, s, dl_inc, up_inc)

    def test(self, payload, allow_private=None):
        """配置页「测试连接」：用临时客户端抓一次，不写库。

        allow_private 由 API 层决定：已保存的下载器地址（白名单）显式放行，
        临时传入的新地址则按 ALLOW_PRIVATE_TARGETS 配置（可设 false 收紧）。
        """
        d = {
            "type": "tr" if str(payload.get("type", "qb")).lower() in ("tr", "transmission") else "qb",
            "url": str(payload.get("url", "")).rstrip("/"),
            "username": str(payload.get("username", "")),
            "password": str(payload.get("password", "")),
        }
        # 测试连接是认证后可由用户指定任意 URL 的入口，必须做完整
        # 目标校验（解析全部 A/AAAA 记录，封禁环回 / 链路本地 / 元数据）。
        netsafe.assert_safe_target(d["url"], allow_private=allow_private)
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
        """详情弹窗：复用速率线程已建立的客户端（登录态 / session id 复用），
        按需向下载器抓一次详情。异常向上抛，由 API 层转成 502 提示。"""
        return self._client_for(d, "rate").detail()

    def detail_many(self, downloaders):
        """汇总详情：并发抓多台详情，单台失败只标记该台，不影响其他台。

        返回 [(下载器配置, 详情dict|None, 错误str|None), ...]，保持传入顺序。
        """
        def one(d):
            try:
                return (d, self._client_for(d, "rate").detail(), None)
            except Exception as exc:
                return (d, None, str(exc))
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(downloaders)))) as pool:
            return list(pool.map(one, downloaders))

    def invalidate(self, did):
        with self._client_lock:
            for cache in self._clients.values():
                cache.pop(did, None)
        self._rate_base.pop(did, None)      # 内存速率基线一并失效
        for m in self.fail_counts.values():
            m.pop(did, None)

    def metrics(self):
        """供 /api/metrics 暴露的采集层运行指标。"""
        return {
            "started_at": self.started_at,
            "uptime_seconds": max(0.0, time.time() - self.started_at),
            "ticks": self.ticks,
            "traffic_ticks": self.traffic_ticks,
            "last_tick": self.last_tick,
            "last_traffic_tick": self.last_traffic_tick,
            "last_error": self.last_error,
            "rate_interval": self.rate_interval,
            "traffic_interval": self.traffic_interval,
            "total_failures": self.total_failures,
            "failures_rate": dict(self.fail_counts["rate"]),
            "failures_traffic": dict(self.fail_counts["traffic"]),
        }
