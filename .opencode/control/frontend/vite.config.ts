import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { writeFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

// 控制台前端 Vite 配置
// dev 模式：5173 端口，/api 反向代理到 9776 控制台后端
// release 模式：构建到 dist/，由控制台后端 starlette.staticfiles 服务

/**
 * write-dev-port 插件：listening 时把实际端口写入 DATA_DIR/.vite-dev.port。
 * 控制台后端 services/console_url.py 读取该文件 + TCP 探测，向 plugin/前端
 * 返回正确的开发态前端 URL。vite 端口冲突自动递增（5173→5174）时，
 * 写入的是递增后的真实端口，后端天然感知。
 */
function writeDevPort(): Plugin {
  return {
    name: "write-dev-port",
    apply: "serve",
    configureServer(server) {
      server.httpServer?.once("listening", () => {
        const addr = server.httpServer?.address();
        const port = typeof addr === "object" && addr ? addr.port : null;
        if (!port) return;
        // 与后端 config.py 对齐：DATA_DIR 环境变量 > 默认 ~/bw-security-analysis
        const dataDir =
          process.env.DATA_DIR ?? join(homedir(), "bw-security-analysis");
        try {
          writeFileSync(join(dataDir, ".vite-dev.port"), String(port));
          server.config.logger.info(
            `[write-dev-port] 已写入 ${dataDir}/.vite-dev.port (port=${port})`,
          );
        } catch (e) {
          server.config.logger.warn(
            `[write-dev-port] 写入失败: ${e instanceof Error ? e.message : e}`,
          );
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), writeDevPort()],
  server: {
    port: 5173,
    // 反向代理 API 请求到控制台后端
    proxy: {
      "/api": {
        target: "http://127.0.0.1:9776",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:9776",
        changeOrigin: true,
      },
      "/embed": {
        target: "http://127.0.0.1:9776",
        changeOrigin: true,
      },
      "/rerank": {
        target: "http://127.0.0.1:9776",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // chunk 大小警告阈值
    chunkSizeWarningLimit: 1000,
  },
});
