#!/usr/bin/env python3
"""社区站点静态生成器：SQLite → site/（GitHub Pages 直接发布）。

产出：
    site/index.html / app.js / style.css   来自 site-template/ 的静态壳
    site/catalog.json                      目录数据（检索站点唯一数据源）
    site/changelog.json                    最近事件
同时把事件写成仓库根 CHANGELOG.md（自动维护的一部分）。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from server import catalog, db

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "site-template"
SITE_DIR = BASE_DIR / "site"

KIND_LABEL = {
    "new": ("🆕 新增", "New"),
    "renamed": ("✏️ 更名", "Renamed"),
    "archived": ("📦 归档", "Archived"),
    "unarchived": ("♻️ 恢复", "Unarchived"),
    "vanished": ("👻 消失", "Vanished"),
}


def generate() -> int:
    db.init_db()
    SITE_DIR.mkdir(exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        src = TEMPLATE_DIR / name
        if src.exists():
            shutil.copyfile(src, SITE_DIR / name)

    data = catalog.build_catalog()
    SITE_DIR.joinpath("catalog.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    events = catalog.build_changelog(60)
    SITE_DIR.joinpath("changelog.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 仓库 CHANGELOG.md：最近事件的 markdown 记录
    lines = [
        "# 变更记录",
        "",
        "> 由 dsh-plug-hub 同步自动生成（GitHub Actions，每 4 小时）。",
        "",
        "_生成时间：%s_" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "",
        "| 时间 (UTC) | 事件 | 仓库 | 说明 |",
        "|---|---|---|---|",
    ]
    for event in events:
        label = KIND_LABEL.get(event["kind"], (event["kind"], event["kind"]))[0]
        when = datetime.fromtimestamp(event["detected_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        detail = (event["detail"] or "").replace("|", "/")
        lines.append("| %s | %s | `%s` | %s |" % (when, label, event["full_name"], detail))
    BASE_DIR.joinpath("CHANGELOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data["total"]


if __name__ == "__main__":
    print("站点已生成：%d 个已策展插件" % generate())
