// server/opencode.ts — OpenCode SDK 封装
import { createOpencodeServer, createOpencodeClient } from "@opencode-ai/sdk"
import path from "node:path"
import fs from "node:fs"
import { fileURLToPath } from "node:url"

// ESM 兼容：Node 22+ 使用 import.meta.dirname，否则用 fileURLToPath
// （不用 URL.pathname，Windows 会多前导斜杠）
const __dirname = import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url))

/** 从当前文件位置向上查找包含 .opencode/ 的目录 */
function findProjectRoot(): string {
  let dir = path.resolve(__dirname, "..")
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, ".opencode"))) return dir
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  // 回退：auto-analysis/ 的上级
  return path.resolve(__dirname, "..")
}

const PROJECT_ROOT = findProjectRoot()

let serverInstance: Awaited<ReturnType<typeof createOpencodeServer>> | null = null
let serverPromise: Promise<Awaited<ReturnType<typeof createOpencodeServer>>> | null = null

/** 获取 OpenCode server 实例（单例，并发安全） */
export async function getServer() {
  if (!serverInstance && !serverPromise) {
    serverPromise = createOpencodeServer().then((server) => {
      serverInstance = server
      return server
    })
  }
  return serverInstance ?? serverPromise!
}

/** 获取 OpenCode SDK client */
export async function getClient() {
  const server = await getServer()
  return createOpencodeClient({ baseUrl: server.url, directory: PROJECT_ROOT })
}

/** 关闭 OpenCode server */
export async function closeServer() {
  if (serverInstance) {
    serverInstance.close()
    serverInstance = null
    serverPromise = null
  }
}

/** 从 SDK 响应中提取文本 */
function extractText(
  data: { parts?: Array<{ type: string; text?: string }> } | undefined,
): string {
  if (!data?.parts) return ""
  return data.parts
    .filter((p) => p.type === "text" && p.text)
    .map((p) => p.text!)
    .join("\n")
}

/**
 * 调用 security-coordinator 分析任务
 *
 * 使用 session.prompt（同步阻塞）：等待 coordinator 完成全部工作后返回结果。
 * 并发由调度器通过 Promise.all 控制。
 */
export async function analyze(taskPrompt: string): Promise<string> {
  const client = await getClient()
  const session = await client.session.create()
  if (session.error) {
    throw new Error(`创建 session 失败: ${JSON.stringify(session.error)}`)
  }
  const result = await client.session.prompt({
    path: { id: session.data.id },
    body: {
      agent: "security-coordinator",
      parts: [{ type: "text", text: taskPrompt }],
    },
  })
  if (result.error) {
    throw new Error(`OpenCode 分析失败: ${JSON.stringify(result.error)}`)
  }
  return extractText(result.data)
}
