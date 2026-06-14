// src/components/TaskCard.tsx — 单个任务卡片
import type { Task } from "../../shared/types"

interface Props {
  task: Task
}

const statusColors: Record<string, string> = {
  pending: "#9e9e9e",
  running: "#2196f3",
  success: "#4caf50",
  failed: "#f44336",
}

export default function TaskCard({ task }: Props) {
  return (
    <div
      style={{
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: 12,
        borderLeft: `4px solid ${statusColors[task.status] ?? "#999"}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <strong>{task.title}</strong>
        <span style={{ fontSize: 12, color: "#666" }}>{task.value} pts</span>
      </div>
      <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
        {task.category} · 状态: {task.status}
        {task.retryCount > 0 && ` (重试 ${task.retryCount}/${task.maxRetries})`}
      </div>
      {task.answer && (
        <div style={{ fontSize: 12, fontFamily: "monospace", background: "#f5f5f5", padding: 4, borderRadius: 4 }}>
          {task.answer}
        </div>
      )}
      {task.error && (
        <div style={{ fontSize: 12, color: "#f44336", marginTop: 4 }}>{task.error}</div>
      )}
    </div>
  )
}
