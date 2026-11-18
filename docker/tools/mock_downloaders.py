#!/usr/bin/env python3
"""本地自测用的模拟下载器（不参与正式部署）。

启动后在 18081/18082/18083 模拟 qBittorrent，在 19091/19092 模拟 Transmission，
速率会随时间波动，累计计数器单调递增，用来验证采集、聚合和前端图表。

补齐详情弹窗所需接口（qB 的 app/version、transfer/info、torrents/info，
TR 的 session-get / torrent-get），以及限速 / 剩余空间 / 磁盘 I/O 状态字段。

TR trackerStats 补齐 hasAnnounced / errorString，并新增「部分 tracker
失败」干扰种子，用于验证 对齐 TrguiNG 后不再多算错误种子。

种子分布改用可读常量表 QB_TORRENT_ROWS / TR_TORRENT_ROWS，额外提供
progress / upspeed / rateUpload 字段，用于验证新的「正在做种＝完成度100%且
非暂停」「正在上传＝有上传速度」统计口径；TR 版本号改成真实格式（数字版本
号 + 括号内带字母的构建号），用于验证前端只展示数字版本号。验证脚本会直接
import 这些常量并按口径独立重算期望值。

用法：python3 tools/mock_downloaders.py
"""
import json
import urllib.parse
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QB_PORTS = [18081, 18082, 18083]
TR_PORTS = [19091, 19092]
TR_SESSION = "mock-session-1234"

QB_VERSIONS = {18081: "4.6.3", 18082: "4.5.5", 18083: "5.0.1"}
# TR 的 session-get.version 真值常带括号构建号（如 "4.0.6 (2a1c9f3d)"），
# 这里按真实格式给出，前端/后端应只展示 "4.0.6" / "3.00"。
TR_VERSIONS = {19091: "4.0.6 (2a1c9f3d4e)", 19092: "3.00 (bb6b5a062e)"}

STATES = {}
for i, p in enumerate(QB_PORTS + TR_PORTS):
    STATES[p] = {
        "t": time.time(),
        "dl": (i + 1) * 321_000_000_000,
        "up": (i + 1) * 654_000_000_000,
        "phase": random.random() * 6.28,
        "scale": 0.6 + random.random() * 1.8,
    }


def port_index(port):
    return (QB_PORTS + TR_PORTS).index(port)


def tick(port):
    s = STATES[port]
    now = time.time()
    dt = min(max(now - s["t"], 0), 30)
    s["t"] = now
    wave = 0.55 + 0.45 * math.sin(now / 47 + s["phase"])
    jitter = 0.75 + random.random() * 0.5
    dl_rate = 2_400_000 * s["scale"] * wave * jitter
    up_rate = 5_800_000 * s["scale"] * (1.2 - wave * 0.5) * jitter
    s["dl"] += dl_rate * dt
    s["up"] += up_rate * dt
    return int(dl_rate), int(up_rate)


# qB 种子分布 (state, progress, upspeed[B/s])。
# 覆盖「完成且有速度 / 完成无速度 / 完成被暂停 / 未完成但有速度（边下边传）/
# 未完成无速度 / 校验 / 排队 / 错误」等情形，便于精确验证新的做种与上传口径。
QB_TORRENT_ROWS = (
    ("uploading",    1.0, 120_000),   # 完成 + 有速度 → 做种 + 上传
    ("uploading",    1.0,       0),   # 完成 + 无速度 → 做种
    ("stalledUP",    1.0,       0),   # 完成 + 无速度 → 做种
    ("forcedUP",     1.0,  90_000),   # 完成 + 有速度 → 做种 + 上传
    ("queuedUP",     1.0,       0),   # 完成 + 排队 → 做种 + 等待
    ("downloading",  0.42, 30_000),   # 未完成 + 有速度 → 上传 + 下载
    ("downloading",  0.10,      0),   # 未完成 + 无速度 → 下载
    ("metaDL",       0.05,      0),   # 未完成 → 下载
    ("stalledDL",    0.99,      0),   # 未完成 → 等待
    ("queuedDL",     0.00,      0),   # 未完成 → 等待
    ("checkingUP",   1.0,       0),   # 完成 + 校验 → 做种 + 校验
    ("checkingDL",   0.50,      0),   # 未完成 + 校验 → 校验
    ("pausedUP",     1.0,       0),   # 完成但暂停 → 不算做种
    ("stoppedDL",    0.20,      0),   # 未完成暂停 → 暂停下载
    ("error",        1.0,       0),   # 完成 + 错误 → 仍算做种（按定义仅排除暂停）
    ("missingFiles", 0.80,      0),   # 未完成 + 错误 → 错误
)

