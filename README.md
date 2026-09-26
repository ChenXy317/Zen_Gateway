# Zen Gateway

<div align="center">

**OpenCode 官方免费模型外接与本地三协议全栈网关**

[特性概览](#-核心特性) • [架构原理](#-架构与双通道引擎) • [快速开始](#-快速开始) • [外部工具接入](#-外部工具无感接入) • [Web 控制台](#-web-极客控制台)

</div>

---

## 🌟 核心特性

- **突破客户端准入校验**：针对 OpenCode Zen 服务端实施的强客户端准入风控（`403 FreeTierError`），创新提供**进程级 Sidecar 官方通道桥接（模式 B）**，100% 走官方握手与 TLS 特征，天然免封、免逆向维护。
- **释放官方免费模型全量潜能**：
  - `mimo-v2.6-flash-free`：官方免费旗舰，支持深度思考链推理（Reasoning Thought），高精度代码生成。
  - `space-bunny-free`：轻量极速模型，极低延迟。
  - `ling-3.0-flash-fin-free` / `nemotron-3-ultra-free` / `nemotron-3.5-lightning-free` 等精选免费层。
- **三协议无感转换**：
  - **OpenAI 兼容**：`/v1/chat/completions`、`/v1/models`（完整支持 SSE 流式与思考链 `reasoning_content`）。
  - **Anthropic 兼容**：`/v1/messages`（支持 Claude Code 多轮对话与流式转接）。
- **禅意极客暗黑现代化 Web 控制台**：
  - 基于 Alpine.js + Tailwind CSS，纯本地内置离线依赖，毫秒级即开。
  - 在线演练场（Playground）：支持打字机流式 SSE 渲染、TTFT 首字延迟与耗时统计、思考过程折叠展现。
  - 模型矩阵与别名映射：支持将 `gpt-4o`、`claude-3-5-sonnet` 等别名无感映射至免费模型。
  - 一键全模型连通性与准入诊断（Diagnostics）。
  - 实时调用日志与性能监控（Logs）。

---

## 🏗️ 架构与双通道引擎

```
+-------------------------------------------------------------------+
| 外部客户端: Cursor / Claude Code / OpenAI SDK / 其它开发工具       |
+---------------------------------+---------------------------------+
                                  | 标准 OpenAI / Anthropic 协议
                                  v
+-------------------------------------------------------------------+
| Zen Gateway (默认监听 127.0.0.1:8790)                             |
|  - 协议路由器 (API Router)                                        |
|  - 格式转换与流式 SSE 引擎 (IR Converter)                         |
|  - 本地凭据安全管理器 (~/.local/share/opencode/auth.json)         |
+---------------------------------+---------------------------------+
                                  |
            +---------------------+---------------------+
            |                                           |
            v                                           v
+-----------------------+                   +-----------------------+
| 模式 B (推荐 / 默认)   |                   | 模式 A (逆向直连伪装) |
| 本地 OpenCode Sidecar  |                   | 1:1 模拟请求头与 TLS  |
| 官方进程通道 (天然免封)|                   | 直连 opencode.ai/zen  |
+-----------+-----------+                   +-----------+-----------+
            |                                           |
            +---------------------+---------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| OpenCode 官方服务端 (支持 mimo-v2.6-flash-free 等模型)            |
+-------------------------------------------------------------------+
```

---

## 🚀 快速开始

### 1. 前置准备
确保本地已安装 OpenCode 并完成登录（系统存在 `~/.local/share/opencode/auth.json`）：
```bash
# 验证 OpenCode 安装
opencode --version
```

### 2. 启动网关
- **Windows 用户**：双击 `start.bat`。
- **命令行启动**：
```bash
# 安装依赖
pip install -r requirements.txt

# 启动网关服务
python -m app.main
```

启动成功后，浏览器访问：
- **Web 控制台**：`http://127.0.0.1:8790/`
- **OpenAI 代理接口**：`http://127.0.0.1:8790/v1`

---

## 🔌 外部工具无感接入

### 1. Cursor IDE 配置
1. 打开 Cursor 设置 -> **Models**。
2. 开启 **OpenAI API Key**：
   - **Base URL**: `http://127.0.0.1:8790/v1`
   - **API Key**: 填入 `sk-zen-local`（若网关未设置 `local_api_key`，可任意填写）
3. 在模型列表中添加或选用 `mimo-v2.6-flash-free` 或 `space-bunny-free`。

### 2. Claude Code 配置
在终端导出环境变量即可无缝使用：
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
    messages=[{"role": "user", "content": "你好，请写一个 Python 装饰器。"}],
    stream=True,
)

for chunk in response:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

---

## 🎨 Web 极客控制台

访问 `http://127.0.0.1:8790/` 即可进入专属控制面板：
1. **运行态卡片**：实时展示 OpenCode 本地凭据掩码、CLI 版本号与 Sidecar 进程 PID。
2. **调试演练场 (Playground)**：提供模型对话测试，实时观察 TTFT 首字延迟、Token 统计与思考链内容。
3. **模型矩阵 (Models)**：一览所有官方免费模型与别名映射关系（如 `gpt-4o` 映射至 `mimo-v2.6-flash-free`）。
4. **连通性诊断 (Diagnostics)**：一键批量探测各个免费模型的可用性与延迟。
5. **实时日志 (Logs)**：记录每一次请求的客户端 IP、协议格式、耗时与 Token 统计。
