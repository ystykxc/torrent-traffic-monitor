"""下载器流量统计 —— MoviePilot V3 本地安装插件（v1.0.32）。

由独立部署的 Docker 版 Torrent Traffic Monitor v50 迁移而来：
- 去掉账户 / 会话 / 登录 / 密码加密 / 限流 / SSRF / CSP / 审计 / SSE / PWA。
  认证与边界安全全部交由 MoviePilot 宿主负责。
- 下载器不再手工增删改：直接读取 MoviePilot 已接入的下载器配置
  （地址、账号、密码等），由插件自主轮询采集数据。
- 所有设置统一迁移到 MoviePilot 原生配置面板（get_form），控件全部使用
  Vuetify 原生组件、单页平铺、无提示信息；下载器设置仅保留「启用停用」
  开关，曲线颜色由系统自动分配，并提供「一键重新分配颜色」按钮。
- v1.0.2 删除实时速率卡片、实时速率采样设置与全部相关代码，采集精简为
  单线程流量统计；下载器卡片恢复独立汇总卡片 + 自适应网格样式。
- v1.0.3 把采集拆成两条节奏：流量统计按配置页「采样间隔」（默认 1 分钟）
  记账，下载器实时速率 / 在线状态按固定 5 秒刷新内存态（不外显设置）；
  汇总卡片右上角改为在线情况；手机端纵坐标固定 5 档刻度。
- v1.0.4 修复单台下载器卡片右上角开关失效（图表改按每台开关显隐）；桌面
  绘图区在填满视口基础上再调低两个下载器小卡高度；设置页重排为五行结构
  （下载器开关一行三个、手机端顺序单列）；手机端除绘图区外整体再收紧、
  一页放下、底部留白一个下载器小卡高度。
- v1.0.5 首次安装默认开启定期通知（每天 22:40，默认通知今日 / 昨日 / 本周 /
  本月四个范围）；通知正文改为「下载器 / 上传 / 下载」三列纯文本表格。
- v1.0.6 通知表格改用 ASCII 边框（+ - |）画线，不再依赖制表符；上传 / 下载
  数值前的 emoji 换成主体色完全不同的 🔴 / 🟢，便于一眼区分。
- v1.0.32 修复「合计」在微信里仍比表头「下载器」偏左的问题：微信把表头居中、
  数据行左对齐，实测偏左约 2 个 NBSP 宽，故合计行首列在居中基础上再右偏 2 格，
  视觉上与表头对齐；其余格式与功能一律不变。
- v1.0.31 修复 v1.0.30 的「合计」居中在微信里失效的问题：居中填充空格改用不换行
  空格 NBSP（U+00A0）。微信把通知渲染成 Markdown 表格会 trim 单元格首尾的普通空格，
  NBSP 不被 trim，故「合计」在微信里才真正居中；其余格式与功能一律不变。
- v1.0.30 在 v1.0.29 基础上，通知表格「合计」行首列的「合计」二字改为居中对齐
  （数值列与其他行不变）；其余格式与功能一律不变。
- v1.0.29 在 v1.0.28 基础上删除标题正下方那根与标题等长的分隔横线（标题后直接
  是无表头明细表）；段间 24 格横线、无表头、🟢↑/🔴↓ 等其他排版一律不变。
- v1.0.28 以 v1.0.6 带边框表格为基础按反馈调整通知正文（其余一律不变）：
  ① 段间分隔横线由 12 格改为 24 格（与 v1.0.27 一致）；② 删除表头行及其上方
  空行，改为标题正下方一根与标题文本等长的分隔横线，明细表无表头；③ 红绿点
  换位——上传由 🔴 改 🟢 并紧跟文本箭头 ↑、下载由 🟢 改 🔴 并紧跟文本箭头 ↓。
- 定期通知所有勾选的时间范围汇总在一条消息里，各范围用分隔线区分。
- 前端页面固定浅色主题、背景透明以采用宿主底色，手机端紧凑一页展示。

作者：YST插件定制
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from starlette.responses import HTMLResponse

# ---- 宿主稳定 SDK（V3）；兼容回退到 V2 旧路径 ----
try:
    from app.sdk.plugin import _PluginBase
except ImportError:  # pragma: no cover
    from app.plugins import _PluginBase

try:
    from app.sdk.services import DownloaderHelper
except ImportError:  # pragma: no cover
    from app.helper.downloader import DownloaderHelper

try:
    from app.sdk.config import settings
except ImportError:  # pragma: no cover
    from app.core.config import settings

from .core import chart, constants, db, log, notify, stats, timeutil
from .core.clients import IO_BAD, IO_WARN, TORRENT_KEYS
from .core.collector import Collector

PLUGIN_ID = "TorrentTrafficMonitor"


class TorrentTrafficMonitor(_PluginBase):
    """下载器流量统计插件主类。"""

    # ---- 插件元信息 ----
    plugin_name = "下载器流量统计"
    plugin_desc = "统计 MoviePilot 已接入下载器的上传/下载流量，支持定期通知"
    plugin_icon = "mdi-chart-line-variant"
    plugin_version = "1.0.32"
    plugin_author = "YST插件定制"
    author_url = ""
    plugin_config_prefix = "torrenttrafficmonitor_"
    plugin_order = 50
    auth_level = 1

    _enabled = True
    _collector: Optional[Collector] = None
    _lock = threading.Lock()
    _detail_cache: Dict[int, Tuple[float, dict]] = {}
    _detail_lock = threading.Lock()
    DETAIL_TTL = 3.0

    # ------------------------------------------------------------------ 生命周期
    def __init__(self) -> None:
        super().__init__()
        self._enabled = True

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """读取配置、初始化数据库、注入下载器来源并启动采集线程。"""
        config = config or {}
        data_dir = self.get_data_path()
        db.configure(str(data_dir))
        db.init_db()

        # 时区：优先使用插件配置，默认东八区（与独立版一致）
        try:
            tz = int(config.get("tz_offset", db.get_setting("tz_offset") or constants.DEFAULT_TZ_OFFSET))
        except (TypeError, ValueError):
            tz = constants.DEFAULT_TZ_OFFSET
        timeutil.configure(tz)

        # 下载器来源：每次采集/查询都从 MoviePilot 已接入的下载器实时读取
        db.set_provider(self._mp_downloaders)
        try:
            db.sync_downloaders(force=True)
        except Exception as exc:
            log.warn("sync downloaders failed", error=str(exc)[:200])

        # 插件表单配置（启用 / 通知）与前端设置页共用同一份 db.app_settings
        if config:
            self._apply_form_config(config)
        self._enabled = bool(self._notify_cfg().get("plugin_enabled", True))

        self._start_collector()

    def _apply_form_config(self, config: dict) -> None:
        """把 MoviePilot 原生配置面板保存的值落到本地 db（唯一一处设置来源）。

        覆盖三块：插件启用 + 通知参数、「采样间隔」（流量统计记账间隔）、
        每台下载器启用停用。曲线颜色由系统自动分配，不再从表单读取。
        """
        # ---- 1) 插件启用 + 通知参数 ----
        cfg = dict(self._notify_cfg())
        if "enabled" in config:
            cfg["plugin_enabled"] = bool(config.get("enabled"))
        if "notify_enabled" in config:
            cfg["enabled"] = bool(config.get("notify_enabled"))
        if "notify_cron" in config:
            try:
                cfg["cron"] = notify.validate_cron(config.get("notify_cron"))
            except ValueError:
                pass
        if "notify_ranges" in config:
            ranges = notify.normalize_ranges(config.get("notify_ranges"))
            if ranges:
                cfg["ranges"] = ranges
        db.set_setting("notify_config", json.dumps(cfg, ensure_ascii=False))

        # ---- 2) 「采样间隔」（流量统计记账间隔） ----
        if "traffic_interval" in config:
            try:
                ti = int(float(config.get("traffic_interval")))
                if ti in constants.TRAFFIC_POLL_CHOICES:
                    db.set_setting("traffic_interval", ti)
            except (TypeError, ValueError):
                pass
            if self._collector:
                try:
                    self._collector.set_traffic_interval(self._runtime()["traffic_interval"])
                except Exception:
                    pass

        # ---- 3) 下载器启用停用（get_form 里按下载器 id 动态生成的字段） ----
        for key, value in config.items():
            m = re.match(r"^dl_(\d+)_enabled$", str(key))
            if not m:
                continue
            did = int(m.group(1))
            try:
                db.update_downloader_config(did, {"enabled": value})
            except Exception as exc:
                log.warn("apply downloader config failed", did=did, error=str(exc)[:120])

    def _start_collector(self) -> None:
        with self._lock:
            if self._collector is not None:
                try:
                    self._collector.stop()
                except Exception:
                    pass
                self._collector = None
            if not self._enabled:
                return
            cfg = {
                "traffic_interval": self._runtime()["traffic_interval"],
                # 实时速率 / 在线状态固定 5 秒刷新，不外显到配置页
                "rate_interval": constants.RATE_POLL_INTERVAL,
                "request_timeout": constants.DEFAULT_REQUEST_TIMEOUT,
                "sample_retention_days": constants.DEFAULT_SAMPLE_RETENTION_DAYS,
            }
            c = Collector(cfg)
            c.start()
            self._collector = c
            log.info("collector started", traffic=cfg["traffic_interval"],
                     rate=cfg["rate_interval"])

    def get_state(self) -> bool:
        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def stop_service(self) -> None:
        with self._lock:
            if self._collector is not None:
                try:
                    self._collector.stop()
                except Exception:
                    pass
                self._collector = None
        log.info("collector stopped")

    def close(self) -> None:
        self.stop_service()

    # ------------------------------------------------------------------ 配置
    def _runtime(self) -> Dict[str, Any]:
        """图表 / 采集所需的运行参数（优先级：数据库 > 默认档位）。"""
        def _num(key, default):
            try:
                return float(db.get_setting(key) or default)
            except (TypeError, ValueError):
                return float(default)
        ti = _num("traffic_interval", constants.DEFAULT_TRAFFIC_POLL)
        if int(ti) not in constants.TRAFFIC_POLL_CHOICES:
            ti = constants.DEFAULT_TRAFFIC_POLL
        return {"traffic_interval": int(ti), "tz_offset": timeutil.TZ_OFFSET}

    def _notify_cfg(self) -> Dict[str, Any]:
        cfg = dict(constants.DEFAULT_NOTIFY)
        cfg["plugin_enabled"] = True
        raw = db.get_setting("notify_config")
        if raw:
            try:
                saved = json.loads(raw)
                if isinstance(saved, dict):
                    cfg.update(saved)
            except (TypeError, ValueError):
                pass
        cfg["ranges"] = notify.normalize_ranges(cfg.get("ranges")) or list(constants.DEFAULT_NOTIFY["ranges"])
        return cfg

    def _save_notify_cfg(self, payload: dict) -> Dict[str, Any]:
        cfg = self._notify_cfg()
        if "enabled" in payload:
            cfg["enabled"] = bool(payload.get("enabled"))
        if "plugin_enabled" in payload:
            cfg["plugin_enabled"] = bool(payload.get("plugin_enabled"))
            self._enabled = bool(cfg["plugin_enabled"])
        if "cron" in payload:
            cfg["cron"] = notify.validate_cron(payload.get("cron"))
        if "ranges" in payload:
            ranges = notify.normalize_ranges(payload.get("ranges"))
            if not ranges:
                raise ValueError("请至少选择一个通知时间范围")
            cfg["ranges"] = ranges
        db.set_setting("notify_config", json.dumps(cfg, ensure_ascii=False))
        return cfg

    def _api_token(self) -> str:
        token = getattr(settings, "API_TOKEN", None)
        if not token:
            try:
                from app.runtime.settings import get_runtime_setting
                token = get_runtime_setting("API_TOKEN")
            except Exception:
                token = None
        return str(token or "")

    # ------------------------------------------------------------------ 下载器来源
    @staticmethod
    def _build_url(raw: dict, dtype: str) -> str:
        """把 MoviePilot 下载器 config 里的连接信息拼成 WebUI / RPC 地址。"""
        raw = raw or {}
        full = str(raw.get("url") or raw.get("base_url") or "").strip()
        base = ""
        if full.startswith("http://") or full.startswith("https://"):
            base = full
        else:
            host = str(raw.get("host") or raw.get("hostname") or raw.get("address") or "").strip()
            if host.startswith("http://") or host.startswith("https://"):
                base = host
            elif host:
                scheme = "https" if (raw.get("ssl") or raw.get("https") or raw.get("use_ssl")) else "http"
                base = "%s://%s" % (scheme, host)
            port = raw.get("port")
            if base and port and ":" not in base.rsplit("/", 1)[-1]:
                base = "%s:%s" % (base, port)
        if not base:
            return ""
        # qBittorrent 反代子路径；Transmission 的 /transmission/rpc 由客户端自动补
        path = str(raw.get("path") or raw.get("rpc_path") or "").strip()
        if full.startswith("/") and not path:
            path = full
        if path and dtype == "qb" and path not in ("/", ""):
            if not path.startswith("/"):
                path = "/" + path
            base = base.rstrip("/") + path
        return base.rstrip("/")

    def _mp_downloaders(self) -> List[dict]:
        """读取 MoviePilot 已接入的全部下载器配置（含停用的），供采集与展示。"""
        out: List[dict] = []
        try:
            confs = DownloaderHelper().get_configs(include_disabled=True) or {}
        except Exception as exc:
            log.warn("read moviepilot downloaders failed", error=str(exc)[:200])
            return out
        for name, conf in confs.items():
            try:
                raw = dict(getattr(conf, "config", None) or {})
                ctype = str(getattr(conf, "type", None) or "").lower()
                dtype = "tr" if ctype in ("tr", "transmission") else "qb"
                user = str(raw.get("username") or raw.get("user") or raw.get("rpc_username") or "")
                pwd = str(raw.get("password") or raw.get("passwd") or raw.get("rpc_password") or "")
                url = self._build_url(raw, dtype)
                pm = getattr(conf, "path_mapping", None) or []
                try:
                    pm = [list(x) for x in pm]
                except TypeError:
                    pm = []
                info = {
                    "名称": name,
                    "类型": ctype,
                    "宿主启用": bool(getattr(conf, "enabled", False)),
                    "默认下载器": bool(getattr(conf, "default", False)),
                    "地址": url,
                    "用户名": user,
                    "密码": pwd,
                    "SSL": bool(raw.get("ssl") or raw.get("https")),
                    "原始配置": raw,
                    "路径映射": pm,
                }
                out.append({
                    "dkey": str(name),
                    "name": str(name),
                    "type": dtype,
                    "url": url,
                    "username": user,
                    "password": pwd,
                    "mp_enabled": bool(getattr(conf, "enabled", False)),
                    "default": bool(getattr(conf, "default", False)),
                    "info": info,
                })
            except Exception as exc:
                log.warn("parse downloader failed", name=str(name), error=str(exc)[:120])
        return out

    # ------------------------------------------------------------------ 表单 / 页面
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """MoviePilot 原生配置面板（唯一设置入口）：全部控件平铺在一页。

        v1.0.2：去掉 VTabs / VWindow 分页与所有 VAlert / hint 提示信息；
        实时速率采样设置随实时速率卡片一并删除；下载器区仅保留「启用停用」
        开关，曲线颜色由系统自动分配。
        v1.0.3：「流量统计采样间隔」更名为「采样间隔」（默认 1 分钟）；
        下载器区新增「一键重新分配下载器颜色」按钮。V3 配置页由前端
        FormRender 渲染，只认 props 里以 on 开头、值为函数代码的事件字段，
        因此按钮用 VBtn + onClick 字符串函数直接 fetch 插件自身 /data 端点。
        v1.0.4：按需求把设置页重排为固定五行 —— ①插件启用 + 采样间隔、
        ②定时通知开关 + 通知时间、③通知范围多选、④一键分配颜色按钮、
        ⑤下载器启用开关（桌面一行三个、手机端按同顺序单列）。VCol 统一
        cols=12（手机占满一行）+ md（桌面并排 / 每行三个）。
        v1.0.5：首次安装默认开启通知（cron `40 22 * * *`，范围今日 / 昨日 /
        本周 / 本月），表单初始值直接取 constants.DEFAULT_NOTIFY。
        """
        cfg = self._notify_cfg()
        rt = self._runtime()

        def opts(choices, labels):
            return [{"title": labels[v], "value": v} for v in choices]

        traffic_items = opts(constants.TRAFFIC_POLL_CHOICES, constants.TRAFFIC_POLL_LABELS)
        range_items = [{"title": x["label"], "value": x["value"]}
                       for x in constants.TRAFFIC_RANGES]

        # v1.0.4 需求3：设置页按固定「五行」顺序排布（手机端保持同一顺序、
        # 每个控件占满一行）。VCol 用 cols=12（手机占满一行）+ md（桌面并排）：
        #  · 第 1 行：插件启用开关 + 采样间隔（md=6 各半）
        #  · 第 2 行：启用定时流量通知开关 + 通知时间（md=6 各半）
        #  · 第 3 行：需要通知的流量统计时间范围多选（占满一行）
        #  · 第 4 行：一键分配下载器颜色按钮（占满一行）
        #  · 第 5 行起：按顺序放下载器启用开关，桌面一行三个（md=4），
        #    手机端 cols=12 自然每个占一行、顺序不变。
        content: List[dict] = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSwitch", "props": {
                        "model": "enabled", "label": "启用插件（启动后台采集）",
                        "color": "primary"}},
                ]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSelect", "props": {
                        "model": "traffic_interval", "label": "采样间隔",
                        "items": traffic_items, "itemTitle": "title",
                        "itemValue": "value", "density": "compact"}},
                ]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSwitch", "props": {
                        "model": "notify_enabled", "label": "启用定时流量通知",
                        "color": "primary"}},
                ]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VTextField", "props": {
                        "model": "notify_cron", "label": "通知时间（五位 cron）",
                        "density": "compact"}},
                ]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [
                    {"component": "VSelect", "props": {
                        "model": "notify_ranges",
                        "label": "需要通知的流量统计时间范围（可多选）",
                        "multiple": True, "chips": True, "closableChips": True,
                        "items": range_items, "itemTitle": "title",
                        "itemValue": "value", "density": "compact"}},
                ]},
            ]},
        ]

        # ---- 第 4 行：一键分配下载器颜色按钮 ----
        # V3 配置页由前端 FormRender 渲染，只认 props 里以 on 开头、值为
        # 「函数代码字符串」的字段（内部用 new Function 在浏览器里执行），
        # 不支持 events / api 字段。因此按钮用 onClick 直接 fetch 插件端点。
        recolor_url = "/api/v1/plugin/%s/data?action=downloaders/recolor&apikey=%s" % (
            self.__class__.__name__, quote(self._api_token(), safe=""))
        recolor_js = (
            "function(){"
            "fetch(" + json.dumps(recolor_url) + ",{credentials:'same-origin'})"
            ".then(function(r){return r.json();})"
            ".then(function(j){"
            "if(j&&j.ok===false){window.alert('重新分配失败，请重试');return;}"
            "window.alert('下载器颜色已重新分配，重新打开数据页即可生效');})"
            "['catch'](function(){window.alert('重新分配失败，请重试');});"
            "}"
        )
        content.append({"component": "VRow", "content": [
            {"component": "VCol", "props": {"cols": 12}, "content": [
                {"component": "VBtn", "props": {
                    "color": "primary", "variant": "tonal", "size": "small",
                    "prependIcon": "mdi-palette", "onClick": recolor_js},
                 "text": "一键重新分配下载器颜色"},
            ]},
        ]})

        # ---- 第 5 行起：下载器启用开关，桌面一行三个、手机端顺序单列 ----
        dl_model: Dict[str, Any] = {}
        try:
            rows = db.list_downloaders(public=True)
        except Exception as exc:
            log.warn("form downloaders read failed", error=str(exc)[:120])
            rows = []
        dl_cols: List[dict] = []
        for d in rows:
            did = int(d["id"])
            k_en = "dl_%d_enabled" % did
            dl_model[k_en] = bool(d["enabled"])
            label = "%s · %s%s" % (
                d["name"],
                "qBittorrent" if d["type"] == "qb" else "Transmission",
                "（宿主已移除）" if d.get("missing") else "",
            )
            dl_cols.append({"component": "VCol", "props": {"cols": 12, "md": 4},
                            "content": [
                {"component": "VSwitch", "props": {
                    "model": k_en, "label": label, "color": "primary"}},
            ]})
        if dl_cols:
            # 所有下载器开关放进同一个 VRow：Vuetify 会按 md=4 自动换成
            # 桌面「每行三个」，手机端 cols=12 则每个占满一行、顺序不变。
            content.append({"component": "VRow", "content": dl_cols})

        page = [{"component": "VForm", "content": content}]
        model = {
            "enabled": bool(cfg.get("plugin_enabled", True)),
            "notify_enabled": bool(cfg.get("enabled", constants.DEFAULT_NOTIFY["enabled"])),
            "notify_cron": str(cfg.get("cron") or constants.DEFAULT_NOTIFY["cron"]),
            "notify_ranges": list(cfg.get("ranges") or constants.DEFAULT_NOTIFY["ranges"]),
            "traffic_interval": rt["traffic_interval"],
        }
        model.update(dl_model)
        return page, model

    def get_page(self) -> List[dict]:
        """插件详情页：用 iframe 嵌入原项目的完整监控页面。"""
        pid = self.__class__.__name__
        src = "/api/v1/plugin/%s/page?apikey=%s" % (pid, quote(self._api_token(), safe=""))
        return [{
            "component": "iframe",
            "props": {
                "src": src,
                "style": "width:100%;height:calc(100vh - 120px);min-height:0;border:0;display:block;",
                "frameborder": "0",
                "title": "下载器流量统计",
            },
        }]

    def get_service(self) -> Optional[List[Dict[str, Any]]]:
        """注册定期通知服务（五位 cron 来自插件配置）。"""
        cfg = self._notify_cfg()
        if not self.get_state() or not cfg.get("enabled"):
            return []
        try:
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger.from_crontab(
                str(cfg.get("cron") or constants.DEFAULT_NOTIFY["cron"]))
        except Exception as exc:
            log.warn("invalid notify cron, fallback daily", error=str(exc)[:120])
            try:
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(constants.DEFAULT_NOTIFY["cron"])
            except Exception:
                return []
        return [{
            "id": "%s.Notify" % self.__class__.__name__,
            "name": "下载器流量统计 · 定期通知",
            "trigger": trigger,
            "func": self._send_notify,
            "kwargs": {},
        }]

    # ------------------------------------------------------------------ 通知
    def _send_notify(self) -> None:
        cfg = self._notify_cfg()
        if not cfg.get("enabled"):
            return
        ranges = notify.normalize_ranges(cfg.get("ranges"))
        if not ranges:
            return
        runtime = self._runtime()
        for title, text in notify.build_messages(ranges, runtime):
            try:
                self.post_message(title=title, text=text)
            except Exception as exc:
                log.warn("notify send failed", error=str(exc)[:200])
        log.info("notify sent", ranges=",".join(ranges))

    # ------------------------------------------------------------------ 插件 API
    def get_api(self) -> List[Dict[str, Any]]:
        # 所有前端请求统一走 /data 分发，避免依赖路径参数 / 请求体注入等运行时差异。
        # 原生 HTML / 业务 dict 响应显式关闭宿主默认 response_model，避免被统一封装。
        return [
            {"path": "/page", "endpoint": self.page, "methods": ["GET"],
             "auth": "apikey", "summary": "监控页面", "description": "返回插件前端页面（内联 CSS/JS）",
             "response_model": None, "response_class": HTMLResponse},
            {"path": "/data", "endpoint": self.data, "methods": ["GET"],
             "auth": "apikey", "summary": "数据接口", "description": "按 action 分发所有监控数据请求",
             "response_model": None},
        ]

    def page(self) -> HTMLResponse:
        """返回自包含的监控页面：把 CSS / JS 内联进 HTML，不依赖宿主静态资源路由。"""
        pid = self.__class__.__name__
        static = Path(__file__).parent / "static"
        html = (static / "index.html").read_text(encoding="utf-8")
        css = (static / "style.css").read_text(encoding="utf-8")
        charts = (static / "charts.js").read_text(encoding="utf-8")
        app_js = (static / "app.js").read_text(encoding="utf-8")
        cfg = "window.TTM_CFG=%s;" % json.dumps({
            "base": "/api/v1/plugin/%s/data" % pid,
            "apikey": self._api_token(),
        }, ensure_ascii=False)
        # 内联脚本里出现 </script 会提前闭合标签，替换成等价的转义写法
        charts = charts.replace("</script", "<\\/script")
        app_js = app_js.replace("</script", "<\\/script")
        html = (html
                .replace("/*__TTM_CFG__*/", cfg)
                .replace("/*__TTM_CSS__*/", css)
                .replace("/*__TTM_CHARTS_JS__*/", charts)
                .replace("/*__TTM_APP_JS__*/", app_js))
        return HTMLResponse(content=html, status_code=200, media_type="text/html")

    def data(self, action: str = "", args: str = "{}") -> dict:
        """统一数据分发端点。前端把原 /api/xxx 的请求转换成 action + args。"""
        try:
            params = json.loads(args) if args else {}
            if not isinstance(params, dict):
                params = {}
        except (TypeError, ValueError):
            params = {}
        a = (action or "").strip().strip("/")
        try:
            return self._dispatch(a, params)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # 保证单个接口异常不影响插件整体
            log.warn("api action failed", action=a, error=str(exc)[:200])
            return {"ok": False, "error": str(exc)[:200]}

    # ------------------------------------------------------------------ 分发实现
    def _dispatch(self, a: str, p: dict) -> dict:
        method = str(p.pop("_method", "GET")).upper()
        rt = self._runtime()

        if a == "health":
            return {"ok": True}

        if a == "settings":
            if method == "POST":
                ti = int(float(p.get("traffic_interval", rt["traffic_interval"])))
                if ti not in constants.TRAFFIC_POLL_CHOICES:
                    raise ValueError("采样间隔只能是 5 秒 / 10 秒 / 30 秒 / 1 / 5 / 10 / 30 分钟")
                db.set_setting("traffic_interval", ti)
                if self._collector:
                    self._collector.set_traffic_interval(ti)
                return {"ok": True, "traffic_interval": ti}
            return {
                "traffic_interval": rt["traffic_interval"],
                "traffic_interval_options": [{"value": v, "label": constants.TRAFFIC_POLL_LABELS[v]}
                                             for v in constants.TRAFFIC_POLL_CHOICES],
                "tz_offset": timeutil.TZ_OFFSET,
                "granularities": list(timeutil.GRANULARITIES),
                "ranges": list(chart.ALL_RANGES),
                "palette": [list(x) for x in constants.PALETTE],
                "summary_colors": {"up": constants.SUMMARY_UP, "down": constants.SUMMARY_DOWN},
                "traffic_ranges": list(constants.TRAFFIC_RANGES),
                "notify": self._notify_cfg(),
            }

        if a == "overview":
            return self._overview(rt)

        if a == "periods":
            return {"ok": True, "periods": stats.period_series(),
                    "counts": dict(stats.PERIOD_COUNTS), "server_time": time.time()}

        if a == "periods/page":
            unit = str(p.get("unit", ""))
            start = max(0, int(p.get("start", 0)))
            count = max(1, min(50, int(p.get("count", 10))))
            return {"ok": True, "unit": unit, "start": start, "count": count,
                    "items": stats.period_page(unit, start, count), "server_time": time.time()}

        if a == "chart":
            # 实时速率曲线已删除，图表只提供流量统计（metric 恒为 traffic）
            return {"ok": True, **chart.build(
                str(p.get("range", "24h")), "traffic",
                live_span=constants.CHART_LIVE_SPAN,
                poll_interval=constants.CHART_POLL_INTERVAL,
                traffic_interval=rt["traffic_interval"], offset=p.get("offset", 0))}

        if a == "stats":
            gran = str(p.get("granularity", "day"))
            now = time.time()
            ds, de = timeutil.range_for(gran, now)
            start = float(p.get("start") or ds)
            end = float(p.get("end") or de)
            did = p.get("downloader_id", "")
            return {"ok": True, **stats.query_stats(gran, start, end, int(did) if did else None)}

        if a == "downloaders":
            return {"ok": True, "items": db.list_downloaders(public=True)}

        if a == "downloaders/config":
            did = int(p.get("id") or p.get("did") or 0)
            item = db.update_downloader_config(did, p)
            if not item:
                raise ValueError("下载器不存在")
            if self._collector:
                self._collector.invalidate(did)
            return {"ok": True, "id": did}

        if a == "downloaders/recolor":
            return {"ok": True, **db.recolor_all(p.get("shift"))}

        if a == "downloaders/reorder":
            # 排序功能已精简：宿主下载器顺序由 MoviePilot 管理，本地保持现状
            return {"ok": True, "ids": p.get("ids", [])}

        if a == "downloaders/test":
            raise ValueError("连接测试已精简，请在 MoviePilot 下载器设置中检查")

        if a == "downloaders/detail":
            did = int(p.get("did") or 0)
            d = db.get_downloader(did)
            if not d:
                raise ValueError("下载器不存在")
            now = time.time()
            with self._detail_lock:
                hit = self._detail_cache.get(did)
                if hit and now - hit[0] < self.DETAIL_TTL:
                    return {"ok": True, **hit[1]}
            if not self._collector:
                raise ValueError("采集器未启动")
            data = self._collector.detail(d)
            with self._detail_lock:
                if len(self._detail_cache) >= 32:
                    self._detail_cache.clear()
                self._detail_cache[did] = (now, data)
            return {"ok": True, **data}

        if a == "downloaders/summary":
            return self._summary_detail()

        if a == "notify/config":
            if method == "POST":
                return {"ok": True, "notify": self._save_notify_cfg(p)}
            return {"ok": True, "notify": self._notify_cfg(),
                    "traffic_ranges": list(constants.TRAFFIC_RANGES)}

        if a == "notify/test":
            cfg = self._notify_cfg()
            ranges = notify.normalize_ranges(p.get("ranges") or cfg.get("ranges"))
            if not ranges:
                raise ValueError("请至少选择一个通知时间范围")
            # v1.0.1：所有时间范围汇总成一条通知，只发送一次
            sent = 0
            for title, text in notify.build_messages(ranges, self._runtime()):
                self.post_message(title=title, text=text)
                sent += 1
            return {"ok": True, "sent": sent, "ranges": ranges}

        if a == "notify/preview":
            ranges = notify.normalize_ranges(p.get("ranges") or self._notify_cfg().get("ranges"))
            return {"ok": True, "messages": [{"title": t, "text": x}
                                             for t, x in notify.build_messages(ranges, self._runtime())]}

        if a in ("auth/status", "auth/login", "auth/logout", "auth/setup", "auth/change"):
            # 账户功能已由 MoviePilot 宿主接管
            return {"ok": True, "authenticated": True, "must_change": False}

        return {"ok": False, "error": "未知操作：%s" % a}

    # ------------------------------------------------------------------ 数据组装
    def _overview(self, rt: dict) -> dict:
        states = db.get_states()
        totals = stats.period_totals()
        items = []
        for d in db.list_downloaders(public=True, enabled_only=True):
            st = states.get(d["id"], {})
            t = totals.get(d["id"], {})
            extra = {}
            if st.get("extra"):
                try:
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

        c = self._collector
        return {
            "server_time": time.time(),
            "tz_offset": timeutil.TZ_OFFSET,
            "collector": {
                "interval": rt["traffic_interval"],
                "rate_interval": c.rate_interval if c else constants.RATE_POLL_INTERVAL,
                "traffic_ticks": c.traffic_ticks if c else 0,
                "ticks": c.ticks if c else 0,
                "last_tick": c.last_tick if c else 0,
                "last_error": c.last_error if c else None,
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
        }

    def _summary_detail(self) -> dict:
        ds = db.list_downloaders(enabled_only=True)
        states = db.get_states()
        if not self._collector:
            return {"ok": True, "total": {"up_rate": 0, "dl_rate": 0, "online": 0,
                                          "count": 0, "offline": 0},
                    "aggregate": {"torrents": {k: 0 for k in TORRENT_KEYS}},
                    "items": [], "io_warn": IO_WARN, "io_bad": IO_BAD}
        results = self._collector.detail_many(ds)
        agg = {k: 0 for k in TORRENT_KEYS}
        items = []
        up_rate = dl_rate = online = 0
        for d, data, err in results:
            st = states.get(d["id"], {})
            is_online = st.get("status") == "online"
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
        return {
            "ok": True,
            "total": {"up_rate": up_rate, "dl_rate": dl_rate,
                      "online": online, "count": len(ds), "offline": len(ds) - online},
            "aggregate": {"torrents": agg},
            "items": items,
            "io_warn": IO_WARN, "io_bad": IO_BAD,
        }
