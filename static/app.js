/**
 * Zen Gateway Alpine.js 前端主应用控制器
 */
function app() {
  return {
    version: "1.0.0",
    healthOk: false,
    needAdmin: false,
    adminKey: localStorage.getItem("zg_admin_key") || "",
    adminError: "",
    toastMessage: "",
    toastVisible: false,

    serverCfg: {
      host: "127.0.0.1",
      port: 8790,
      local_api_key: "",
      admin_api_key: "",
      default_model: "mimo-v2.6-flash-free",
      engine_mode: "sidecar",
      sidecar_host: "127.0.0.1",
      sidecar_port: 4096,
      auto_start_sidecar: true,
      has_local_api_key: false,
      has_admin_api_key: false,
      local_api_key_masked: "",
      admin_api_key_masked: "",
    },

    auth: {
      logged_in: false,
      masked_key: "",
      provider_name: "",
      auth_file: "",
      cli_path: "",
      cli_version: "",
      error: null,
    },

    sidecar: {
      healthy: false,
      base_url: "http://127.0.0.1:4096",
      is_managed: false,
      proc_alive: false,
      pid: null,
      auto_start: true,
    },

    models: [],
    aliases: {},
    newAliasKey: "",
    newAliasVal: "",

    tab: "play", // "play" | "models" | "diagnostics" | "logs"
    showLocalKey: false,
    restartingSidecar: false,
    savingConfig: false,

    // Playground
    playModel: "mimo-v2.6-flash-free",
    playSystem: "",
    playPrompt: "你好！请用精炼的一句话证明你的能力与优势。",
    playStream: true,
    playTemperature: 0.7,
    playReply: "",
    playReasoning: "",
    playLatency: 0,
    playTtft: 0,
    playTokens: { input: 0, output: 0, total: 0 },
    playing: false,
    showReasoning: true,

    // Diagnostics
    diagTesting: false,
    diagResults: {}, // modelId -> { status, latency_ms, text, error }

    // Logs
    logs: [],
    logFilterModel: "",
    logFilterProtocol: "",
    expandedLogId: null,

    get gatewayUrl() {
      const port = this.serverCfg.port || 8790;
      return `http://127.0.0.1:${port}/v1`;
    },

    async init() {
      await this.loadConfig();
      await this.fetchStatus();
      await this.fetchModels();
      await this.fetchLogs();

      if (this.models.length > 0 && !this.playModel) {
        this.playModel = this.serverCfg.default_model || this.models[0].id;
      }

      setInterval(() => {
        if (!this.needAdmin) {
          this.fetchStatus();
        }
      }, 8000);
    },

    _headers() {
      const h = { "Content-Type": "application/json" };
      if (this.adminKey) {
        h["Authorization"] = "Bearer " + this.adminKey;
        h["X-Admin-Key"] = this.adminKey;
      }
      return h;
    },

    toast(msg, dur = 3000) {
      this.toastMessage = msg;
      this.toastVisible = true;
      setTimeout(() => {
        this.toastVisible = false;
      }, dur);
    },

    copy(text) {
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        this.toast("已复制到剪贴板");
      }).catch(() => {
        this.toast("复制失败，请手动选取复制");
      });
    },

    async unlockAdmin() {
      this.adminError = "";
      localStorage.setItem("zg_admin_key", this.adminKey);
      await this.fetchStatus();
      if (!this.needAdmin) {
        await this.loadConfig();
        await this.fetchModels();
        await this.fetchLogs();
      } else {
        this.adminError = "密钥验证不通过，请检查";
      }
    },

    async fetchStatus() {
      try {
        const resp = await fetch("/api/status", { headers: this._headers() });
        if (resp.status === 401 || resp.status === 403) {
          this.needAdmin = true;
          this.healthOk = false;
          return;
        }
        if (!resp.ok) {
          this.healthOk = false;
          return;
        }
        this.needAdmin = false;
        this.healthOk = true;
        const data = await resp.json();
        this.version = data.version || "1.0.0";
        if (data.auth) this.auth = data.auth;
        if (data.sidecar) this.sidecar = data.sidecar;
        if (data.default_model) this.serverCfg.default_model = data.default_model;
        if (data.engine_mode) this.serverCfg.engine_mode = data.engine_mode;
      } catch (e) {
        this.healthOk = false;
      }
    },

    async loadConfig() {
      try {
        const resp = await fetch("/api/config", { headers: this._headers() });
        if (resp.ok) {
          const data = await resp.json();
          if (data.server) {
            this.serverCfg = { ...this.serverCfg, ...data.server };
          }
          if (data.model_aliases) {
            this.aliases = data.model_aliases;
          }
        }
      } catch (e) {}
    },

    async saveConfig() {
      this.savingConfig = true;
      try {
        const srv = {
          host: this.serverCfg.host,
          port: parseInt(this.serverCfg.port),
          default_model: this.serverCfg.default_model,
          engine_mode: this.serverCfg.engine_mode,
          sidecar_port: parseInt(this.serverCfg.sidecar_port),
          auto_start_sidecar: this.serverCfg.auto_start_sidecar,
        };
        // 过滤掩码占位符，仅在用户输入新密钥时提交
        if (this.serverCfg.local_api_key !== undefined && !this.serverCfg.local_api_key.includes("...")) {
          srv.local_api_key = this.serverCfg.local_api_key.trim();
        }
        if (this.serverCfg.admin_api_key !== undefined && !this.serverCfg.admin_api_key.includes("...")) {
          srv.admin_api_key = this.serverCfg.admin_api_key.trim();
        }

        const payload = {
          server: srv,
          model_aliases: this.aliases,
        };
        const resp = await fetch("/api/config", {
          method: "POST",
          headers: this._headers(),
          body: JSON.stringify(payload),
        });
        if (resp.ok) {
          this.toast("网关配置已成功保存");
          await this.loadConfig();
        } else {
          const errData = await resp.json().catch(() => ({}));
          this.toast("保存失败: " + (errData?.detail || resp.statusText));
        }
      } catch (e) {
        this.toast("保存异常: " + e.message);
      } finally {
        this.savingConfig = false;
      }
    },

    async restartSidecar() {
      this.restartingSidecar = true;
      try {
        const resp = await fetch("/api/sidecar/restart", {
          method: "POST",
          headers: this._headers(),
        });
        const data = await resp.json();
        if (data.healthy) {
          this.toast("OpenCode Sidecar 重启成功并就绪");
        } else {
          this.toast("Sidecar 重启响应未就绪，请查看控制台日志");
        }
        await this.fetchStatus();
      } catch (e) {
        this.toast("重启失败: " + e.message);
      } finally {
        this.restartingSidecar = false;
      }
    },

    async fetchModels() {
      try {
        const resp = await fetch("/api/models", { headers: this._headers() });
        if (resp.ok) {
          const data = await resp.json();
          this.models = data.models || [];
          this.aliases = data.aliases || {};
          if (this.models.length > 0 && !this.playModel) {
            this.playModel = this.models[0].id;
          }
        }
      } catch (e) {}
    },

    addAlias() {
      if (!this.newAliasKey || !this.newAliasVal) return;
      this.aliases[this.newAliasKey.trim()] = this.newAliasVal.trim();
      this.newAliasKey = "";
      this.newAliasVal = "";
      this.saveAliases();
    },

    removeAlias(key) {
      delete this.aliases[key];
      this.saveAliases();
    },

    async saveAliases() {
      try {
        const resp = await fetch("/api/models/alias", {
          method: "POST",
          headers: this._headers(),
          body: JSON.stringify(this.aliases),
        });
        if (resp.ok) {
          this.toast("别名映射已更新");
        }
      } catch (e) {}
    },

    async fetchLogs() {
      try {
        let url = `/api/logs?limit=50`;
        if (this.logFilterModel) url += `&model=${encodeURIComponent(this.logFilterModel)}`;
        if (this.logFilterProtocol) url += `&protocol=${encodeURIComponent(this.logFilterProtocol)}`;
        const resp = await fetch(url, { headers: this._headers() });
        if (resp.ok) {
          const data = await resp.json();
          this.logs = data.logs || [];
        }
      } catch (e) {}
    },

    async clearLogs() {
      try {
        await fetch("/api/logs/clear", { method: "POST", headers: this._headers() });
        this.logs = [];
        this.toast("日志已清空");
      } catch (e) {}
    },

    toggleLog(id) {
      this.expandedLogId = this.expandedLogId === id ? null : id;
    },

    // ==========================
    // Playground 调试交互
    // ==========================

    async sendPlayground() {
      if (!this.playPrompt || this.playing) return;
      this.playing = true;
      this.playReply = "";
      this.playReasoning = "";
      this.playLatency = 0;
      this.playTtft = 0;
      this.playTokens = { input: 0, output: 0, total: 0 };

      const t0 = performance.now();
      let firstChunk = true;

      const messages = [];
      if (this.playSystem && this.playSystem.trim()) {
        messages.push({ role: "system", content: this.playSystem.trim() });
      }
      messages.push({ role: "user", content: this.playPrompt.trim() });

      const payload = {
        model: this.playModel,
        messages: messages,
        temperature: parseFloat(this.playTemperature),
        stream: this.playStream,
      };

      const headers = { "Content-Type": "application/json" };
      if (this.serverCfg.local_api_key) {
        headers["Authorization"] = "Bearer " + this.serverCfg.local_api_key;
      }

      try {
        const resp = await fetch("/v1/chat/completions", {
          method: "POST",
          headers: headers,
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          this.playReply = `[请求失败 ${resp.status}]: ${errData?.error?.message || resp.statusText}`;
          return;
        }

        if (!this.playStream) {
          const data = await resp.json();
          const choice = data.choices?.[0] || {};
          this.playReply = choice.message?.content || "";
          this.playReasoning = choice.message?.reasoning_content || "";
          if (data.usage) {
            this.playTokens = {
              input: data.usage.prompt_tokens || 0,
              output: data.usage.completion_tokens || 0,
              total: data.usage.total_tokens || 0,
            };
          }
          this.playLatency = Math.round(performance.now() - t0);
          return;
        }

        // 处理 SSE 流式响应
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop(); // 保留不完整的一行

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const dataStr = trimmed.slice(6);
            if (dataStr === "[DONE]") break;

            try {
              const chunk = JSON.parse(dataStr);
              if (firstChunk) {
                firstChunk = false;
                this.playTtft = Math.round(performance.now() - t0);
              }
              const delta = chunk.choices?.[0]?.delta || {};
              if (delta.content) {
                this.playReply += delta.content;
              }
              if (delta.reasoning_content) {
                this.playReasoning += delta.reasoning_content;
              }
              if (chunk.usage) {
                this.playTokens = {
                  input: chunk.usage.prompt_tokens || 0,
                  output: chunk.usage.completion_tokens || 0,
                  total: chunk.usage.total_tokens || 0,
                };
              }
            } catch (err) {}
          }
        }
        this.playLatency = Math.round(performance.now() - t0);
      } catch (e) {
        this.playReply = `[网络异常]: ${e.message}`;
      } finally {
        this.playing = false;
        setTimeout(() => this.fetchLogs(), 800);
      }
    },

    // ==========================
    // 一键连通性基准诊断
    // ==========================

    async runDiagnostics() {
      if (this.diagTesting) return;
      this.diagTesting = true;
      this.diagResults = {};

      const testTargets = this.models.filter(m => m.is_free).map(m => m.id);
      if (testTargets.length === 0 && this.models.length > 0) {
        testTargets.push(this.models[0].id);
      }

      for (const mId of testTargets) {
        this.diagResults[mId] = { status: "testing" };
        try {
          const resp = await fetch("/api/test", {
            method: "POST",
            headers: this._headers(),
            body: JSON.stringify({ model: mId, prompt: "请回复 OK" }),
          });
          const data = await resp.json();
          this.diagResults[mId] = data;
        } catch (e) {
          this.diagResults[mId] = {
            status: "error",
            latency_ms: 0,
            error: e.message,
          };
        }
      }
      this.diagTesting = false;
      this.toast("免费模型连通性诊断完成");
    },
  };
}
