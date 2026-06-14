// src/components/TaskBoard.tsx — 任务看板
import { useEffect, useState } from "react"
import type { Task } from "../../shared/types"
import TaskCard from "./TaskCard"
import type { SSEMessage } from "../hooks/useSSE"

interface Props {
  messages: SSEMessage[]
}

export default function TaskBoard({ messages }: Props) {
  const [tasks, setTasks] = useState<Task[]>([])

  // 从 API 加载初始任务列表
  useEffect(() => {
    fetch("/api/tasks")
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data)) setTasks(data) })
      .catch(() => {})
  }, [])

  // 从 SSE 事件更新任务状态（upsert：存在则更新，不存在则添加）
  useEffect(() => {
    for (const msg of messages) {
      if (msg.event === "task:status") {
        const updated = msg.data as Task
        setTasks((prev) => {
          const exists = prev.some((t) => t.id === updated.id)
          return exists
            ? prev.map((t) => (t.id === updated.id ? { ...t, ...updated } : t))
            : [...prev, updated]
        })
      }
    }
  }, [messages])

  if (tasks.length === 0) {
    return <p style={{ color: "#666" }}>暂无任务。输入 CTFd 网站地址后点击"开始分析"。</p>
  }

  const statuses = ["running", "pending", "failed", "success"] as const

  return (
    <div>
      <h2>任务看板 ({tasks.length})</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
        {statuses.map((status) =>
          tasks
            .filter((t) => t.status === status)
            .map((task) => <TaskCard key={task.id} task={task} />),
        )}
      </div>
    </div>
  )
}
