"""Zen Gateway FastAPI 主服务路由与外部协议代理。"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .access_log import AccessLogEntry, access_log
from .auth import opencode_auth
from .config import (
    ServerConfig,
    config_manager,
    effective_bind_host,
    is_public_bind,
)
from .converter.chat_anthropic import ir_to_anthropic_response
from .converter.chat_responses import ir_to_openai_response, openai_models_response
from .models import model_registry
from .secrets import collect_secrets, redact_any
from .sidecar import sidecar_manager
from .stream import stream_anthropic_generator, stream_openai_generator
from .transform import (
    error_payload,
    parse_anthropic_request,
    parse_openai_request,
)
from .upstream import upstream_dispatcher

logger = logging.getLogger("zen_gateway.server")
STARTED_AT = time.time()

# 路由定义
api_router = APIRouter(prefix="/api")
v1_router = APIRouter(prefix="/v1")


def _token_eq(a: str, b: str) -> bool:
    """安全定长字符串比较。"""
    da = hashlib.sha256(a.encode("utf-8")).digest()
    db = hashlib.sha256(b.encode("utf-8")).digest()
    return hmac.compare_digest(da, db)


def _extract_bearer(request: Request) -> str:
    """从请求中提取 Bearer Token 或对应 Header。"""
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth:
        return auth.removeprefix("Bearer ").removeprefix("bearer ").strip()
    return (
        request.headers.get("x-api-key")
        or request.headers.get("x-admin-key")
        or request.headers.get("api-key")
        or ""
    ).strip()


async def require_local_auth(request: Request) -> None:
    """校验外部调用 /v1/* 接口的本地授权密钥。"""
    cfg = config_manager.config.server
    local_key = (cfg.local_api_key or "").strip()
    if not local_key:
        return  # 留空为免鉴权模式

    token = _extract_bearer(request)
    if not token or not _token_eq(token, local_key):
        raise HTTPException(
            status_code=401,
            detail=error_payload(401, "无效或缺失的 API Key", "openai")["error"],
        )


async def require_admin_auth(request: Request) -> None:
    """校验管理控制台 API 鉴权。"""
    cfg = config_manager.config.server
    admin_key = (cfg.admin_api_key or "").strip()
    local_key = (cfg.local_api_key or "").strip()
    public_bind = is_public_bind(cfg.host)

    if public_bind:
        required_key = admin_key or local_key
        if not required_key:
            raise HTTPException(403, "绑定非本机地址时必须在配置中设置 admin_api_key 或 local_api_key")
        token = _extract_bearer(request)
        if not token or not _token_eq(token, required_key):
            raise HTTPException(401, "管理接口需要有效的 admin_api_key 或 local_api_key")
        return

    if admin_key:
        token = _extract_bearer(request)
        if not token or not (_token_eq(token, admin_key) or (local_key and _token_eq(token, local_key))):
            raise HTTPException(401, "管理接口鉴权失败")


# ==========================
# 管理 API 路由 (/api/*)
# ==========================

@api_router.get("/status")
async def get_status(request: Request, _: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """获取网关状态、OpenCode 凭据检测与运行时统计。"""
    cfg = config_manager.config.server
    auth_info = opencode_auth.to_dict()
    sidecar_info = sidecar_manager.get_status()
    stats = access_log.get_stats()

    return {
        "version": __version__,
        "uptime_seconds": int(time.time() - STARTED_AT),
        "host": cfg.host,
        "port": cfg.port,
        "default_model": cfg.default_model,
        "engine_mode": cfg.engine_mode,
        "auth": auth_info,
        "sidecar": sidecar_info,
        "stats": stats,
    }


@api_router.get("/config")
async def get_config(_: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """获取脱敏后的当前配置。"""
    return config_manager.to_public_dict()


@api_router.post("/config")
async def update_config(data: dict[str, Any], _: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """更新服务器与别名配置。"""
    cfg = config_manager.config
    srv_in = data.get("server", {})

    if "default_model" in srv_in:
        cfg.server.default_model = srv_in["default_model"]
    if "engine_mode" in srv_in:
        cfg.server.engine_mode = srv_in["engine_mode"]
    if "host" in srv_in:
        cfg.server.host = srv_in["host"]
    if "port" in srv_in:
        cfg.server.port = int(srv_in["port"])
    if "local_api_key" in srv_in:
        val = srv_in["local_api_key"].strip()
        if val != "..." and not val.endswith("..."):
            cfg.server.local_api_key = val
    if "admin_api_key" in srv_in:
        val = srv_in["admin_api_key"].strip()
        if val != "..." and not val.endswith("..."):
            cfg.server.admin_api_key = val
    if "sidecar_port" in srv_in:
        cfg.server.sidecar_port = int(srv_in["sidecar_port"])
    if "auto_start_sidecar" in srv_in:
        cfg.server.auto_start_sidecar = bool(srv_in["auto_start_sidecar"])

    if "model_aliases" in data:
        cfg.model_aliases = data["model_aliases"]
        model_registry.set_aliases(cfg.model_aliases)

    config_manager.save()
    return {"status": "ok", "message": "配置已保存", "data": config_manager.to_public_dict()}


@api_router.get("/models")
async def list_models(_: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """获取所有模型元信息与别名。"""
    return {
        "models": model_registry.list_models(),
        "aliases": model_registry.get_aliases(),
    }


@api_router.post("/models/alias")
async def update_aliases(data: dict[str, str], _: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """保存模型别名映射表。"""
    config_manager.config.model_aliases = data
    model_registry.set_aliases(data)
    config_manager.save()
    return {"status": "ok", "aliases": model_registry.get_aliases()}


@api_router.get("/logs")
async def get_logs(
    limit: int = 50,
    model: str | None = None,
    protocol: str | None = None,
    _: None = Depends(require_admin_auth),
) -> dict[str, Any]:
    """获取调用日志。"""
    return {
        "logs": access_log.list_entries(limit=limit, model=model, protocol=protocol),
        "stats": access_log.get_stats(),
    }


@api_router.post("/logs/clear")
async def clear_logs(_: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """清空访问日志。"""
    access_log.clear()
    return {"status": "ok"}


@api_router.post("/sidecar/restart")
async def restart_sidecar(_: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """手动重启 OpenCode Sidecar 进程。"""
    ok = await sidecar_manager.restart()
    return {"status": "ok" if ok else "failed", "healthy": ok}


@api_router.post("/test")
async def test_model(data: dict[str, Any], _: None = Depends(require_admin_auth)) -> dict[str, Any]:
    """对指定模型发起单次连通性测试。"""
    target_model = data.get("model") or config_manager.config.server.default_model
    prompt = data.get("prompt") or "请用简短一句话说明你是谁。"

    from .ir import IRMessage, IRRequest

    req = IRRequest(
        model=target_model,
        messages=[IRMessage(role="user", content=prompt)],
        stream=False,
    )
    t0 = time.time()
    try:
        resp = await upstream_dispatcher.execute_non_stream(req)
        dur = (time.time() - t0) * 1000
        return {
            "status": "success",
            "model": target_model,
            "latency_ms": round(dur, 2),
            "text": resp.text,
            "reasoning": resp.reasoning,
            "tokens": {
                "input": resp.usage.prompt_tokens,
                "output": resp.usage.completion_tokens,
                "total": resp.usage.total_tokens,
            },
        }
    except Exception as e:
        dur = (time.time() - t0) * 1000
        return {
            "status": "error",
            "model": target_model,
            "latency_ms": round(dur, 2),
            "error": str(e),
        }


# ==========================
# 协议代理路由 (/v1/*)
# ==========================

@v1_router.get("/models")
async def proxy_models(_: None = Depends(require_local_auth)) -> dict[str, Any]:
    """OpenAI 兼容模型列表端点。"""
    return openai_models_response(model_registry.list_models())


@v1_router.post("/chat/completions")
async def proxy_chat_completions(
    request: Request,
    _: None = Depends(require_local_auth),
) -> Any:
    """OpenAI 兼容对话补全端点（流式与非流式）。"""
    t0 = time.time()
    req_id = uuid.uuid4().hex[:12]
    client_ip = request.client.host if request.client else "unknown"

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON 请求体")

    raw_model = body.get("model", "")
    ir_req = parse_openai_request(body)
    stream = ir_req.stream

    ttft_holder = {"val": None}

    def _set_ttft(val: float) -> None:
        ttft_holder["val"] = val

    if stream:
        finish_tokens = {"in": 0, "out": 0}

        def _on_finish(inp: int, outp: int) -> None:
            finish_tokens["in"] = inp
            finish_tokens["out"] = outp
            dur = (time.time() - t0) * 1000
            access_log.record(AccessLogEntry(
                id=req_id,
                timestamp=t0,
                time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
                client_ip=client_ip,
                method="POST",
                path="/v1/chat/completions",
                protocol="OpenAI",
                model=raw_model,
                actual_model=ir_req.model,
                status_code=200,
                duration_ms=round(dur, 2),
                ttft_ms=round(ttft_holder["val"], 2) if ttft_holder["val"] else None,
                input_tokens=inp,
                output_tokens=outp,
                stream=True,
            ))

        try:
            event_stream = upstream_dispatcher.execute_stream(ir_req)
            gen = stream_openai_generator(
                event_stream=event_stream,
                model=ir_req.model,
                on_ttft=_set_ttft,
                on_finish=_on_finish,
            )
            return StreamingResponse(gen, media_type="text/event-stream")
        except Exception as e:
            dur = (time.time() - t0) * 1000
            access_log.record(AccessLogEntry(
                id=req_id,
                timestamp=t0,
                time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
                client_ip=client_ip,
                method="POST",
                path="/v1/chat/completions",
                protocol="OpenAI",
                model=raw_model,
                actual_model=ir_req.model,
                status_code=500,
                duration_ms=round(dur, 2),
                ttft_ms=None,
                input_tokens=0,
                output_tokens=0,
                stream=True,
                error=str(e),
            ))
            return JSONResponse(status_code=500, content=error_payload(500, str(e), "openai"))

    # 非流式处理
    try:
        resp = await upstream_dispatcher.execute_non_stream(ir_req)
        dur = (time.time() - t0) * 1000
        access_log.record(AccessLogEntry(
            id=req_id,
            timestamp=t0,
            time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
            client_ip=client_ip,
            method="POST",
            path="/v1/chat/completions",
            protocol="OpenAI",
            model=raw_model,
            actual_model=ir_req.model,
            status_code=200,
            duration_ms=round(dur, 2),
            ttft_ms=None,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
            stream=False,
        ))
        return ir_to_openai_response(resp)
    except Exception as e:
        dur = (time.time() - t0) * 1000
        access_log.record(AccessLogEntry(
            id=req_id,
            timestamp=t0,
            time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
            client_ip=client_ip,
            method="POST",
            path="/v1/chat/completions",
            protocol="OpenAI",
            model=raw_model,
            actual_model=ir_req.model,
            status_code=500,
            duration_ms=round(dur, 2),
            ttft_ms=None,
            input_tokens=0,
            output_tokens=0,
            stream=False,
            error=str(e),
        ))
        return JSONResponse(status_code=500, content=error_payload(500, str(e), "openai"))


@v1_router.post("/messages")
async def proxy_anthropic_messages(
    request: Request,
    _: None = Depends(require_local_auth),
) -> Any:
    """Anthropic /v1/messages 协议兼容端点（供 Claude Code 等工具调用）。"""
    t0 = time.time()
    req_id = uuid.uuid4().hex[:12]
    client_ip = request.client.host if request.client else "unknown"

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON 请求体")

    raw_model = body.get("model", "")
    ir_req = parse_anthropic_request(body)
    stream = ir_req.stream

    ttft_holder = {"val": None}

    def _set_ttft(val: float) -> None:
        ttft_holder["val"] = val

    if stream:
        finish_tokens = {"in": 0, "out": 0}

        def _on_finish(inp: int, outp: int) -> None:
            finish_tokens["in"] = inp
            finish_tokens["out"] = outp
            dur = (time.time() - t0) * 1000
            access_log.record(AccessLogEntry(
                id=req_id,
                timestamp=t0,
                time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
                client_ip=client_ip,
                method="POST",
                path="/v1/messages",
                protocol="Anthropic",
                model=raw_model,
                actual_model=ir_req.model,
                status_code=200,
                duration_ms=round(dur, 2),
                ttft_ms=round(ttft_holder["val"], 2) if ttft_holder["val"] else None,
                input_tokens=inp,
                output_tokens=outp,
                stream=True,
            ))

        try:
            event_stream = upstream_dispatcher.execute_stream(ir_req)
            gen = stream_anthropic_generator(
                event_stream=event_stream,
                model=ir_req.model,
                on_ttft=_set_ttft,
                on_finish=_on_finish,
            )
            return StreamingResponse(gen, media_type="text/event-stream")
        except Exception as e:
            dur = (time.time() - t0) * 1000
            access_log.record(AccessLogEntry(
                id=req_id,
                timestamp=t0,
                time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
                client_ip=client_ip,
                method="POST",
                path="/v1/messages",
                protocol="Anthropic",
                model=raw_model,
                actual_model=ir_req.model,
                status_code=500,
                duration_ms=round(dur, 2),
                ttft_ms=None,
                input_tokens=0,
                output_tokens=0,
                stream=True,
                error=str(e),
            ))
            return JSONResponse(status_code=500, content=error_payload(500, str(e), "anthropic"))

    # 非流式处理
    try:
        resp = await upstream_dispatcher.execute_non_stream(ir_req)
        dur = (time.time() - t0) * 1000
        access_log.record(AccessLogEntry(
            id=req_id,
            timestamp=t0,
            time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
            client_ip=client_ip,
            method="POST",
            path="/v1/messages",
            protocol="Anthropic",
            model=raw_model,
            actual_model=ir_req.model,
            status_code=200,
            duration_ms=round(dur, 2),
            ttft_ms=None,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
            stream=False,
        ))
        return ir_to_anthropic_response(resp)
    except Exception as e:
        dur = (time.time() - t0) * 1000
        access_log.record(AccessLogEntry(
            id=req_id,
            timestamp=t0,
            time_str=time.strftime("%H:%M:%S", time.localtime(t0)),
            client_ip=client_ip,
            method="POST",
            path="/v1/messages",
            protocol="Anthropic",
            model=raw_model,
            actual_model=ir_req.model,
            status_code=500,
            duration_ms=round(dur, 2),
            ttft_ms=None,
            input_tokens=0,
            output_tokens=0,
            stream=False,
            error=str(e),
        ))
        return JSONResponse(status_code=500, content=error_payload(500, str(e), "anthropic"))


def create_app() -> FastAPI:
    """构建并配置 FastAPI 主应用。"""
    app = FastAPI(title="Zen Gateway", version=__version__)

    # CORS 跨域支持
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(api_router)
    app.include_router(v1_router)

    # 静态前端资源目录
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if (static_dir / "vendor").is_dir():
        app.mount("/vendor", StaticFiles(directory=str(static_dir / "vendor")), name="vendor")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def index():
        idx_file = static_dir / "index.html"
        if idx_file.is_file():
            return FileResponse(idx_file)
        return {"name": "Zen Gateway", "version": __version__, "status": "running"}

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.on_event("startup")
    async def startup():
        logger.info("Zen Gateway 正在启动...")
        # 预加载凭据并在配置开启时拉起 Sidecar
        opencode_auth.get_credentials()
        cfg = config_manager.config.server
        if cfg.auto_start_sidecar and cfg.engine_mode in ("sidecar", "auto"):
            asyncio.create_task(sidecar_manager.ensure_running())

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("Zen Gateway 正在关闭，清理子进程...")
        sidecar_manager.stop()

    return app
