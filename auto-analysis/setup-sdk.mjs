// setup-sdk.mjs — npm postinstall: 为 SDK 创建 node_modules junction
// SDK 通过 file: link 安装，但其内部依赖 (cross-spawn) 无法从 SDK 目录解析到我们的 node_modules。
// 创建 junction 让 SDK 的模块解析能找到我们的 node_modules。
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const sdkDir = path.resolve(__dirname, "../vendor/opencode/packages/sdk/js")
const sdkNodeModules = path.join(sdkDir, "node_modules")
const ourNodeModules = path.resolve(__dirname, "node_modules")

// 检查 SDK 目录是否存在
if (!fs.existsSync(sdkDir)) {
  console.log("setup-sdk: SDK 目录不存在，跳过")
  process.exit(0)
}

// 已存在则跳过
if (fs.existsSync(sdkNodeModules)) {
  console.log("setup-sdk: SDK node_modules 已存在，跳过")
  process.exit(0)
}

// 创建 junction（Windows 目录符号链接）
try {
  fs.mkdirSync(sdkNodeModules, { recursive: true })
  // Windows: 用 junction 替代空目录
  fs.rmdirSync(sdkNodeModules)
  fs.symlinkSync(ourNodeModules, sdkNodeModules, "junction")
  console.log("setup-sdk: 已创建 SDK node_modules junction")
} catch (e) {
  console.error("setup-sdk: 创建 junction 失败:", e.message)
  console.error("setup-sdk: 请手动运行: New-Item -ItemType Junction -Path vendor/opencode/packages/sdk/js/node_modules -Target auto-analysis/node_modules")
}
