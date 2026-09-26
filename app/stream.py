"""流式 SSE 协议转接与分发引擎。"""
from __future__ import annotations

import time
import uuid
from typing import Any, AsyncGenerator, Callable

from .converter.chat_responses import ir_delta_to_openai_chunk
from .converter.common import sse_done, sse_format
from .ir import IRChunkDelta, IRUsage


async def stream_openai_generator(
    event_stream: AsyncGenerator[dict[str, Any], None],
    model: str,
    on_ttft: Callable[[float], None] | None = None,
    on_finish: Callable[[int, int], None] | None = None,
) -> AsyncGenerator[str, None]:
    """将内部事件流转换为标准 OpenAI /v1/chat/completions SSE 格式。"""
    resp_id = uuid.uuid4().hex[:24]
    start_time = time.time()
    first_chunk = True
    input_tokens = 0
    output_tokens = 0

    try:
        # 首帧声明 assistant 角色与空内容
        yield sse_format(ir_delta_to_openai_chunk(
            chunk_id=resp_id,
            model=model,
            delta=IRChunkDelta(text=""),
            role="assistant",
        ))

        async for item in event_stream:
            kind = item.get("kind")
            if kind == "delta":
                if first_chunk:
                    first_chunk = False
                    if on_ttft:
                        on_ttft((time.time() - start_time) * 1000)

                field = item.get("field", "text")
                text_val = item.get("delta", "")
                delta = IRChunkDelta(
                    reasoning=text_val if field == "reasoning" else None,
                    text=text_val if field == "text" else None,
                )
                output_tokens += 1
                yield sse_format(ir_delta_to_openai_chunk(
                    chunk_id=resp_id,
                    model=model,
                    delta=delta,
                ))

            elif kind == "finish":
                tokens = item.get("tokens", {})
                input_tokens = tokens.get("input", input_tokens)
                output_tokens = tokens.get("output", output_tokens)
                total = tokens.get("total", input_tokens + output_tokens)
                usage = IRUsage(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=total,
                    reasoning_tokens=tokens.get("reasoning", 0),
                )
                yield sse_format(ir_delta_to_openai_chunk(
                    chunk_id=resp_id,
                    model=model,
                    delta=IRChunkDelta(finish_reason="stop", usage=usage),
                ))

            elif kind == "error":
                err_msg = item.get("error", "上游处理错误")
                yield sse_format({"error": {"message": err_msg, "type": "upstream_error"}})
                break

    finally:
        if on_finish:
            on_finish(input_tokens, output_tokens)
        yield sse_done()


async def stream_anthropic_generator(
    event_stream: AsyncGenerator[dict[str, Any], None],
    model: str,
    on_ttft: Callable[[float], None] | None = None,
    on_finish: Callable[[int, int], None] | None = None,
) -> AsyncGenerator[str, None]:
    """将内部事件流转换为标准 Anthropic /v1/messages SSE 格式。"""
    resp_id = uuid.uuid4().hex[:24]
    start_time = time.time()
    first_chunk = True
    input_tokens = 0
    output_tokens = 0

    current_block_type: str | None = None
    block_index = 0

    try:
        # 1. 消息起始事件
        yield sse_format({
            "type": "message_start",
            "message": {
                "id": f"msg_{resp_id}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }, event="message_start")

        async for item in event_stream:
            kind = item.get("kind")
            if kind == "delta":
                if first_chunk:
                    first_chunk = False
                    if on_ttft:
                        on_ttft((time.time() - start_time) * 1000)

                field = item.get("field", "text")
                text_val = item.get("delta", "")
                output_tokens += 1

                # 处理思考过程与正文内容块状态切换
                if field == "reasoning":
                    if current_block_type != "thinking":
                        if current_block_type is not None:
                            yield sse_format({"type": "content_block_stop", "index": block_index}, event="content_block_stop")
                            block_index += 1
                        yield sse_format({
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {"type": "thinking", "thinking": ""},
                        }, event="content_block_start")
                        current_block_type = "thinking"

                    yield sse_format({
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "thinking_delta", "thinking": text_val},
                    }, event="content_block_delta")

                else:
                    if current_block_type != "text":
                        if current_block_type is not None:
                            yield sse_format({"type": "content_block_stop", "index": block_index}, event="content_block_stop")
                            block_index += 1
                        yield sse_format({
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {"type": "text", "text": ""},
                        }, event="content_block_start")
                        current_block_type = "text"

                    yield sse_format({
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "text_delta", "text": text_val},
                    }, event="content_block_delta")

            elif kind == "finish":
                tokens = item.get("tokens", {})
                input_tokens = tokens.get("input", input_tokens)
                output_tokens = tokens.get("output", output_tokens)

        # 关闭最后一个内容块
        if current_block_type is not None:
            yield sse_format({"type": "content_block_stop", "index": block_index}, event="content_block_stop")
        else:
            # 无有效输出时补齐空正文块
            yield sse_format({
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }, event="content_block_start")
            yield sse_format({"type": "content_block_stop", "index": 0}, event="content_block_stop")

        # 消息完成事件
        yield sse_format({
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        }, event="message_delta")

        yield sse_format({"type": "message_stop"}, event="message_stop")

    finally:
        if on_finish:
            on_finish(input_tokens, output_tokens)
