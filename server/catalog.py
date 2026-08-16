"""目录生成：把「已策展 approved 插件 × 快照事实 × 活跃度信号」合成 catalog。

活跃度四级信号（依据仓库最近提交 pushed_at）：
    active   活跃   ≤ 30 天
    watch    关注   31 ~ 90 天
    slowing  放缓   91 ~ 180 天
    stalled  停更   > 180 天
归档仓库一律记为 stalled 并带 archived 标记。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from . import db

ACTIVITY_LEVELS = [
    {"level": "active", "label_zh": "活跃", "label_en": "Active", "max_days": 30},
    {"level": "watch", "label_zh": "关注", "label_en": "Watch", "max_days": 90},
    {"level": "slowing", "label_zh": "放缓", "label_en": "Slowing", "max_days": 180},
    {"level": "stalled", "label_zh": "停更", "label_en": "Stalled", "max_days": None},
]


def activity_of(pushed_at: str, archived: bool) -> dict:
    """由最近提交时间计算活跃度信号。"""
    if archived:
        level = ACTIVITY_LEVELS[3]
        return {**level, "days_since": None}
    days = None
    try:
        dt = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        days = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
    except (ValueError, TypeError):
        pass
    if days is None:
        return {**ACTIVITY_LEVELS[3], "days_since": None}
    for level in ACTIVITY_LEVELS:
        if level["max_days"] is None or days <= level["max_days"]:
            return {**level, "days_since": days}
    return {**ACTIVITY_LEVELS[3], "days_since": days}


def build_catalog(conn=None) -> dict:
    """生成对外目录（API 与站点共用同一形状）。"""
    own = conn is None
    if own:
        db.init_db()
        conn = db.connect()
    try:
        categories = {
            row["id"]: {"id": row["id"], "slug": row["slug"], "name_zh": row["name_zh"], "name_en": row["name_en"]}
            for row in conn.execute("SELECT * FROM categories ORDER BY sort")
        }
        repos = {row["repo_id"]: dict(row) for row in conn.execute("SELECT * FROM repos")}
        plugins = []
        rows = conn.execute(
            """SELECT p.*, c.slug AS category_slug, c.name_zh AS category_zh, c.name_en AS category_en
                FROM plugins p JOIN categories c ON c.id = p.category_id
                WHERE p.status = 'approved' ORDER BY c.sort, p.sort DESC, p.updated_at DESC"""
        )
        for row in rows:
            repo = repos.get(row["repo_id"]) if row["repo_id"] is not None else None
            pushed_at = repo["pushed_at"] if repo is not None else ""
            archived = bool(repo["archived"]) if repo is not None else False
            full_name = row["full_name"]
            entry = {
                "name": row["name"],
                "full_name": full_name,
                "url": repo["html_url"] if repo is not None else "https://github.com/" + full_name,
                "category": {
                    "slug": row["category_slug"],
                    "name_zh": row["category_zh"],
                    "name_en": row["category_en"],
                },
                "summary_zh": row["summary_zh"],
                "summary_en": row["summary_en"],
                "tags": json.loads(row["tags"] or "[]"),
                "install": {
                    "npm": row["npm_package"] or None,
                    "github": "github:" + full_name if full_name != "" else None,
                    "command": row["install_cmd"] or (
                        "dsh plugin --profile web add -w " + (row["npm_package"] or "github:" + full_name)
                        if full_name != "" or row["npm_package"] != "" else ""
                    ),
                },
                "stats": {
                    "stars": repo["stars"] if repo is not None else 0,
                    "forks": repo["forks"] if repo is not None else 0,
                    "license": repo["license"] if repo is not None else "",
                    "language": repo["language"] if repo is not None else "",
                    "pushed_at": pushed_at,
                },
                "activity": activity_of(pushed_at, archived),
                "archived": archived,
            }
            plugins.append(entry)
        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "dsh-plug-hub",
            "topic": "dsh-plugin",
            "total": len(plugins),
            "categories": [categories[k] for k in sorted(categories, key=lambda i: categories[i]["id"])],
            "activity_levels": [{k: v for k, v in lvl.items() if k != "max_days"} for lvl in ACTIVITY_LEVELS],
            "plugins": plugins,
        }
    finally:
        if own:
            conn.close()


def build_changelog(limit: int = 60) -> list[dict]:
    """最近事件（站点与仓库 CHANGELOG 共用）。"""
    db.init_db()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT kind, full_name, detail, detected_at FROM repo_events ORDER BY detected_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()
