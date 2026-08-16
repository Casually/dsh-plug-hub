"""dsh-plug-hub 主服务（FastAPI）。

路由分层
- /api/v1/*        公开只读接口（供 dsh-plug-manager 等外部消费，CORS 全开）
- /api/admin/*     管理接口（X-Admin-Token 校验）
- /admin           管理 SPA（Vue3 + Element Plus，CDN 引入）
- /site/*          本地预览生成的社区站点
- /                重定向到 /site/

调度器：进程内 asyncio 循环，每 4 小时全量同步一次；启动时若距上次
同步超过 4 小时则立即补一次。手动触发走 /api/admin/sync。
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, db, github_sync

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
SITE_DIR = BASE_DIR / "site"
SYNC_INTERVAL_SECONDS = 4 * 3600

ADMIN_TOKEN = os.environ.get("HUB_ADMIN_TOKEN", "")
if ADMIN_TOKEN == "":
    ADMIN_TOKEN = secrets.token_urlsafe(16)
    print("[dsh-plug-hub] 未设置 HUB_ADMIN_TOKEN，本次运行使用临时令牌：" + ADMIN_TOKEN)

sync_lock = asyncio.Lock()


async def run_sync(trigger: str) -> dict:
    """同一时刻只允许一次同步（CI/手动/调度共用）。"""
    if sync_lock.locked():
        return {"ok": False, "error": "已有同步任务在进行"}
    async with sync_lock:
        return await asyncio.to_thread(github_sync.sync, trigger)


async def scheduler_loop() -> None:
    while True:
        try:
            db.init_db()
            conn = db.connect()
            row = conn.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
            conn.close()
            last = int(row["value"]) if row is not None else 0
            if db.now() - last >= SYNC_INTERVAL_SECONDS:
                print("[dsh-plug-hub] 定时同步开始…")
                result = await run_sync("scheduler")
                print("[dsh-plug-hub] 定时同步结束：" + json.dumps(result, ensure_ascii=False))
        except Exception as error:  # noqa: BLE001
            print("[dsh-plug-hub] 调度器异常：" + str(error))
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(scheduler_loop())
    yield
    task.cancel()


app = FastAPI(title="dsh-plug-hub", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_admin(token: str | None) -> None:
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="管理令牌无效")


# ---------------- 公开接口（07：对外接口） ----------------

@app.get("/")
async def root():
    if SITE_DIR.joinpath("index.html").exists():
        return RedirectResponse("/site/")
    return {"name": "dsh-plug-hub", "hint": "站点尚未生成，访问 /docs 查看 API，/admin 进入管理页"}


@app.get("/api/v1/meta")
async def api_meta():
    db.init_db()
    conn = db.connect()
    try:
        repo_count = conn.execute("SELECT COUNT(*) AS n FROM repos").fetchone()["n"]
        plugin_count = conn.execute("SELECT COUNT(*) AS n FROM plugins WHERE status='approved'").fetchone()["n"]
        candidate_count = conn.execute("SELECT COUNT(*) AS n FROM plugins WHERE status='candidate'").fetchone()["n"]
        last_row = conn.execute("SELECT value FROM settings WHERE key='last_sync_at'").fetchone()
        last_sync = None
        if last_row is not None:
            last_sync = datetime.fromtimestamp(int(last_row["value"]), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "ok": True,
            "topic": "dsh-plugin",
            "repo_total": repo_count,
            "approved_total": plugin_count,
            "candidate_total": candidate_count,
            "last_sync_at": last_sync,
            "sync_interval_seconds": SYNC_INTERVAL_SECONDS,
            "activity_levels": catalog.ACTIVITY_LEVELS,
        }
    finally:
        conn.close()


@app.get("/api/v1/catalog")
async def api_catalog(q: str = "", category: str = "", activity: str = ""):
    """对外目录：支持关键词 / 分类 / 活跃度过滤。"""
    data = catalog.build_catalog()
    plugins = data["plugins"]
    if category != "":
        plugins = [p for p in plugins if p["category"]["slug"] == category]
    if activity != "":
        plugins = [p for p in plugins if p["activity"]["level"] == activity]
    if q != "":
        needle = q.lower()
        def hit(p: dict) -> bool:
            hay = " ".join([
                p["name"], p["full_name"], p["summary_zh"], p["summary_en"],
                " ".join(p["tags"]), p["category"]["name_zh"], p["category"]["name_en"],
            ]).lower()
            return needle in hay
        plugins = [p for p in plugins if hit(p)]
    return {**data, "total": len(plugins), "plugins": plugins}


@app.get("/api/v1/repos")
async def api_repos(limit: int = 200):
    """全量快照（监测视图）。"""
    db.init_db()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM repos ORDER BY stars DESC, pushed_at DESC LIMIT ?",
            (min(max(limit, 1), 2000),),
        )
        return {"ok": True, "repos": db.rows_to_dicts(rows)}
    finally:
        conn.close()


@app.get("/api/v1/changelog")
async def api_changelog(limit: int = 60):
    return {"ok": True, "events": catalog.build_changelog(min(max(limit, 1), 500))}


# ---------------- 管理接口（08：服务管理页后端） ----------------

@app.get("/api/admin/overview")
async def admin_overview(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    meta = await api_meta()
    conn = db.connect()
    try:
        runs = db.rows_to_dicts(conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 15"))
        events = db.rows_to_dicts(conn.execute(
            "SELECT * FROM repo_events ORDER BY detected_at DESC, id DESC LIMIT 30"))
        return {**meta, "sync_runs": runs, "events": events}
    finally:
        conn.close()


@app.get("/api/admin/repos")
async def admin_repos(x_admin_token: str | None = Header(default=None), limit: int = 2000):
    """快照 + 策展状态联表，管理页主表格数据源（按 star 排序截取）。"""
    require_admin(x_admin_token)
    db.init_db()
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM repos").fetchone()["n"]
        rows = conn.execute(
            """SELECT r.*, p.id AS plugin_id, p.status AS plugin_status,
                    p.category_id AS plugin_category_id, p.summary_zh, p.summary_en,
                    p.name AS plugin_name, p.npm_package, p.install_cmd, p.tags AS plugin_tags
                FROM repos r
                LEFT JOIN plugins p ON p.repo_id = r.repo_id
                ORDER BY r.stars DESC, r.pushed_at DESC LIMIT ?""",
            (min(max(limit, 50), 5000),),
        )
        categories = db.rows_to_dicts(conn.execute("SELECT * FROM categories ORDER BY sort"))
        return {"ok": True, "total": total, "repos": db.rows_to_dicts(rows), "categories": categories}
    finally:
        conn.close()


@app.post("/api/admin/plugins/{repo_id}")
async def admin_save_plugin(repo_id: int, request: Request, x_admin_token: str | None = Header(default=None)):
    """保存某仓库的策展信息（类型 / 状态 / 双语简介 / 包名 / 安装命令）。"""
    require_admin(x_admin_token)
    body = await request.json()
    conn = db.connect()
    try:
        repo = conn.execute("SELECT * FROM repos WHERE repo_id=?", (repo_id,)).fetchone()
        if repo is None:
            raise HTTPException(status_code=404, detail="仓库不在快照中")
        plugin = conn.execute("SELECT * FROM plugins WHERE repo_id=?", (repo_id,)).fetchone()
        fields = {
            "name": str(body.get("name", repo["name"])),
            "category_id": int(body.get("category_id", 11)),
            "status": str(body.get("status", "candidate")),
            "summary_zh": str(body.get("summary_zh", "")),
            "summary_en": str(body.get("summary_en", "")),
            "npm_package": str(body.get("npm_package", "")),
            "install_cmd": str(body.get("install_cmd", "")),
            "tags": json.dumps(body.get("tags", []), ensure_ascii=False),
        }
        if fields["status"] not in ("candidate", "approved", "rejected"):
            raise HTTPException(status_code=400, detail="status 取值无效")
        if plugin is None:
            conn.execute(
                """INSERT INTO plugins(repo_id, full_name, name, category_id, status, summary_zh,
                    summary_en, npm_package, install_cmd, tags, created_at, updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (repo_id, repo["full_name"], fields["name"], fields["category_id"], fields["status"],
                 fields["summary_zh"], fields["summary_en"], fields["npm_package"],
                 fields["install_cmd"], fields["tags"], db.now(), db.now()),
            )
        else:
            conn.execute(
                """UPDATE plugins SET name=:name, category_id=:category_id, status=:status,
                    summary_zh=:summary_zh, summary_en=:summary_en, npm_package=:npm_package,
                    install_cmd=:install_cmd, tags=:tags, updated_at=:ts WHERE repo_id=:repo_id""",
                {**fields, "ts": db.now(), "repo_id": repo_id},
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/admin/sync")
async def admin_sync(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    result = await run_sync("manual")
    if result.get("ok") is not True:
        raise HTTPException(status_code=502, detail=result.get("error", "同步失败"))
    return result


@app.post("/api/admin/generate-site")
async def admin_generate_site(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    import generate_site  # 项目根目录脚本
    count = await asyncio.to_thread(generate_site.generate)
    return {"ok": True, "plugins": count}


# ---------------- 静态资源 ----------------

app.mount("/admin-static", StaticFiles(directory=STATIC_DIR), name="admin-static")
# check_dir=False：site/ 可能在服务启动后才由调度器/CI 生成
SITE_DIR.mkdir(exist_ok=True)
app.mount("/site", StaticFiles(directory=SITE_DIR, html=True, check_dir=False), name="site")


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")
