// src/components/LiveLog.tsx — 实时日志
import { useRef, useEffect } from "react"
import type { SSEMessage } from "../hooks/useSSE"

interface Props {
  messages: SSEMessage[]
  onClear: () => void
}

export default function LiveLog({ messages, onClear }: Props) {
  const logRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [messages])

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>实时日志</h2>
        <button onClick={onClear} style={{ fontSize: 12 }}>清空</button>
      </div>
      <div
        ref={logRef}
        style={{
          background: "#1e1e1e",
          color: "#d4d4d4",
          fontFamily: "monospace",
          fontSize: 12,
          padding: 12,
          borderRadius: 8,
          height: 200,
          overflowY: "auto",
        }}
      >
        {messages.length === 0 ? (
          <span style={{ color: "#666" }}>等待事件...</span>
        ) : (
          messages.map((msg, i) => (
            <div key={i} style={{ marginBottom: 2 }}>
              <span style={{ color: "#569cd6" }}>[{msg.event}]</span>{" "}
              {msg.event === "task:log"
                ? (msg.data as { message?: string }).message
                : JSON.stringify(msg.data)}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
