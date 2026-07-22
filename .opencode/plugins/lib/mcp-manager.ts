import { join } from "path";
import { existsSync } from "fs";
import type { OpencodeClient } from "./session-manager";
import { OPENCODE_ROOT } from "./constants";
import { getPythonCmd } from "./venv";
import { debugLog } from "./logging";

// MCP server 定义：name → (server.py 路径, timeout)
// 依赖声明在 mcp-servers/<name>/pyproject.toml 的 [tool.opensecurity].import_names
// 这里不重复检测——server.py 启动失败时错误从 stderr 捕获
const MCP_SERVERS = [
  {
    name: "knowledge",
    script: join(OPENCODE_ROOT, "mcp-servers", "knowledge", "server.py"),
    timeout: 60000,
  },
  {
    name: "events",
    script: join(OPENCODE_ROOT, "mcp-servers", "events", "server.py"),
    timeout: 120000,
  },
] as const;

export class McpManager {
  private client: OpencodeClient;

  constructor(client: OpencodeClient) {
    this.client = client;
  }

  /**
   * 注册所有 MCP server。
   * 不预检测依赖——直接 spawn server.py，依赖错误从握手失败的 stderr 捕获。
   * 节省每个 server 启动时 ~1-2s 同步子进程开销（原 checkPackages）。
   */
  async registerAll(): Promise<void> {
    const venvPython = getPythonCmd();
    if (!venvPython) {
      debugLog(`[McpManager] 注册中止：venv Python 未找到（getPythonCmd 返回 null，conda/venv 未就绪）`);
      return;
    }

    for (const server of MCP_SERVERS) {
      await this.registerOne(server, venvPython);
    }
  }

  private async registerOne(
    server: (typeof MCP_SERVERS)[number],
    venvPython: string,
  ): Promise<void> {
    const { name, script, timeout } = server;

    // 1. 检测 server.py 是否存在
    if (!existsSync(script)) {
      debugLog(`[McpManager] ${name} 跳过：server.py 不存在 ${script}`);
      return;
    }

    // 2. 直接通过 SDK 官方 API 注册（不预检测依赖）
    // 如果 server.py 缺依赖（ImportError），握手失败 → catch 内捕获 e.stderr 输出
    try {
      await this.client.mcp.add({
        body: {
          name,
          config: {
            type: "local" as const,
            command: [venvPython, script],
            enabled: true,
            timeout,
          },
        },
      });
      debugLog(`[McpManager] ${name} 注册成功：python=${venvPython} server=${script}`);
    } catch (e) {
      const errMsg = (e as Error)?.message ?? String(e);
      debugLog(`[McpManager] ${name} 注册失败：${errMsg}`);
      // 捕获 server stderr（含 ImportError 等启动错误）
      const stderr = (e as { stderr?: Buffer }).stderr;
      if (stderr) {
        debugLog(`  server stderr: ${stderr.toString().slice(-500)}`);
      }
    }
  }
}
