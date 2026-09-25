import { join } from "path";
import { existsSync } from "fs";
import type { OpencodeClient } from "@opencode-ai/sdk";
import { OPENCODE_ROOT, DATA_DIR } from "./constants";
import { getPythonCmd } from "./venv";
import { startControl } from "./control-manager";
import { debugLog } from "./logging";

// MCP server 定义：项目内 server.py（script）或 venv 模块入口（module + moduleArgs）
// 依赖安装收口在 detect_py_deps.py 唯一清单（server 由 venv python 直跑）
// 这里不检测依赖——启动失败时错误从握手失败的 stderr 捕获
interface McpServerDef {
  name: string;
  timeout: number;
  script?: string;        // 项目内 server.py（注册前 existsSync 检查）
  module?: string;        // venv 内 `python -m <module>` 入口（第三方包自带 MCP server）
  moduleArgs?: string[];  // -m 后参数
}
const MCP_SERVERS: McpServerDef[] = [
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
  {
    name: "proxy",
    script: join(OPENCODE_ROOT, "mcp-servers", "proxy", "server.py"),
    timeout: 60000, // 薄壳（IP池在控制台），握手快
  },
];

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
   * 端口发现：不注入任何地址——Python 侧统一走 control_url.py 连 IPC
   * （sock/管道，编译期常量地址），控制台重启后 MCP 重连自愈。
   * 此处调 startControl() 确保控制台已启动（必要时触发启动）。
   */
  async registerAll(): Promise<void> {
    const venvPython = getPythonCmd();
    if (!venvPython) {
      debugLog(`[McpManager] 注册中止：venv Python 未找到（getPythonCmd 返回 null，conda/venv 未就绪）`);
      return;
    }

    // 确保控制台已启动（幂等：活则复用、死则拉起）。MCP 经 IPC 地址自行连接。
    const ready = await startControl();
    debugLog(
      ready
        ? `[McpManager] 控制台就绪（MCP 经 IPC 自行发现）`
        : `[McpManager] 控制台未启动——MCP 首次请求时经 IPC 地址自行重试`,
    );

    for (const server of MCP_SERVERS) {
      await this.registerOne(server, venvPython);
    }
  }

  private async registerOne(
    server: McpServerDef,
    venvPython: string,
  ): Promise<void> {
    const { name, timeout } = server;

    // 1. 构造启动命令: script=项目内 server.py（存在性检查）/ module=venv 内 python -m
    let command: string[];
    if (server.script) {
      if (!existsSync(server.script)) {
        debugLog(`[McpManager] ${name} 跳过：server.py 不存在 ${server.script}`);
        return;
      }
      command = [venvPython, server.script];
    } else if (server.module) {
      // 模块型不预检（预检=每注册一次起子进程 import，开销回到被砍掉的 checkPackages 时代）;
      // 包缺失 → 握手失败 stderr 捕获（与 script 型同哲学）
      command = [venvPython, "-m", server.module, ...(server.moduleArgs ?? [])];
    } else {
      debugLog(`[McpManager] ${name} 跳过：script 与 module 均未定义`);
      return;
    }

    // 2. 构造 env：只注入 DATA_DIR（control_url.py 用它定位 IPC socket）
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
            command,
            // 字段名必须是 environment（opencode 运行时读 mcp.environment）。
            // 历史上误写 env 被静默丢弃 → DATA_DIR 从未注入 MCP 子进程，
            // 生产靠默认值巧合可用，测试沙箱 DATA_DIR 则泄漏到生产端口文件
            environment: mcpEnv,
            enabled: true,
            timeout,
          },
        },
      });
      debugLog(`[McpManager] ${name} 注册成功：command=${command.join(" ")}（IPC 地址自行发现）`);
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
