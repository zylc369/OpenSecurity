import { join } from "path";
import { existsSync } from "fs";
import type { OpencodeClient } from "@opencode-ai/sdk";
import { OPENCODE_ROOT, DATA_DIR } from "./constants";
import { getPythonCmd } from "./venv";
import { getControlPort } from "./control-manager";
import { debugLog } from "./logging";

// MCP server 定义：name → (server.py 路径, timeout)
// 依赖安装收口在 detect_py_deps.py 唯一清单（server 由 venv python 直跑）
// 这里不检测依赖——server.py 启动失败时错误从 stderr 捕获
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
  {
    name: "ocr",
    script: join(OPENCODE_ROOT, "mcp-servers", "ocr", "server.py"),
    timeout: 60000, // 薄壳（模型在控制台），握手快；acquire 在 lifespan 内含首载余量
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
   *
   * 端口发现：不再注入 OPENCODE_CONTROL_PORT——Python 侧统一走 control_url.py
   * 读端口文件（事实来源），控制台重启换端口后 MCP 自动恢复（无需重启）。
   * 此处仍调 getControlPort() 确保控制台已启动（必要时触发启动），仅用于日志。
   */
  async registerAll(): Promise<void> {
    const venvPython = getPythonCmd();
    if (!venvPython) {
      debugLog(`[McpManager] 注册中止：venv Python 未找到（getPythonCmd 返回 null，conda/venv 未就绪）`);
      return;
    }

    // 确保控制台已启动（必要时触发启动）。端口由 Python 侧 control_url.py 自行发现。
    const controlPort = await getControlPort();
    debugLog(
      controlPort
        ? `[McpManager] 控制台端口 ${controlPort}（Python 侧经 control_url.py 自动发现）`
        : `[McpManager] 控制台未启动——MCP 首次请求时经端口文件自行发现`,
    );

    for (const server of MCP_SERVERS) {
      await this.registerOne(server, venvPython, controlPort);
    }
  }

  private async registerOne(
    server: (typeof MCP_SERVERS)[number],
    venvPython: string,
    controlPort: number | null,
  ): Promise<void> {
    const { name, script, timeout } = server;

    // 1. 检测 server.py 是否存在
    if (!existsSync(script)) {
      debugLog(`[McpManager] ${name} 跳过：server.py 不存在 ${script}`);
      return;
    }

    // 2. 构造 env：只注入 DATA_DIR（control_url.py 用它定位端口文件）
    const mcpEnv: Record<string, string> = {
      DATA_DIR: DATA_DIR,
    };

    // 3. 通过 SDK 官方 API 注册
    try {
      await this.client.mcp.add({
        body: {
          name,
          config: {
            type: "local" as const,
            command: [venvPython, script],
            // 字段名必须是 environment（opencode 运行时读 mcp.environment）。
            // 历史上误写 env 被静默丢弃 → DATA_DIR 从未注入 MCP 子进程，
            // 生产靠默认值巧合可用，测试沙箱 DATA_DIR 则泄漏到生产端口文件
            environment: mcpEnv,
            enabled: true,
            timeout,
          },
        },
      });
      debugLog(`[McpManager] ${name} 注册成功：python=${venvPython} server=${script} port=${controlPort}`);
    } catch (e) {
      const errMsg = (e as Error)?.message ?? String(e);
      debugLog(`[McpManager] ${name} 注册失败：${errMsg}`);
      const stderr = (e as { stderr?: Buffer }).stderr;
      if (stderr) {
        debugLog(`  server stderr: ${stderr.toString().slice(-500)}`);
      }
    }
  }
}
