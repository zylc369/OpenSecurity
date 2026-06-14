// ==========================================
// 共享类型定义（前后端共用）
// ==========================================

/** 任务状态 */
export type TaskStatus = "pending" | "running" | "success" | "failed"

/** 任务对象（调度器内部 + 前端展示） */
export interface Task {
  id: string
  title: string
  category: string
  value: number
  status: TaskStatus
  retryCount: number
  maxRetries: number
  error?: string
  answer?: string
  createdAt: number
  updatedAt: number
}

/** 任务详情（从网站适配器获取） */
export interface TaskInfo {
  id: string
  title: string
  category: string
  value: number
  description: string
  files: Array<{ url: string; name: string }>
  hints?: Array<{ content: string }>
}

/** 提交结果 */
export interface SubmitResult {
  success: boolean
  message?: string
}

/** 下载结果 */
export interface DownloadResult {
  success: boolean
  path: string
  extractDir?: string
}

/** 调度器配置 */
export interface SchedulerConfig {
  maxConcurrency: number
  maxRetries: number
}
