"""SQLite 数据层：schema 初始化 + 11 大类种子 + 轻量连接帮助函数。

设计要点
- 单文件 SQLite（data/hub.db），WAL 模式便于读写并发。
- 全量快照（repos）与人工策展（plugins）分离：快照是事实，策展是观点。
- 仓库更名 / 归档靠稳定 repo_id 追踪，事件落入 repo_events。
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("HUB_DB", DATA_DIR / "hub.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    repo_id        INTEGER PRIMARY KEY,          -- GitHub 稳定 id（更名不变）
    full_name      TEXT NOT NULL UNIQUE,          -- owner/repo（当前名）
    owner          TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT DEFAULT '',
    homepage       TEXT DEFAULT '',
    html_url       TEXT NOT NULL,
    stars          INTEGER DEFAULT 0,
    forks          INTEGER DEFAULT 0,
    open_issues    INTEGER DEFAULT 0,
    language       TEXT DEFAULT '',
    license        TEXT DEFAULT '',
    topics         TEXT DEFAULT '[]',             -- JSON 数组
    archived       INTEGER DEFAULT 0,
    disabled       INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT '',
    pushed_at      TEXT DEFAULT '',               -- 最近提交（活跃度依据）
    updated_at     TEXT DEFAULT '',
    default_branch TEXT DEFAULT 'main',
    first_seen_at  INTEGER NOT NULL,              -- 首次进入快照（epoch）
    last_seen_at   INTEGER NOT NULL,              -- 最近一次快照命中（epoch）
    prev_full_name TEXT DEFAULT ''                -- 更名前全名（便于事件展示）
);
CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repos(full_name);
CREATE INDEX IF NOT EXISTS idx_repos_pushed ON repos(pushed_at);

CREATE TABLE IF NOT EXISTS repo_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     INTEGER NOT NULL,
    full_name   TEXT NOT NULL,
    kind        TEXT NOT NULL,                    -- new | renamed | archived | unarchived | vanished
    detail      TEXT DEFAULT '',
    detected_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON repo_events(detected_at DESC);

CREATE TABLE IF NOT EXISTS categories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    slug     TEXT NOT NULL UNIQUE,
    name_zh  TEXT NOT NULL,
    name_en  TEXT NOT NULL,
    sort     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plugins (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id      INTEGER,                          -- 关联快照（可空：纯人工条目）
    full_name    TEXT NOT NULL,                    -- 冗余存储，站点/API 直读
    name         TEXT NOT NULL,                    -- 展示名 / 包名
    category_id  INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'candidate',-- candidate | approved | rejected
    summary_zh   TEXT DEFAULT '',
    summary_en   TEXT DEFAULT '',
    npm_package  TEXT DEFAULT '',                  -- 若发布到 npm
    install_cmd  TEXT DEFAULT '',                  -- 一键安装命令
    tags         TEXT DEFAULT '[]',                -- JSON 数组
    sort         INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    FOREIGN KEY(repo_id) REFERENCES repos(repo_id),
    FOREIGN KEY(category_id) REFERENCES categories(id)
);
CREATE INDEX IF NOT EXISTS idx_plugins_status ON plugins(status);
CREATE INDEX IF NOT EXISTS idx_plugins_category ON plugins(category_id);

CREATE TABLE IF NOT EXISTS sync_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    trigger     TEXT NOT NULL DEFAULT 'manual',    -- scheduler | manual | ci
    added       INTEGER DEFAULT 0,
    updated     INTEGER DEFAULT 0,
    renamed     INTEGER DEFAULT 0,
    archived    INTEGER DEFAULT 0,
    vanished    INTEGER DEFAULT 0,
    ok          INTEGER DEFAULT 1,
    message     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 十一大类（slug / 中文 / 英文 / 排序）。与需求 03 对应。
CATEGORIES = [
    ("web-ui", "Web UI 增强", "Web UI Enhancement", 1),
    ("agent", "Agent 能力", "Agent Capabilities", 2),
    ("coding", "编码开发", "Coding & Development", 3),
    ("messaging", "消息通讯", "Messaging & Communication", 4),
    ("vision-multimodal", "视觉与多模态", "Vision & Multimodal", 5),
    ("theme-fun", "皮肤与娱乐", "Themes & Fun", 6),
    ("distro", "合集与发行版", "Collections & Distros", 7),
    ("data-storage", "数据与存储", "Data & Storage", 8),
    ("devops", "运维与部署", "DevOps & Deployment", 9),
    ("audio-voice", "音频与语音", "Audio & Voice", 10),
    ("utility", "工具与效率", "Utilities & Productivity", 11),
]


def connect() -> sqlite3.Connection:
    """返回一个行工厂为 dict 的连接；调用方负责 close。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """建表 + 幂等写入类别种子。"""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        for slug, name_zh, name_en, sort in CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO categories(slug, name_zh, name_en, sort) VALUES(?,?,?,?)",
                (slug, name_zh, name_en, sort),
            )
        conn.commit()
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


def checkpoint() -> None:
    """把 WAL 全部刷回主库并清空 -wal 文件，让 hub.db 成为自包含快照。

    提交进 git / 复制备份前调用。WAL 模式下若带着未 checkpoint 的 -wal
    边车文件去替换主库（如 git checkout/pull），会因 change-counter 错配
    报 "database disk image is malformed"。
    """
    conn = connect()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