# TR 种子分布
# (status, error, percentDone, peersGettingFromUs, isFinished, rateUpload[B/s])
# TR status：0=STOPPED(暂停) / 1,2=CHECK / 3,5=排队 / 4=DOWNLOAD / 6=SEED
# 模拟 qB WebUI 归入「Errored」的两类 tracker 异常种子。
# key = QB_TORRENT_ROWS 的行索引（对应 torrent hash 末三位）。
QB_TRACKER_ERRORS = {
    8: 'Tracker is not reachable',                   # 连不上 tracker
    9: 'Torrent not registered with this tracker',    # 种子未在 tracker 注册
}
# TR tracker 错误模拟，字段与 TrguiNG 读取的 TrackerStats 对齐。
# 只有「全部 tracker 都失败」(hasAnnounced=True / lastAnnounceSucceeded=False)
# 才算错误；与 TrguiNG getTorrentError 的判定完全一致。
TR_TRACKER_ERRORS = {
    3: 'Torrent not registered with this tracker',
    5: 'Could not connect to tracker',
}
# 复现「关键词匹配会多算 1 个」的干扰种子 —— 一个 tracker
# 报了含 FATAL 关键词的错误，但另一个 tracker 宣告成功。
# TrguiNG 判为正常，的 any(FATAL) 误判为错误（即用户看到的多 1 个）。
TR_TRACKER_MIXED = {
    0: [
        {'host': 'tracker-bad.example', 'hasAnnounced': True,
         'lastAnnounceSucceeded': False,
         'lastAnnounceResult': 'Torrent not registered with this tracker'},
        {'host': 'tracker-ok.example', 'hasAnnounced': True,
         'lastAnnounceSucceeded': True, 'lastAnnounceResult': 'Success'},
    ],
}

TR_TORRENT_ROWS = (
    (6, 0, 1.0, 3, True,  150_000),   # 完成 + 有速度 → 做种 + 上传
    (6, 0, 1.0, 0, True,        0),   # 完成 + 无速度 → 做种
    (4, 0, 0.42, 0, False, 40_000),   # 未完成 + 有速度 → 上传 + 下载
    (4, 0, 0.10, 0, False,      0),   # 未完成 + 无速度 → 下载
    (3, 0, 1.0, 0, True,        0),   # 完成 + 排队 → 做种 + 等待
    (2, 0, 0.90, 0, False,      0),   # 校验 → 校验
    (0, 0, 1.0, 0, True,        0),   # 完成但暂停 → 不算做种
    (0, 0, 0.30, 0, False,      0),   # 未完成暂停 → 暂停下载
    (4, 2, 0.10, 0, False,      0),   # 错误 → 错误
)


def qb_torrents(port):
    """固定分布；每台相同，验证脚本按 QB_TORRENT_ROWS 独立重算期望值。"""
    idx = port_index(port)
    out = []
    for i, (state, progress, upspeed) in enumerate(QB_TORRENT_ROWS):
        size = (i + 1 + idx) * 1_073_741_824  # 1 GiB 起递增
        out.append({"hash": "mock%02d%03d" % (idx, i), "name": "torrent-%03d" % i,
                    "state": state, "size": size, "total_size": size,
                    "progress": progress, "upspeed": upspeed})
    return out


