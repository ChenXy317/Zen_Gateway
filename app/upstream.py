"""上游分发与双通道（Sidecar/Direct）调度器。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator

from .config import config_manager
from .direct import direct_client
from .ir import IRRequest, IRResponse, IRUsage
from .models import model_registry
from .sidecar import sidecar_manager

logger = logging.getLogger("zen_gateway.upstream")


class UpstreamDispatcher:
    """负责将内部统一请求分发给 Sidecar 桥接或直连伪装引擎。"""

    async def execute_non_stream(self, req: IRRequest) -> IRResponse:
        """执行非流式调用并返回统一 IRResponse。"""
        cfg = config_manager.config.server
        mode = cfg.engine_mode.lower()

        # 如果是 auto 模式，重校验模型使用 sidecar，其余尝试直接直连
        if mode == "auto":
            meta = model_registry._models.get(req.model)
            if meta and meta.verification_tier == "heavy":
                mode = "sidecar"
            else:
                mode = "direct"

        if mode == "direct":
            try:
                # 转换消息结构为标准 OpenAI dict 格式
                msgs = [{"role": m.role, "content": m.content} for m in req.messages]
                if req.system_prompt:
                    msgs.insert(0, {"role": "system", "content": req.system_prompt})
                resp = await direct_client.chat_completions(
                    model=req.model,
                    messages=msgs,
                    stream=False,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                )
                choice = resp.get("choices", [{}])[0]
                msg = choice.get("message", {})
                usage_raw = resp.get("usage", {})
                return IRResponse(
                    id=resp.get("id") or uuid.uuid4().hex[:20],
                    model=req.model,
                    text=msg.get("content", ""),
                    reasoning=msg.get("reasoning_content"),
                    finish_reason=choice.get("finish_reason", "stop"),
                    usage=IRUsage(
                        prompt_tokens=usage_raw.get("prompt_tokens", 0),
                        completion_tokens=usage_raw.get("completion_tokens", 0),
                        total_tokens=usage_raw.get("total_tokens", 0),
                    ),
                )
            except Exception as e:
                logger.warning("直连调用遇到异常 (%s)，自动降级至 Sidecar 桥接", e)
                # 降级至 sidecar
                pass

        # 默认与降级：使用 Sidecar 本地进程桥接
        await sidecar_manager.ensure_running()
        session_id = await sidecar_manager.create_session(f"ZG-{req.model}")
        try:
            msgs = [{"role": m.role, "content": m.content} for m in req.messages]
            raw_data = await sidecar_manager.send_message_non_stream(
                session_id=session_id,
                model_id=req.model,
                messages=msgs,
                system_prompt=req.system_prompt,
            )
            # 解析 parts
            text_buf = []
            reasoning_buf = []
            tokens_dict = {}
            for p in raw_data.get("parts", []):
                p_type = p.get("type")
                if p_type == "text":
                    text_buf.append(p.get("text", ""))
                elif p_type == "reasoning":
                    reasoning_buf.append(p.get("text", ""))
                elif p_type == "step-finish":
                    tokens_dict = p.get("tokens", {})

            if not tokens_dict:
                tokens_dict = raw_data.get("info", {}).get("tokens", {})

            input_tok = tokens_dict.get("input", 0)
            output_tok = tokens_dict.get("output", 0)
            total_tok = tokens_dict.get("total", input_tok + output_tok)
            reason_tok = tokens_dict.get("reasoning", 0)

            return IRResponse(
                id=uuid.uuid4().hex[:20],
                model=req.model,
                text="".join(text_buf),
                reasoning="".join(reasoning_buf) if reasoning_buf else None,
                finish_reason="stop",
                usage=IRUsage(
                    prompt_tokens=input_tok,
                    completion_tokens=output_tok,
                    total_tokens=total_tok,
                    reasoning_tokens=reason_tok,
                ),
            )
        finally:
            await sidecar_manager.delete_session(session_id)

    async def execute_stream(self, req: IRRequest) -> AsyncGenerator[dict[str, Any], None]:
        """执行流式调用并返回统一事件流。"""
        cfg = config_manager.config.server
        mode = cfg.engine_mode.lower()

        if mode == "auto":
            meta = model_registry._models.get(req.model)
            if meta and meta.verification_tier == "heavy":
                mode = "sidecar"
            else:
                mode = "direct"

        if mode == "direct":
            has_yielded = False
            try:
                msgs = [{"role": m.role, "content": m.content} for m in req.messages]
                if req.system_prompt:
                    msgs.insert(0, {"role": "system", "content": req.system_prompt})
                raw_stream = await direct_client.chat_completions(
                    model=req.model,
                    messages=msgs,
                    stream=True,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                )
                import json
                async for line in raw_stream:
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            cj = json.loads(data_str)
                            choice = cj.get("choices", [{}])[0]
                            delta_obj = choice.get("delta", {})
                            if "content" in delta_obj:
                                has_yielded = True
                                yield {"kind": "delta", "field": "text", "delta": delta_obj["content"]}
                            if "reasoning_content" in delta_obj:
                                has_yielded = True
                                yield {"kind": "delta", "field": "reasoning", "delta": delta_obj["reasoning_content"]}
                        except Exception:
                            pass
                yield {"kind": "finish", "tokens": {}}
                return
            except Exception as e:
                if has_yielded:
                    # 避免在已产生部分增量时重跑造成内容重复
                    yield {"kind": "error", "error": f"直连流传输中断: {e}"}
                    return
                logger.warning("直连流式调用启动异常 (%s)，降级至 Sidecar 桥接", e)
                pass

        # 默认与降级：使用 Sidecar 桥接流式
        await sidecar_manager.ensure_running()
        session_id = await sidecar_manager.create_session(f"ZG-Stream-{req.model}")
        try:
            msgs = [{"role": m.role, "content": m.content} for m in req.messages]
            async for ev in sidecar_manager.stream_message(
                session_id=session_id,
                model_id=req.model,
                messages=msgs,
                system_prompt=req.system_prompt,
            ):
                yield ev
        finally:
            await sidecar_manager.delete_session(session_id)


upstream_dispatcher = UpstreamDispatcher()
