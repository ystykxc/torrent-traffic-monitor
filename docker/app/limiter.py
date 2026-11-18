"""轻量全局限流。

按「客户端 key」做固定窗口计数：默认每个 key 60 秒内最多 180 次请求，
/api/chart 与连接测试等严格路径取一半并独立计数；纯内存、带锁、带上限与
过期清理，零外部依赖。SSE 长连接只在建立时计一次，不按帧计数。
"""
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits = defaultdict(deque)
_MAX_KEYS = 4096


def allow(key, limit, window=60.0):
    """返回 (是否放行, 本窗口已用次数, 剩余重置秒数)。"""
    now = time.time()
    with _lock:
        if len(_hits) > _MAX_KEYS:
            # 极端扫描下整体清空，防止字典无界增长（与原 _fails 同思路）
            _hits.clear()
        q = _hits[key]
        cut = now - window
        while q and q[0] <= cut:
            q.popleft()
        if len(q) >= limit:
            return False, len(q), max(1, int(window - (now - q[0])) + 1)
        q.append(now)
        return True, len(q), 0


def reset(key=None):
    with _lock:
        if key is None:
            _hits.clear()
        else:
            _hits.pop(key, None)
