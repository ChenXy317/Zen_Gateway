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
class AppConfig:
    """网关全局配置聚合体。"""
    server: ServerConfig = field(default_factory=ServerConfig)
    model_aliases: dict[str, str] = field(default_factory=dict)


class ConfigManager:
    """配置文件读取、验证与持久化。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path(__file__).resolve().parent.parent / "config.json"
        self.config = AppConfig()
        self.load()

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
                return
            except Exception:
                pass

        # 默认配置初始化
        self.config.model_aliases = model_registry.get_aliases()
        self.save()

    def save(self) -> None:
        """将当前内存配置持久化写入磁盘。"""
        payload = {
            "server": asdict(self.config.server),
            "model_aliases": self.config.model_aliases,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

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
        }


config_manager = ConfigManager()
