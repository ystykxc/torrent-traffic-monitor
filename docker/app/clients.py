"""qBittorrent / Transmission 的轻量 API 客户端（仅用标准库 urllib）。

统一返回结构：
{
 "dl_rate": int,        # 当前下载速率 B/s（只用于速率曲线，不参与累计流量）
 "up_rate": int,        # 当前上传速率 B/s
 "dl_total": int|None,  # 自安装以来累计下载字节（持久计数器，重启不归零）
 "up_total": int|None,  # 自安装以来累计上传字节
 "extra": {...}         # 详情：版本 / I/O / 限速 / 剩余空间 / 种子状态
}

流量只能来自累计计数器差值——下载器自己记账的真实字节数，与采样间隔、
速率抖动、容器重启都无关。qB 的 sync/maindata 是增量响应，空闲轮次会省略
alltime_*，因此客户端缓存累计值防止基线被 NULL 冲掉；计数器缺失 / 回退 /
首次采集 / 异常跳变一律记 0，绝不用「速率 × 时间」估算。

详情弹窗按需只读：qB 取 app/version、transfer/info、torrents/info，并按需
读 torrents/trackers 补齐 tracker 异常种子；TR 取 session-get、session-stats、
torrent-get。10 项种子状态按真实数据独立判定，「正在做种」（完成度 100%
且非暂停）与「正在上传」（当前有上传速度）可重叠；TR 错误种子判定对齐
TrguiNG getTorrentError()，版本号只显示数字部分；qB 的 I/O 胶囊按排队
作业数分绿 / 黄 / 红三级着色。

所有外连地址统一经过 netsafe 目标校验，测试连接 / 新增下载器还会解析全部
A/AAAA 记录防 DNS rebinding。TR 的 X-Transmission-Session-Id 409 协商、
qB 的 Host / Origin 同源头（兼容 4.6+ 的 CSRF 校验）均已自动处理。
"""
import base64
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import netsafe


class ClientError(Exception):
    pass


