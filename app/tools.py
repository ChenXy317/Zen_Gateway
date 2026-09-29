"""工具定义解析、指令注入与反向提取工具集。"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any


def format_tools_system_instruction(tools: list[dict[str, Any]]) -> str:
    """将客户端传入的工具定义转换为高保真系统调用规范。"""
    if not tools:
        return ""

    tool_specs = []
    for t in tools:
        if "function" in t:
            fn = t["function"]
            name = fn.get("name", "")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
        else:
            # 兼容 Anthropic 等其他格式
            name = t.get("name", "")
            desc = t.get("description", "")
            params = t.get("input_schema", {})

        spec = {
            "name": name,
            "description": desc,
            "parameters": params,
        }
        tool_specs.append(json.dumps(spec, ensure_ascii=False, indent=2))

    tools_joined = "\n\n".join(tool_specs)

    instruction = (
        "# Function Calling Capability\n\n"
        "You have access to the following set of tools:\n\n"
        f"{tools_joined}\n\n"
        "## Tool Invocation Protocol\n"
        "When you decide to call one or more tools, you MUST format each tool call in the following XML block:\n\n"
        "<tool_call>\n"
        '{"name": "tool_name", "arguments": {"arg_key": "arg_value"}}\n'
        "</tool_call>\n\n"
        "Rules:\n"
        "1. Do not hallucinate tools that are not listed above.\n"
        "2. The JSON inside <tool_call> must be valid and conform to the specified parameter schema.\n"
        "3. You may call multiple tools in succession if needed.\n"
        "4. If no tool is needed, answer normally without the <tool_call> tags."
    )
    return instruction


def parse_tool_calls_from_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """从模型输出文本中反向解析工具调用并分离纯文本。"""
    if not text:
        return text, []

    tool_calls: list[dict[str, Any]] = []

    # 1. 优先匹配 <tool_call>...</tool_call>
    pattern = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
    matches = list(pattern.finditer(text))

    if matches:
        cleaned_text = pattern.sub("", text).strip()
        for m in matches:
            raw_json = m.group(1).strip()
            # 剥离可能存在的 markdown 代码块包裹
            if raw_json.startswith("```"):
                raw_json = re.sub(r"^```[a-zA-Z]*\n?", "", raw_json)
                raw_json = re.sub(r"\n?```$", "", raw_json).strip()

            try:
                parsed = json.loads(raw_json)
                fn_name = parsed.get("name")
                fn_args = parsed.get("arguments", {})
                if isinstance(fn_args, dict):
                    fn_args_str = json.dumps(fn_args, ensure_ascii=False)
                else:
                    fn_args_str = str(fn_args)

                if fn_name:
                    tool_calls.append({
                        "id": f"call_{uuid.uuid4().hex[:18]}",
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": fn_args_str,
                        },
                    })
            except Exception:
                pass

        return cleaned_text, tool_calls

    # 2. 备用兜底匹配：纯 markdown 代码块声明的 tool_call
    alt_pattern = re.compile(r"```(?:tool_call|function_call|json:tool)\s*\n(.*?)\n```", re.DOTALL)
    alt_matches = list(alt_pattern.finditer(text))
    if alt_matches:
        cleaned_text = alt_pattern.sub("", text).strip()
        for m in alt_matches:
            raw_json = m.group(1).strip()
            try:
                parsed = json.loads(raw_json)
                fn_name = parsed.get("name")
                fn_args = parsed.get("arguments", {})
                if isinstance(fn_args, dict):
                    fn_args_str = json.dumps(fn_args, ensure_ascii=False)
                else:
                    fn_args_str = str(fn_args)

                if fn_name:
                    tool_calls.append({
                        "id": f"call_{uuid.uuid4().hex[:18]}",
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": fn_args_str,
                        },
                    })
            except Exception:
                pass
        return cleaned_text, tool_calls

    return text, []
