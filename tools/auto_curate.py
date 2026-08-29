#!/usr/bin/env python3
"""一键批量策展：把快照内全部仓库收录并按启发式规则分类。

规则：按 仓库名 + 描述 + topics 的关键词匹配十一大类（首个命中生效，
规则按优先级排序）；中文描述归简介（中），英文描述归简介（英），
不虚构翻译。已有人工策展记录（plugins 表已有行）的仓库一律跳过。

用法：python tools/auto_curate.py [--dry-run]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import db  # noqa: E402

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# (slug, 关键词)：ASCII 词用 \b 词边界匹配，CJK 词用子串匹配。首个命中生效。
RULES = [
    ("distro", {
        "ascii": ["awesome", "collection", "curated", "plugin pack", "plugins pack",
                  "plugin list", "suite", "bundle", "marketplace"],
        "cjk": ["合集", "插件集", "发行版", "大全", "列表"],
    }),
    ("audio-voice", {
        "ascii": ["voice", "audio", "speech", "tts", "stt", "asr", "whisper",
                  "music", "sound", "sing"],
        "cjk": ["语音", "音频", "音乐", "朗读", "唱歌", "配音"],
    }),
    ("vision-multimodal", {
        "ascii": ["vision", "image", "ocr", "screenshot", "video", "camera",
                  "photo", "multimodal", "diagram", "chart", "draw"],
        "cjk": ["视觉", "图像", "截图", "识别", "生图", "绘图", "视频", "相机", "看图"],
    }),
    ("messaging", {
        "ascii": ["telegram", "discord", "slack", "wechat", "weixin", "qq bot",
                  "dingtalk", "feishu", "lark", "email", "mail", "whatsapp", "sms"],
        "cjk": ["微信", "钉钉", "飞书", "邮件", "消息推送", "聊天机器人", "通知"],
    }),
    ("theme-fun", {
        "ascii": ["theme", "skin", "mascot", "wallpaper", "anime", "game",
                  "gamemode", "pet", "whale", "emoji", "roleplay", "fun"],
        "cjk": ["主题", "皮肤", "看板娘", "壁纸", "二次元", "游戏", "娱乐",
                "角色扮演", "宠物", "美化", "萌"],
    }),
    ("coding", {
        "ascii": ["code review", "coding", "developer", "git ", "github", "ide",
                  "refactor", "lint", "debug", "terminal", "shell", "cli",
                  "compiler", "unittest", "vscode", "programming"],
        "cjk": ["代码", "编程", "开发", "调试", "终端", "命令行", "测试"],
    }),
    ("data-storage", {
        "ascii": ["database", "sqlite", "storage", "vector", "embedding",
                  "knowledge", "notes", "file manager", "backup", "memory bank"],
        "cjk": ["数据库", "存储", "知识库", "笔记", "文件管理", "备份", "记忆库"],
    }),
    ("devops", {
        "ascii": ["deploy", "docker", "kubernetes", "server", "monitor",
                  "self-host", "homelab", "installer", "updater", "manager",
                  "ci/cd", "devops", "proxy"],
        "cjk": ["部署", "服务器", "监控", "运维", "安装器", "管理"],
    }),
    ("agent", {
        "ascii": ["agent", "skill", "memory", "mcp", "prompt", "reasoning",
                  "workflow", "rag", "llm", "gpt", "claude",
                  "automation", "preset", "subagent", "model routing"],
        "cjk": ["智能体", "提示词", "预设", "子代理", "自动化", "技能", "记忆"],
    }),
    ("web-ui", {
        "ascii": ["sidebar", "ui", "gui", "layout", "dashboard", "desktop",
                  "editor", "preview", "component", "menu", "panel", "window",
                  "web", "modal", "dialog", "css", "button", "icon"],
        "cjk": ["侧边栏", "界面", "桌面", "编辑器", "预览", "菜单", "面板",
                "窗口", "网页", "样式", "按钮", "图标"],
    }),
]
FALLBACK = "utility"
GENERIC_TOPICS = {"deepseek-harness", "dsh", "dsh-plugin", "cordis", "ai-agents", "ai-agent"}


def classify(text: str) -> str:
    low = text.lower()
    for slug, kws in RULES:
        for kw in kws["ascii"]:
            if re.search(r"\b" + re.escape(kw.strip()) + r"\b", low):
                return slug
        for kw in kws["cjk"]:
            if kw in low:
                return slug
    return FALLBACK


def main() -> int:
    dry = "--dry-run" in sys.argv
    db.init_db()
    conn = db.connect()

    slug_to_id = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM categories")}
    curated_ids = {r["repo_id"] for r in conn.execute("SELECT repo_id FROM plugins")}

    repos = conn.execute(
        "SELECT repo_id, full_name, name, description, topics FROM repos").fetchall()

    counts: dict[str, int] = {}
    added = 0
    now = db.now()
    for repo in repos:
        if repo["repo_id"] in curated_ids:
            continue
        # 墓碑仓库（已删除、名字被复用）不收
        if "#deleted-" in (repo["full_name"] or ""):
            continue
        try:
            topics = json.loads(repo["topics"] or "[]")
        except json.JSONDecodeError:
            topics = []
        text = " ".join([repo["name"] or "", repo["description"] or "", " ".join(topics)])
        slug = classify(text)
        counts[slug] = counts.get(slug, 0) + 1
        desc = (repo["description"] or "").strip()
        if CJK_RE.search(desc):
            summary_zh, summary_en = desc, ""
        else:
            summary_zh, summary_en = "", desc
        tags = [t for t in topics if t not in GENERIC_TOPICS][:6]
        if not dry:
            conn.execute(
                """INSERT INTO plugins(repo_id, full_name, name, category_id, status,
                    summary_zh, summary_en, npm_package, install_cmd, tags, created_at, updated_at)
                    VALUES(?,?,?,?, 'approved', ?,?, '', '', ?,?,?)""",
                (repo["repo_id"], repo["full_name"], repo["name"], slug_to_id[slug],
                 summary_zh, summary_en, json.dumps(tags, ensure_ascii=False), now, now),
            )
        added += 1
    if not dry:
        conn.commit()
    conn.close()

    print("批量策展%s：%d 个仓库收录" % ("（试运行）" if dry else "完成", added))
    for slug, n in sorted(counts.items(), key=lambda x: -x[1]):
        print("  %-18s %d" % (slug, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
