import { defineConfig } from "vitest/config";

// 前端单测（node 环境——纯逻辑层: utils/api/hooks 计算与解析；
// DOM 组件不在本套件范围）。
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
