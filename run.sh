#!/usr/bin/env bash
# 本地启动 dsh-plug-hub：python run.sh 等价 uvicorn server.app:app --port 8900
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

export HUB_DB="${HUB_DB:-$PWD/data/hub.db}"
echo "→ http://127.0.0.1:8900/site/   社区站点（本地预览）"
echo "→ http://127.0.0.1:8900/admin    管理台"
echo "→ http://127.0.0.1:8900/docs     API 文档"
exec ./.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port "${HUB_PORT:-8900}"
