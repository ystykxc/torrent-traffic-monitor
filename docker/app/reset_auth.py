"""容器内重置认证：忘记账号密码时使用。

用法（飞牛 SSH 里执行，容器名按实际情况改）：
 docker exec -it torrent-traffic-monitor python -m app.reset_auth
 docker restart torrent-traffic-monitor

会清空 users / sessions，重启后由 auth.bootstrap 重建账号：配置了
BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD 时直接用它们重建强账号
（must_change=0，无需强制改密），否则回落默认 admin / admin 并强制改密。
流量数据完全不受影响。
"""
from . import config, db


def main():
    cfg = config.load()
    db.configure(cfg["data_dir"])
    db.init_db()
    db.reset_auth()
    print("[auth] 已清空账户与全部登录会话。重启容器后按 BOOTSTRAP_* "
          "重建强账号（未配置则回落默认 admin / admin 并要求强制改密）。", flush=True)


if __name__ == "__main__":
    main()
