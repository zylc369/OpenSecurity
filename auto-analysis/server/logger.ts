// server/logger.ts — 全局日志（pino）
import pino from "pino"

const isDev = process.env.NODE_ENV !== "production"

const logger = pino({
  level: process.env.LOG_LEVEL ?? "info",
  ...(isDev
    ? {
        transport: {
          target: "pino-pretty",
          options: { colorize: true, translateTime: "SYS:yyyy-mm-dd HH:MM:ss.l" },
        },
      }
    : {}),
})

export default logger