def tr_torrents(port):
    idx = port_index(port)
    out = []
    for i, (st, err, done, peers, fin, rate_up) in enumerate(TR_TORRENT_ROWS):
        size = (i + 1 + idx) * 1_073_741_824
        row = {"id": i + 1, "status": st, "error": err, "percentDone": done,
               "totalSize": size, "peersGettingFromUs": peers,
               "isFinished": fin, "rateUpload": rate_up,
               "errorString": ""}      # TrguiNG 的全局错误串
        if i in TR_TRACKER_ERRORS:
            row["trackerStats"] = [{
                "host": "tracker.example",
                "hasAnnounced": True,       # 必须已宣告过
                "lastAnnounceSucceeded": False,
                "lastAnnounceResult": TR_TRACKER_ERRORS[i],
            }]
        elif i in TR_TRACKER_MIXED:
            row["trackerStats"] = TR_TRACKER_MIXED[i]
        out.append(row)
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body, headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200, headers=None):
        self._send(code, json.dumps(obj, ensure_ascii=False), headers)

    def do_POST(self):
        port = self.server.server_address[1]
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        if port in QB_PORTS:
            self._send(200, "Ok.", {"Set-Cookie": "SID=mockqb; path=/"})
            return
        if self.headers.get("X-Transmission-Session-Id") != TR_SESSION:
            self._send(409, '{"result":"conflict"}', {"X-Transmission-Session-Id": TR_SESSION})
            return
        try:
            method = (json.loads(raw.decode("utf-8")) or {}).get("method")
        except (ValueError, UnicodeDecodeError):
            method = None
        if method == "session-get":
            idx = port_index(port) - len(QB_PORTS)
            dl_lim, up_lim = (0, 0) if idx == 0 else (2048, 1024)  # KiB/s
            self._json({"result": "success", "arguments": {
                "version": TR_VERSIONS[port], "rpc-version": 18,
                "speed-limit-down": dl_lim, "speed-limit-up": up_lim,
                "speed-limit-down-enabled": bool(dl_lim), "speed-limit-up-enabled": bool(up_lim),
                "alt-speed-enabled": False, "alt-speed-down": 512, "alt-speed-up": 256,
                "download-dir-free-space": (900 - idx * 300) * 1_073_741_824,
            }})
            return
        if method == "torrent-get":
            self._json({"result": "success", "arguments": {"torrents": tr_torrents(port)}})
            return
        # session-stats（原采集逻辑）及其它
        dl_r, up_r = tick(port)
        s = STATES[port]
        args = {
            "downloadSpeed": dl_r, "uploadSpeed": up_r,
            "activeTorrentCount": 12, "torrentCount": 320,
            "cumulative-stats": {"downloadedBytes": int(s["dl"]), "uploadedBytes": int(s["up"])},
            "current-stats": {"downloadedBytes": 123456, "uploadedBytes": 654321},
        }
        self._json({"result": "success", "arguments": args})

    def do_GET(self):
        port = self.server.server_address[1]
        path = self.path.split("?")[0]
        dl_r, up_r = tick(port)
        s = STATES[port]
        idx = port_index(port)
        if path in ("/api/v2/sync/maindata", "/api/v2/transfer/info"):
            # 第 1 台 qB 不限速，其余各给一组限速；供弹窗「无限图标」验证
            lim = 0 if idx == 0 else (5_242_880 if idx == 1 else 2_097_152)
            # 三台 qB 的排队 I/O 作业数分别落在 绿(<20) / 黄(20~99) / 红(>=100)
            # 三档，供详情弹窗的 I/O 胶囊三级着色验证。字段名对齐 qB 真实 API。
            queued_io = (5, 45, 150)[idx] if idx < 3 else 5
            st = {
                "dl_info_speed": dl_r, "up_info_speed": up_r,
                "alltime_dl": int(s["dl"]), "alltime_ul": int(s["up"]),
                "dl_info_data": 123456, "up_info_data": 654321,
                "connection_status": "connected",
                "free_space_on_disk": (1200 - idx * 250) * 1_073_741_824,
                "dl_rate_limit": lim, "up_rate_limit": lim // 2,
                "read_cache_hits": 97.5 - idx, "write_cache_overload": 0,
                "queued_io_jobs": queued_io, "total_buffers_size": 16_777_216,
                "average_time_queue": 3 + idx,
            }
            if path == "/api/v2/transfer/info":
                st.pop("alltime_dl", None)
                st.pop("alltime_ul", None)
                st.pop("read_cache_hits", None)
                st.pop("queued_io_jobs", None)
                self._json(st)
            else:
                self._json({"rid": 1, "full_update": False, "server_state": st})
            return
        if path == "/api/v2/app/version":
            self._send(200, QB_VERSIONS.get(port, "4.6.3"))
            return
        if path == "/api/v2/app/buildInfo":
            self._json({"bitness": 64, "boost": "1.83.0", "libtorrent": "2.0.9.0",
                        "openssl": "3.0.11", "qt": "6.4.2", "zlib": "1.2.13"})
            return
        if path == "/api/v2/torrents/info":
            self._json(qb_torrents(port))
            return
        if path == "/api/v2/torrents/trackers":
            # 按 hash 末三位定位 QB_TORRENT_ROWS 行，返回带 tracker 错误的
            # 真实 tracker（另附一个正常的 DHT 伪 tracker，用于验证会被忽略）。
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            h = q.get('hash', [''])[0]
            try:
                i = int(str(h)[-3:])
            except (ValueError, TypeError):
                i = -1
            msg = QB_TRACKER_ERRORS.get(i, '')
            self._json([
                {"url": "http://tracker.example/announce", "tier": 0,
                 "status": 4 if msg else 2, "num_peers": 0, "num_seeds": 0,
                 "num_leechers": 0, "num_downloaded": 0, "msg": msg},
                {"url": "** [DHT] **", "tier": -1, "status": 2,
                 "num_peers": 0, "num_seeds": 0, "num_leechers": 0,
                 "num_downloaded": 0, "msg": ""},
            ])
            return
        self._send(404, '{"error":"not found"}')


def main():
    servers = []
    for port in QB_PORTS + TR_PORTS:
        srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        print(f"mock 已启动: {'qB' if port in QB_PORTS else 'TR'} http://127.0.0.1:{port}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
