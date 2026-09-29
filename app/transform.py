"""外部请求转换至统一 IR 及统一错误格式封装。"""
from __future__ import annotations

from typing import Any

from .config import config_manager
from .ir import IRMessage, IRRequest
from .models import model_registry


import json


def extract_system_and_messages(raw_messages: list[dict[str, Any]]) -> tuple[str | None, list[IRMessage]]:
    """提取独立系统提示词与常规对话序列，精确保留工具调用结构。"""
    system_prompts = []
    messages = []
    for m in raw_messages:
        role = m.get("role", "user")
        raw_content = m.get("content", "")
        tool_calls = list(m.get("tool_calls", []))
        tool_call_id = m.get("tool_call_id")

        if isinstance(raw_content, list):
            buf = []
            for item in raw_content:
                if isinstance(item, dict):
                    t = item.get("type")
                    if t == "text":
                        buf.append(item.get("text", ""))
                    elif t == "tool_use":
                        tool_calls.append({
                            "id": item.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": json.dumps(item.get("input", {}), ensure_ascii=False),
                            },
                        })
                    elif t == "tool_result":
                        role = "tool"
                        tool_call_id = item.get("tool_use_id")
                        res_val = item.get("content", "")
                        if isinstance(res_val, list):
                            sub = [b.get("text", "") for b in res_val if isinstance(b, dict) and b.get("type") == "text"]
                            res_val = "\n".join(sub)
                        buf.append(str(res_val))
                    elif t == "thinking":
                        buf.append(item.get("thinking", ""))
                elif isinstance(item, str):
                    buf.append(item)
            content = "\n".join(buf)
        else:
            content = str(raw_content or "")

        if role == "system":
            system_prompts.append(content)
        else:
            messages.append(IRMessage(
                role=role,
                content=content,
                name=m.get("name"),
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            ))

    sys = "\n\n".join(system_prompts) if system_prompts else None
    return sys, messages



from .skills import skill_registry


def resolve_model_and_skills(raw_model_str: str) -> tuple[str, list[str]]:
    """解析模型名称中附带的技能后缀（例如 model+skill1+skill2）。"""
    if "+" not in raw_model_str:
        return raw_model_str, []
    tokens = raw_model_str.split("+")
    base_model = tokens[0].strip()
    skills = [t.strip() for t in tokens[1:] if t.strip()]
    return base_model, skills


def apply_profile_to_request(req: IRRequest, dynamic_skills: list[str] | None = None) -> IRRequest:
    """根据全局与模型专属 Profile 装配系统提示词、超参数、技能及 Agent。"""
    global_prof, model_prof = config_manager.get_profile_for_model(req.model)

    # 1. 确定生效的提示词与合并策略
    target_sys = ""
    target_mode = "prepend"
    if model_prof and model_prof.system_prompt:
        target_sys = model_prof.system_prompt
        target_mode = model_prof.system_prompt_mode
    elif global_prof.system_prompt:
        target_sys = global_prof.system_prompt
        target_mode = global_prof.system_prompt_mode

    client_sys = req.system_prompt or ""
    if target_sys:
        if target_mode == "override":
            req.system_prompt = target_sys
        elif target_mode == "append":
            req.system_prompt = f"{client_sys}\n\n{target_sys}".strip() if client_sys else target_sys
        elif target_mode == "fallback":
            req.system_prompt = client_sys if client_sys else target_sys
        else:  # prepend
            req.system_prompt = f"{target_sys}\n\n{client_sys}".strip() if client_sys else target_sys

    # 2. 确定超参数（模型 Profile 优先，再看全局 Profile）
    force = (model_prof.force_hyperparams if model_prof else False) or global_prof.force_hyperparams

    prof_temp = (model_prof.temperature if model_prof and model_prof.temperature is not None else global_prof.temperature)
    if force and prof_temp is not None:
        req.temperature = prof_temp
    elif req.temperature is None and prof_temp is not None:
        req.temperature = prof_temp

    prof_top_p = (model_prof.top_p if model_prof and model_prof.top_p is not None else global_prof.top_p)
    if force and prof_top_p is not None:
        req.top_p = prof_top_p
    elif req.top_p is None and prof_top_p is not None:
        req.top_p = prof_top_p

    prof_max_tokens = (model_prof.max_tokens if model_prof and model_prof.max_tokens is not None else global_prof.max_tokens)
    if force and prof_max_tokens is not None:
        req.max_tokens = prof_max_tokens
    elif req.max_tokens is None and prof_max_tokens is not None:
        req.max_tokens = prof_max_tokens

    prof_reasoning = (model_prof.reasoning_effort if model_prof and model_prof.reasoning_effort else global_prof.reasoning_effort)
    if force and prof_reasoning:
        req.reasoning_effort = prof_reasoning
    elif not req.reasoning_effort and prof_reasoning:
        req.reasoning_effort = prof_reasoning

    # 3. 收集并装配 Skills
    active_skills: list[str] = []
    if global_prof.active_skills:
        active_skills.extend(global_prof.active_skills)
    if model_prof and model_prof.active_skills:
        active_skills.extend(model_prof.active_skills)
    if dynamic_skills:
        active_skills.extend(dynamic_skills)

    # 去重
    unique_skills = []
    for s in active_skills:
        if s and s not in unique_skills:
            unique_skills.append(s)
    req.skills = unique_skills

    # 4. 确定绑定的 Agent
    agent = (model_prof.agent if model_prof and model_prof.agent else global_prof.agent)
    if agent:
        req.agent = agent

    return req


