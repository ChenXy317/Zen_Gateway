"""内部统一协议中间表示（IR）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IRMessage:
    """标准消息结构。"""
    role: str
    content: str
    name: str | None = None


@dataclass
class IRRequest:
    """网关内部标准请求。"""
    model: str
    messages: list[IRMessage]
    stream: bool = False
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    protocol: str = "openai"  # openai | anthropic


@dataclass
class IRUsage:
    """Token 消耗统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class IRResponse:
    """网关内部标准完整响应。"""
    id: str
    model: str
    text: str
    reasoning: str | None = None
    finish_reason: str = "stop"
    usage: IRUsage = field(default_factory=IRUsage)


@dataclass
class IRChunkDelta:
    """流式增量 Chunk。"""
    text: str | None = None
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: IRUsage | None = None
