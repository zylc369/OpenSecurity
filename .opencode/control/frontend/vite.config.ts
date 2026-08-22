import { defineConfig, type Plugin, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";
import { request } from "node:http";
import { join } from "path";
import { homedir } from "os";

// 控制台前端 Vite 配置
// dev 模式：5173 端口，/api 反向代理到控制台 TCP（浏览器通道，真实端口经 IPC 查询——
// 控制台 9776 被占时顺延）；release 模式：构建到 dist/，由控制台后端 staticfiles 服务

/** IPC 地址（与控制台 config.py 常量一致，进程不同按约定复制）。 */
function ipcSocketPath(): string {
  const dataDir = process.env.DATA_DIR ?? join(homedir(), "bw-security-analysis");
  return process.platform === "win32"
    ? "\\\\.\\pipe\\opensecurity-control-482964"
    : join(dataDir, "opensecurity-control.sock");
}

/** 经 IPC 查控制台真实 TCP 端口（顺延后动态值）；失败回退 9776。 */
function fetchConsoleTcpPort(): Promise<number> {
  return new Promise((resolve) => {
    const req = request(
      {
        socketPath: ipcSocketPath(),
        path: "/api/console-url",
        method: "GET",
        timeout: 3000,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => {
          try {
            const port = JSON.parse(Buffer.concat(chunks).toString()).tcp_port;
            resolve(typeof port === "number" && port > 0 ? port : 9776);
          } catch {
            resolve(9776);
          }
        });
      },
    );
    req.on("timeout", () => {
      req.destroy();
      resolve(9776);
    });
    req.on("error", () => resolve(9776));
    req.end();
  });
}

/**
 * report-dev-port 插件：listening 时把实际端口经 IPC 上报给控制台
 * （POST /api/dev-url，控制台存内存 FrontendPortRegistry）。
 * vite 端口冲突自动递增（5173→5174）时，上报的是递增后的真实端口。
 */
function reportDevPort(): Plugin {
  return {
    name: "report-dev-port",
    apply: "serve",
    configureServer(server) {
      server.httpServer?.once("listening", () => {
        const addr = server.httpServer?.address();
        const port = typeof addr === "object" && addr ? addr.port : null;
        if (!port) return;
        const body = JSON.stringify({ port });
        try {
          const req = request(
            {
              socketPath: ipcSocketPath(),
              path: "/api/dev-url",
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(body),
              },
              timeout: 3000,
            },
            (res) => {
              res.resume();
              server.config.logger.info(
                `[report-dev-port] 已上报 dev 端口 ${port}（IPC ${res.statusCode}）`,
              );
            },
          );
          req.on("timeout", () => req.destroy());
          req.on("error", (e) => {
            server.config.logger.warn(
              `[report-dev-port] 上报失败（控制台未启动？）: ${e.message}`,
            );
          });
          req.write(body);
          req.end();
        } catch (e) {
          server.config.logger.warn(
            `[report-dev-port] 上报异常: ${e instanceof Error ? e.message : e}`,
          );
        }
      });
    },
  };
}

export default defineConfig(async (): Promise<UserConfig> => {
  // 异步配置：proxy target 用控制台真实 TCP 端口（顺延场景自动对齐）
  const consolePort = await fetchConsoleTcpPort();
  const target = `http://127.0.0.1:${consolePort}`;
  return {
    plugins: [react(), reportDevPort()],
  server: {
    port: 5173,
    // 反向代理 API 请求到控制台后端
    proxy: {
      "/api": { target, changeOrigin: true },
      "/health": { target, changeOrigin: true },
      "/embed": { target, changeOrigin: true },
      "/rerank": { target, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // chunk 大小警告阈值
    chunkSizeWarningLimit: 1000,
  },
  };
});
