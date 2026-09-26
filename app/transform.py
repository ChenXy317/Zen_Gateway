"""外部请求转换至统一 IR 及统一错误格式封装。"""
from __future__ import annotations

from typing import Any

from .config import config_manager
from .ir import IRMessage, IRRequest
from .models import model_registry


def extract_system_and_messages(raw_messages: list[dict[str, Any]]) -> tuple[str | None, list[IRMessage]]:
    """提取独立系统提示词与常规对话序列。"""
    system_prompts = []
    messages = []
    for m in raw_messages:
        role = m.get("role", "user")
        raw_content = m.get("content", "")
        if isinstance(raw_content, list):
            # 展平多段文本内容
            buf = []
            for item in raw_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    buf.append(item.get("text", ""))
                elif isinstance(item, str):
                    buf.append(item)
            content = "\n".join(buf)
        else:
            content = str(raw_content or "")

        if role == "system":
            system_prompts.append(content)
        else:
            messages.append(IRMessage(role=role, content=content, name=m.get("name")))

    sys = "\n\n".join(system_prompts) if system_prompts else None
    return sys, messages


def parse_openai_request(data: dict[str, Any]) -> IRRequest:
    """解析 OpenAI /v1/chat/completions 入站请求。"""
    raw_model = data.get("model") or config_manager.config.server.default_model
    actual_model = model_registry.resolve_model(raw_model)
    raw_msgs = data.get("messages", [])
    sys_prompt, messages = extract_system_and_messages(raw_msgs)

    return IRRequest(
        model=actual_model,
        messages=messages,
        stream=bool(data.get("stream", False)),
        system_prompt=sys_prompt,
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens") or data.get("max_completion_tokens"),
        protocol="openai",
    )


def parse_anthropic_request(data: dict[str, Any]) -> IRRequest:
    """解析 Anthropic /v1/messages 入站请求。"""
    raw_model = data.get("model") or config_manager.config.server.default_model
    actual_model = model_registry.resolve_model(raw_model)
    raw_msgs = data.get("messages", [])
    sys_field = data.get("system")
    system_prompt = None
    if isinstance(sys_field, str):
        system_prompt = sys_field
    elif isinstance(sys_field, list):
        system_prompt = "\n\n".join(
            item.get("text", "") for item in sys_field if isinstance(item, dict) and item.get("type") == "text"
        )

    _, messages = extract_system_and_messages(raw_msgs)

    return IRRequest(
        model=actual_model,
        messages=messages,
        stream=bool(data.get("stream", False)),
        system_prompt=system_prompt,
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens"),
        protocol="anthropic",
    )


def error_payload(status_code: int, message: str, protocol: str = "openai") -> dict[str, Any]:
    """生成符合协议标准的错误报文。"""
    if protocol == "anthropic":
        return {
            "type": "error",
            "error": {
                "type": "invalid_request_error" if status_code < 500 else "api_error",
                "message": message,
            },
        }
    return {
        "error": {
            "message": message,
            "type": "invalid_request_error" if status_code < 500 else "server_error",
            "param": None,
            "code": status_code,
        }
    }
