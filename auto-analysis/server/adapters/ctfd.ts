// server/adapters/ctfd.ts — CTFd REST API 适配器
import type { Task, TaskInfo, DownloadResult, SubmitResult } from "../../shared/types.js"
import type { SiteAdapter } from "./base.js"
import path from "node:path"
import fs from "node:fs"
import { execSync } from "node:child_process"

/**
 * CTFd 网站适配器
 *
 * 使用原生 fetch 调用 CTFd REST API。
 * API 参考: https://docs.ctfd.io/docs/api/
 */
export class CTFdAdapter implements SiteAdapter {
  private baseUrl: string
  private sessionCookie = ""

  constructor(baseUrl: string) {
    // 确保 baseUrl 不以 / 结尾
    this.baseUrl = baseUrl.replace(/\/+$/, "")
  }

  async login(username: string, password: string): Promise<void> {
    // CTFd 登录需要先获取 CSRF nonce，再 POST 登录
    const nonceResp = await fetch(`${this.baseUrl}/api/v1/auth/login`, {
      method: "GET",
    })
    const nonceData = await nonceResp.json() as { data?: { nonce?: string } }
    const nonce = nonceData?.data?.nonce
    if (!nonce) throw new Error("无法获取 CTFd CSRF nonce")

    const resp = await fetch(`${this.baseUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: username, password, nonce }),
    })

    // 从 Set-Cookie 提取 session
    const setCookie = resp.headers.getSetCookie()
    const sessionMatch = setCookie.find((c) => c.includes("session="))
    if (!sessionMatch) throw new Error("CTFd 登录失败：未获取到 session cookie")
    this.sessionCookie = sessionMatch.split(";")[0]!
  }

  private get headers(): Record<string, string> {
    return { Cookie: this.sessionCookie }
  }

  async listTasks(): Promise<Task[]> {
    const resp = await fetch(`${this.baseUrl}/api/v1/challenges`, {
      headers: this.headers,
    })
    const data = await resp.json() as { data?: Array<{ id: number; name: string; category: string; value: number }> }
    if (!data.data) throw new Error("获取题目列表失败")

    return data.data.map((c) => ({
      id: String(c.id),
      title: c.name,
      category: c.category,
      value: c.value,
      status: "pending" as const,
      retryCount: 0,
      maxRetries: 3,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }))
  }

  async getTaskInfo(taskId: string): Promise<TaskInfo> {
    const resp = await fetch(`${this.baseUrl}/api/v1/challenges/${taskId}`, {
      headers: this.headers,
    })
    const data = await resp.json() as {
      data?: {
        id: number
        name: string
        category: string
        value: number
        description: string
        files?: Array<{ url?: string; name?: string }>
        hints?: Array<{ content?: string }>
      }
    }
    if (!data.data) throw new Error(`获取题目 ${taskId} 详情失败`)

    const chal = data.data
    return {
      id: String(chal.id),
      title: chal.name,
      category: chal.category,
      value: chal.value,
      description: chal.description,
      files: (chal.files ?? []).map((f) => ({
        url: f.url ?? "",
        name: f.name ?? "unknown",
      })),
      hints: (chal.hints ?? []).filter((h) => h.content).map((h) => ({ content: h.content! })),
    }
  }

  async submitAnswer(taskId: string, answer: string): Promise<SubmitResult> {
    // 提交前需要获取最新的 CSRF nonce
    const nonceResp = await fetch(`${this.baseUrl}/api/v1/challenges/${taskId}`, {
      headers: this.headers,
    })
    const nonceText = await nonceResp.text()
    // CTFd 页面中 nonce 通常在 meta 标签或 JSON 中
    const nonceMatch = nonceText.match(/"nonce"\s*:\s*"([^"]+)"/)
    const nonce = nonceMatch?.[1] ?? ""

    const resp = await fetch(`${this.baseUrl}/api/v1/challenges/attempt`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Cookie: this.sessionCookie,
      },
      body: JSON.stringify({
        challenge_id: Number(taskId),
        submission: answer,
        nonce,
      }),
    })
    const result = await resp.json() as { success?: boolean; message?: string; data?: { status?: string } }

    return {
      success: result.success === true || result.data?.status === "correct",
      message: result.message ?? result.data?.status,
    }
  }

  async downloadFile(url: string, outputPath: string): Promise<DownloadResult> {
    // 拼接完整 URL
    const fullUrl = url.startsWith("http") ? url : `${this.baseUrl}${url}`

    const resp = await fetch(fullUrl, { headers: this.headers })
    if (!resp.ok) {
      return { success: false, path: outputPath }
    }

    // 确保输出目录存在
    const dir = path.dirname(outputPath)
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true })
    }

    // 写入文件
    const buffer = Buffer.from(await resp.arrayBuffer())
    fs.writeFileSync(outputPath, buffer)

    // 智能解压
    const extractDir = tryExtract(outputPath)
    return { success: true, path: outputPath, extractDir }
  }
}

/**
 * 智能解压：检测压缩格式并解压
 * zip/tar.gz，散落一级目录时创建子目录
 */
function tryExtract(filePath: string): string | undefined {
  const ext = filePath.toLowerCase()
  const dir = path.dirname(filePath)
  const baseName = path.basename(filePath, path.extname(filePath))
  const extractDir = path.join(dir, baseName)

  try {
    if (ext.endsWith(".zip")) {
      // 使用 PowerShell 的 Expand-Archive（跨平台兼容）
      execSync(`powershell -Command "Expand-Archive -Path '${filePath}' -DestinationPath '${extractDir}' -Force"`, {
        stdio: "pipe",
      })

      // 检查是否散落一级（解压后只有一个目录 → 不需要子目录）
      const entries = fs.readdirSync(extractDir)
      if (entries.length === 1) {
        const singleEntry = path.join(extractDir, entries[0]!)
        if (fs.statSync(singleEntry).isDirectory()) {
          // 单目录：将子目录内容提升到 extractDir
          const tempDir = extractDir + "_tmp"
          fs.renameSync(singleEntry, tempDir)
          fs.rmdirSync(extractDir)
          fs.renameSync(tempDir, extractDir)
          return extractDir
        }
      }
      return extractDir
    }

    if (ext.endsWith(".tar.gz") || ext.endsWith(".tgz")) {
      execSync(`tar -xzf "${filePath}" -C "${dir}"`, { stdio: "pipe" })
      return dir
    }
  } catch {
    // 解压失败不影响下载成功
  }

  return undefined
}