from .tools import format_tools_system_instruction


def parse_openai_request(data: dict[str, Any], header_skills: list[str] | None = None) -> IRRequest:
    """解析 OpenAI /v1/chat/completions 入站请求并执行能力装配。"""
    raw_input_model = data.get("model") or config_manager.config.server.default_model or model_registry.get_first_model_id()
    base_model_name, inline_skills = resolve_model_and_skills(raw_input_model)
    actual_model = model_registry.resolve_model(base_model_name)

    raw_msgs = data.get("messages", [])
    sys_prompt, messages = extract_system_and_messages(raw_msgs)

    tools = data.get("tools", [])
    tool_choice = data.get("tool_choice")
    if tools:
        tool_instruction = format_tools_system_instruction(tools)
        if sys_prompt:
            sys_prompt = f"{sys_prompt}\n\n{tool_instruction}".strip()
        else:
            sys_prompt = tool_instruction

    combined_dynamic_skills = list(inline_skills)
    if header_skills:
        combined_dynamic_skills.extend(header_skills)

    req = IRRequest(
        model=actual_model,
        messages=messages,
        stream=bool(data.get("stream", False)),
        system_prompt=sys_prompt,
        temperature=data.get("temperature"),
        top_p=data.get("top_p"),
        max_tokens=data.get("max_tokens") or data.get("max_completion_tokens"),
        reasoning_effort=data.get("reasoning_effort"),
        tools=tools,
        tool_choice=tool_choice,
        protocol="openai",
    )

    return apply_profile_to_request(req, combined_dynamic_skills)


def parse_anthropic_request(data: dict[str, Any], header_skills: list[str] | None = None) -> IRRequest:
    """解析 Anthropic /v1/messages 入站请求并执行能力装配。"""
    raw_input_model = data.get("model") or config_manager.config.server.default_model or model_registry.get_first_model_id()
    base_model_name, inline_skills = resolve_model_and_skills(raw_input_model)
    actual_model = model_registry.resolve_model(base_model_name)

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

    tools = data.get("tools", [])
    if tools:
        tool_instruction = format_tools_system_instruction(tools)
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{tool_instruction}".strip()
        else:
            system_prompt = tool_instruction

    combined_dynamic_skills = list(inline_skills)
    if header_skills:
        combined_dynamic_skills.extend(header_skills)

    req = IRRequest(
        model=actual_model,
        messages=messages,
        stream=bool(data.get("stream", False)),
        system_prompt=system_prompt,
        temperature=data.get("temperature"),
        top_p=data.get("top_p"),
        max_tokens=data.get("max_tokens"),
        tools=tools,
        protocol="anthropic",
    )

    return apply_profile_to_request(req, combined_dynamic_skills)



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
