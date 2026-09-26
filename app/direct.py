"""OpenCode 协议级特征逆向直连通信模块（模式 A）。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator

import httpx

from .auth import opencode_auth
from .config import config_manager

logger = logging.getLogger("zen_gateway.direct")

ZEN_API_BASE = "https://opencode.ai/zen/v1"


class DirectClient:
    """模式 A：通过 1:1 伪装官方请求头直连 OpenCode Zen API。"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def get_client(self) -> httpx.AsyncClient:
        """获取或创建内部异步 HTTP 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    def _build_headers(self, session_id: str | None = None) -> dict[str, str]:
        """构建完整的官方客户端特征请求头链。"""
        creds = opencode_auth.get_credentials()
        api_key = creds.api_key or ""
        ver = creds.cli_version or "1.18.30"
        sid = session_id or f"ses_{uuid.uuid4().hex[:26]}"

        return {
            "User-Agent": f"opencode/{ver}/cli",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "x-opencode-client": "cli",
            "x-opencode-version": ver,
            "x-opencode-session": sid,
            "x-opencode-project": "global",
            "x-opencode-request": f"req_{uuid.uuid4().hex[:20]}",
        }

    async def chat_completions(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """向官方 Zen API 发起直连对话补全请求。"""
        headers = self._build_headers()
        client = self.get_client()

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        url = f"{ZEN_API_BASE}/chat/completions"
        if not stream:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code == 403 and "FreeTierError" in r.text:
                raise PermissionError("OpenCode 服务端拦截: 该模型要求官方运行态环境，请使用模式 B (Sidecar 进程中继)")
            r.raise_for_status()
            return r.json()

        # 流式返回
        async def _stream_generator() -> AsyncGenerator[str, None]:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code == 403:
                    text = await resp.aread()
                    if b"FreeTierError" in text:
                        raise PermissionError("OpenCode 服务端拦截: 该模型要求官方运行态环境，请使用模式 B (Sidecar 进程中继)")
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield line

        return _stream_generator()


direct_client = DirectClient()
