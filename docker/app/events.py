"""采集完成事件总线（SSE 推流）。

collector 每完成一轮采集就 publish 一次；/api/stream 订阅并把事件推给前端，
前端收到后只做局部刷新，不再各自定时盲发 HTTP 请求。

服务端节流：高频档位（0.1 秒采样）下若每轮都推会压垮前端，因此每种 kind
做最小发布间隔（默认 1 秒）合并，低频档位采集完成即推。订阅队列有界（32），
慢客户端积压时丢最旧的一条保最新，绝不阻塞采集线程。
"""
import json
import queue
import threading
import time


class EventBus:
    def __init__(self, min_interval=1.0, max_subscribers=6):
        self._subs = []
        self._lock = threading.Lock()
        self._last = {}
        self._min_interval = min_interval
        self._max_subscribers = max_subscribers
        self._seq = 0
        self.published = 0
        self.throttled = 0

    def can_subscribe(self):
        """只预检名额、不占用名额。供 SSE 端点在返回响应前判断能否接纳连接，
        真正的 subscribe() 放到响应生成器内部，避免 WSGI 层异常导致泄漏。"""
        with self._lock:
            return len(self._subs) < self._max_subscribers

    def subscribe(self):
        q = queue.Queue(maxsize=32)
        with self._lock:
            if len(self._subs) >= self._max_subscribers:
                return None
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        if q is None:
            return
        with self._lock:
            try:
                self._subs.remove(q)
            except ValueError:
                pass

    def publish(self, kind, data=None):
        now = time.time()
        with self._lock:
            if now - self._last.get(kind, 0.0) < self._min_interval:
                self.throttled += 1
                return False
            self._last[kind] = now
            self._seq += 1
            self.published += 1
            msg = {"kind": kind, "seq": self._seq, "ts": now, "data": data or {}}
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass
        return True

    @staticmethod
    def sse(msg):
        return ("event: %s\ndata: %s\n\n" %
                (msg["kind"], json.dumps(msg, ensure_ascii=False, separators=(",", ":"))))

    def stats(self):
        with self._lock:
            return {"subscribers": len(self._subs), "published": self.published,
                    "throttled": self.throttled, "seq": self._seq}


BUS = EventBus()
