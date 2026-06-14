// server/routes/tasks.ts — 任务 API 路由
import type { Router } from "express"
import express from "express"
import type { Scheduler } from "../scheduler.js"
import { getCredentials } from "../credentials.js"
import { CTFdAdapter } from "../adapters/ctfd.js"
import logger from "../logger.js"

export function taskRouter(scheduler: Scheduler): Router {
  const router = express.Router()

  /** GET / — 获取所有任务 */
  router.get("/", async (_req, res) => {
    const tasks = await scheduler.getTasks()
    res.json(tasks)
  })

  /** POST /start — 开始分析 */
  router.post("/start", async (req, res) => {
    const { siteUrl } = req.body as { siteUrl?: string }
    if (!siteUrl) {
      res.status(400).json({ error: "缺少 siteUrl 参数" })
      return
    }

    try {
      if (scheduler.isRunning()) {
        res.status(409).json({ error: "调度器正在运行，请先取消当前任务" })
        return
      }

      const creds = await getCredentials(siteUrl)
      if (!creds) {
        res.status(404).json({ error: `未找到 ${siteUrl} 的凭据，请先配置` })
        return
      }

      const adapter = new CTFdAdapter(siteUrl)
      await adapter.login(creds.username, creds.password)

      const tasks = await adapter.listTasks()

      // 异步启动调度（不阻塞响应）
      scheduler.start(tasks, {
        getTaskInfo: (taskId) => adapter.getTaskInfo(taskId),
        downloadFile: (url, outputPath) => adapter.downloadFile(url, outputPath),
        submitAnswer: (taskId, answer) => adapter.submitAnswer(taskId, answer),
      }).catch((err) => {
        logger.error({ err }, "调度器异常退出")
      })

      res.json({ message: `开始分析 ${tasks.length} 个题目`, taskCount: tasks.length })
    } catch (e) {
      res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
    }
  })

  /** POST /abort — 取消调度 */
  router.post("/abort", (_req, res) => {
    scheduler.abort()
    res.json({ message: "已取消调度" })
  })

  return router
}
