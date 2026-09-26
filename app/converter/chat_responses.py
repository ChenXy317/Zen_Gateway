"""OpenAI /v1/chat/completions 协议格式转换器。"""
from __future__ import annotations

import time
from typing import Any

from ..ir import IRChunkDelta, IRResponse


def ir_to_openai_response(resp: IRResponse) -> dict[str, Any]:
    """将 IRResponse 封装为 OpenAI 标准 chat.completion 对象。"""
    created = int(time.time())
    message: dict[str, Any] = {
        "role": "assistant",
        "content": resp.text,
    }
    if resp.reasoning:
        message["reasoning_content"] = resp.reasoning

    return {
        "id": f"chatcmpl-{resp.id}",
        "object": "chat.completion",
        "created": created,
        "model": resp.model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": resp.finish_reason or "stop",
            }
        ],
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
            "completion_tokens_details": {
                "reasoning_tokens": resp.usage.reasoning_tokens
            },
        },
    }


def ir_delta_to_openai_chunk(
    chunk_id: str,
    model: str,
    delta: IRChunkDelta,
    role: str | None = None,
    created: int | None = None,
) -> dict[str, Any]:
    """生成单帧 OpenAI 流式 chat.completion.chunk 字典。"""
    created_ts = created or int(time.time())
    delta_dict: dict[str, Any] = {}
    if role is not None:
        delta_dict["role"] = role
    if delta.text is not None:
        delta_dict["content"] = delta.text
    if delta.reasoning is not None:
        delta_dict["reasoning_content"] = delta.reasoning

    chunk: dict[str, Any] = {
        "id": f"chatcmpl-{chunk_id}",
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta_dict,
                "finish_reason": delta.finish_reason,
            }
        ],
    }
    if delta.usage:
        chunk["usage"] = {
            "prompt_tokens": delta.usage.prompt_tokens,
            "completion_tokens": delta.usage.completion_tokens,
            "total_tokens": delta.usage.total_tokens,
        }
    return chunk


def openai_models_response(model_list: list[dict[str, Any]]) -> dict[str, Any]:
    """封装 OpenAI 规范的 /v1/models 模型清单。"""
    data = []
    created = int(time.time())
    for m in model_list:
        data.append({
            "id": m["id"],
            "object": "model",
            "created": created,
            "owned_by": m.get("provider", "opencode"),
            "permission": [],
            "root": m["id"],
            "parent": None,
        })
    return {"object": "list", "data": data}
