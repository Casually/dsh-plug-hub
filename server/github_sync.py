"""GitHub dsh-plugin 主题全量快照同步器。

- 经 search API 拉取 topic:dsh-plugin 全量仓库（分页，单页 100）。
- 用稳定 repo_id 对比上一份快照，产出事件：
    new        新出现的仓库
    renamed    同一 repo_id 的 full_name 变了
    archived   archived 0→1；unarchived 1→0
    vanished   上次快照里有、这次没了（删除 / 取消 topic / 转私有）
- 每次运行写入 sync_runs 日志；httpx 遵循 HTTPS_PROXY/HTTP_PROXY 环境变量。

入库采用两阶段：先更新/改名已有仓库（改名会释放旧 full_name），再插入新仓库，
避免「改名腾出的名字被新仓库注册」撞唯一约束；仍冲突时（旧仓库已删除、名字
被复用）把占用者标记为墓碑后重试。
"""
from __future__ import annotations

import json
import os
import sqlite3

import httpx

from . import db

SEARCH_URL = "https://api.github.com/search/repositories"
TOPIC = "dsh-plugin"
PAGE_SIZE = 100
SHARD_LIMIT = 1000  # GitHub search 每个查询最多返回 1000 条（超出翻页返回 422）


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "dsh-plug-hub-sync",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token != "":
        headers["Authorization"] = "Bearer " + token
    return headers


_last_request_ts = 0.0


def _throttle() -> None:
    """客户端主动限速：宁可慢也别吃满 API 速率。

    带令牌 2.6s/请求（约 23 次/分，低于 search 30 次/分上限并避开
    二级限流/滥用检测——持续满速搜索会触发后者，2026-08-23 起
    CI 连续失败即此因）；无令牌 7s/请求（约 8.5 次/分，低于 10 次/分）。
    """
    global _last_request_ts
    import time as _time

    interval = 2.6 if os.environ.get("GITHUB_TOKEN", "") != "" else 7.0
    wait = interval - (_time.time() - _last_request_ts)
    if wait > 0:
        _time.sleep(wait)
    _last_request_ts = _time.time()


def _search(client: httpx.Client, query: str, page: int) -> dict:
    """抓一页搜索，限流时按 reset 时间退避重试（未认证 search 仅 10 次/分钟）。"""
    import time as _time

    params = {"q": query, "per_page": str(PAGE_SIZE), "page": str(page)}
    for attempt in range(12):
        _throttle()
        resp = client.get(SEARCH_URL, params=params, headers=_headers(), timeout=30)
        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset", "")
            retry_after = resp.headers.get("Retry-After", "")
            wait = None
            try:
                if retry_after != "":
                    wait = int(retry_after)
                elif reset != "":
                    wait = max(1, int(reset) - int(_time.time()))
            except ValueError:
                wait = None
            wait = 65 if wait is None else min(wait, 300)
            if attempt >= 11:
                raise RuntimeError("GitHub 限流（HTTP %d），退避重试 %d 次仍失败——配置 GITHUB_TOKEN 可提速" % (resp.status_code, attempt))
            print("[sync] 限流，等待 %ds 后重试（第 %d 次）page=%d" % (wait + 1, attempt + 1, page), flush=True)
            _time.sleep(wait + 1)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("GitHub 同步失败：重试次数耗尽")


