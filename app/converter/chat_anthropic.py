"""Anthropic /v1/messages 协议格式转换器。"""
from __future__ import annotations

from typing import Any

from ..ir import IRResponse


def ir_to_anthropic_response(resp: IRResponse) -> dict[str, Any]:
    """将 IRResponse 封装为 Anthropic 标准 messages 响应。"""
    content = []
    if resp.reasoning:
        content.append({
            "type": "thinking",
            "thinking": resp.reasoning,
        })
    content.append({
        "type": "text",
        "text": resp.text,
    })

    return {
        "id": f"msg_{resp.id}",
        "type": "message",
        "role": "assistant",
        "model": resp.model,
        "content": content,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        },
    }
