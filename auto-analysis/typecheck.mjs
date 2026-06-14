// typecheck.mjs — 仅检查项目自有代码的类型
// 排除 vendor SDK 的自身类型错误（SDK 未构建，exports 指向 .ts 源码）
import { execSync } from "node:child_process"

let output = ""
try {
  output = execSync("npx tsc --noEmit", { encoding: "utf8" })
} catch (e) {
  output = [e.stdout, e.stderr, e.output?.[1]?.toString(), e.output?.[2]?.toString()]
    .filter(Boolean)
    .join("")
}

if (!output.trim()) {
  console.log("类型检查通过（无错误）")
  process.exit(0)
}

// 过滤掉 SDK 自身的错误（路径包含 vendor/opencode）
const ourErrors = []
const sdkErrors = []
for (const line of output.split("\n")) {
  if (!line.includes(".ts") || !line.includes("error TS")) continue
  if (line.includes("vendor/opencode")) {
    sdkErrors.push(line)
  } else {
    ourErrors.push(line)
  }
}

if (ourErrors.length > 0) {
  console.error("项目代码类型错误:")
  ourErrors.forEach((e) => console.error(e))
  process.exit(1)
} else {
  console.log(`类型检查通过（忽略 ${sdkErrors.length} 个 SDK 内部错误）`)
}
