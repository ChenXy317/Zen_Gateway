"""网关配置加载与持久化管理。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import model_registry
from .secrets import redact


def is_public_bind(host: str) -> bool:
    """判断监听地址是否暴露给外部公网或局域网。"""
    h = (host or "").strip().lower()
    return h in ("0.0.0.0", "::", "") or not (h == "127.0.0.1" or h == "localhost" or h.startswith("127."))


def effective_bind_host(host: str) -> str:
    """返回实际绑定的安全主机地址。"""
    h = (host or "").strip()
    return h if h else "127.0.0.1"


@dataclass
class ServerConfig:
    """网关服务器网络与安全配置。"""
    host: str = "127.0.0.1"
    port: int = 8790
    local_api_key: str = ""
    admin_api_key: str = ""
    default_model: str = ""
    engine_mode: str = "sidecar"  # sidecar | direct | auto
    sidecar_host: str = "127.0.0.1"
    sidecar_port: int = 4096
    auto_start_sidecar: bool = True
    timeout_seconds: float = 120.0


@dataclass
class ProfileConfig:
    """模型或全局运行态预设配置。"""
    system_prompt: str = ""
    system_prompt_mode: str = "prepend"  # prepend | append | override | fallback
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None  # low | medium | high | none
    force_hyperparams: bool = False
    active_skills: list[str] = field(default_factory=list)
    agent: str = ""


@dataclass
class ProfilesConfig:
    """预设配置集合（全局与各模型专属）。"""
    global_profile: ProfileConfig = field(default_factory=ProfileConfig)
    models: dict[str, ProfileConfig] = field(default_factory=dict)


@dataclass
class AppConfig:
    """网关全局配置聚合体。"""
    server: ServerConfig = field(default_factory=ServerConfig)
    model_aliases: dict[str, str] = field(default_factory=dict)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)


class ConfigManager:
    """配置文件读取、验证与持久化。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path(__file__).resolve().parent.parent / "config.json"
        self.config = AppConfig()
        self.load()

    def _parse_profile(self, data: dict[str, Any]) -> ProfileConfig:
        """从字典解析单个 ProfileConfig。"""
        return ProfileConfig(
            system_prompt=str(data.get("system_prompt", "") or ""),
            system_prompt_mode=str(data.get("system_prompt_mode", "prepend") or "prepend"),
            temperature=float(data["temperature"]) if data.get("temperature") is not None else None,
            top_p=float(data["top_p"]) if data.get("top_p") is not None else None,
            max_tokens=int(data["max_tokens"]) if data.get("max_tokens") is not None else None,
            reasoning_effort=str(data["reasoning_effort"]) if data.get("reasoning_effort") else None,
            force_hyperparams=bool(data.get("force_hyperparams", False)),
            active_skills=list(data.get("active_skills", []) or []),
            agent=str(data.get("agent", "") or ""),
        )

    def load(self) -> None:
        """从磁盘加载配置，不存在则从默认生成。"""
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                srv = data.get("server", {})
                self.config.server = ServerConfig(
                    host=srv.get("host", "127.0.0.1"),
                    port=int(srv.get("port", 8790)),
                    local_api_key=srv.get("local_api_key", ""),
                    admin_api_key=srv.get("admin_api_key", ""),
                    default_model=srv.get("default_model", ""),
                    engine_mode=srv.get("engine_mode", "sidecar"),
                    sidecar_host=srv.get("sidecar_host", "127.0.0.1"),
                    sidecar_port=int(srv.get("sidecar_port", 4096)),
                    auto_start_sidecar=bool(srv.get("auto_start_sidecar", True)),
                    timeout_seconds=float(srv.get("timeout_seconds", 120.0)),
                )
                aliases = data.get("model_aliases", {})
                if aliases:
                    self.config.model_aliases = aliases
                    model_registry.set_aliases(aliases)

                prof_data = data.get("profiles", {})
                global_prof = self._parse_profile(prof_data.get("global", {}))
                model_profs = {}
                for m_id, m_cfg in prof_data.get("models", {}).items():
                    if isinstance(m_cfg, dict):
                        model_profs[m_id] = self._parse_profile(m_cfg)
                self.config.profiles = ProfilesConfig(global_profile=global_prof, models=model_profs)
                return
            except Exception:
                pass

        # 默认配置初始化
        self.config.model_aliases = model_registry.get_aliases()
        self.config.profiles = ProfilesConfig()
        self.save()

    def save(self) -> None:
        """将当前内存配置持久化写入磁盘。"""
        payload = {
            "server": asdict(self.config.server),
            "model_aliases": self.config.model_aliases,
            "profiles": {
                "global": asdict(self.config.profiles.global_profile),
                "models": {k: asdict(v) for k, v in self.config.profiles.models.items()},
            },
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def get_profile_for_model(self, model_name: str) -> tuple[ProfileConfig, ProfileConfig | None]:
        """获取适用于该模型的全局 Profile 及模型专属 Profile（若存在）。"""
        actual_model = model_registry.resolve_model(model_name)
        model_prof = self.config.profiles.models.get(actual_model) or self.config.profiles.models.get(model_name)
        return self.config.profiles.global_profile, model_prof

    def update_profiles(self, profiles_data: dict[str, Any]) -> None:
        """更新并持久化全局与模型专属 Profile。"""
        if "global" in profiles_data and isinstance(profiles_data["global"], dict):
            self.config.profiles.global_profile = self._parse_profile(profiles_data["global"])

        if "models" in profiles_data and isinstance(profiles_data["models"], dict):
            new_models = {}
            for m_id, m_cfg in profiles_data["models"].items():
                if isinstance(m_cfg, dict):
                    new_models[m_id] = self._parse_profile(m_cfg)
            self.config.profiles.models = new_models

        self.save()

    def to_public_dict(self) -> dict[str, Any]:
        """导出用于前端安全展示的公开字典。"""
        srv = asdict(self.config.server)
        raw_local = srv.pop("local_api_key", "")
        raw_admin = srv.pop("admin_api_key", "")
        srv["has_local_api_key"] = bool(raw_local)
        srv["has_admin_api_key"] = bool(raw_admin)
        srv["local_api_key_masked"] = redact(raw_local) if raw_local else ""
        srv["admin_api_key_masked"] = redact(raw_admin) if raw_admin else ""
        return {
            "server": srv,
            "model_aliases": self.config.model_aliases,
            "profiles": {
                "global": asdict(self.config.profiles.global_profile),
                "models": {k: asdict(v) for k, v in self.config.profiles.models.items()},
            },
        }


config_manager = ConfigManager()
