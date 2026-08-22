/**
 * 控制台 IPC HTTP 客户端（TS 侧唯一出口）。
 *
 * 平台策略（两平台均走 IPC，无 TCP 降级路径）：
 *   • macOS/Linux：Bun fetch 原生 `unix:` 选项连 Unix Domain Socket（实测 Bun 1.3.14 ✓）
 *   • Windows：node:net.connect 连命名管道（Bun 1.1.28+ 官方支持）+ 手写 HTTP/1.1
 *     报文。不用 node:http 的 socketPath——Bun 在 Windows 管道上有未修复 bug
 *     （oven-sh/bun#18653：socketPath 被误解析为 localhost TCP 连接）。
 *     管道故障 = 控制台故障，如实抛错（不做 TCP 盲扫降级——降级掩盖根因）。
 *
 * 浏览器 TCP 真实端口（服务端可能顺延，仅供展示 URL 用）：
 *   经 IPC GET /api/console-url 获取（IPC 不可达时无意义，返回 null）。
 *
 * 语义：connect 即发现即校验（无端口文件、无 PID 四步检查）。
 */
import { connect as netConnect, type Socket } from "node:net";
import {
  CONTROL_UNIX_SOCKET,
  CONTROL_WIN_PIPE,
  IS_WINDOWS,
} from "./constants";
import { debugLog } from "./logging";

export interface ControlFetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  timeoutMs?: number;
}

/** Windows 管道可达性缓存（探测失败置 false，后续请求直接明确报错）。 */
class ControlHttpClient {
  private winPipeUsable: boolean | undefined;

  /** 控制台 HTTP 请求（Unix: uds / Windows: node:net 管道）。 */
  async fetch(path: string, init: ControlFetchInit = {}): Promise<Response> {
    const timeoutMs = init.timeoutMs ?? 8000;
    if (!IS_WINDOWS) {
      // Unix：Bun fetch 原生 unix 选项（host 为占位，实际由 socket 决定）
      try {
        return await fetch(`http://localhost${path}`, {
          method: init.method,
          headers: init.headers,
          body: init.body,
          unix: CONTROL_UNIX_SOCKET,
          signal: AbortSignal.timeout(timeoutMs),
        } as RequestInit);
      } catch (e) {
        debugLog(
          `controlFetch: uds 请求失败 ${path}: ${(e as Error)?.message}（sock=${CONTROL_UNIX_SOCKET}）`,
        );
        throw e;
      }
    }

    // Windows：node:net 管道（1.1.28+ 官方支持）。故障 = 控制台故障，如实抛错
    if (this.winPipeUsable === false) {
      debugLog(`controlFetch: Windows 管道已标记不可用，拒绝请求 ${path}`);
      throw new Error(
        "Windows 管道通道不可用（此前探测失败；控制台未启动或管道故障）",
      );
    }
    try {
      const res = await this.winPipeRequest(path, init, timeoutMs);
      this.winPipeUsable = true;
      return res;
    } catch (e) {
      this.winPipeUsable = false;
      debugLog(
        `controlFetch: Windows 管道请求失败 ${path}: ${(e as Error).message}（后续请求直接拒绝）`,
      );
      throw e;
    }
  }

  /** node:net 连命名管道 + 手写 HTTP/1.1 报文（Windows）。聚合响应为 Response。 */
  private winPipeRequest(
    path: string,
    init: ControlFetchInit,
    timeoutMs: number,
  ): Promise<Response> {
    return new Promise<Response>((resolve, reject) => {
      const socket: Socket = netConnect(CONTROL_WIN_PIPE);
      const chunks: Buffer[] = [];
      let settled = false;

      const fail = (err: Error) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        reject(err);
      };
      const timer = setTimeout(
        () => fail(new Error(`pipe request timeout ${timeoutMs}ms`)),
        timeoutMs,
      );

      socket.on("connect", () => {
        // 手写 HTTP/1.1 报文（无传输层依赖——Bun node:http socketPath 在管道上有 bug）
        const headers: Record<string, string> = {
          Host: "localhost",
          Connection: "close", // 单请求单连接（控制台 API 均短请求），免解析 keep-alive
          ...init.headers,
        };
        if (init.body !== undefined) {
          headers["Content-Length"] = String(Buffer.byteLength(init.body));
        }
        const reqLines = [`${init.method ?? "GET"} ${path} HTTP/1.1`];
        for (const [k, v] of Object.entries(headers)) {
          reqLines.push(`${k}: ${v}`);
        }
        socket.write(reqLines.join("\r\n") + "\r\n\r\n" + (init.body ?? ""));
      });

      socket.on("data", (c: Buffer) => chunks.push(c));
      socket.on("end", () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try {
          const raw = Buffer.concat(chunks);
          const headerEnd = raw.indexOf("\r\n\r\n");
          if (headerEnd < 0) {
            throw new Error("pipe response: 未找到 HTTP 头边界");
          }
          const statusLine = raw.subarray(0, raw.indexOf("\r\n")).toString();
          const statusMatch = statusLine.match(/^HTTP\/\d\.\d (\d+)/);
          if (!statusMatch) {
            throw new Error(`pipe response: 非法状态行 ${statusLine.slice(0, 40)}`);
          }
          const respHeaders = new Headers();
          for (const line of raw.subarray(raw.indexOf("\r\n") + 2, headerEnd)
            .toString().split("\r\n")) {
            const idx = line.indexOf(":");
            if (idx > 0) respHeaders.set(line.slice(0, idx).trim(), line.slice(idx + 1).trim());
          }
          // Content-Length 定界响应体（chunked 理论上不出现——API 均小 JSON；
          // 出现则按 0-length chunk 兜底到 end 事件已收的全部字节）
          const body = raw.subarray(headerEnd + 4);
          resolve(
            new Response(body, {
              status: parseInt(statusMatch[1], 10),
              headers: respHeaders,
            }),
          );
        } catch (e) {
          reject(e as Error);
        }
      });
      socket.on("error", (e: Error) => fail(e));
      socket.on("close", () => {
        // 服务器在 end 前断开（Connection: close 正常路径已由 end 处理）
        if (!settled) fail(new Error("pipe closed before response"));
      });
    });
  }
}

// 模块级单例 + 同名委托（消费方零改动）
const client = new ControlHttpClient();

export function controlFetch(path: string, init?: ControlFetchInit): Promise<Response> {
  return client.fetch(path, init);
}
