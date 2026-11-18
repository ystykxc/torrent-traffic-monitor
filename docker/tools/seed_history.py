#!/usr/bin/env python3
"""【仅用于演示/自测】给测试库灌入历史小时数据，用来查看日/周/月/年图表。

⚠️ 不要对生产库运行！它会往 hourly 表追加数据且不可撤销。
运行前必须显式传 --yes，并用 DATA_DIR 指向一个独立的测试目录。

示例：
  DATA_DIR=/tmp/ttm-demo python3 tools/seed_history.py --yes
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, timeutil  # noqa: E402


def main():
    if "--yes" not in sys.argv:
        print("这是演示数据生成工具，会污染数据库。确认后请加 --yes 重新运行。")
        return
    data_dir = os.environ.get("DATA_DIR", "/tmp/ttm-demo")
    timeutil.configure(int(os.environ.get("TZ_OFFSET", "8")))
    db.configure(data_dir)
    db.init_db()

    # 保证有 5 个下载器
    if not db.list_downloaders():
        for i in range(5):
            db.save_downloader({
                "name": f"DEMO-{i+1}", "type": "qb" if i < 3 else "tr",
                "url": f"http://127.0.0.1:{18081 + i}", "enabled": True,
            })
    ids = [d["id"] for d in db.list_downloaders()]

    now = time.time()
    start = timeutil.floor_hour(now) - 400 * 86400
    rows = 0
    with db.conn() as c:
        for h in range(start, timeutil.floor_hour(now) + 3600, 3600):
            meta = timeutil.hour_meta(h)
            for did in ids:
                dl = 1_000_000 + (did * 100_000)
                up = 500_000 + (did * 50_000)
                c.execute(
                    "INSERT INTO hourly (downloader_id,hour_ts,day,week,month,year,dl_bytes,up_bytes,samples) "
                    "VALUES (?,?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(downloader_id,hour_ts) DO UPDATE SET "
                    "dl_bytes=dl_bytes+excluded.dl_bytes,up_bytes=up_bytes+excluded.up_bytes",
                    (did, h, meta["day"], meta["week"], meta["month"], meta["year"], dl, up),
                )
                rows += 1
        # 灌入最近 24 小时的「流量统计采样点」（每 60 秒一个），
        # 供流量统计卡片的 1 / 6 / 12 小时短窗口展示（新口径只读
        # traffic_samples，不再读 samples 的 inc）。
        t0 = now - 86400
        n_ts = 0
        while t0 < now:
            for did2 in ids:
                c.execute(
                    "INSERT INTO traffic_samples (downloader_id,ts,dl_inc,up_inc) "
                    "VALUES (?,?,?,?)", (did2, t0, 60_000_000, 30_000_000))
                n_ts += 1
            t0 += 60
    print(f"已写入 {rows} 条小时记录 + {n_ts} 条流量统计采样点到 "
          f"{data_dir}/traffic.db（仅供演示）")


if __name__ == "__main__":
    main()
