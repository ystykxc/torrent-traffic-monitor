"""内存回收：让容器长时间运行（>1 个月）保持低 RSS。

根因：waitress 多线程 + 高频 API 请求（overview / 图表）会在 glibc 与 CPython
分配器里不断堆出短命大对象，分配器把堆扩到峰值后默认不把空闲页归还 OS，
RSS 会从 30MB 爬到 100MB+ 后停在平台期。本模块在采集循环里被低频调用：
 1) gc.collect 回收循环垃圾，促使 CPython 释放空闲 pymalloc arena；
 2) ctypes 调 glibc malloc_trim(0)，把各 arena 顶部的空闲页归还内核。
配合 Dockerfile 的 MALLOC_ARENA_MAX=2 与 waitress --threads=12（限制 arena
总数与并发峰值），三者叠加把长跑稳态压到 50MB 以内。
"""
import ctypes
import gc
import os

_libc = None


def rss_mb():
    """当前进程常驻内存（MB）；非 Linux 环境返回 None。"""
    try:
        with open("/proc/self/statm", encoding="utf-8") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except (OSError, ValueError, IndexError):
        return None


def trim():
    """回收一次：gc + malloc_trim，返回回收后的 RSS（MB）。"""
    gc.collect()
    global _libc
    try:
        if _libc is None:
            _libc = ctypes.CDLL("libc.so.6")
        _libc.malloc_trim(0)
    except (OSError, AttributeError):
        pass               # 非 glibc 平台（如 musl）静默降级，仅靠 gc.collect
    return rss_mb()
