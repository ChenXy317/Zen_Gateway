"""OpenCode 模型列表与映射管理模块。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelMeta:
    """模型元数据定义。"""
    id: str
    name: str
    provider: str
    is_free: bool
    verification_tier: str  # "heavy" | "light" | "standard"
    description: str
    context_window: int = 128000
    support_reasoning: bool = False


# 内置免费模型与精选模型库
DEFAULT_MODELS: list[ModelMeta] = [
    ModelMeta(
        id="mimo-v2.6-flash-free",
        name="Mimo v2.6 Flash (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="heavy",
        description="OpenCode 官方免费旗舰模型，支持思考链推理，高准确率与低延迟",
        context_window=128000,
        support_reasoning=True,
    ),
    ModelMeta(
        id="space-bunny-free",
        name="Space Bunny (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="light",
        description="极速轻量免费模型，轻量级代码补全与日常问答",
        context_window=64000,
        support_reasoning=False,
    ),
    ModelMeta(
        id="ling-3.0-flash-fin-free",
        name="Ling 3.0 Flash Fin (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="heavy",
        description="专精结构化逻辑与快速分析的官方免费模型",
        context_window=128000,
        support_reasoning=False,
    ),
    ModelMeta(
        id="nemotron-3-ultra-free",
        name="Nemotron 3 Ultra (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="heavy",
        description="Nvidia Nemotron 架构大容量免费模型，优秀的复杂上下文处理",
        context_window=128000,
        support_reasoning=False,
    ),
    ModelMeta(
        id="nemotron-3.5-lightning-free",
        name="Nemotron 3.5 Lightning (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="light",
        description="极致低首字延迟免费模型，适合高频补全与实时转接",
        context_window=64000,
        support_reasoning=False,
    ),
    ModelMeta(
        id="muse-spark-1.3-contributor-free",
        name="Muse Spark 1.3 Contributor (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="heavy",
        description="社区贡献者专属免费模型，优秀的自然语言理解",
        context_window=64000,
        support_reasoning=False,
    ),
]


class ModelRegistry:
    """模型仓库与别名映射管理器。"""

    def __init__(self) -> None:
        self._models: dict[str, ModelMeta] = {m.id: m for m in DEFAULT_MODELS}
        # 默认外部别名映射
        self._aliases: dict[str, str] = {
            "gpt-4o": "mimo-v2.6-flash-free",
            "gpt-4o-mini": "space-bunny-free",
            "gpt-3.5-turbo": "space-bunny-free",
            "claude-3-5-sonnet": "mimo-v2.6-flash-free",
            "claude-3-5-haiku": "space-bunny-free",
            "claude-3-sonnet-20240229": "mimo-v2.6-flash-free",
        }

    def resolve_model(self, model_name: str, default: str = "mimo-v2.6-flash-free") -> str:
        """根据模型名称或别名解析出真实模型 ID。"""
        if not model_name:
            return default
        raw = model_name.strip()
        # 处理可能的前缀，例如 opencode/mimo-v2.6-flash-free
        if raw.startswith("opencode/"):
            raw = raw[len("opencode/"):]

        if raw in self._models:
            return raw
        if raw in self._aliases:
            return self._aliases[raw]
        # 模糊匹配或保持原样
        for k in self._models:
            if raw.lower() == k.lower():
                return k
        return raw

    def list_models(self) -> list[dict[str, Any]]:
        """获取所有已注册的官方免费模型元信息。"""
        res = []
        for m in self._models.values():
            if not m.is_free:
                continue
            res.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "is_free": m.is_free,
                "verification_tier": m.verification_tier,
                "description": m.description,
                "context_window": m.context_window,
                "support_reasoning": m.support_reasoning,
            })
        return res

    def get_aliases(self) -> dict[str, str]:
        """获取当前模型别名映射表。"""
        return dict(self._aliases)

    def set_aliases(self, aliases: dict[str, str]) -> None:
        """更新模型别名映射表。"""
        self._aliases = dict(aliases)

    async def sync_free_models(self, sidecar_base_url: str = "http://127.0.0.1:4096") -> dict[str, Any]:
        """从官方 Sidecar 或云端动态同步最新免费模型列表与元数据。"""
        import httpx
        from .auth import opencode_auth

        source = "sidecar"
        free_models_raw: dict[str, dict[str, Any]] = {}

        # 优先从本地 Sidecar 获取完整元数据
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(f"{sidecar_base_url}/provider")
                if r.status_code == 200:
                    data = r.json()
                    for p in data.get("all", []):
                        if p.get("id") == "opencode":
                            for mid, mdict in p.get("models", {}).items():
                                if mid.endswith("-free"):
                                    free_models_raw[mid] = mdict
        except Exception:
            pass

        # 降级：从官方 Zen API 获取
        if not free_models_raw:
            source = "cloud"
            try:
                creds = opencode_auth.get_credentials()
                headers = {
                    "User-Agent": f"opencode/{creds.cli_version or '1.18.30'}/cli",
                    "x-opencode-client": "cli",
                }
                if creds.api_key:
                    headers["Authorization"] = f"Bearer {creds.api_key}"

                async with httpx.AsyncClient(timeout=8.0) as client:
                    r = await client.get("https://opencode.ai/zen/v1/models", headers=headers)
                    if r.status_code == 200:
                        data = r.json()
                        m_list = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                        for item in m_list:
                            mid = item.get("id", "")
                            if mid.endswith("-free"):
                                free_models_raw[mid] = {
                                    "id": mid,
                                    "name": mid.replace("-free", "").replace("-", " ").title() + " (Free)",
                                }
            except Exception:
                pass

        if not free_models_raw:
            return {"status": "unchanged", "total": len(self.list_models()), "added": [], "source": "none"}

        added: list[str] = []
        for mid, meta in free_models_raw.items():
            name = meta.get("name") or (mid.replace("-free", "").replace("-", " ").title() + " (Free)")
            limits = meta.get("limit") or {}
            caps = meta.get("capabilities") or {}

            context_window = limits.get("context", 128000)
            support_reasoning = bool(caps.get("reasoning", False) or "mimo" in mid.lower() or "longcat" in mid.lower())
            verification_tier = "light" if ("bunny" in mid.lower() or "lightning" in mid.lower() or "preview" in mid.lower()) else "heavy"

            desc = f"OpenCode 官方免费层模型，上下文 {context_window // 1000}k"
            if support_reasoning:
                desc += "，支持深度思考链"

            if mid not in self._models:
                added.append(mid)
                self._models[mid] = ModelMeta(
                    id=mid,
                    name=name,
                    provider="opencode",
                    is_free=True,
                    verification_tier=verification_tier,
                    description=desc,
                    context_window=context_window,
                    support_reasoning=support_reasoning,
                )
            else:
                existing = self._models[mid]
                existing.name = name
                existing.context_window = context_window
                existing.support_reasoning = support_reasoning

        return {
            "status": "ok",
            "total": len(self.list_models()),
            "added": added,
            "source": source,
        }


model_registry = ModelRegistry()
