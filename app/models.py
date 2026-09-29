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


class ModelRegistry:
    """模型仓库与别名映射管理器。"""

    def __init__(self) -> None:
        self._models: dict[str, ModelMeta] = {}
        self._aliases: dict[str, str] = {}

    def get_first_model_id(self) -> str:
        """获取已加载的首个官方可用模型 ID。"""
        for mid in self._models:
            return mid
        return ""

    def resolve_model(self, model_name: str, default: str | None = None) -> str:
        """根据模型名称或别名解析出真实模型 ID。"""
        fallback = default or self.get_first_model_id()
        if not model_name:
            return fallback
        raw = model_name.strip()
        if raw.startswith("opencode/"):
            raw = raw[len("opencode/"):]

        if raw in self._models:
            return raw
        if raw in self._aliases:
            return self._aliases[raw]
        for k in self._models:
            if raw.lower() == k.lower():
                return k
        return raw or fallback

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

    async def sync_free_models(self, sidecar_base_url: str = "http://127.0.0.1:4098") -> dict[str, Any]:
        """从官方 Sidecar 或云端动态同步最新免费模型列表与元数据。"""
        import httpx
        from .auth import opencode_auth

        source = "sidecar"
        free_models_raw: dict[str, dict[str, Any]] = {}

        # 优先从本地 Sidecar 获取权威元数据
        try:
            async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
                r = await client.get(f"{sidecar_base_url}/provider")
                if r.status_code == 200:
                    data = r.json()
                    for p in data.get("all", []):
                        if p.get("id") == "opencode":
                            for mid, mdict in p.get("models", {}).items():
                                cost = mdict.get("cost", {})
                                is_zero_cost = (cost.get("input", 1) == 0 and cost.get("output", 1) == 0)
                                if mid.endswith("-free") or is_zero_cost:
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

        # 若成功拉取到官方 Sidecar 数据，清理已下线的过时历史免费模型
        if source == "sidecar":
            stale_keys = [
                k for k, v in self._models.items()
                if v.provider == "opencode" and v.is_free and k not in free_models_raw
            ]
            for sk in stale_keys:
                del self._models[sk]

        added: list[str] = []
        for mid, meta in free_models_raw.items():
            name = meta.get("name") or (mid.replace("-free", "").replace("-", " ").title() + " (Free)")
            limits = meta.get("limit") or {}
            caps = meta.get("capabilities") or {}
            inputs = caps.get("input") or {}

            context_window = limits.get("context", 128000)
            output_limit = limits.get("output", 32000)
            support_reasoning = bool(caps.get("reasoning", False))
            has_multimodal = bool(inputs.get("image") or inputs.get("audio") or inputs.get("video"))
            verification_tier = "light" if ("bunny" in mid.lower() or "lightning" in mid.lower()) else "heavy"

            ctx_text = f"{context_window // 1000000}M" if context_window >= 1000000 else f"{context_window // 1000}k"
            out_text = f"{output_limit // 1000}k" if output_limit else ""

            features = []
            if has_multimodal:
                features.append("多模态")
            if support_reasoning:
                features.append("深度思考链")
            feature_str = f"，支持{'/'.join(features)}" if features else ""
            desc = f"输入 {ctx_text}" + (f" / 输出 {out_text}" if out_text else "") + feature_str

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
                existing.description = desc
                existing.verification_tier = verification_tier

        return {
            "status": "ok",
            "total": len(self.list_models()),
            "first_model": self.get_first_model_id(),
            "added": added,
            "source": source,
        }


model_registry = ModelRegistry()
