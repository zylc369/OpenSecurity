// src/components/ConcurrencyControl.tsx — 并发控制滑块
import { useEffect, useState } from "react"

export default function ConcurrencyControl() {
  const [concurrency, setConcurrency] = useState(2)

  // 从 API 加载当前配置
  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((data) => {
        if (data.maxConcurrency) setConcurrency(data.maxConcurrency)
      })
      .catch(() => {})
  }, [])

  async function handleChange(value: number) {
    setConcurrency(value)
    await fetch("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maxConcurrency: value }),
    })
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ fontSize: 14 }}>
        并发数: <strong>{concurrency}</strong>
      </label>
      <input
        type="range"
        min={1}
        max={5}
        value={concurrency}
        onChange={(e) => handleChange(Number(e.target.value))}
        style={{ width: 200, marginLeft: 8 }}
      />
    </div>
  )
}
