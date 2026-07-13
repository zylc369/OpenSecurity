import { join } from "path";
import { execFileSync } from "child_process";
import { existsSync } from "fs";
import type { OpencodeClient } from "./session-manager";
import { OPENCODE_ROOT } from "./constants";
import { getPythonCmd } from "./venv";
import { debugLog } from "./logging";

// MCP server 定义：name → (server.py 路径, timeout)
const MCP_SERVERS = [
  {
    name: "knowledge",
    script: join(OPENCODE_ROOT, "mcp-servers", "knowledge", "server.py"),
    timeout: 60000,
    // 启动前检测的依赖包（用 venv Python 尝试 import）
    requiredPackages: ["mcp", "sentence_transformers", "sqlite_vec"],
  },
  {
    name: "events",
    script: join(OPENCODE_ROOT, "mcp-servers", "events", "server.py"),
    timeout: 10000,
    requiredPackages: ["mcp"],
  },
] as const;

export class McpManager {
  private client: OpencodeClient;

  constructor(client: OpencodeClient) {
    this.client = client;
  }

  /**
   * 注册所有 MCP server。
   * 跨平台：通过 getPythonCmd() 获取当前平台的 venv Python 路径。
   * 依赖检测：启动前验证 requiredPackages 可 import，失败则跳过注册并输出安装提示。
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
    const { name, script, timeout, requiredPackages } = server;

    // 1. 检测 server.py 是否存在
    if (!existsSync(script)) {
      debugLog(`[McpManager] ${name} 跳过：server.py 不存在 ${script}`);
      return;
    }

    // 2. 检测依赖包
    const missing = this.checkPackages(venvPython, [...requiredPackages]);
    if (missing.length > 0) {
      debugLog(
        `[McpManager] ${name} 跳过：缺少依赖包 ${missing.join(", ")}。` +
        `安装命令：${venvPython} -m pip install ${missing.join(" ")}`,
      );
      return;
    }

    // 3. 通过 SDK 官方 API 注册
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
      debugLog(`[McpManager] ${name} 注册失败：${(e as Error)?.message}`);
    }
  }

  /**
   * 用 venv Python 一次性检测所有依赖包是否可 import。
   * 单次子进程调用，避免串行开 N 个进程。
   * 返回缺失的包名列表（空数组 = 全部可用）。
   */
  private checkPackages(venvPython: string, packages: string[]): string[] {
    try {
      const script = packages
        .map((pkg) => `try:\n  import ${pkg}\nexcept ImportError:\n  print("${pkg}")`)
        .join("\n");
      const output = execFileSync(venvPython, ["-c", script], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 15000,
        encoding: "utf-8",
      });
      return output.trim().split("\n").filter(Boolean);
    } catch (e) {
      debugLog(`[McpManager] checkPackages 子进程失败：${(e as Error)?.message}`);
      return packages;
    }
  }
}
