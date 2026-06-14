// src/App.tsx — 主应用组件
import { useState, useEffect } from "react"
import TaskBoard from "./components/TaskBoard"
import ConcurrencyControl from "./components/ConcurrencyControl"
import LiveLog from "./components/LiveLog"
import { useSSE } from "./hooks/useSSE"

export default function App() {
  const [siteUrl, setSiteUrl] = useState("")
  const [running, setRunning] = useState(false)
  const { messages, connected, clearMessages } = useSSE("/api/events")

  async function handleStart() {
    if (!siteUrl) return
    setRunning(true)
    clearMessages()
    try {
      const resp = await fetch("/api/tasks/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ siteUrl }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        alert(data.error ?? "启动失败")
        setRunning(false)
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "启动失败")
      setRunning(false)
    }
  }

  // 监听 scheduler:complete 事件
  useEffect(() => {
    if (!running) return
    const hasComplete = messages.some((m) => m.event === "scheduler:complete")
    if (hasComplete) setRunning(false)
  }, [messages, running])

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: 20 }}>
      <h1>Auto Analysis</h1>

      {/* 开始分析按钮 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          type="url"
          placeholder="CTFd 网站地址 (https://...)"
          value={siteUrl}
          onChange={(e) => setSiteUrl(e.target.value)}
          style={{ flex: 1, padding: 8, fontSize: 14 }}
          disabled={running}
        />
        <button
          onClick={handleStart}
          disabled={running || !siteUrl}
          style={{ padding: "8px 16px", fontSize: 14 }}
        >
          {running ? "分析中..." : "开始分析"}
        </button>
        {running && (
          <button onClick={() => fetch("/api/tasks/abort", { method: "POST" })} style={{ padding: "8px 16px", fontSize: 14 }}>
            取消
          </button>
        )}
        <span style={{ fontSize: 12, alignSelf: "center" }}>
          SSE: {connected ? "🟢 已连接" : "🔴 未连接"}
        </span>
      </div>

      <ConcurrencyControl />
      <TaskBoard messages={messages} />
      <LiveLog messages={messages} onClear={clearMessages} />
    </div>
  )
}
