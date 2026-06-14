// server/routes/config.ts — 配置 API 路由
import type { Router } from "express"
import express from "express"
import type { Scheduler } from "../scheduler.js"
import type { SchedulerConfig } from "../../shared/types.js"
import { saveCredentials, getCredentials } from "../credentials.js"

export function configRouter(scheduler: Scheduler): Router {
  const router = express.Router()

  /** GET / — 获取当前配置 */
  router.get("/", (_req, res) => {
    const config = scheduler.getConfig()
    res.json(config)
  })

  /** PATCH / — 更新调度器配置 */
  router.patch("/", (req, res) => {
    const { maxConcurrency, maxRetries } = req.body as Partial<SchedulerConfig>
    scheduler.updateConfig({ maxConcurrency, maxRetries })
    res.json(scheduler.getConfig())
  })

  /** PUT /credentials — 保存网站凭据 */
  router.put("/credentials", async (req, res) => {
    const { siteUrl, username, password } = req.body as {
      siteUrl?: string
      username?: string
      password?: string
    }
    if (!siteUrl || !username || !password) {
      res.status(400).json({ error: "缺少 siteUrl、username 或 password" })
      return
    }
    await saveCredentials(siteUrl, username, password)
    res.json({ message: "凭据已保存" })
  })

  /** GET /credentials — 检查凭据是否存在 */
  router.get("/credentials", async (req, res) => {
    const { siteUrl } = req.query as { siteUrl?: string }
    if (!siteUrl) {
      res.status(400).json({ error: "缺少 siteUrl 参数" })
      return
    }
    const creds = await getCredentials(siteUrl)
    res.json({ exists: creds !== null, username: creds?.username })
  })

  return router
}
