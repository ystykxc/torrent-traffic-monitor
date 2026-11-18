"""Flask 应用入口：路由、鉴权守卫、全局限流、SSE 推流与运行时指标。

除 /api/health、/api/auth/status、/api/auth/login 外，所有 /api/* 都需要
Authorization: Bearer <token>。未登录返回 401 auth_required，首次未改密
返回 403 setup_required。健康检查只返回 {"ok":true}，内部指标移到
需鉴权的 /api/overview 与 /api/metrics。

生产由 waitress 以单进程多线程启动（见 Dockerfile）；直接运行本模块时用
Flask 开发服务器，仅供本地自测。
"""
import gc
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, g, jsonify, request, send_from_directory

from . import auth, chart, config, db, events, limiter, log, netsafe, rollup, stats, timeutil
from .clients import IO_BAD, IO_WARN, TORRENT_KEYS
from .collector import Collector

cfg = config.load()
timeutil.configure(cfg["tz_offset"])
db.configure(cfg["data_dir"])
db.init_db()
auth.bootstrap()
db.import_initial(cfg["downloaders"])

# 「设置 → 采集」改过的参数持久化在库里，优先级高于环境变量 / config.json
# 实时速率与流量统计两套采样间隔分别读取、分别校验。
try:
    saved = db.get_setting("poll_interval")
    if saved is not None and config.in_choices(saved, config.RATE_POLL_CHOICES):
        cfg["poll_interval"] = float(saved)   # 支持 0.1 / 0.2 / 0.5 秒亚秒档位
    saved = db.get_setting("traffic_interval")
    if saved is not None and config.in_choices(saved, config.TRAFFIC_POLL_CHOICES):
        cfg["traffic_interval"] = int(float(saved))
    saved = db.get_setting("live_span")
    if saved is not None and int(saved) in config.LIVE_SPAN_CHOICES:
        cfg["live_span"] = int(saved)
except (ValueError, TypeError):
    pass

collector = Collector(cfg)
collector.start()
# 内存优化：把启动期已创建的常驻对象冻结到 GC 永久代，
# 运行期每轮 GC 不再反复扫描这些对象，减少长跑的 CPU 抖动与堆扩张。
gc.freeze()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
PWA_DIR = os.path.join(APP_DIR, "pwa")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.json.ensure_ascii = False
# 请求体上限 256 KB，超大 body 直接拒绝，避免耗尽 waitress 线程。
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

# 健康检查与登录/状态查询不需要 token；其余 /api/* 一律鉴权
# （/api/stream、/api/metrics、/api/audit 均需鉴权）。
AUTH_FREE = {"/api/health", "/api/auth/status", "/api/auth/login"}

# 需要更严格限流的接口：图表全窗口聚合、连接测试会外连下载器。
STRICT_PATHS = ("/api/chart", "/api/downloaders/test")
STRICT_SUFFIX = "/test"


def _err(exc, code=400):
    return jsonify({"ok": False, "error": str(exc)}), code


def _limit_key():
    """登录后按 token 计、未登录按真实客户端 IP 计。"""
    t = auth.token_from_request()
    return ("tok:" + t[:24]) if t else ("ip:" + auth.client_ip())


