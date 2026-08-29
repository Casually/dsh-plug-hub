#!/bin/sh
# 容器启动：先确保站点存在（依赖挂载进来的 data/hub.db），再常驻服务。
# 之后每 4 小时的定时同步由进程内调度器完成，数据写入 /app/data（宿主卷）。
set -e

mkdir -p data site
if [ ! -f data/hub.db ]; then
  echo "[entrypoint] 未发现 data/hub.db —— 首次启动，将自建空库并在首轮同步抓取全量快照"
fi
python generate_site.py || echo "[entrypoint] 站点生成跳过（数据库可能为空）"

exec uvicorn server.app:app --host 0.0.0.0 --port "${HUB_PORT:-8900}"
