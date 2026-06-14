// src/hooks/useSSE.ts — SSE 事件 hook
import { useEffect, useState, useCallback } from "react"

export interface SSEMessage {
  event: string
  data: unknown
}

/**
 * 连接 SSE 事件流
 * @param url SSE 端点 URL
 */
export function useSSE(url: string) {
  const [messages, setMessages] = useState<SSEMessage[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const es = new EventSource(url)

    es.addEventListener("connected", () => {
      setConnected(true)
    })

    es.addEventListener("task:status", (e) => {
      try { setMessages((prev) => [...prev, { event: "task:status", data: JSON.parse(e.data) }]) } catch {}
    })

    es.addEventListener("task:log", (e) => {
      try { setMessages((prev) => [...prev, { event: "task:log", data: JSON.parse(e.data) }]) } catch {}
    })

    es.addEventListener("scheduler:complete", (e) => {
      try { setMessages((prev) => [...prev, { event: "scheduler:complete", data: JSON.parse(e.data) }]) } catch {}
    })

    es.onerror = () => {
      setConnected(false)
    }

    return () => {
      es.close()
      setConnected(false)
    }
  }, [url])

  const clearMessages = useCallback(() => setMessages([]), [])

  return { messages, connected, clearMessages }
}
