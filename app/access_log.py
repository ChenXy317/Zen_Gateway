"""访问日志与指标统计模块。"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque


@dataclass
class AccessLogEntry:
    """单条访问日志记录。"""
    id: str
    timestamp: float
    time_str: str
    client_ip: str
    method: str
    path: str
    protocol: str
    model: str
    actual_model: str
    status_code: int
    duration_ms: float
    ttft_ms: float | None
    input_tokens: int
    output_tokens: int
    stream: bool
    error: str | None = None


class AccessLogManager:
    """访问日志内存管理器（最大保留 200 条）。"""

    def __init__(self, max_entries: int = 200):
        self._entries: Deque[AccessLogEntry] = deque(maxlen=max_entries)
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._total_tokens: int = 0

    def record(self, entry: AccessLogEntry) -> None:
        """记录一条访问日志并更新统计。"""
        self._entries.appendleft(entry)
        self._total_requests += 1
        self._total_tokens += (entry.input_tokens + entry.output_tokens)
        if entry.status_code >= 400:
            self._total_errors += 1

    def list_entries(
        self,
        limit: int = 50,
        model: str | None = None,
        protocol: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取过滤后的日志列表。"""
        results = []
        for e in self._entries:
            if model and model.lower() not in e.model.lower():
                continue
            if protocol and protocol.lower() != e.protocol.lower():
                continue
            results.append(asdict(e))
            if len(results) >= limit:
                break
        return results

    def get_stats(self) -> dict[str, Any]:
        """获取网关统计指标。"""
        return {
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
            "total_tokens": self._total_tokens,
            "current_logs_count": len(self._entries),
        }

    def clear(self) -> None:
        """清空日志缓存。"""
        self._entries.clear()


access_log = AccessLogManager()
