"""OpenCode 本地进程与 Sidecar 中继管理。"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from typing import Any, AsyncGenerator

import httpx

from .auth import opencode_auth
from .config import config_manager

logger = logging.getLogger("zen_gateway.sidecar")


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """检查指定主机与端口是否处于空闲可绑定状态。"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(preferred_port: int, host: str = "127.0.0.1") -> int:
    """寻找首个空闲端口，优先使用首选配置端口。"""
    if is_port_available(preferred_port, host):
        return preferred_port

    candidates = [14096, 14097, 14098, 4097, 4099, 4100, 4101]
    for p in candidates:
        if p != preferred_port and is_port_available(p, host):
            return p

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class SidecarManager:
    """OpenCode 本地进程与 HTTP 中继客户端管理器。"""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._is_managed: bool = False
        self._last_health_check: float = 0.0
        self._cached_healthy: bool = False
        self._client: httpx.AsyncClient | None = None
        self._active_port: int | None = None

    @property
    def base_url(self) -> str:
        """获取本地 Sidecar 服务地址。"""
        cfg = config_manager.config.server
        port = self._active_port or cfg.sidecar_port
        return f"http://{cfg.sidecar_host}:{port}"

    def get_client(self) -> httpx.AsyncClient:
        """获取或创建内部异步 HTTP 客户端。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0, trust_env=False)
        return self._client

    async def is_healthy(self, force: bool = False) -> bool:
        """检查 Sidecar 服务健康状况。"""
        now = time.time()
        if not force and now - self._last_health_check < 3.0:
            return self._cached_healthy

        self._last_health_check = now
        try:
            client = self.get_client()
            r = await client.get(f"{self.base_url}/session", timeout=2.0)
            self._cached_healthy = (r.status_code == 200)
            return self._cached_healthy
        except Exception:
            self._cached_healthy = False
            return False

    async def ensure_running(self) -> bool:
        """确保 Sidecar 进程处于运行就绪状态。"""
        if await self.is_healthy():
            return True

        cfg = config_manager.config.server
        if not cfg.auto_start_sidecar:
            return False

        creds = opencode_auth.get_credentials()
        cli_path = creds.cli_path
        if not cli_path:
            logger.warning("未检测到本地 opencode CLI 可执行文件，无法自动启动 Sidecar")
            return False

        # 确保先前残留的托管进程已被彻底终止
        self.stop()

        target_port = find_available_port(cfg.sidecar_port, cfg.sidecar_host)
        if target_port != cfg.sidecar_port:
            logger.warning(
                "配置的 Sidecar 端口 %s 当前不可用，已自动切换至可用端口 %s",
                cfg.sidecar_port,
                target_port,
            )
        self._active_port = target_port

        cmd = [
            cli_path,
            "serve",
            "--port",
            str(target_port),
            "--hostname",
            cfg.sidecar_host,
        ]

        logger.info("正在启动 OpenCode 本地 Sidecar 进程: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._is_managed = True

            # 轮询等待服务端口就绪
            for _ in range(16):
                await asyncio.sleep(0.5)
                if await self.is_healthy(force=True):
                    logger.info("OpenCode Sidecar 进程已就绪于 %s", self.base_url)
                    if cfg.sidecar_port != target_port:
                        cfg.sidecar_port = target_port
                        config_manager.save()
                    return True
                if self._proc.poll() is not None:
                    _, err = self._proc.communicate()
                    logger.error("Sidecar 进程异常退出: %s", err.strip())
                    break
        except Exception as e:
            logger.error("启动 Sidecar 进程失败: %e", e)

        return False

    def stop(self) -> None:
        """停止由本网关托管启动的 Sidecar 进程及子进程树。"""
        if self._is_managed and self._proc:
            pid = self._proc.pid
            try:
                logger.info("正在关闭 OpenCode Sidecar 托管进程 (PID: %s)...", pid)
                import platform
                if platform.system() == "Windows":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                else:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._is_managed = False
            self._cached_healthy = False

    async def restart(self) -> bool:
        """重启本地 Sidecar 进程。"""
        self.stop()
        await asyncio.sleep(1.0)
        return await self.ensure_running()

    def get_status(self) -> dict[str, Any]:
        """获取 Sidecar 状态概览。"""
        cfg = config_manager.config.server
        proc_alive = (self._proc is not None and self._proc.poll() is None) if self._is_managed else None
        active_port = self._active_port or cfg.sidecar_port
        return {
            "healthy": self._cached_healthy,
            "base_url": self.base_url,
            "port": active_port,
            "is_managed": self._is_managed,
            "proc_alive": proc_alive,
            "pid": self._proc.pid if self._proc and proc_alive else None,
            "auto_start": cfg.auto_start_sidecar,
        }

    # ==========================
    # 消息中继核心操作
    # ==========================

    async def create_session(self, title: str = "ZenGateway Relay") -> str:
        """在 OpenCode 中创建一个对话会话。"""
        client = self.get_client()
        r = await client.post(f"{self.base_url}/session", json={"title": title}, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        return data["id"]

    async def delete_session(self, session_id: str) -> None:
        """在会话结束后清理该会话。"""
        try:
            client = self.get_client()
            await client.delete(f"{self.base_url}/session/{session_id}", timeout=5.0)
        except Exception:
            pass

    async def send_message_non_stream(
        self,
        session_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """向 Sidecar 发送消息并等待完整回复。"""
        client = self.get_client()
        prompt_text = self._build_prompt_text(messages, system_prompt)

        payload = {
            "model": {"providerID": "opencode", "modelID": model_id},
            "parts": [{"type": "text", "text": prompt_text}],
        }

        r = await client.post(
            f"{self.base_url}/session/{session_id}/message",
            json=payload,
            timeout=config_manager.config.server.timeout_seconds,
        )
        r.raise_for_status()
        return r.json()

    async def stream_message(
        self,
        session_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """向 Sidecar 发送请求并通过 /event SSE 实时流式捕获 delta。"""
        client = self.get_client()
        prompt_text = self._build_prompt_text(messages, system_prompt)

        payload = {
            "model": {"providerID": "opencode", "modelID": model_id},
            "parts": [{"type": "text", "text": prompt_text}],
        }

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        sender_res: dict[str, Any] = {}
        sender_done = asyncio.Event()
        done_flag = asyncio.Event()

        # 启动消息发送任务
        async def _sender():
            try:
                r = await client.post(
                    f"{self.base_url}/session/{session_id}/message",
                    json=payload,
                    timeout=config_manager.config.server.timeout_seconds,
                )
                r.raise_for_status()
                data = r.json()
                toks = {}
                for p in data.get("parts", []):
                    if p.get("type") == "step-finish":
                        toks = p.get("tokens", {})
                if not toks:
                    toks = data.get("info", {}).get("tokens", {})
                sender_res["tokens"] = toks
            except Exception as err:
                sender_res["error"] = str(err)
                await queue.put({"kind": "error", "error": str(err)})
            finally:
                sender_done.set()

        sender_task = asyncio.create_task(_sender())

        # 启动后台任务监听 /event SSE
        async def _event_listener():
            try:
                import json
                async with httpx.AsyncClient(timeout=None, trust_env=False) as sse_client:
                    async with sse_client.stream("GET", f"{self.base_url}/event") as resp:
                        async for line in resp.aiter_lines():
                            if done_flag.is_set():
                                break
                            if not line.startswith("data: "):
                                continue
                            try:
                                ev = json.loads(line[6:])
                                ev_type = ev.get("type")
                                props = ev.get("properties", {})
                                if props.get("sessionID") != session_id:
                                    continue

                                if ev_type == "message.part.delta":
                                    await queue.put({
                                        "kind": "delta",
                                        "field": props.get("field", "text"),
                                        "delta": props.get("delta", ""),
                                    })
                                elif ev_type == "session.idle":
                                    # 收到闲置通知，确认消息发送任务已完成并提取统计
                                    await sender_done.wait()
                                    if "error" in sender_res:
                                        await queue.put({"kind": "error", "error": sender_res["error"]})
                                    else:
                                        await queue.put({"kind": "finish", "tokens": sender_res.get("tokens", {})})
                                    done_flag.set()
                                    break
                            except Exception:
                                pass
            except Exception as e:
                logger.debug("SSE 监听结束或中断: %s", e)
            finally:
                # 兜底超时同步发送任务结果
                if not sender_done.is_set():
                    try:
                        await asyncio.wait_for(sender_done.wait(), timeout=3.0)
                    except Exception:
                        pass
                if "error" in sender_res:
                    await queue.put({"kind": "error", "error": sender_res["error"]})
                elif "tokens" in sender_res and not done_flag.is_set():
                    await queue.put({"kind": "finish", "tokens": sender_res.get("tokens", {})})
                await queue.put(None)

        listener_task = asyncio.create_task(_event_listener())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
                if item.get("kind") in ("finish", "error"):
                    break
        finally:
            done_flag.set()
            listener_task.cancel()
            sender_task.cancel()

    def _build_prompt_text(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> str:
        """将标准多轮消息转换为 OpenCode 提示词文本。"""
        parts = []
        if system_prompt:
            parts.append(f"[System Instruction]\n{system_prompt}\n")

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                # 兼容多模态/内容块列表
                sub_texts = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        sub_texts.append(b.get("text", ""))
                    elif isinstance(b, str):
                        sub_texts.append(b)
                content = "\n".join(sub_texts)
            parts.append(f"[{role.capitalize()}]\n{content}\n")

        # 如果最后一条不是用户，增加 User 引导
        if messages and messages[-1].get("role") != "user":
            parts.append("[User]\n请继续\n")

        return "\n".join(parts).strip()


sidecar_manager = SidecarManager()
