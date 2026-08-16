# dsh-plug-hub — DeepSeek Harness 插件社区目录服务

为 `dsh-plugin` 生态提供**全量监测、人工策展、分类编目、活跃度信号、社区站点、
自动维护与对外接口**的一体化服务端。技术栈：**Python (FastAPI) + SQLite +
Vue 3 + Element Plus**。

## 功能对照

| # | 功能 | 实现 |
|---|---|---|
| 01 | 全量监测 | `server/github_sync.py`：每 4 小时抓取 `topic:dsh-plugin` 全量快照（当前生态约 4400+ 仓库）。GitHub search 单查询上限 1000 条，故按 `created` 日期自适应二分分片抓取，限流自动退避；按稳定 repo_id 检测**新增 / 更名 / 归档 / 消失**事件 |
| 02 | 人工策展 | 管理台（`/admin`）：对快照仓库逐项核验，指定分类、撰写中英双语简介、标记收录/排除 |
| 03 | 分类编目 | 十一大类（Web UI 增强 / Agent 能力 / 编码开发 / 消息通讯 / 视觉与多模态 / 皮肤与娱乐 / 合集与发行版 / 数据与存储 / 运维与部署 / 音频与语音 / 工具与效率），条目兼容中英双语 |
| 04 | 活跃度信号 | 按最近提交时间四级标注：🟢 活跃 ≤30d / 🔵 关注 ≤90d / 🟡 放缓 ≤180d / 🔴 停更 >180d（归档一律停更） |
| 05 | 社区站点 | `site-template/` 纯静态检索站（关键词 + 分类 + 活跃度筛选 + 一键复制安装命令），经 GitHub Pages 部署 |
| 06 | 自动维护 | `.github/workflows/hub-sync.yml`：cron 每 4 小时同步 → 提交 `data/hub.db` 与 `CHANGELOG.md` → 发布站点到 gh-pages，全程无人工 |
| 07 | 对外接口 | `GET /api/v1/catalog`（支持 `q` / `category` / `activity` 过滤）、`/api/v1/meta`、`/api/v1/repos`、`/api/v1/changelog`，CORS 全开，供 dsh-plug-manager 等消费 |
| 08 | 服务管理页 | `/admin`：Vue 3 + Element Plus，含概览、策展表格、事件监测、同步日志、手动同步/生成站点 |

## 快速开始

```sh
cd dsh-plug-hub
./run.sh                 # 自动建 .venv、装依赖、起服务（127.0.0.1:8900）
```

- 社区站点（本地预览）：http://127.0.0.1:8900/site/
- 管理台：http://127.0.0.1:8900/admin （令牌：启动日志打印的 `HUB_ADMIN_TOKEN`，
  或自行 `export HUB_ADMIN_TOKEN=xxx` 后启动）
- API 文档：http://127.0.0.1:8900/docs

首次启动时调度器会立即执行一次全量同步（未认证约 8~10 分钟：search 限流
10 次/分钟，分片探测 + 翻页共约 60+ 请求；配置 `GITHUB_TOKEN` 可缩短到
约 2~3 分钟），之后每 4 小时一次。

手动同步 / 生成站点：

```sh
python sync.py --trigger manual --generate-site
```

## 目录结构

```
dsh-plug-hub/
├── server/
│   ├── app.py            # FastAPI：公开 API + 管理 API + 调度器 + 静态托管
│   ├── db.py             # SQLite schema + 11 大类种子
│   ├── github_sync.py    # 全量快照 + 事件检测（新增/更名/归档/消失）
│   └── catalog.py        # 目录生成 + 活跃度信号
├── static/               # 管理台 SPA（Vue3 + Element Plus，CDN 零构建）
│   ├── admin.html
│   └── admin.js
├── site-template/        # 社区站点静态壳（生成时拷贝到 site/）
│   ├── index.html
│   ├── app.js
│   └── style.css
├── sync.py               # CI/命令行同步入口
├── generate_site.py      # site/ 与 CHANGELOG.md 生成器
├── data/hub.db           # SQLite（提交入库，CI 事件历史依赖它）
└── .github/workflows/hub-sync.yml
```

## 对外接口（供插件市场客户端）

```
GET /api/v1/meta        # 仓库总数 / 收录数 / 最近同步时间 / 活跃度定义
GET /api/v1/catalog     # 已收录目录；?q=关键词&category=web-ui&activity=active
GET /api/v1/repos       # 全量快照（监测视图）
GET /api/v1/changelog   # 最近事件
```

catalog 单条形状（节选）：

```json
{
  "name": "dsh-better-sidebar",
  "full_name": "xxx/dsh-better-sidebar",
  "category": { "slug": "web-ui", "name_zh": "Web UI 增强", "name_en": "Web UI Enhancement" },
  "summary_zh": "…", "summary_en": "…",
  "install": { "npm": "dsh-better-sidebar", "github": "github:xxx/dsh-better-sidebar", "command": "dsh plugin --profile web add -w dsh-better-sidebar" },
  "stats": { "stars": 12, "license": "MIT", "pushed_at": "…" },
  "activity": { "level": "active", "label_zh": "活跃", "days_since": 3 }
}
```

## GitHub Pages 部署（社区站点）

1. 仓库 Settings → Pages → Source 选 **GitHub Actions**（或直接用工作流里的
   peaceiris 发布到 `gh-pages` 分支，两种皆可，工作流默认发布到 gh-pages）。
2. 推送本目录到 GitHub 后，Actions 每 4 小时自动：同步快照 → 提交数据与
   变更记录 → 发布站点。也可在 Actions 页手动 `workflow_dispatch`。

## 环境变量

| 变量 | 说明 |
|---|---|
| `HUB_ADMIN_TOKEN` | 管理接口令牌；不设置则启动时生成临时令牌并打印 |
| `GITHUB_TOKEN` | GitHub API 令牌；强烈建议设置（限流从 10 次/分提到 30 次/分） |
| `HUB_DB` | SQLite 路径（默认 `data/hub.db`） |
| `HUB_PORT` | run.sh 监听端口（默认 8900） |
| `HTTPS_PROXY` / `HTTP_PROXY` | 网络代理（同步与站点部署环境按需） |

## 策展工作流（人工部分）

1. 管理台「策展管理」搜索/筛选快照仓库（按 star 排序，默认前 2000 条）；
2. 点「策展」：选分类（十一大类）、填中英简介、npm 包名（若已发布）、标签；
3. 状态置为「收录」→ 下次生成站点 / 调用 `/api/v1/catalog` 即可见；
4. 活跃度信号与仓库事实（star/许可证/最近提交）每次同步自动刷新，无需维护。
