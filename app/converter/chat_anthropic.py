"""Anthropic /v1/messages 协议格式转换器。"""
from __future__ import annotations

from typing import Any

from ..ir import IRResponse


import json


def ir_to_anthropic_response(resp: IRResponse) -> dict[str, Any]:
    """将 IRResponse 封装为 Anthropic 标准 messages 响应。"""
    content = []
    if resp.reasoning:
        content.append({
            "type": "thinking",
            "thinking": resp.reasoning,
        })
    if resp.text or not resp.tool_calls:
        content.append({
            "type": "text",
            "text": resp.text,
        })

    if resp.tool_calls:
        for tc in resp.tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                parsed_args = {}
            content.append({
                "type": "tool_use",
                "id": tc.get("id"),
                "name": fn.get("name"),
                "input": parsed_args,
            })

    stop_reason = "tool_use" if resp.tool_calls else "end_turn"

    return {
        "id": f"msg_{resp.id}",
        "type": "message",
        "role": "assistant",
        "model": resp.model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        },
    }

