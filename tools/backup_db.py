#!/usr/bin/env python3
"""在线备份 hub.db（SQLite backup API，服务运行中/WAL 模式下也安全）。

用法：
    python tools/backup_db.py [备份目录] [--keep N]

默认备份到项目根下 backups/，保留最近 14 份。备份文件名带时间戳，
另存一份 latest 副本，方便异地同步脚本（rsync/rclone）直接取。
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import db  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = 14
    if "--keep" in sys.argv:
        keep = int(sys.argv[sys.argv.index("--keep") + 1])

    base = Path(__file__).resolve().parent.parent
    target_dir = Path(args[0]) if args else base / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target_dir / ("hub-%s.db" % stamp)

    src = sqlite3.connect(str(db.DB_PATH))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    latest = target_dir / "hub-latest.db"
    latest.write_bytes(target.read_bytes())

    old = sorted(target_dir.glob("hub-2*.db"))[:-keep]
    for f in old:
        f.unlink()

    print("备份完成：%s（%d KB，保留 %d 份）" % (target, target.stat().st_size // 1024, keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