@app.before_request
def guard():
    if not request.path.startswith("/api/"):
        return None
    # 全局限流对所有 /api/* 生效（含登录 / 健康检查），按 key 计。
    # 长连接 SSE 只在建立时计一次，不按帧计数。
    strict = request.path in STRICT_PATHS or request.path.endswith(STRICT_SUFFIX)
    limit = max(20, config.SECURITY["rate_limit"] // 2) if strict else config.SECURITY["rate_limit"]
    # 严格路径用独立 key 计数，避免普通请求把 /api/chart 的配额消耗掉
    lkey = _limit_key() + (":strict" if strict else "")
    ok, used, retry = limiter.allow(lkey, limit,
                                    config.SECURITY["rate_limit_window"])
    if not ok:
        log.warn("http.rate_limited", path=request.path, used=used)
        return jsonify({"ok": False, "error": "请求过于频繁，请稍后再试",
                        "code": "rate_limited"}), 429
    if request.path in AUTH_FREE:
        return None
    s = auth.current_session()
    if not s:
        return jsonify({"ok": False, "error": "请先登录", "code": "auth_required"}), 401
    # 首次登录未改默认账号密码前，不允许读取任何监控数据
    if s["must_change"] and not request.path.startswith("/api/auth/"):
        return jsonify({"ok": False, "error": "请先修改默认账号与密码", "code": "setup_required"}), 403
    g.session = s
    return None


@app.after_request
def _secure_headers(resp):
    # 浏览器侧安全响应头。原本全站只有 Cache-Control，一旦出现任何
    # XSS，localStorage 里的会话 token 会直接被盗，且可被 iframe 嵌套做点击劫持。
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy",
                            "geolocation=(), microphone=(), camera=()")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; manifest-src 'self'; "
        "worker-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'",
    )
    return resp


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(PWA_DIR, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(PWA_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ---------------- 账户 ----------------

@app.route("/api/auth/status")
def auth_status():
    # 不再回显登录用户名（未鉴权接口），省去攻击者猜用户名这一步。
    # 前端把用户名记在 localStorage，登录 / 改密响应里本来就有。
    s = auth.current_session()
    return jsonify({
        "ok": True,
        "authenticated": bool(s),
        "must_change": bool(s["must_change"]) if s else False,
    })


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    body = request.get_json(silent=True) or {}
    res, err = auth.login(body.get("username"), body.get("password"))
    if err:
        return _err(err, 401)
    return jsonify({"ok": True, **res})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    auth.logout()
    return jsonify({"ok": True})


@app.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    """首次登录强制修改账号与密码。"""
    body = request.get_json(silent=True) or {}
    err = auth.setup(body.get("username"), body.get("password"))
    if err:
        return _err(err)
    return jsonify({"ok": True, "username": str(body.get("username")).strip()})


@app.route("/api/auth/change", methods=["POST"])
def auth_change():
    """后续修改账号/密码：保留当前会话，其他设备需要重新登录。"""
    if g.session["must_change"]:
        return _err("请先完成首次设置", 403)
    body = request.get_json(silent=True) or {}
    err = auth.change(body.get("old_password"), body.get("username"), body.get("password"))
    if err:
        return _err(err)
    db.delete_other_sessions(auth.token_from_request())
    return jsonify({"ok": True, "username": str(body.get("username")).strip() or g.session["username"]})


# ---------------- 监控数据 ----------------

@app.route("/api/health")
def health():
    # 未鉴权的健康检查不再暴露采样间隔 / 时区 / 服务器时间 / 采集轮次 /
    # 错误等内部配置（应用指纹 + 爆破辅助信息）。这些指标移到需鉴权的
    # /api/overview 与 /api/metrics。容器 HEALTHCHECK 只需 HTTP 200。
    return jsonify({"ok": True})


@app.route("/api/stream")
def api_stream():
    """SSE 推流。采集完成由 EventBus 推一次增量通知，前端只做
    局部刷新，替代固定间隔盲轮询；低频档位实时性更好，高频档位由服务端
    节流到 1 秒，避免 0.1 秒采样把前端压垮。

    用 fetch() + ReadableStream 读取（可带 Authorization 头），而不是
    EventSource —— 后者不能自定义请求头，只能把 token 塞进 URL，反而是泄露面。
    订阅数有上限，满了返回 503，前端自动降级回轮询。
    """
    if not config.SECURITY["sse_enabled"]:
        return jsonify({"ok": False, "error": "SSE 未启用", "code": "sse_disabled"}), 503
    # 只做容量预检，**不在这里 subscribe**：订阅必须放到生成器内部。
    # 否则一旦 WSGI 层在迭代生成器之前抛异常（例如响应头不合规被 waitress
    # 拒绝），finally 里的 unsubscribe 永远不会执行，订阅名额会永久泄漏，
    # 累计几次之后所有 SSE 连接都会返回 503，只能重启进程恢复。
    if not events.BUS.can_subscribe():
        return jsonify({"ok": False, "error": "推流连接数已满，请降级轮询",
                        "code": "sse_full"}), 503

    def gen():
        q = events.BUS.subscribe()
        if q is None:                       # 预检与实际订阅之间的竞态兜底
            yield events.BUS.sse({"kind": "error", "seq": 0, "ts": time.time(),
                                 "data": {"code": "sse_full"}})
            return
        try:
            yield "retry: 3000\n\n"
            yield events.BUS.sse({"kind": "hello", "seq": 0,
                                 "ts": time.time(), "data": {}})
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield events.BUS.sse(msg)
                except queue.Empty:
                    yield ": keep-alive\n\n"     # 反代空闲超时保活
        finally:
            events.BUS.unsubscribe(q)

    # 注意：不能设置 "Connection" —— 它是 hop-by-hop 头，waitress 会按
    # PEP 3333 直接抛 AssertionError 让整个 SSE 请求 500。长连接保活由
    # 生成器里的 ": keep-alive" 注释帧 + 反代 X-Accel-Buffering 保证。
    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/metrics")
def api_metrics():
    """Prometheus 文本格式的最小指标端点（需鉴权），便于接 Grafana。
    同时提供 ?format=json 供前端 / 排障直接读。"""
    if not config.SECURITY["metrics_enabled"]:
        return jsonify({"ok": False, "error": "指标端点未启用"}), 404
    m = collector.metrics()
    try:
        states = db.get_states()
        online = sum(1 for v in states.values() if v.get("status") == "online")
        dls = len(states)
    except Exception:
        online = dls = 0
    rs = rollup.status()
    es = events.BUS.stats()
    payload = {
        "collector": m,
        "downloaders": {"online": online, "total": dls},
        "sessions": db.count_sessions(),
        "rollup": rs,
        "events": es,
        "audit_enabled": config.SECURITY["audit_enabled"],
    }
    if request.args.get("format") == "json":
        return jsonify({"ok": True, **payload})

    def md(name, value, help_text=""):
        return ("# HELP %s %s\n# TYPE %s gauge\n%s %s\n" %
                (name, help_text or name, name, name, value))
    lines = [
        md("ttm_uptime_seconds", round(m["uptime_seconds"], 1), "进程运行秒数"),
        md("ttm_collector_ticks_total", m["ticks"], "实时速率采样轮次"),
        md("ttm_collector_traffic_ticks_total", m["traffic_ticks"], "流量统计采样轮次"),
        md("ttm_collector_failures_total", m["total_failures"], "采集失败累计次数"),
        md("ttm_downloaders_online", online, "在线下载器数"),
        md("ttm_downloaders_total", dls, "下载器总数"),
        md("ttm_sessions_active", payload["sessions"], "有效会话数"),
        md("ttm_rollup_rows_1m", rs.get("rows_1m", 0), "1 分钟物化层行数"),
        md("ttm_rollup_rows_1d", rs.get("rows_1d", 0), "1 天物化层行数"),
        md("ttm_stream_subscribers", es.get("subscribers", 0), "SSE 订阅数"),
        md("ttm_stream_events_published", es.get("published", 0), "SSE 已推事件数"),
        md("ttm_stream_events_throttled", es.get("throttled", 0), "SSE 被节流事件数"),
    ]
    for kind in ("rate", "traffic"):
        for did, n in m["failures_" + kind].items():
            lines.append('ttm_collector_failures{kind="%s",downloader_id="%s"} %s\n'
                         % (kind, did, n))
    return Response("".join(lines), mimetype="text/plain; version=0.0.4; charset=utf-8")


@app.route("/api/audit")
def api_audit():
    """最近审计事件（需鉴权），便于回溯配置变更与登录行为。"""
    if not config.SECURITY["audit_enabled"]:
        return jsonify({"ok": True, "items": []})
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    return jsonify({"ok": True, "items": db.list_audit(limit)})


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        try:
            # 两套间隔分开存。缺省字段沿用当前值，兼容旧版前端的 POST。
            pi = float(body.get("poll_interval", cfg["poll_interval"]))
            ti = int(float(body.get("traffic_interval", cfg["traffic_interval"])))
            ls = int(body.get("live_span", cfg["live_span"]))
        except (TypeError, ValueError):
            return _err("参数格式不正确")
        if not config.in_choices(pi, config.RATE_POLL_CHOICES):
            return _err("实时速率采样间隔只能是 0.1 / 0.2 / 0.5 / 1 / 3 / 5 / 10 秒")
        if not config.in_choices(ti, config.TRAFFIC_POLL_CHOICES):
            return _err("流量统计采样间隔只能是 5 秒 / 10 秒 / 30 秒 / 1 / 5 / 10 / 30 分钟")
        if ls not in config.LIVE_SPAN_CHOICES:
            return _err("实时窗口只能是 30 秒 / 1 / 3 / 5 / 10 / 30 分钟")
        pi = next(v for v in config.RATE_POLL_CHOICES if abs(pi - v) < 1e-9)
        ti = next(v for v in config.TRAFFIC_POLL_CHOICES if abs(ti - v) < 1e-9)
        db.set_setting("poll_interval", pi)
        db.set_setting("traffic_interval", ti)
        db.set_setting("live_span", ls)
        cfg["poll_interval"], cfg["traffic_interval"], cfg["live_span"] = pi, ti, ls
        collector.set_rate_interval(pi)        # 各自打断等待，下一轮按新间隔
        collector.set_traffic_interval(ti)
        db.audit("settings.change", actor=g.session.get("username", ""),
                 ip=auth.client_ip(),
                 detail="rate=%s traffic=%s live_span=%s" % (pi, ti, ls))
        return jsonify({"ok": True, "poll_interval": pi,
                        "traffic_interval": ti, "live_span": ls})
    return jsonify({
        "poll_interval": cfg["poll_interval"],
        "traffic_interval": cfg["traffic_interval"],
        "poll_interval_options": [{"value": v, "label": config.RATE_POLL_LABELS[v]}
                                  for v in config.RATE_POLL_CHOICES],
        "traffic_interval_options": [{"value": v, "label": config.TRAFFIC_POLL_LABELS[v]}
                                     for v in config.TRAFFIC_POLL_CHOICES],
        "live_span_options": [{"value": v, "label": config.LIVE_SPAN_LABELS[v]}
                              for v in config.LIVE_SPAN_CHOICES],
        "sample_retention_days": cfg["sample_retention_days"],
        "tz_offset": timeutil.TZ_OFFSET,
        "request_timeout": cfg["request_timeout"],
        "granularities": list(timeutil.GRANULARITIES),
        "ranges": list(chart.ALL_RANGES),
        "palette": [list(p) for p in db.PALETTE],
        "summary_colors": {"up": db.SUMMARY_UP, "down": db.SUMMARY_DOWN},
    })


@app.route("/api/overview")
def overview():
    states = db.get_states()
    totals = stats.period_totals()
    items = []
    # 停用的下载器在主界面「所有展示内容」全部取消，不只是停止采集。
    # 配置表走 /api/downloaders（不带 enabled_only），仍能看到并重新启用。
    for d in db.list_downloaders(public=True, enabled_only=True):
        st = states.get(d["id"], {})
        t = totals.get(d["id"], {})
        extra = {}
        if st.get("extra"):
            try:
                import json
                extra = json.loads(st["extra"])
            except (ValueError, TypeError):
                pass
        items.append({
            **d,
            "status": st.get("status", "unknown"),
            "error": st.get("error"),
            "last_seen": st.get("last_seen"),
            "dl_rate": st.get("dl_rate", 0),
            "up_rate": st.get("up_rate", 0),
            "extra": extra,
            "today": {"dl": t.get("day_dl") or 0, "up": t.get("day_up") or 0},
            "week": {"dl": t.get("week_dl") or 0, "up": t.get("week_up") or 0},
            "month": {"dl": t.get("month_dl") or 0, "up": t.get("month_up") or 0},
            "year": {"dl": t.get("year_dl") or 0, "up": t.get("year_up") or 0},
            "all": {"dl": t.get("all_dl") or 0, "up": t.get("all_up") or 0},
        })

    def s(key, sub):
        return sum(i[key][sub] for i in items)

    return jsonify({
        "server_time": time.time(),
        "tz_offset": timeutil.TZ_OFFSET,
        "collector": {
            "interval": cfg["poll_interval"],
            "traffic_interval": cfg["traffic_interval"],
            "traffic_ticks": collector.traffic_ticks,
            "ticks": collector.ticks,
            "last_tick": collector.last_tick,
            "last_error": collector.last_error,
        },
        "total": {
            "dl_rate": sum(i["dl_rate"] for i in items),
            "up_rate": sum(i["up_rate"] for i in items),
            "online": sum(1 for i in items if i["status"] == "online"),
            "count": len(items),
            "today": {"dl": s("today", "dl"), "up": s("today", "up")},
            "week": {"dl": s("week", "dl"), "up": s("week", "up")},
            "month": {"dl": s("month", "dl"), "up": s("month", "up")},
            "year": {"dl": s("year", "dl"), "up": s("year", "up")},
            "all": {"dl": s("all", "dl"), "up": s("all", "up")},
        },
        "downloaders": items,
    })


@app.route("/api/stats")
def api_stats():
    try:
        gran = request.args.get("granularity", "day")
        now = time.time()
        default_start, default_end = timeutil.range_for(gran, now)
        start = float(request.args.get("start", default_start))
        end = float(request.args.get("end", default_end))
        did = request.args.get("downloader_id", "")
        return jsonify({"ok": True, **stats.query_stats(gran, start, end, int(did) if did else None)})
    except (ValueError, TypeError) as exc:
        return _err(exc)


@app.route("/api/realtime")
def api_realtime():
    try:
        minutes = int(request.args.get("minutes", 60))
        did = request.args.get("downloader_id", "")
        return jsonify({"ok": True, **stats.realtime(minutes, int(did) if did else None)})
    except (ValueError, TypeError) as exc:
        return _err(exc)


@app.route("/api/periods")
def api_periods():
    """顶部 4 张汇总卡片的下拉数据：今日往前 30 天 / 本周往前 26 周 /
    本月往前 12 个月 / 本年往前 5 年的上传、下载合计（全部下载器之和）。"""
    return jsonify({"ok": True, "periods": stats.period_series(),
                    "counts": dict(stats.PERIOD_COUNTS), "server_time": time.time()})


@app.route("/api/periods/page")
def api_periods_page():
    # 顶部卡片「历史周期数据」清单的无限下滑分页。start 为历史周期序号
    # （0=当前周期），count 每批条数。更早周期即使没有采集数据也照常返回条目，
    # 因此没有「最早下限」，前端可一直向下加载。
    unit = request.args.get("unit", "")
    try:
        start = max(0, int(request.args.get("start", 0)))
        count = max(1, min(50, int(request.args.get("count", 10))))
    except (TypeError, ValueError):
        return _err("start / count 必须是整数")
    try:
        items = stats.period_page(unit, start, count)
    except ValueError as exc:
        return _err(exc)
    return jsonify({"ok": True, "unit": unit, "start": start, "count": count,
                    "items": items, "server_time": time.time()})


@app.route("/api/chart")
def api_chart():
    """多系列图表数据：range × metric 一次返回汇总与所有下载器。

    offset 为横向拖动往前平移的桶数，上限 30 个当前窗口长度（由 chart.build 校验）。
    """
    try:
        return jsonify({"ok": True, **chart.build(
            request.args.get("range", "live"), request.args.get("metric", "rate"),
            live_span=cfg["live_span"], poll_interval=cfg["poll_interval"],
            traffic_interval=cfg["traffic_interval"],
            offset=request.args.get("offset", 0))})
    except ValueError as exc:
        return _err(exc)


# ---------------- 下载器配置 ----------------

@app.route("/api/downloaders", methods=["GET", "POST"])
def api_downloaders():
    if request.method == "GET":
        return jsonify({"ok": True, "items": db.list_downloaders(public=True)})
    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    if not url:
        return _err("URL 不能为空")
    try:
        # 新增下载器也先做轻量目标校验，杜绝把 file:// / 环回 /
        # 元数据地址写进库（采集器虽会再校验一次，提前拒绝更明确）。
        netsafe.assert_client_target(url)
    except ValueError as exc:
        return _err(exc)
    did = db.save_downloader(body)
    collector.invalidate(did)
    db.audit("downloaders.create", actor=g.session.get("username", ""),
             ip=auth.client_ip(), detail="id=%s url=%s" % (did, url))
    return jsonify({"ok": True, "id": did})


@app.route("/api/downloaders/reorder", methods=["POST"])
def api_reorder():
    """配置页上移/下移按钮：一次性提交新的下载器 id 顺序。"""
    body = request.get_json(silent=True) or {}
    ids = body.get("ids", [])
    if not isinstance(ids, list):
        return _err("ids 必须是数组")
    return jsonify({"ok": True, "ids": db.reorder_downloaders(ids)})


@app.route("/api/downloaders/recolor", methods=["POST"])
def api_recolor():
    """一键重新分配所有下载器的上传 / 下载颜色（只改颜色，不动流量数据）。"""
    body = request.get_json(silent=True) or {}
    shift = body.get("shift")
    if shift is not None:
        try:
            shift = int(shift)
        except (TypeError, ValueError):
            return _err("shift 必须是整数")
    return jsonify({"ok": True, **db.recolor_all(shift)})


@app.route("/api/downloaders/<int:did>", methods=["PUT", "DELETE"])
def api_downloader(did):
    if not db.get_downloader(did):
        return _err("下载器不存在", 404)
    if request.method == "DELETE":
        db.delete_downloader(did)
        collector.invalidate(did)
        clear_detail_cache(did)
        db.audit("downloaders.delete", actor=g.session.get("username", ""),
                 ip=auth.client_ip(), detail="id=%s" % did)
        return jsonify({"ok": True})
    body = request.get_json(silent=True) or {}
    if "url" in body:
        try:
            netsafe.assert_client_target(str(body.get("url", "")))
        except ValueError as exc:
            return _err(exc)
    db.save_downloader(body, did)
    collector.invalidate(did)
    clear_detail_cache(did)
    db.audit("downloaders.update", actor=g.session.get("username", ""),
             ip=auth.client_ip(), detail="id=%s" % did)
    return jsonify({"ok": True, "id": did})


def _saved_urls():
    """已保存下载器地址白名单 —— 这些内网地址属于管理员显式授权，
    即使开启了严格模式（ALLOW_PRIVATE_TARGETS=false）也允许测试。"""
    try:
        return {str(d["url"]).rstrip("/") for d in db.list_downloaders()}
    except Exception:
        return set()


def _test_allow_private(target):
    """新地址按配置；已授权地址显式放行（报告 7.3 的白名单思路）。"""
    return True if target in _saved_urls() else None


def _test_failed(exc, target, did=None):
    """原始异常只写服务端结构化日志，对外统一文案，

    杜绝用错误回显当内网端口 / HTTP 状态码探测器。"""
    log.warn("downloaders.test_failed", downloader_id=did, url=target,
             error=str(exc)[:200])
    db.audit("downloaders.test", actor=g.session.get("username", ""),
             ip=auth.client_ip(), detail="failed url=%s" % target)
    return _err("连接测试失败（详细原因已写入服务端日志）", 400)


@app.route("/api/downloaders/<int:did>/test", methods=["POST"])
def api_test(did):
    current = db.get_downloader(did)
    if not current:
        return _err("下载器不存在", 404)
    payload = dict(current)
    body = request.get_json(silent=True) or {}
    for k in ("name", "type", "url", "username", "password", "enabled", "sort_order",
              "color_up", "color_down"):
        if k in body:
            payload[k] = body[k]
    target = str(payload.get("url", "")).rstrip("/")
    # URL 被改成与库中保存的不一致时，禁止沿用已存密码。
    # 这正是「把 qB/Transmission 凭据 POST 到攻击者服务器」的入口。
    if not netsafe.same_target(target, current["url"]):
        if not str(body.get("password", "")):
            return _err("地址已变更，测试新地址必须重新填写密码"
                        "（禁止把已保存的凭据发往新地址）", 400)
    if not payload.get("password"):
        payload["password"] = current["password"]
    try:
        result = collector.test(payload, allow_private=_test_allow_private(target))
    except Exception as exc:
        return _test_failed(exc, target, did)
    db.audit("downloaders.test", actor=g.session.get("username", ""),
             ip=auth.client_ip(), detail="ok url=%s" % target)
    return jsonify({"ok": True, **result})


@app.route("/api/downloaders/test", methods=["POST"])
def api_test_new():
    body = request.get_json(silent=True) or {}
    target = str(body.get("url", "")).strip().rstrip("/")
    if not target:
        return _err("URL 不能为空")
    try:
        result = collector.test(body, allow_private=_test_allow_private(target))
    except Exception as exc:
        return _test_failed(exc, target)
    db.audit("downloaders.test", actor=g.session.get("username", ""),
             ip=auth.client_ip(), detail="ok url=%s" % target)
    return jsonify({"ok": True, **result})


# ---------------- 下载器详情弹窗 / 汇总详情 ----------------
# 点击卡片时才向下载器发请求，3 秒内重复打开复用结果，避免连点打爆 WebUI。
#
# 工程化前提说明：_detail_cache / _summary_cache / limiter / EventBus
# 都是**模块级进程内内存**，只在「单进程 + 多线程」部署下生效 —— 当前
# waitress 以单进程 12 线程运行（Dockerfile CMD），完全正确。若以后改成
# 多进程 / 多副本（gunicorn -w N、k8s 多 pod），这些缓存、限流计数与 SSE
# 订阅都各自独立、互不可见，必须换成 Redis 等外部存储 + Pub/Sub 广播，
# 否则会出现「限流被绕过」「SSE 只推到本进程」「详情缓存不一致」。
_detail_cache = {}
_detail_lock = threading.Lock()
DETAIL_TTL = 3.0
# 汇总详情单独缓存一份（聚合结果），与单台缓存一起在配置变更时失效。
_summary_cache = [None, None]          # (写入时刻, payload)


def clear_detail_cache(did=None):
    global _summary_cache
    with _detail_lock:
        if did is None:
            _detail_cache.clear()
        else:
            _detail_cache.pop(did, None)
        _summary_cache = [None, None]


def _detail_for(d):
    """带 3 秒缓存地抓单台详情（单台弹窗用），异常向上抛给 API 层转 502。"""
    did = d["id"]
    now = time.time()
    with _detail_lock:
        hit = _detail_cache.get(did)
        if hit:
            if now - hit[0] < DETAIL_TTL:
                return hit[1]
            # 内存优化：过期即释放 payload，不再让最后一次详情长期驻留
            _detail_cache.pop(did, None)
    data = collector.detail(d)
    with _detail_lock:
        # 设条目上限，防御异常 id 长期堆积
        if len(_detail_cache) >= 32:
            _detail_cache.clear()
        _detail_cache[did] = (now, data)
    return data


@app.route("/api/downloaders/<int:did>/detail")
def api_downloader_detail(did):
    d = db.get_downloader(did)
    if not d:
        return _err("下载器不存在", 404)
    try:
        data = _detail_for(d)
    except Exception as exc:
        return _err("读取下载器详情失败：%s" % exc, 502)
    return jsonify({"ok": True, **data})


@app.route("/api/downloaders/summary/detail")
def api_downloaders_summary_detail():
    """汇总卡片详情：标题＝汇总实时速率 + 下载器数量与连接情况；
    第一块＝全部下载器的种子状态求和；第二块＝按 sort_order 逐台列出，
    每台字段与单台详情弹窗完全一致。单台抓取失败只标记该台，不影响其他台。"""
    global _summary_cache
    now = time.time()
    with _detail_lock:
        hit = _summary_cache
        if hit[0] and now - hit[0] < DETAIL_TTL and hit[1] is not None:
            return jsonify({"ok": True, **hit[1]})
        # 内存优化：聚合 payload 过期即释放，避免长跑驻留
        if hit[0] and now - hit[0] >= DETAIL_TTL:
            _summary_cache = [None, None]

    # 保留 password 供采集器登录；返回给前端时只挑必要字段，不外泄密码
    # 汇总详情只列启用的下载器
    ds = db.list_downloaders(enabled_only=True)
    states = db.get_states()
    results = collector.detail_many(ds)          # 并发，保持传入顺序

    agg = {k: 0 for k in TORRENT_KEYS}
    items = []
    up_rate = dl_rate = online = 0
    for d, data, err in results:
        st = states.get(d["id"], {})
        is_online = st.get("status") == "online"
        # 汇总速率与总量口径沿用 overview（读采集状态，不重新累加详情里的瞬时值）
        up_rate += int(st.get("up_rate") or 0)
        dl_rate += int(st.get("dl_rate") or 0)
        online += 1 if is_online else 0
        if data:
            t = data.get("torrents") or {}
            for k in TORRENT_KEYS:
                agg[k] += int(t.get(k) or 0)
        items.append({
            "id": d["id"], "name": d["name"], "type": d["type"], "url": d["url"],
            "status": st.get("status", "unknown"), "online": is_online,
            "color_up": d["color_up"], "color_down": d["color_down"],
            "detail": data, "error": err,
        })

    payload = {
        "total": {"up_rate": up_rate, "dl_rate": dl_rate,
                  "online": online, "count": len(ds), "offline": len(ds) - online},
        "aggregate": {"torrents": agg},
        "items": items,
        "io_warn": IO_WARN, "io_bad": IO_BAD,
    }
    with _detail_lock:
        _summary_cache = [now, payload]
    return jsonify({"ok": True, **payload})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=cfg["http_port"], threaded=True, use_reloader=False)
