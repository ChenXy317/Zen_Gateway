"""Zen Gateway 命令行启动入口。"""
from __future__ import annotations

import argparse
import sys

import uvicorn

from . import __version__
from .config import config_manager, effective_bind_host
from .server import create_app


def main() -> None:
    """网关启动主函数。"""
    parser = argparse.ArgumentParser(description="Zen Gateway - OpenCode 免费模型外接与本地网关")
    parser.add_argument("--host", type=str, default=None, help="监听 IP（默认读取 config.json）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 8790）")
    parser.add_argument("--reload", action="store_true", help="启用热重载（开发模式）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    cfg = config_manager.config.server
    host = args.host or cfg.host
    port = args.port or cfg.port

    print("=" * 60)
    print(f"  Zen Gateway v{__version__} - OpenCode 免费模型本地网关")
    print(f"  监听地址: http://{effective_bind_host(host)}:{port}")
    print(f"  管理面板: http://127.0.0.1:{port}/")
    print(f"  OpenAI 代理端点: http://127.0.0.1:{port}/v1/chat/completions")
    print(f"  Anthropic 代理端点: http://127.0.0.1:{port}/v1/messages")
    print(f"  默认模型: {cfg.default_model}")
    print("=" * 60)

    uvicorn.run(
        "app.server:create_app",
        factory=True,
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
