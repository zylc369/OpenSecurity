// server/index.ts — 入口：启动 Express + OpenCode server
import express from "express"
import cors from "cors"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { handleSSE, registerSchedulerEvents } from "./routes/events.js"
import { taskRouter } from "./routes/tasks.js"
import { configRouter } from "./routes/config.js"
import { Scheduler } from "./scheduler.js"
import { closeServer } from "./opencode.js"
import logger from "./logger.js"

const __dirname = import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url))
const PORT = parseInt(process.env.PORT ?? "3001", 10)

const app = express()
app.use(cors())
app.use(express.json())

// 静态文件（前端构建产物）
app.use(express.static(path.resolve(__dirname, "../../dist")))

// 调度器（全局单例）
const scheduler = new Scheduler()
registerSchedulerEvents(scheduler)

// API 路由
app.get("/api/events", handleSSE)
app.use("/api/tasks", taskRouter(scheduler))
app.use("/api/config", configRouter(scheduler))

// 启动
const server = app.listen(PORT, () => {
  logger.info({ port: PORT }, "Auto Analysis 后端已启动")
  logger.info(`SSE 端点: http://localhost:${PORT}/api/events`)
})

// 优雅退出：关闭 HTTP server + OpenCode server
async function shutdown() {
  logger.info("正在关闭服务器...")
  server.close()
  await closeServer()
  logger.info("服务器已关闭")
  process.exit(0)
}

process.on("SIGINT", shutdown)
process.on("SIGTERM", shutdown)
