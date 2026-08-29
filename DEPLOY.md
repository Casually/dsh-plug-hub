# dsh-plug-hub 服务器部署指南

把插件市场中枢部署到你自己的服务器，**同步与数据全部落在服务器本地**：

```
┌─ 你的服务器 ─────────────────────────────────────┐
│  uvicorn（server.app）                            │
│   ├─ 进程内调度器：每 4 小时同步 GitHub topic     │
│   ├─ 数据：data/hub.db（SQLite，本地磁盘）        │
│   ├─ 站点：/site/（同步后自动重建）               │
│   ├─ 管理台：/admin（HUB_ADMIN_TOKEN）            │
│   └─ 对外 API：/api/v1/*（插件市场客户端消费）    │
└──────────────────────────────────────────────────┘
```

应用是自包含的——不需要 GitHub Actions 也能完成"同步 → 入库 → 重建站点"全流程。
迁移到服务器后，建议**停用 GitHub Actions 的定时触发**（避免两个同步源各写各的库），
仓库里的 `data/hub.db` 退化为"初始种子数据"。

---

## 0. 服务器要求

- 任意 Linux（Ubuntu/Debian 20.04+ 为例），1C / 512MB 内存即可，磁盘 < 200MB
- Python 3.10+（非 Docker 路线）或 Docker + docker-compose（推荐）
- 出网可访问 `api.github.com`（国内服务器若无直连条件，需给进程配代理：
  `HTTPS_PROXY=http://...` 环境变量，httpx 会自动识别）

## 1. 获取代码与初始数据

```bash
git clone https://github.com/Casually/dsh-plug-hub.git /opt/dsh-plug-hub
cd /opt/dsh-plug-hub
```

仓库里已带 `data/hub.db`（全量快照 + 全部收录分类的策展数据），克隆下来即完成"数据初始化"，
无需从零抓取。之后服务器自己的调度器会接管增量维护。

> 注意：如果本地另有更新的 `hub.db`（比如你机器上跑过更新的同步），直接用它覆盖
> `data/hub.db` 再启动即可。

## 2. 路线 A：Docker 部署（推荐）

```bash
cd /opt/dsh-plug-hub

# 环境变量（二选一）：
export HUB_ADMIN_TOKEN="$(openssl rand -hex 24)"      # 管理台令牌，自己记好
export GITHUB_TOKEN="***"            # 任意 PAT，无需任何权限，只为提速（强烈建议）

docker compose up -d --build
docker compose logs -f        # 看到 "Uvicorn running on 0.0.0.0:8900" 即成功
```

- 数据持久化在宿主 `./data/`（SQLite）与 `./site/`，容器可随时重建
- 首次启动后**首轮全量同步在后台自动进行**（带令牌约 10 分钟），完成后每 4 小时一轮，
  每轮同步成功会自动重建站点
- 也可以写 `.env` 文件（与 docker-compose.yml 同目录）代替 export：

  ```
  HUB_ADMIN_TOKEN=***
  GITHUB_TOKEN=***
  ```

## 3. 路线 B：systemd 裸部署（无 Docker）

```bash
sudo useradd -r -s /usr/sbin/nologin hub || true
sudo mkdir -p /opt/dsh-plug-hub && sudo chown hub /opt/dsh-plug-hub
git clone https://github.com/Casually/dsh-plug-hub.git /opt/dsh-plug-hub
cd /opt/dsh-plug-hub

python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 环境变量文件（只有 root 可读）
sudo tee /etc/dsh-plug-hub.env > /dev/null <<'EOF'
HUB_ADMIN_TOKEN=*** rand -hex 24 生成>
GITHUB_TOKEN=***
***
sudo chmod 600 /etc/dsh-plug-hub.env

# 安装服务
sudo cp deploy/hub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hub
sudo journalctl -u hub -f       # 看日志
```

## 4. 反向代理 + HTTPS（可选）

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf /etc/nginx/conf.d/dsh-plug-hub.conf
# 编辑 server_name 为你的域名
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d hub.example.com
```

之后：`https://hub.example.com/` 是社区站点，`/admin` 是管理台，`/api/v1/catalog` 是对外目录。

## 5. 与 GitHub CI 的关系（重要）

服务器接管后，二选一：

1. **推荐：停用 CI 定时**。仓库 Settings → Actions → General → 关闭 scheduled workflows
   （或删除 `.github/workflows/hub-sync.yml` 的 `schedule:` 段）。GitHub Pages 站点若还想保留
   作为镜像，见方案 2。
2. 保留 CI 仅用于发布 Pages 镜像：但注意 CI 的库与服务器库会各自演化，页面内容以谁为准需要
   自己约定（一般不建议长期维持双源）。

## 6. 备份与恢复

```bash
# 手动备份（在线安全，服务不用停）
./.venv/bin/python tools/backup_db.py /opt/backups/dsh-plug-hub --keep 14

# 定时备份（可选）
sudo cp deploy/hub-backup.service deploy/hub-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hub-backup.timer
```

异地备份：`backups/hub-latest.db` 是最新副本，用任意工具（rsync / rclone / 对象存储 CLI）
定时拉走即可。

恢复 = 停服务 → 用备份覆盖 `data/hub.db` → 起服务：

```bash
systemctl stop hub            # 或 docker compose down
cp backups/hub-20260829-033000.db data/hub.db
rm -f data/hub.db-wal data/hub.db-shm
systemctl start hub           # 或 docker compose up -d
```

> 切记：服务运行（持有 WAL）时不要对 `data/hub.db` 做 `git checkout`/覆盖/`cp -f` 等
> 原地替换，会损坏数据库；替换前必须先停服务并删除 `-wal`/`-shm`。

## 7. 验证清单

| 检查 | 命令/地址 |
|---|---|
| 站点 | `http://服务器:8900/site/` |
| 管理台 | `http://服务器:8900/admin`（令牌 = HUB_ADMIN_TOKEN） |
| API | `curl http://服务器:8900/api/v1/meta` → `repo_total`/`approved_total` |
| 调度器 | 日志出现"定时同步开始/结束"（启动时若距上次同步超 4 小时会立即跑一轮） |
| 数据位置 | `ls -lh data/hub.db`（每轮同步后 mtime 更新） |
