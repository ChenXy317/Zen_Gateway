# Zen Gateway

本地运行的 OpenCode 免费模型协议网关服务。读取本机已登录的 OpenCode 凭据（`~/.local/share/opencode/auth.json`），将 OpenCode 官方免费层模型（如 `mimo-v2.6-flash-free`、`space-bunny-free` 等）转换为标准的 OpenAI (`/v1/chat/completions`) 与 Anthropic (`/v1/messages`) 协议端点，供外部开发工具（如 Cursor、Claude Code、OpenAI SDK 等）调用。

---

## 架构原理

针对服务端对部分免费模型的客户端校验策略，Zen Gateway 提供了双通道通信机制：

```
┌────────────────────────────────────────────────────────┐
│ 外部工具: Cursor / Claude Code / OpenAI SDK             │
└───────────────────────────┬────────────────────────────┘
                            │ 标准 OpenAI / Anthropic 协议
                            ▼
┌────────────────────────────────────────────────────────┐
│ Zen Gateway (默认监听 127.0.0.1:8790)                   │
│ ├─ 协议转码器 (IR 中间表示与流式 SSE 引擎)              │
│ ├─ 模型别名映射器 (如 gpt-4o 映射至 mimo 模型)          │
│ └─ Web 管理控制台 (支持明暗色与主题配色切换)            │
└───────────────────────────┬────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌───────────────────────────┐ ┌───────────────────────────┐
│ 模式 B (推荐 / 默认):      │ │ 模式 A (直连模式):        │
│ 本地 OpenCode Sidecar 通道 │ │ 模拟请求头与 TLS 指纹     │
│ 走本地进程官方通信渠道    │ │ 直连官方后端              │
└─────────────┬─────────────┘ └───────────┬───────────────┘
              │                           │
              └─────────────┬─────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│ OpenCode 官方服务端 (mimo-v2.6-flash-free 等模型)       │
└────────────────────────────────────────────────────────┘
```

---

## 主要功能

* **多协议互转**：支持 OpenAI Chat Completions 与 Anthropic Messages 协议，流式输出完整保留 `reasoning_content`（深度思考链推理）与模型响应。
* **双通道中继引擎**：
  * **模式 B（Sidecar 桥接，推荐）**：通过网关管理或对接本地常驻的 OpenCode 客户端进程，复用原生通信握手通道，确保各免费层模型均可稳定调用；
  * **模式 A（直连伪装）**：针对无需复杂校验的轻量模型进行请求头拟态与直接通信，不依赖后台常驻进程。
* **模型别名映射 (Alias Mapping)**：支持在控制台或配置文件中设置映射规则，例如将外部请求的 `gpt-4o` 或 `claude-3-5-sonnet` 无感路由到指定的免费模型上。
* **轻量 Web 控制台**：基于 Alpine.js + Tailwind CSS，纯本地内置离线依赖，支持深色 / 浅色模式与 7 套主题配色切换，内置在线演练场（Playground）、一键批量模型测速诊断与实时调用日志。

---

## 快速开始

### 前置要求
* Python 3.11+
* 本机已安装并完成登录的 OpenCode（存在 `~/.local/share/opencode/auth.json` 凭据）

### 启动服务

**Windows**：
双击运行 `start.bat`，或在命令行中运行：
```powershell
python -m app.main
```

**macOS / Linux**：
```bash
chmod +x start.sh
./start.sh
```

服务启动后，在浏览器访问控制台：`http://127.0.0.1:8790`。

---

## 客户端接入方式

### 1. Cursor IDE
* **OpenAI API Key**: `sk-zen-local`（或网关配置的 `local_api_key`）
* **Base URL**: `http://127.0.0.1:8790/v1`
* **Model**: `mimo-v2.6-flash-free`、`space-bunny-free` 或配置的别名（如 `gpt-4o`）

### 2. Claude Code
在终端中设置环境变量后启动 Claude Code：
```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8790/v1"
export ANTHROPIC_API_KEY="sk-zen-local"
claude
```

### 3. Python OpenAI SDK
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8790/v1",
    api_key="sk-zen-local",
)

response = client.chat.completions.create(
    model="mimo-v2.6-flash-free",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)

for chunk in response:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
```

### 4. cURL
```bash
curl http://127.0.0.1:8790/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-zen-local" \
  -d '{
    "model": "mimo-v2.6-flash-free",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

---

## 配置说明

配置文件为 `config.json`（可参考 `config.example.json`）：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8790,
    "local_api_key": "",
    "admin_api_key": "",
    "default_model": "mimo-v2.6-flash-free",
    "engine_mode": "sidecar",
    "sidecar_host": "127.0.0.1",
    "sidecar_port": 4096,
    "auto_start_sidecar": true,
    "timeout_seconds": 120.0
  },
  "model_aliases": {
    "gpt-4o": "mimo-v2.6-flash-free",
    "gpt-4o-mini": "space-bunny-free",
    "claude-3-5-sonnet": "mimo-v2.6-flash-free"
  }
}
```

| 参数项 | 说明 | 默认值 |
|---|---|---|
| `host` | 监听地址 | `127.0.0.1` |
| `port` | 监听端口 | `8790` |
| `local_api_key` | 客户端入站鉴权密钥，留空且仅绑定本机时免鉴权 | `""` |
| `admin_api_key` | 管理控制台密钥 | `""` |
| `default_model` | 缺省模型 | `mimo-v2.6-flash-free` |
| `engine_mode` | 中继模式 (`sidecar` / `direct` / `auto`) | `sidecar` |
| `sidecar_port` | 本地 Sidecar 桥接端口 | `4096` |
| `auto_start_sidecar` | 是否在服务启动时自动拉起本地 Sidecar 进程 | `true` |

---

## 安全注意事项

1. 本网关读取的是本机个人的 OpenCode 凭据，仅供个人本地开发测试使用，请勿直接暴露至公网环境。
2. 若需开放局域网或公网访问，请在配置文件中显式配置 `local_api_key` 与 `admin_api_key`。
