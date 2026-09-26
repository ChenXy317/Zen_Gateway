"""敏感数据脱敏与安全打码工具。"""
from __future__ import annotations

from typing import Any, Iterable


def redact(val: str | None, prefix_len: int = 6, suffix_len: int = 4) -> str:
    """对敏感字符串进行掩码脱敏显示。"""
    if not val:
        return ""
    s = str(val).strip()
    if len(s) <= prefix_len + suffix_len:
        return "..."
    return f"{s[:prefix_len]}...{s[-suffix_len:]}"


def collect_secrets(*values: str | None) -> list[str]:
    """收集非空敏感字符列表。"""
    res = []
    for v in values:
        if v and len(str(v).strip()) >= 4:
            res.append(str(v).strip())
    return res


def redact_text(text: str, secrets: Iterable[str]) -> str:
    """在文本中查找敏感词并替换为掩码。"""
    if not text:
        return ""
    result = text
    for sec in secrets:
        if sec and sec in result:
            result = result.replace(sec, redact(sec))
    return result


def redact_any(obj: Any, secrets: Iterable[str]) -> Any:
    """递归脱敏字典、列表或字符串中的敏感信息。"""
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    if isinstance(obj, dict):
        return {k: redact_any(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_any(x, secrets) for x in obj]
    return obj
