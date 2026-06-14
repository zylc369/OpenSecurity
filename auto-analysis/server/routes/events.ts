// server/routes/events.ts — SSE 事件流路由
import type { Request, Response } from "express"
import type { Scheduler } from "../scheduler.js"

/** SSE 客户端管理 */
const clients = new Set<Response>()

/** 向所有 SSE 客户端广播事件 */
export function broadcastSSE(event: string, data: unknown) {
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  for (const res of clients) {
    try {
      res.write(payload)
    } catch {
      // 写入失败（客户端已断开），移除该客户端
      clients.delete(res)
    }
  }
}

/** 注册调度器事件到 SSE */
export function registerSchedulerEvents(scheduler: Scheduler) {
  scheduler.on("task:status", (task) => {
    broadcastSSE("task:status", task)
  })
  scheduler.on("task:log", (taskId: string, message: string) => {
    broadcastSSE("task:log", { taskId, message, timestamp: Date.now() })
  })
  scheduler.on("scheduler:complete", (summary) => {
    broadcastSSE("scheduler:complete", summary)
  })
}

/** GET /api/events — SSE 端点 */
export function handleSSE(req: Request, res: Response) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  })

  // 发送初始连接确认
  res.write(`event: connected\ndata: ${JSON.stringify({ timestamp: Date.now() })}\n\n`)

  clients.add(res)

  // 客户端断开时清理
  req.on("close", () => {
    clients.delete(res)
  })
}
