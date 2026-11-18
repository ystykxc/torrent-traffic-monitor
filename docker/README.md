# 独立 Docker 版 · v50

单容器部署的下载器流量监控，适用于 x86 架构的飞牛 NAS 或其他 Linux 主机。自带账户登录、深浅双主题、手机端自适应与安卓 PWA。

> 插件版请见 [../moviepilot/README.md](../moviepilot/README.md)。

## 快速开始

**在线部署**（需能拉取 `python:3.11-slim`）：

```bash
docker compose up -d --build
```

**离线部署**（飞牛默认加速源报 401 时使用）：

```bash
docker load -i torrent-traffic-monitor-image-amd64-v48.tar
docker compose -f docker-compose.offline.yml up -d
```

> 离线镜像体积约 130 MB，超过 GitHub 单文件 100 MB 限制，故未随仓库入库。可用 `docker build -t torrent-traffic-monitor:1.0.0 .` 构建后执行 `docker save -o torrent-traffic-monitor-image-amd64-v48.tar torrent-traffic-monitor:1.0.0` 自行导出；历史交付包中也已附带。

两个 compose 的端口映射默认为 `"${WEB_PORT:-8080}:8080"`，即监听宿主机所有网卡，**局域网内其他主机可直接访问 `http://<NAS 内网 IP>:8080`**，无需反向代理。

如需改回仅本机访问，把 `ports` 改为：

```yaml
- "127.0.0.1:${WEB_PORT:-8080}:8080"
```

若只想放行单个内网 IP，使用 `- "<宿主机内网IP>:${WEB_PORT:-8080}:8080"` 并在宿主机防火墙放行该 IP。

## 首次使用

1. 浏览器打开 `http://<NAS 内网 IP>:8080`。
2. 用 `BOOTSTRAP_USERNAME` / `BOOTSTRAP_PASSWORD` 登录（建议部署前在 `.env` 中设置强凭据，参考 [.env.example](.env.example)）。
3. 在「设置 → 下载器配置」中接入 qBittorrent / Transmission 的地址、账号、密码，并测试连接。
4. 在「设置 → 采集参数」中设定采样间隔与保留天数。

## 配置参考

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `HTTP_PORT` | 容器内监听端口 | `8080` |
| `WEB_PORT` | 宿主机映射端口 | `8080` |
| `DATA_DIR` | SQLite 数据目录 | `/data` |
| `CONFIG_FILE` | 下载器配置文件路径 | `/app/config.json` |
| `BOOTSTRAP_USERNAME` | 首次启动管理员账号 | — |
| `BOOTSTRAP_PASSWORD` | 首次启动管理员密码 | — |
| `SECRET_KEY` | 会话签名密钥，务必自定义 | — |
| `TZ_OFFSET` | 时区偏移（小时） | `0` |

完整字段见 [config.example.json](config.example.json) 与 [.env.example](.env.example)。

## 目录说明

- `app/` — Flask + Waitress 后端，`static/` 为原生 JS/SVG 前端，`pwa/` 为 Service Worker 与 manifest，`tools/` 为演示与灌数据脚本。
- 数据只写入一个 SQLite 文件，备份时拷贝该文件即可。

## 更多资料

- [简要版图文介绍与部署](../docs/下载器流量统计-简要版介绍与部署.docx)
- [详细版图文介绍与部署](../docs/下载器流量统计-详细版介绍与部署.docx)
- [流量统计口径深度解析](../docs/流量统计口径深度解析.md)
- [安全加固与重新部署指南](../docs/安全加固与重新部署指南.md)
- [完整版本历史](../CHANGELOG.md)
