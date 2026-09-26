#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  Zen Gateway: OpenCode 免费模型本地三协议网关"
echo "========================================================"

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 python3，请先安装 Python 3.9+。"
    exit 1
fi

python3 -m app.main "$@"
