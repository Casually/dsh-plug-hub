#!/usr/bin/env python3
"""独立同步入口（CI 与命令行用）：python sync.py [--generate-site]

不依赖 FastAPI 运行时，直接执行一次全量快照同步；可选顺带重新生成站点。
"""
from __future__ import annotations

import argparse
import json
import sys

from server import db, github_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="dsh-plug-hub 全量同步")
    parser.add_argument("--generate-site", action="store_true", help="同步后重新生成社区站点")
    parser.add_argument("--trigger", default="ci", help="运行来源标记（ci/manual）")
    args = parser.parse_args()

    db.init_db()
    result = github_sync.sync(args.trigger)
    print(json.dumps(result, ensure_ascii=False))
    if args.generate_site:
        import generate_site
        count = generate_site.generate()
        print("站点已生成：%d 个已策展插件" % count)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
