"""SSE 格式化与公用工具。"""
from __future__ import annotations

import json
from typing import Any


def sse_format(data: Any, event: str | None = None) -> str:
    """将数据打包为 SSE 标准帧。"""
    lines = []
    if event:
        lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def sse_done() -> str:
    """OpenAI 标准流式结束标记。"""
    return "data: [DONE]\n\n"
