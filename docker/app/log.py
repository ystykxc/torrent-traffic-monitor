"""结构化日志。

所有可观测性事件输出为单行 JSON 到 stdout，docker logs / json-file 驱动可直接
采集；审计事件同时由 db.audit 落 SQLite，保证容器重启后仍可回溯「谁在什么
时候改了什么」。输出中绝不记录密码、token、下载器凭据等敏感值。
"""
import json
import sys
import threading
import time

_lock = threading.Lock()

_SENSITIVE = ("password", "token", "secret", "authorization", "cookie", "hash")


def _scrub(k, v):
    if any(word in str(k).lower() for word in _SENSITIVE):
        return "***"
    if isinstance(v, (dict, list, tuple)):
        return str(type(v).__name__)
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "…"
    return v


def event(level, name, **fields):
    rec = {"ts": round(time.time(), 3), "level": level, "event": name}
    rec.update({k: _scrub(k, v) for k, v in fields.items()})
    try:
        line = json.dumps(rec, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        line = json.dumps({"ts": rec["ts"], "level": level, "event": name},
                          ensure_ascii=False)
    with _lock:
        print(line, file=sys.stdout, flush=True)


def info(name, **kw):
    event("INFO", name, **kw)


def warn(name, **kw):
    event("WARN", name, **kw)


def error(name, **kw):
    event("ERROR", name, **kw)
