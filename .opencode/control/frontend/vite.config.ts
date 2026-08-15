import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 控制台前端 Vite 配置
// dev 模式：5173 端口，/api 反向代理到 9776 控制台后端
// release 模式：构建到 dist/，由控制台后端 starlette.staticfiles 服务
export default defineConfig({
  plugins: [react()],
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