def _positive(v):
    try:
        return max(0, int(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _rate_positive(v):
    """速率可能是小数（B/s）；判断「当前是否真的有上传速度」时不能先取整，
    否则 0.4 B/s 会被抹成 0。只用于比较，不用于累加流量。"""
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return 0.0


def _short_version(v):
    """TR 的 session-get.version 常形如 "4.0.6 (2a1c9f3d4e)" 或
    "3.00 (bb6b5a062e)" —— 只保留数字版本号，去掉括号里那段很长的带字母
    的构建号。qB 的 /app/version 本来就是纯数字，不受影响。"""
    s = str(v or "未知").strip()
    head = s.split("(", 1)[0].strip()
    m = re.search(r"\d+(?:\.\d+)*", head)
    return (m.group(0) if m else head) or s


def _pct(v):
    """qB 的 read_cache_hits 等字段在不同版本里可能是 0~1 比例或 0~100 百分数。"""
    try:
        f = float(str(v).strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    if f <= 1:
        f *= 100
    return max(0.0, min(100.0, f))


# qB 详情弹窗的 I/O 胶囊改成「一个数字」——排队 I/O 作业数
# (server_state.queued_io_jobs)，按磁盘队列积压程度分三级着色。
# 依据 qB/libtorrent：默认 aio_threads=10，队列里的作业数远大于线程数即积压。
# < IO_WARN 绿（健康）：队列基本跟得上磁盘
# IO_WARN ~ IO_BAD 黄（繁忙）：开始积压
# >= IO_BAD 红（过载）：磁盘成为瓶颈
# 阈值是经验值，可在部署时按磁盘性能调整；仅影响展示，不碰流量统计。
IO_WARN = 20
IO_BAD = 100


def io_level(v):
    if v is None:
        return None
    v = max(0, int(v))
    return 'good' if v < IO_WARN else ('warn' if v < IO_BAD else 'bad')


def _short_bytes(n):
    # 换算后的数值统一四舍五入保留两位小数（整数 B 本身没有小数位）
    n = _positive(n)
    for unit in ('B', 'K', 'M', 'G', 'T', 'P'):
        if n < 1024 or unit == 'P':
            return ('%d%s' % (n, unit)) if unit == 'B' else ('%.2f%s' % (n, unit))
        n /= 1024.0
    return '0B'


# qBittorrent torrent state -> 详情弹窗的 8 类计数。
# 依据 qB WebUI 的 state 取值（4.5+ 把 pausedUP/DL 改名为 stoppedUP/DL，两种都认）。
# 「正在做种 / 正在上传」不再由 state 字符串互斥归类，改为按真实数据判定
# （见 detail 内的 seeding_n / uploading_n）；本表只负责其余 6 类。
# 表里的 'seeding' / 'uploading' 两个落点被跳过，避免与新口径重复计数。
# qB 5.1+ / 增强版 WebUI 会把「连不上 tracker」「tracker 返回错误」
# 「种子未在 tracker 注册」的种子也归入「Errored」。不同版本返回的 state 字符串
# 可能是 tracker_down / tracker_error / unregistered / errored，统一映射到 error；
# 老版本 qB 只返回 stalledDL 之类 state，则走下面 _qb_tracker_error 读
# /api/v2/torrents/trackers 兜底判定。
QB_STATE_KEYS = {
    'error': 'error', 'missingFiles': 'error',
    'errored': 'error', 'tracker_down': 'error',
    'tracker_error': 'error', 'unregistered': 'error',
    'uploading': 'uploading', 'forcedUP': 'uploading',
    'stalledUP': 'seeding',
    'queuedUP': 'waiting', 'allocating': 'waiting', 'moving': 'waiting',
    'checkingUP': 'checking', 'checkingDL': 'checking',
    'checkingResumeData': 'checking',
    'pausedUP': 'paused_up', 'stoppedUP': 'paused_up',
    'downloading': 'downloading', 'forcedDL': 'downloading', 'metaDL': 'downloading',
    'stalledDL': 'waiting', 'queuedDL': 'waiting',
    'pausedDL': 'paused_down', 'stoppedDL': 'paused_down',
    'unknown': 'waiting',
}
TORRENT_KEYS = ('total', 'total_size', 'seeding', 'uploading', 'downloading',
                'waiting', 'checking', 'paused_up', 'paused_down', 'error')
# qB 的暂停态集合（4.5+ 把 pausedUP/DL 改名为 stoppedUP/DL，两种都认）。
# 「正在做种」＝完成度 100% 且状态不属于这些；「正在上传」＝当前有上传速度。
QB_PAUSED_STATES = frozenset(('pausedUP', 'pausedDL', 'stoppedUP', 'stoppedDL'))

# tracker 错误消息关键词（大小写不敏感），分两类：
# FATAL —— 任一真实 tracker 命中即算错误（种子已死：未注册 / passkey 失效 / 被删）
# DOWN —— 只有「所有真实 tracker 都连不上」才算错误（避免单个 tracker 抖动误报）
QB_TRACKER_FATAL = (
    'unregistered', 'not registered', 'torrent not registered',
    'info_hash not found', 'infohash not found', 'not found',
    'deleted', 'removed', 'duplicate', 'banned', 'invalid passkey',
    'forbidden', 'client not allowed', 'whitelist', '410', '404',
    'not exist', 'does not exist', 'invalid torrent',
)
QB_TRACKER_DOWN = (
    'not reachable', 'unreachable', 'could not connect', 'cannot connect',
    'connection failed', 'connection refused', 'connection timed out',
    'timed out', 'timeout', 'host not found', 'no route',
    'network is unreachable', 'name or service not known',
    'tracker error', 'tracker gave', 'socket', 'ssl', 'eof',
)


def _qb_real_trackers(trackers, host_key='url'):
    # 剔除 DHT / PeX / LSD 伪 tracker，只保留真实 tracker
    real = []
    for tr in trackers or []:
        if not isinstance(tr, dict):
            continue
        host = str(tr.get(host_key) or '')
        if not host or host.startswith('** ['):
            continue
        real.append(tr)
    return real


def _qb_tracker_error(trackers):
    # qB：tracker 全挂 / 明确报「未注册」等致命错误的种子算错误。
    # 对齐 qB WebUI 的 Errored 口径：state=error/missingFiles 之外，还要把
    # 「连不上 tracker」「种子未在 tracker 注册」一并计入。
    real = _qb_real_trackers(trackers)
    if not real:
        return False
    msgs = [str(tr.get('msg') or '').lower() for tr in real]
    if any(any(k in m for k in QB_TRACKER_FATAL) for m in msgs if m):
        return True

    def down(tr, m):
        try:
            st = int(tr.get('status') or 0)
        except (TypeError, ValueError):
            st = 0
        # status: 0=禁用 1=未联系 2=正常 3=更新中 4=不工作
        return st == 4 or (bool(m) and any(k in m for k in QB_TRACKER_DOWN))

    return all(down(tr, m) for tr, m in zip(real, msgs))


def _tr_torrent_error(t, status):
    # 完整复刻 TrguiNG(jayzcoder/TrguiNG) src/rpc/torrent.ts 的
    # getTorrentError，返回 cachedError 字符串；配合 _positive(error) 即
    # src/components/filters.tsx 的「错误」分组条件
    # filter: (t) => (t.error !== 0 || t.cachedError !== "")
    # 与旧版关键词匹配的本质差异，正是「总比 Web 端多一个种子」的根因：
    # 1) 只有 hasAnnounced=true 且 lastAnnounceSucceeded=false 的 tracker
    # 才把 lastAnnounceResult 当作错误文本；从未宣告过的 tracker 忽略；
    # 2) 只要有任一 tracker 正常 / 成功 / 结果为 "Success"，noTrackerError
    # 置位，整颗种子忽略全部 tracker 错误（TrguiNG 要求「全部失败」）；
    # 3) 暂停种子 status=stopped(0) 同样忽略 tracker 错误；
    # 4) tracker 错误文本与全局 errorString 相同时去重（清空全局串）。
    # 旧版按 any(FATAL 关键词) 只要一个 tracker 命中就判错，把「部分 tracker
    # 失败」「暂停种子 tracker 报错」「从未宣告的残留错误串」都误算成错误。
    torrent_error = str(t.get('errorString') or '')
    tracker_error = ''
    no_tracker_error = False
    for tr in (t.get('trackerStats') or []):
        if not isinstance(tr, dict):
            continue
        err = ''
        if tr.get('hasAnnounced') and not tr.get('lastAnnounceSucceeded'):
            err = str(tr.get('lastAnnounceResult') or '')
        if err == '' or err == 'Success':
            no_tracker_error = True
        elif tracker_error == '':
            if err == torrent_error:
                torrent_error = ''
            tracker_error = 'Tracker: ' + err
    if no_tracker_error or status == 0:
        return torrent_error
    return tracker_error


def _empty_torrents():
    d = {k: 0 for k in TORRENT_KEYS}
    return d


class QBittorrentClient:
    def __init__(self, url, username, password, timeout=5):
        self.base = str(url).rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.rid = 0
        self.authed = False
        # 缓存累计计数器。sync/maindata 是增量响应，空闲轮次 alltime_* 会缺席；
        # 此时沿用上一次的累计值，差值即 0，而不是返回 None 让采集器去猜速率。
        self._totals = {"dl": None, "ul": None}

    def _totals_from(self, st):
        """从 server_state 取累计计数器；字段缺席时用缓存值补齐，绝不返回 None。

        返回 (dl_total, up_total, source)：source 为 live / cached / partial，
        写进 extra 便于排查「本轮是否真的拿到了下载器的累计值」。
        """
        got_dl = "alltime_dl" in st
        got_ul = "alltime_ul" in st
        if got_dl:
            self._totals["dl"] = _positive(st.get("alltime_dl"))
        if got_ul:
            self._totals["ul"] = _positive(st.get("alltime_ul"))
        src = "live" if (got_dl and got_ul) else ("partial" if (got_dl or got_ul) else "cached")
        return self._totals["dl"], self._totals["ul"], src

    def _open(self, path, data=None, headers=None):
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        h = dict(headers or {})
        # qBittorrent 4.6+ 默认开启 CSRF / Host 头校验，带上同源头可避免 403
        parts = urllib.parse.urlsplit(self.base)
        origin = f"{parts.scheme}://{parts.netloc}"
        h.setdefault("Origin", origin)
        h.setdefault("Referer", self.base + "/")
        req = urllib.request.Request(self.base + path, data=body, headers=h)
        with self.opener.open(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def _login(self):
        r = self._open("/api/v2/auth/login", {"username": self.username, "password": self.password})
        if "Ok" not in r:
            raise ClientError("qBittorrent 登录失败（用户名或密码错误）")
        self.authed = True

    def _relogin(self):
        self.jar.clear()
        self.authed = False
        self.rid = 0
        self._login()

    def fetch(self):
        if not self.authed:
            self._login()
        try:
            raw = self._open(f"/api/v2/sync/maindata?rid={self.rid}")
            data = json.loads(raw)
            st = data.get("server_state") or {}
            if not st:
                raise ValueError("maindata 缺少 server_state")
            self.rid = int(data.get("rid") or self.rid)
            dl_total, up_total, src = self._totals_from(st)
            return {
                "dl_rate": _positive(st.get("dl_info_speed")),
                "up_rate": _positive(st.get("up_info_speed")),
                "dl_total": dl_total,
                "up_total": up_total,
                "extra": {
                    "session_dl": _positive(st.get("dl_info_data")),
                    "session_up": _positive(st.get("up_info_data")),
                    "connection": st.get("connection_status", ""),
                    "counter_source": src,
                },
            }
        except urllib.error.HTTPError as exc:
            # SID 过期 / 被踢下线：重新登录一次再取
            if exc.code in (401, 403):
                self._relogin()
                raw = self._open("/api/v2/sync/maindata?rid=0")
                st = (json.loads(raw).get("server_state") or {})
                if not st:
                    raise ClientError("qBittorrent 重新登录后仍无 server_state")
                self.rid = 0
                dl_total, up_total, src = self._totals_from(st)
                return {
                    "dl_rate": _positive(st.get("dl_info_speed")),
                    "up_rate": _positive(st.get("up_info_speed")),
                    "dl_total": dl_total,
                    "up_total": up_total,
                    "extra": {"counter_source": src, "relogin": True},
                }
            raise
        except (ValueError, KeyError, urllib.error.URLError):
            # 老版本 / 反向代理拿不到 maindata 时退到 transfer/info。
            # 该接口没有 alltime_*，但 会沿用缓存的累计值：本次差值记 0，
            # 等下一轮 maindata 恢复时由累计差值自动补齐，绝不用速率估算。
            raw = self._open("/api/v2/transfer/info")
            st = json.loads(raw)
            return {
                "dl_rate": _positive(st.get("dl_info_speed")),
                "up_rate": _positive(st.get("up_info_speed")),
                "dl_total": self._totals["dl"],
                "up_total": self._totals["ul"],
                "extra": {"session_dl": _positive(st.get("dl_info_data")),
                          "session_up": _positive(st.get("up_info_data")),
                          "fallback": "transfer/info",
                          "counter_source": "cached"},
            }

    def detail(self):
        """详情弹窗：按需抓一次版本 / I/O / 限速 / 剩余空间 / 种子状态。

        只读取、不写库、不改 fetch() 的 rid 增量状态，因此对 流量统计
        口径零影响。任一子接口失败都降级为「该字段为空」，不拖垮整个弹窗。
        """
        if not self.authed:
            self._login()

        def get(path):
            try:
                return self._open(path)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    self._relogin()
                    return self._open(path)
                raise

        version = '未知'
        try:
            version = get('/api/v2/app/version').strip() or '未知'
        except Exception:
            pass

        st, ti = {}, {}
        try:
            st = (json.loads(get('/api/v2/sync/maindata?rid=0')).get('server_state') or {})
        except Exception:
            pass
        try:
            ti = json.loads(get('/api/v2/transfer/info')) or {}
        except Exception:
            pass
        torrents = []
        try:
            parsed = json.loads(get('/api/v2/torrents/info'))
            if isinstance(parsed, list):
                torrents = parsed
        except Exception:
            pass

        dl_rate = _positive(ti.get('dl_info_speed') or st.get('dl_info_speed'))
        up_rate = _positive(ti.get('up_info_speed') or st.get('up_info_speed'))
        # qB 的限速单位是 B/s，0 表示不限速
        dl_limit = _positive(ti.get('dl_rate_limit') or st.get('dl_rate_limit'))
        up_limit = _positive(ti.get('up_rate_limit') or st.get('up_rate_limit'))
        free_space = st.get('free_space_on_disk')
        free_space = _positive(free_space) if free_space is not None else None

        # I/O 胶囊显示「排队 I/O 作业数」这个整数（qB WebUI 状态栏磁盘
        # 缓存图标里的 queued_io_jobs），不再是读缓存命中率百分比。数字按
        # io_level 的三级阈值上色：绿 < 20 / 黄 20~99 / 红 >= 100。
        # io_full 仍把完整磁盘状态放进悬停提示，方便对照 qB WebUI。
        io_value, io_label, io, io_full = None, '排队 I/O 作业', None, None
        bits = []
        if st.get('queued_io_jobs') is not None:
            io_value = _positive(st.get('queued_io_jobs'))
        hits = _pct(st.get('read_cache_hits'))
        if hits is not None:
            bits.append('读缓存命中 %.2f%%' % hits)
        wo = _pct(st.get('write_cache_overload'))
        if wo is not None:
            bits.append('写缓存过载 %.2f%%' % wo)
        if io_value is not None:
            bits.append('排队 I/O 作业 %d' % io_value)
        buf = st.get('total_buffers_size', st.get('total_buff_size'))
        if buf is not None:
            bits.append('缓冲区 %s' % _short_bytes(buf))
        if st.get('average_time_queue') is not None:
            bits.append('平均排队 %d ms' % _positive(st.get('average_time_queue')))
        if io_value is None and st.get('average_time_queue') is not None:
            # 极老版本没给 queued_io_jobs 时退到平均排队时长（同样是整数），
            # 阈值沿用同一套，语义仍是「磁盘 I/O 是否繁忙」
            io_value = _positive(st.get('average_time_queue'))
            io_label = '平均排队 ms'
        io_full = ' · '.join(bits) or None
        if io_value is not None:
            io = 'IO %d' % io_value
        else:
            # 完全没有磁盘 I/O 字段时，用本次会话 I/O 数据量兜底展示
            sd = _positive(st.get('dl_info_data') or ti.get('dl_info_data'))
            su = _positive(st.get('up_info_data') or ti.get('up_info_data'))
            io = 'IO ↓%s ↑%s' % (_short_bytes(sd), _short_bytes(su))
            io_full = '本次会话 I/O：下载 %s / 上传 %s' % (_short_bytes(sd), _short_bytes(su))
            io_label = '本次会话 I/O'

        # 老版本 qB 的 state 里没有 tracker 错误信息，按需并发读取
        # /api/v2/torrents/trackers，把「连不上 tracker / 未注册」的种子也计入
        # 错误（与 qB WebUI 的 Errored 口径一致）。暂停态与已是 error 的种子
        # 不再重复请求；单个请求失败静默降级，不影响其它统计。
        tracker_bad = set()

        def read_trackers(t):
            h = t.get('hash')
            if not h:
                return (h, [])
            try:
                raw = self._open('/api/v2/torrents/trackers?hash=' +
                                 urllib.parse.quote(str(h)))
                arr = json.loads(raw)
                return (h, arr if isinstance(arr, list) else [])
            except Exception:
                return (h, [])

        candidates = [t for t in torrents
                      if isinstance(t, dict) and t.get('hash')
                      and str(t.get('state', '')) not in QB_PAUSED_STATES
                      and QB_STATE_KEYS.get(str(t.get('state', '')), 'waiting') != 'error']
        if candidates:
            pool = ThreadPoolExecutor(max_workers=min(6, len(candidates)))
            try:
                futs = [pool.submit(read_trackers, t) for t in candidates]
                deadline = time.time() + max(2.0, float(self.timeout))
                for f in futs:
                    try:
                        h, arr = f.result(timeout=max(0.2, deadline - time.time()))
                        if h and _qb_tracker_error(arr):
                            tracker_bad.add(h)
                    except Exception:
                        pass
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        buckets = _empty_torrents()
        buckets['total'] = len(torrents)
        # 两个「活跃维度」按真实数据独立判定，可与互斥类别重叠（语义上本就
        # 该重叠：边下边传的种子既算「正在下载」也算「正在上传」）：
        # 正在做种 = 完成度 100% 且状态不是暂停（无论当前有没有上传速度）
        # 正在上传 = 当前有上传速度（无论种子是否完成）
        # 其余 6 类仍按 QB_STATE_KEYS 互斥归类，数值保持不变。
        seeding_n = uploading_n = 0
        for t in torrents:
            if not isinstance(t, dict):
                continue
            buckets['total_size'] += _positive(t.get('total_size') or t.get('size'))
            state = str(t.get('state', ''))
            key = QB_STATE_KEYS.get(state, 'waiting')
            # tracker 异常种子从原互斥类别挪到 error（不重复计数）
            if t.get('hash') in tracker_bad and key != 'error':
                key = 'error'
            if key not in ('seeding', 'uploading'):
                buckets[key] += 1
            # qB 的 progress 是 0~1 浮点，1.0 即完成度 100%
            try:
                done = float(t.get('progress') or 0) >= 1.0
            except (TypeError, ValueError):
                done = False
            if done and state not in QB_PAUSED_STATES:
                seeding_n += 1
            # upspeed 单位 B/s；0 表示当前没有上传活动
            if _rate_positive(t.get('upspeed', t.get('up_speed'))) > 0:
                uploading_n += 1
        buckets['seeding'] = seeding_n
        buckets['uploading'] = uploading_n
        return {
            'type': 'qb', 'version': version,
            'io': io, 'io_value': io_value, 'io_level': io_level(io_value),
            'io_label': io_label, 'io_full': io_full,
            'io_warn': IO_WARN, 'io_bad': IO_BAD,
            'dl_rate': dl_rate, 'up_rate': up_rate,
            'dl_limit': dl_limit, 'up_limit': up_limit,
            'free_space': free_space, 'torrents': buckets,
        }


class TransmissionClient:
    def __init__(self, url, username, password, timeout=5):
        u = str(url).rstrip("/")
        if not u.endswith("/transmission/rpc"):
            u += "/transmission/rpc"
        self.url = u
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        self.session_id = ""
        # 与 qB 同样缓存累计值，防止个别版本字段缺席时基线被冲成 NULL
        self._totals = {"dl": None, "ul": None}

    def _rpc(self, method, arguments=None):
        payload = json.dumps({"method": method, "arguments": arguments or {}}).encode("utf-8")
        for attempt in range(3):
            headers = {"Content-Type": "application/json",
                       "X-Transmission-Session-Id": self.session_id}
            if self.username or self.password:
                token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
                headers["Authorization"] = "Basic " + token
            req = urllib.request.Request(self.url, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    self.session_id = exc.headers.get("X-Transmission-Session-Id", "")
                    if self.session_id:
                        continue
                raise ClientError(f"Transmission HTTP {exc.code}: {exc.reason}")
            if body.get("result") != "success":
                raise ClientError(f"Transmission 返回: {body.get('result')}")
            return body.get("arguments", {})
        raise ClientError("Transmission 会话 ID 协商失败")

    def fetch(self):
        a = self._rpc("session-stats")
        # 部分 TR 版本 / 代理用下划线键名；两种都接受，取不到的字段沿用缓存值
        cum = a.get("cumulative-stats") or a.get("cumulative_stats") or {}
        cur = a.get("current-stats") or a.get("current_stats") or {}
        if "downloadedBytes" in cum:
            self._totals["dl"] = _positive(cum.get("downloadedBytes"))
        if "uploadedBytes" in cum:
            self._totals["ul"] = _positive(cum.get("uploadedBytes"))
        return {
            "dl_rate": _positive(a.get("downloadSpeed")),
            "up_rate": _positive(a.get("uploadSpeed")),
            # cumulative-stats 是跨会话持久累计；current-stats 是本次会话，仅作参考
            "dl_total": self._totals["dl"],
            "up_total": self._totals["ul"],
            "extra": {
                "active_torrents": _positive(a.get("activeTorrentCount")),
                "torrents": _positive(a.get("torrentCount")),
                "session_dl": _positive(cur.get("downloadedBytes")),
                "session_up": _positive(cur.get("uploadedBytes")),
                "counter_source": "live" if cum else "cached",
            },
        }

    def detail(self):
        """详情弹窗：session-get + session-stats + torrent-get，只读不写库。"""
        try:
            s = self._rpc("session-get") or {}
        except Exception:
            s = {}
        try:
            stats = self._rpc("session-stats") or {}
        except Exception:
            stats = {}
        torrents = []
        try:
            args = self._rpc("torrent-get", {"fields": [
                # trackerStats 自带 hasAnnounced /
                # lastAnnounceSucceeded / lastAnnounceResult / host 子字段
                "id", "status", "error", "errorString", "trackerStats",
                "percentDone", "totalSize",
                "peersGettingFromUs", "isFinished", "rateUpload"]}) or {}
            torrents = args.get("torrents") or []
        except Exception:
            pass

        # 只保留数字版本号，去掉 "4.0.6 (2a1c9f3d4e)" 括号里那串构建号
        version = _short_version(s.get("version"))
        dl_rate = _positive(stats.get("downloadSpeed"))
        up_rate = _positive(stats.get("uploadSpeed"))
        # Transmission RPC 的限速单位是 KiB/s，需要换算成 B/s
        if s.get("alt-speed-enabled"):
            dl_limit = _positive(s.get("alt-speed-down")) * 1024
            up_limit = _positive(s.get("alt-speed-up")) * 1024
        else:
            dl_limit = (_positive(s.get("speed-limit-down")) * 1024
                        if s.get("speed-limit-down-enabled") else 0)
            up_limit = (_positive(s.get("speed-limit-up")) * 1024
                        if s.get("speed-limit-up-enabled") else 0)
        free_space = s.get("download-dir-free-space")
        free_space = _positive(free_space) if free_space is not None else None

        buckets = _empty_torrents()
        buckets["total"] = len(torrents)
        # 与 qB 同一套口径 —— 做种 = 完成度 100% 且状态非暂停（TR 的
        # STOPPED=0 即暂停）；上传 = rateUpload > 0，无论种子是否完成。
        # 其余 6 类仍按 status 互斥归类（SEED=6 不再落到 seeding/uploading，
        # 这两项改由新口径独立累加）。
        seeding_n = uploading_n = 0
        for t in torrents:
            if not isinstance(t, dict):
                continue
            buckets["total_size"] += _positive(t.get("totalSize"))
            try:
                status = int(t.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
            # TR 的 percentDone 是 0~1；isFinished 作兼容兜底
            try:
                done = float(t.get("percentDone") or 0) >= 1.0 or bool(t.get("isFinished"))
            except (TypeError, ValueError):
                done = bool(t.get("isFinished"))
            if done and status != 0:
                seeding_n += 1
            # rateUpload 单位 B/s（部分版本/代理用 uploadSpeed 别名）
            if _rate_positive(t.get("rateUpload", t.get("uploadSpeed"))) > 0:
                uploading_n += 1
            # 完整对齐 TrguiNG 的「错误」判定（见 _tr_torrent_error 注释）。
            # error 字段对应 error !== 0，cachedError 对应 tracker 综合判定；
            # 不再用「任一 tracker 命中关键词」的宽松匹配，消除多算 1 个的问题。
            if _positive(t.get("error")) or _tr_torrent_error(t, status):
                key = "error"
            elif status in (1, 2):                       # CHECK_WAIT / CHECK
                key = "checking"
            elif status == 4:                            # DOWNLOAD
                key = "downloading"
            elif status in (3, 5):                      # *_WAIT 排队
                key = "waiting"
            elif status == 0:                            # STOPPED：按完成度分暂停上传/下载
                key = "paused_up" if done else "paused_down"
            elif status == 6:                            # SEED：由 seeding/uploading 覆盖
                key = None
            else:
                key = "waiting"
            if key:
                buckets[key] += 1
        buckets["seeding"] = seeding_n
        buckets["uploading"] = uploading_n
        return {
            "type": "tr", "version": version,
            "io": None, "io_full": None,               # TR 无 qB 的 I/O 统计
            "dl_rate": dl_rate, "up_rate": up_rate,
            "dl_limit": dl_limit, "up_limit": up_limit,
            "free_space": free_space, "torrents": buckets,
        }


def make_client(d, timeout=5):
    # 所有下载器客户端统一过一遍目标校验。urllib 默认支持 file/ftp，
    # 不加这道闸会把「已登录用户指定的 URL」变成读取容器内文件 / 探测内网的
    # 通道。测试连接另有一层 assert_safe_target 的完整 DNS 校验。
    netsafe.assert_client_target(d["url"])
    if d["type"] == "tr":
        return TransmissionClient(d["url"], d["username"], d["password"], timeout)
    return QBittorrentClient(d["url"], d["username"], d["password"], timeout)
