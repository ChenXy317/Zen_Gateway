"""OpenCode 本地凭据与 CLI 探测模块。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .secrets import redact


@dataclass
class OpenCodeCredentials:
    """OpenCode 凭据数据结构。"""
    logged_in: bool
    api_key: str | None = None
    masked_key: str | None = None
    auth_file: str | None = None
    provider_name: str | None = None
    cli_path: str | None = None
    cli_version: str | None = None
    error: str | None = None


class OpenCodeAuthManager:
    """管理 OpenCode 凭据与运行时检测。"""

    def __init__(self) -> None:
        self._cached: OpenCodeCredentials | None = None

    def find_auth_file(self) -> Path | None:
        """寻找本地 auth.json 文件路径。"""
        candidates = [
            os.environ.get("OPENCODE_AUTH_PATH"),
            Path.home() / ".local" / "share" / "opencode" / "auth.json",
            Path.home() / ".config" / "opencode" / "auth.json",
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "opencode" / "auth.json")

        for c in candidates:
            if c:
                p = Path(c)
                if p.is_file():
                    return p
        return None

    def find_cli_executable(self) -> str | None:
        """探测本地 opencode 可执行文件路径。"""
        # 优先检测常见的全局 npm 安装路径
        appdata = os.environ.get("APPDATA")
        if appdata:
            exe_candidate = Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
            if exe_candidate.is_file():
                return str(exe_candidate)

        which_path = shutil.which("opencode")
        if which_path:
            return which_path
        return None

    def get_cli_version(self, cli_path: str | None) -> str | None:
        """获取本地 OpenCode CLI 版本号。"""
        if not cli_path:
            return None
        try:
            res = subprocess.run([cli_path, "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return res.stdout.strip().splitlines()[0]
        except Exception:
            pass
        return None

    def get_credentials(self, force_reload: bool = False) -> OpenCodeCredentials:
        """获取或刷新当前凭据状态。"""
        if self._cached and not force_reload:
            return self._cached

        cli_path = self.find_cli_executable()
        cli_ver = self.get_cli_version(cli_path)

        auth_path = self.find_auth_file()
        if not auth_path:
            self._cached = OpenCodeCredentials(
                logged_in=False,
                cli_path=cli_path,
                cli_version=cli_ver,
                error="未找到 OpenCode 凭据文件 (~/.local/share/opencode/auth.json)，请先在终端运行 opencode 完成登录",
            )
            return self._cached

        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 支持从 opencode 或 opencode-go 取凭据
            api_key = None
            provider = None
            for p in ["opencode", "opencode-go"]:
                if p in data and isinstance(data[p], dict):
                    k = data[p].get("key") or data[p].get("apiKey")
                    if k:
                        api_key = k
                        provider = p
                        break

            if not api_key:
                self._cached = OpenCodeCredentials(
                    logged_in=False,
                    auth_file=str(auth_path),
                    cli_path=cli_path,
                    cli_version=cli_ver,
                    error="auth.json 中未包含有效的 key 字段",
                )
                return self._cached

            self._cached = OpenCodeCredentials(
                logged_in=True,
                api_key=api_key,
                masked_key=redact(api_key, prefix_len=8, suffix_len=6),
                auth_file=str(auth_path),
                provider_name=provider,
                cli_path=cli_path,
                cli_version=cli_ver,
            )
            return self._cached
        except Exception as e:
            self._cached = OpenCodeCredentials(
                logged_in=False,
                auth_file=str(auth_path),
                cli_path=cli_path,
                cli_version=cli_ver,
                error=f"解析 auth.json 失败: {e}",
            )
            return self._cached

    def to_dict(self) -> dict[str, Any]:
        """导出用于前端展示的凭据信息字典。"""
        c = self.get_credentials()
        return {
            "logged_in": c.logged_in,
            "masked_key": c.masked_key,
            "provider_name": c.provider_name,
            "auth_file": c.auth_file,
            "cli_path": c.cli_path,
            "cli_version": c.cli_version,
            "error": c.error,
        }


opencode_auth = OpenCodeAuthManager()
