// server/scheduler.ts — 任务调度器（并发控制、重试）
import type { Task, TaskInfo, SchedulerConfig, DownloadResult, SubmitResult } from "../shared/types.js"
import { analyze } from "./opencode.js"
import { readJson, writeJson } from "./file-store.js"
import logger from "./logger.js"
import { EventEmitter } from "node:events"
import path from "node:path"
import fs from "node:fs"
import { fileURLToPath } from "node:url"

const TASKS_FILE = "tasks.json"
const __dirname = import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url))
const FILES_DIR = path.resolve(__dirname, "../private_data/files")

/** 任务回调（由路由层注入适配器实现） */
export interface TaskCallbacks {
  getTaskInfo: (taskId: string) => Promise<TaskInfo>
  downloadFile: (url: string, outputPath: string) => Promise<DownloadResult>
  submitAnswer: (taskId: string, answer: string) => Promise<SubmitResult>
}

/** 调度器事件，用于 SSE 推送 */
export interface SchedulerEvents {
  "task:status": (task: Task) => void
  "task:log": (taskId: string, message: string) => void
  "scheduler:complete": (summary: { total: number; success: number; failed: number }) => void
}

export class Scheduler extends EventEmitter {
  private config: SchedulerConfig
  private abortController: AbortController | null = null
  private taskMap = new Map<string, Task>()
  private running = false

  constructor(config?: Partial<SchedulerConfig>) {
    super()
    this.config = {
      maxConcurrency: config?.maxConcurrency ?? 2,
      maxRetries: config?.maxRetries ?? 3,
    }
  }

  /** 更新配置 */
  updateConfig(config: Partial<SchedulerConfig>) {
    if (config.maxConcurrency !== undefined) this.config.maxConcurrency = config.maxConcurrency
    if (config.maxRetries !== undefined) this.config.maxRetries = config.maxRetries
  }

  getConfig(): SchedulerConfig {
    return { ...this.config }
  }

  /** 获取所有任务（首次从文件加载，之后用内存缓存） */
  async getTasks(): Promise<Task[]> {
    if (this.taskMap.size === 0) {
      const tasks = (await readJson<Task[]>(TASKS_FILE)) ?? []
      for (const t of tasks) this.taskMap.set(t.id, t)
    }
    return [...this.taskMap.values()]
  }

  /** 持久化当前内存中的任务到文件 */
  private async persistTasks() {
    await writeJson(TASKS_FILE, [...this.taskMap.values()])
  }

  /** 更新单个任务（内存 + 持久化） */
  private async updateAndPersist(task: Task) {
    task.updatedAt = Date.now()
    this.taskMap.set(task.id, task)
    await this.persistTasks()
  }

  /** 是否正在运行 */
  isRunning(): boolean {
    return this.running
  }

  /** 启动分析调度 */
  async start(tasks: Task[], callbacks: TaskCallbacks): Promise<void> {
    if (this.running) throw new Error("调度器正在运行，请先取消当前任务")
    this.running = true
    this.abortController = new AbortController()
    const signal = this.abortController.signal

    try {
      this.taskMap.clear()
      for (const task of tasks) this.taskMap.set(task.id, task)
      await this.persistTasks()

      // 信号量控制并发
      const queue = [...tasks]

      const runNext = async (): Promise<void> => {
        while (queue.length > 0 && !signal.aborted) {
          const task = queue.shift()!
          try {
            await this.executeTask(task, callbacks, signal)
          } catch (err) {
            // executeTask 内部已处理异常，此处仅保证 worker 不退出
            logger.error({ err, taskId: task.id }, "任务执行意外失败")
          }
        }
      }

      // 启动 maxConcurrency 个 worker
      const workers = Array.from({ length: Math.min(this.config.maxConcurrency, tasks.length) }, () => runNext())
      await Promise.all(workers)

      // 输出汇总
      const finalTasks = [...this.taskMap.values()]
      const success = finalTasks.filter((t) => t.status === "success").length
      const failed = finalTasks.filter((t) => t.status === "failed").length
      this.emit("scheduler:complete", { total: finalTasks.length, success, failed })
    } finally {
      this.running = false
    }
  }

  /** 执行单个任务（含重试） */
  private async executeTask(
    task: Task,
    callbacks: TaskCallbacks,
    signal: AbortSignal,
  ): Promise<void> {
    for (let attempt = 0; attempt <= task.maxRetries; attempt++) {
      if (signal.aborted) return

      task.status = "running"
      task.retryCount = attempt
      await this.updateAndPersist(task)
      this.emit("task:status", task)

      try {
        this.emit("task:log", task.id, `开始分析（第 ${attempt + 1} 次）`)

        // 1. 获取题目详情
        this.emit("task:log", task.id, "获取题目详情...")
        const info = await callbacks.getTaskInfo(task.id)

        // 2. 下载附件
        const downloadedPaths: string[] = []
        if (info.files && info.files.length > 0) {
          const taskDir = path.join(FILES_DIR, task.id)
          fs.mkdirSync(taskDir, { recursive: true })
          for (const file of info.files) {
            if (!file.url) continue
            const outputPath = path.join(taskDir, file.name)
            this.emit("task:log", task.id, `下载附件: ${file.name}`)
            const dlResult = await callbacks.downloadFile(file.url, outputPath)
            if (dlResult.success) {
              downloadedPaths.push(dlResult.extractDir ?? dlResult.path)
            }
          }
        }

        // 3. 构建分析 prompt
        const prompt = buildPrompt(task, info, downloadedPaths)
        this.emit("task:log", task.id, "开始 AI 分析...")

        // 4. 调用 coordinator 分析
        const result = await analyze(prompt)
        this.emit("task:log", task.id, "分析完成，提取答案中...")

        // 5. 提取 flag 格式的答案
        const flagMatch = result.match(/flag\{[^}]+\}/i) ?? result.match(/[a-f0-9]{32}/i)
        const answer = flagMatch?.[0]?.trim() ?? result.trim()
        task.answer = answer

        // 6. 提交答案
        const submitResult = await callbacks.submitAnswer(task.id, answer)
        this.emit("task:log", task.id, `提交结果: ${submitResult.message ?? (submitResult.success ? "正确" : "错误")}`)

        if (submitResult.success) {
          task.status = "success"
          await this.updateAndPersist(task)
          this.emit("task:status", task)
          return
        }

        // 提交失败，准备重试
        task.error = submitResult.message ?? "答案错误"
      } catch (e) {
        task.error = e instanceof Error ? e.message : String(e)
        this.emit("task:log", task.id, `分析出错: ${task.error}`)
      }
    }

    // 所有重试用完，标记失败
    task.status = "failed"
    await this.updateAndPersist(task)
    this.emit("task:status", task)
  }

  /** 取消调度 */
  abort() {
    this.abortController?.abort()
  }
}

/** 构建分析 prompt（题目信息 + 附件路径） */
function buildPrompt(task: Task, info: TaskInfo, downloadedPaths: string[]): string {
  let prompt = `请分析以下 CTF 题目并给出 flag：\n题目：${task.title}\n类别：${task.category}\n分值：${task.value}\n\n描述：${info.description}`

  if (info.hints && info.hints.length > 0) {
    prompt += `\n\n提示：${info.hints.map((h) => h.content).join("\n")}`
  }

  if (downloadedPaths.length > 0) {
    prompt += `\n\n附件已下载到以下路径：\n${downloadedPaths.join("\n")}`
  }

  return prompt
}