def fetch_all_topic_repos(client: httpx.Client) -> list[dict]:
    """拉全 topic 仓库。

    GitHub search 单查询上限 1000 条，因此按 created 日期自适应二分：
    某时间段命中超过 1000 就拆半递归，直到每个分片可完整翻页。
    结果按 repo_id 去重（分片边界不重叠，去重只是保险）。
    """
    import datetime as _dt

    items: dict[int, dict] = {}

    def paginate(query: str, first: dict) -> None:
        for item in first.get("items", []):
            items[int(item["id"])] = item
        total = int(first.get("total_count", 0))
        pages = min((total + PAGE_SIZE - 1) // PAGE_SIZE, SHARD_LIMIT // PAGE_SIZE)
        for page in range(2, pages + 1):
            data = _search(client, query, page)
            for item in data.get("items", []):
                items[int(item["id"])] = item

    def walk_star_bands(lo: str, hi: str) -> None:
        """日期粒度已到底仍超 1000 条（如生态爆发日）：star 递归细分，
        stars:0 到底再按 forks、最后按仓库 size 兜底。"""

        def band_fetch(query: str) -> tuple[dict, int]:
            first = _search(client, query, 1)
            return first, int(first.get("total_count", 0))

        def overflow_paginate(query: str, first: dict, total: int, label: str) -> None:
            print("[sync] 警告：%s..%s %s 仍超 %d 条（%d），仅抓取前 %d 条" % (lo, hi, label, SHARD_LIMIT, total, SHARD_LIMIT), flush=True)
            paginate(query, first)

        def walk_band(slo: int, shi: int) -> None:
            band = f"stars:>={slo}" if shi >= 10 ** 6 else f"stars:{slo}..{shi}"
            query = f"topic:{TOPIC} created:{lo}..{hi} {band}"
            first, total = band_fetch(query)
            if total == 0:
                return
            if total > SHARD_LIMIT and shi > slo:
                mid = (slo + shi) // 2
                walk_band(slo, mid)
                walk_band(mid + 1, shi)
                return
            if total > SHARD_LIMIT and slo == 0 and shi == 0:
                walk_zero()
                return
            if total > SHARD_LIMIT:
                overflow_paginate(query, first, total, band)
                return
            paginate(query, first)

        def walk_zero() -> None:
            for fband in ("forks:>=1", "forks:0"):
                fq = f"topic:{TOPIC} created:{lo}..{hi} stars:0 {fband}"
                first, total = band_fetch(fq)
                if total == 0:
                    continue
                if total > SHARD_LIMIT and fband == "forks:0":
                    walk_size()
                    continue
                if total > SHARD_LIMIT:
                    overflow_paginate(fq, first, total, "stars:0 " + fband)
                    continue
                paginate(fq, first)

        def walk_size() -> None:
            for sband in ("size:<=20", "size:21..50", "size:51..500", "size:>500"):
                sq = f"topic:{TOPIC} created:{lo}..{hi} stars:0 forks:0 {sband}"
                first, total = band_fetch(sq)
                if total == 0:
                    continue
                if total > SHARD_LIMIT:
                    overflow_paginate(sq, first, total, "stars:0 forks:0 " + sband)
                    continue
                paginate(sq, first)

        walk_band(0, 9)
        walk_band(10, 99)
        walk_band(100, 10 ** 6)

    def walk(lo: str, hi: str, depth: int) -> None:
        query = f"topic:{TOPIC} created:{lo}..{hi}"
        first = _search(client, query, 1)
        total = int(first.get("total_count", 0))
        if total == 0:
            return
        if total > SHARD_LIMIT and depth < 12:
            d0 = _dt.date.fromisoformat(lo)
            d1 = _dt.date.fromisoformat(hi)
            span = (d1 - d0).days
            if span <= 1:
                print("[sync] 分片 %s..%s 单日超 %d 条，改按 star 二级分片" % (lo, hi, total), flush=True)
                walk_star_bands(lo, hi)
                return
            mid = d0 + _dt.timedelta(days=span // 2)
            walk(lo, mid.isoformat(), depth + 1)
            walk((mid + _dt.timedelta(days=1)).isoformat(), hi, depth + 1)
        else:
            if total > SHARD_LIMIT:
                print("[sync] 分片 %s..%s 超深递归仍超 %d 条，改按 star 二级分片" % (lo, hi, total), flush=True)
                walk_star_bands(lo, hi)
            else:
                paginate(query, first)

    today = _dt.date.today().isoformat()
    walk("2008-01-01", today, 0)
    print("[sync] 全量抓取完成：%d 个仓库" % len(items), flush=True)
    return list(items.values())


def _license_of(item: dict) -> str:
    lic = item.get("license")
    if isinstance(lic, dict):
        return str(lic.get("spdx_id", "") or "")
    return ""


def sync(trigger: str = "manual") -> dict:
    """执行一次全量同步；返回本次运行的统计摘要。"""
    db.init_db()
    started = db.now()
    stats = {"added": 0, "updated": 0, "renamed": 0, "archived": 0, "vanished": 0}
    run_id = None
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO sync_runs(started_at, trigger) VALUES(?,?)",
            (started, trigger),
        )
        run_id = cur.lastrowid
        conn.commit()

        with httpx.Client(follow_redirects=True) as client:
            items = fetch_all_topic_repos(client)

        before = {row["repo_id"]: dict(row) for row in conn.execute("SELECT * FROM repos")}
        seen_ids: set[int] = set()
        new_items: list[tuple[dict, str]] = []

        # 第一遍：只处理已存在仓库（更新/改名/归档）。改名会释放旧 full_name，
        # 必须先于新仓库插入完成，否则「A 改名腾出的名字被新仓库 B 注册」会撞唯一约束。
        for item in items:
            repo_id = int(item["id"])
            seen_ids.add(repo_id)
            full_name = str(item.get("full_name", ""))
            owner = str(item.get("owner", {}).get("login", ""))
            name = str(item.get("name", ""))
            archived = 1 if item.get("archived") else 0
            record = {
                "repo_id": repo_id,
                "full_name": full_name,
                "owner": owner,
                "name": name,
                "description": str(item.get("description") or ""),
                "homepage": str(item.get("homepage") or ""),
                "html_url": str(item.get("html_url", "")),
                "stars": int(item.get("stargazers_count", 0)),
                "forks": int(item.get("forks_count", 0)),
                "open_issues": int(item.get("open_issues_count", 0)),
                "language": str(item.get("language") or ""),
                "license": _license_of(item),
                "topics": json.dumps(item.get("topics", []), ensure_ascii=False),
                "archived": archived,
                "disabled": 1 if item.get("disabled") else 0,
                "created_at": str(item.get("created_at", "")),
                "pushed_at": str(item.get("pushed_at", "")),
                "updated_at": str(item.get("updated_at", "")),
                "default_branch": str(item.get("default_branch", "main")),
            }
            old = before.get(repo_id)
            if old is None:
                new_items.append((record, full_name))
                continue
            conn.execute(
                """UPDATE repos SET full_name=:full_name, owner=:owner, name=:name,
                    description=:description, homepage=:homepage, html_url=:html_url,
                    stars=:stars, forks=:forks, open_issues=:open_issues, language=:language,
                    license=:license, topics=:topics, archived=:archived, disabled=:disabled,
                    created_at=:created_at, pushed_at=:pushed_at, updated_at=:updated_at,
                    default_branch=:default_branch, last_seen_at=:ts WHERE repo_id=:repo_id""",
                {**record, "ts": db.now()},
            )
            stats["updated"] += 1
            if old["full_name"] != full_name:
                conn.execute("UPDATE repos SET prev_full_name=? WHERE repo_id=?", (old["full_name"], repo_id))
                conn.execute("UPDATE plugins SET full_name=?, name=? WHERE repo_id=?", (full_name, record["name"], repo_id))
                conn.execute(
                    "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                    (repo_id, full_name, "renamed", old["full_name"] + " → " + full_name, db.now()),
                )
                stats["renamed"] += 1
            if old["archived"] == 0 and archived == 1:
                conn.execute(
                    "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                    (repo_id, full_name, "archived", "仓库被归档", db.now()),
                )
                stats["archived"] += 1
            elif old["archived"] == 1 and archived == 0:
                conn.execute(
                    "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                    (repo_id, full_name, "unarchived", "仓库取消归档", db.now()),
                )

        # 第二遍：插入新仓库。极端情况下旧行仍占着同名 full_name（旧仓库已删除、
        # 名字被新仓库复用）——把占用者标记为墓碑后重试。
        tombstoned: set[int] = set()
        for record, full_name in new_items:
            try:
                conn.execute(
                    """INSERT INTO repos(repo_id, full_name, owner, name, description, homepage,
                        html_url, stars, forks, open_issues, language, license, topics, archived,
                        disabled, created_at, pushed_at, updated_at, default_branch,
                        first_seen_at, last_seen_at, prev_full_name)
                        VALUES(:repo_id,:full_name,:owner,:name,:description,:homepage,:html_url,
                        :stars,:forks,:open_issues,:language,:license,:topics,:archived,:disabled,
                        :created_at,:pushed_at,:updated_at,:default_branch,:ts,:ts,'')""",
                    {**record, "ts": db.now()},
                )
            except sqlite3.IntegrityError:
                holder = conn.execute(
                    "SELECT repo_id FROM repos WHERE full_name=?", (full_name,)).fetchone()
                if holder is not None:
                    tomb = "%s#deleted-%d" % (full_name, holder["repo_id"])
                    conn.execute(
                        "UPDATE repos SET full_name=?, disabled=1 WHERE repo_id=?",
                        (tomb, holder["repo_id"]),
                    )
                    conn.execute(
                        "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                        (holder["repo_id"], full_name, "vanished", "仓库已删除，名字被新仓库复用", db.now()),
                    )
                    tombstoned.add(holder["repo_id"])
                conn.execute(
                    """INSERT INTO repos(repo_id, full_name, owner, name, description, homepage,
                        html_url, stars, forks, open_issues, language, license, topics, archived,
                        disabled, created_at, pushed_at, updated_at, default_branch,
                        first_seen_at, last_seen_at, prev_full_name)
                        VALUES(:repo_id,:full_name,:owner,:name,:description,:homepage,:html_url,
                        :stars,:forks,:open_issues,:language,:license,:topics,:archived,:disabled,
                        :created_at,:pushed_at,:updated_at,:default_branch,:ts,:ts,'')""",
                    {**record, "ts": db.now()},
                )
            conn.execute(
                "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                (record["repo_id"], full_name, "new", "首次进入 dsh-plugin 主题快照", db.now()),
            )
            stats["added"] += 1
            # 注意：不自动创建策展候选——topic 下已有数千仓库（含大量
            # 仅挂 topic 的非插件仓库），候选池由管理台按需「加入策展」。

        # vanished：上次有这次没有（墓碑行已单独记过事件，跳过）
        for repo_id, old in before.items():
            if repo_id not in seen_ids and repo_id not in tombstoned:
                conn.execute(
                    "INSERT INTO repo_events(repo_id, full_name, kind, detail, detected_at) VALUES(?,?,?,?,?)",
                    (repo_id, old["full_name"], "vanished", "本次快照未命中（可能删除、转私有或取消 topic）", db.now()),
                )
                stats["vanished"] += 1

        conn.execute("UPDATE settings SET value=? WHERE key='last_sync_at'", (str(db.now()),))
        if conn.execute("SELECT changes()").fetchone()[0] == 0:
            conn.execute("INSERT INTO settings(key, value) VALUES('last_sync_at', ?)", (str(db.now()),))
        conn.execute(
            """UPDATE sync_runs SET finished_at=?, added=?, updated=?, renamed=?, archived=?,
                vanished=?, ok=1, message=? WHERE id=?""",
            (db.now(), stats["added"], stats["updated"], stats["renamed"], stats["archived"],
             stats["vanished"], "同步 %d 个主题仓库" % len(items), run_id),
        )
        conn.commit()
        return {"ok": True, "total": len(items), **stats}
    except Exception as error:  # noqa: BLE001 — 运行日志要完整捕获
        message = str(error)
        if run_id is not None:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, ok=0, message=? WHERE id=?",
                (db.now(), message[:500], run_id),
            )
            conn.commit()
        return {"ok": False, "error": message, **stats}
    finally:
        conn.close()
        # WAL 刷回主库：让 hub.db 自包含（CI 紧接着 git add 提交它；
        # 本地也避免遗留 -wal 边车文件与后续 git 操作错配）
        try:
            db.checkpoint()
        except sqlite3.Error:
            pass
