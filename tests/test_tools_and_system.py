"""针对外部自定义系统提示词与工具调用的单元测试。"""
import json
import pytest

from app.ir import IRMessage, IRRequest, IRResponse, IRChunkDelta
from app.tools import format_tools_system_instruction, parse_tool_calls_from_text
from app.transform import (
    extract_system_and_messages,
    parse_openai_request,
    parse_anthropic_request,
)
from app.converter.chat_responses import ir_to_openai_response, ir_delta_to_openai_chunk
from app.converter.chat_anthropic import ir_to_anthropic_response
from app.sidecar import sidecar_manager


def test_format_tools_system_instruction():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    instruction = format_tools_system_instruction(tools)
    assert "lookup_weather" in instruction
    assert "<tool_call>" in instruction
    assert "city" in instruction


def test_parse_tool_calls_from_text_xml():
    raw_text = (
        "I will check the weather for you.\n"
        "<tool_call>\n"
        '{"name": "lookup_weather", "arguments": {"city": "Tokyo"}}\n'
        "</tool_call>"
    )
    cleaned, tool_calls = parse_tool_calls_from_text(raw_text)
    assert cleaned == "I will check the weather for you."
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "lookup_weather"
    args = json.loads(tool_calls[0]["function"]["arguments"])
    assert args["city"] == "Tokyo"
    assert tool_calls[0]["id"].startswith("call_")


def test_parse_openai_request_with_tools():
    data = {
        "model": "mimo-v2.6-flash-free",
        "messages": [
            {"role": "system", "content": "You are a helpful bot."},
            {"role": "user", "content": "Check weather in Paris"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Weather lookup",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ],
    }
    req = parse_openai_request(data)
    assert req.tools is not None
    assert len(req.tools) == 1
    assert "get_weather" in req.system_prompt
    assert "You are a helpful bot." in req.system_prompt
    assert "<tool_call>" in req.system_prompt


def test_parse_anthropic_request_with_tools():
    data = {
        "model": "mimo-v2.6-flash-free",
        "system": "You are Claude assistant.",
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
        "tools": [
            {
                "name": "run_sql",
                "description": "Run SQL query",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ],
    }
    req = parse_anthropic_request(data)
    assert req.tools is not None
    assert len(req.tools) == 1
    assert "run_sql" in req.system_prompt
    assert "You are Claude assistant." in req.system_prompt


def test_extract_system_and_messages_preserves_tool_calls():
    raw_msgs = [
        {"role": "system", "content": "Sys prompt"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "test_fn", "arguments": '{"x": 1}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": '{"result": 42}'},
    ]
    sys, msgs = extract_system_and_messages(raw_msgs)
    assert sys == "Sys prompt"
    assert len(msgs) == 2
    assert msgs[0].role == "assistant"
    assert len(msgs[0].tool_calls) == 1
    assert msgs[0].tool_calls[0]["id"] == "call_abc"
    assert msgs[1].role == "tool"
    assert msgs[1].tool_call_id == "call_abc"
    assert msgs[1].content == '{"result": 42}'


def test_openai_response_converter_tool_calls():
    resp = IRResponse(
        id="resp-123",
        model="mimo-v2.6-flash-free",
        text="",
        finish_reason="tool_calls",
        tool_calls=[
            {
                "id": "call_xyz",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"a": 1, "b": 2}'},
            }
        ],
    )
    converted = ir_to_openai_response(resp)
    choice = converted["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    assert len(choice["message"]["tool_calls"]) == 1
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "calculator"


def test_anthropic_response_converter_tool_calls():
    resp = IRResponse(
        id="resp-456",
        model="mimo-v2.6-flash-free",
        text="",
        finish_reason="tool_calls",
        tool_calls=[
            {
                "id": "call_789",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "python"}'},
            }
        ],
    )
    converted = ir_to_anthropic_response(resp)
    assert converted["stop_reason"] == "tool_use"
    assert len(converted["content"]) == 1
    assert converted["content"][0]["type"] == "tool_use"
    assert converted["content"][0]["name"] == "search"
    assert converted["content"][0]["input"] == {"q": "python"}


def test_sidecar_bridge_environment_setup():
    sidecar_manager._setup_bridge_environment()
    bridge_plugin = sidecar_manager._opencode_dir / "plugins" / "zen_bridge.js"
    plugin_code = bridge_plugin.read_text(encoding="utf-8")
    assert "experimental.chat.system.transform" in plugin_code
    assert "output.system = [String(ctx.system).trim()]" in plugin_code

    # 测试会话上下文存取与清理
    sid = "test_ses_999"
    sidecar_manager.set_session_context(sid, system="Custom Sys", temperature=0.7)
    ctx_file = sidecar_manager._opencode_dir / "sessions" / f"{sid}.json"
    assert ctx_file.exists()
    ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
    assert ctx["system"] == "Custom Sys"
    assert ctx["temperature"] == 0.7

    sidecar_manager.clear_session_context(sid)
    assert not ctx_file.exists()


def test_parse_openai_request_enable_thinking():
    # 测试不同层级 extra_body 及 chat_template_kwargs 中的 enable_thinking
    req1 = parse_openai_request({
        "model": "mimo-v2.6-flash-free",
        "messages": [{"role": "user", "content": "hi"}],
        "enable_thinking": False,
    })
    assert req1.enable_thinking is False

    req2 = parse_openai_request({
        "model": "mimo-v2.6-flash-free",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    })
    assert req2.enable_thinking is False

    req3 = parse_openai_request({
        "model": "mimo-v2.6-flash-free",
        "messages": [{"role": "user", "content": "hi"}],
        "reasoning_effort": "none",
    })
    assert req3.enable_thinking is False


def test_stream_openai_generator_reasoning():
    import asyncio
    from app.stream import stream_openai_generator

    async def _test():
        async def mock_stream():
            yield {"kind": "delta", "field": "reasoning", "delta": "Thinking..."}
            yield {"kind": "delta", "field": "text", "delta": "Hello!"}
            yield {"kind": "finish"}

        # 1. 禁用思考：reasoning 被过滤，仅保留 text
        gen_off = stream_openai_generator(mock_stream(), "mimo-v2.6-flash-free", enable_thinking=False)
        chunks_off = [line async for line in gen_off]
        parsed_off = [json.loads(c[6:]) for c in chunks_off if c.startswith("data: ") and not c.startswith("data: [DONE]")]
        reasoning_off = [p["choices"][0]["delta"].get("reasoning_content") for p in parsed_off if p.get("choices") and p["choices"][0]["delta"].get("reasoning_content")]
        content_off = [p["choices"][0]["delta"].get("content") for p in parsed_off if p.get("choices") and p["choices"][0]["delta"].get("content")]
        assert len(reasoning_off) == 0
        assert "Hello!" in content_off

        # 2. 正常流式：reasoning 走 reasoning_content，不混入 content
        gen_on = stream_openai_generator(mock_stream(), "mimo-v2.6-flash-free", enable_thinking=True)
        chunks_on = [line async for line in gen_on]
        parsed_on = [json.loads(c[6:]) for c in chunks_on if c.startswith("data: ") and not c.startswith("data: [DONE]")]
        reasoning_on = [p["choices"][0]["delta"].get("reasoning_content") for p in parsed_on if p.get("choices") and p["choices"][0]["delta"].get("reasoning_content")]
        content_on = [p["choices"][0]["delta"].get("content") for p in parsed_on if p.get("choices") and p["choices"][0]["delta"].get("content")]
        assert "Thinking..." in reasoning_on
        assert "Thinking..." not in content_on
        assert "Hello!" in content_on

    asyncio.run(_test())

