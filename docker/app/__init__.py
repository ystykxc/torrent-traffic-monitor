"""下载器流量统计（Torrent Traffic Monitor）。

单容器 + 一个 SQLite 文件 + 零外部依赖前端的多下载器流量监控。
项目版本固定为 v50；离线镜像 tag 恒为 torrent-traffic-monitor:1.0.0，
不随项目版本变化（详见 README「镜像文件命名规则」）。
"""

__version__ = "50"
VERSION = "v50"
APP_NAME = "下载器流量统计"
