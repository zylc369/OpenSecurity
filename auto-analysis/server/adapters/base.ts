// server/adapters/base.ts — 网站适配器基类
import type { Task, TaskInfo, SubmitResult, DownloadResult } from "../../shared/types.js"

/**
 * 网站适配器接口
 *
 * 所有网站操作（CTFd 等）必须实现此接口。
 * 适配器内部维护 cookie/session 状态，不需要外部传递。
 */
export interface SiteAdapter {
  /** 登录网站，成功后内部保存 session */
  login(username: string, password: string): Promise<void>

  /** 获取所有可用的任务列表 */
  listTasks(): Promise<Task[]>

  /** 获取单个任务的详情（描述、附件、提示等） */
  getTaskInfo(taskId: string): Promise<TaskInfo>

  /** 提交答案（flag） */
  submitAnswer(taskId: string, answer: string): Promise<SubmitResult>

  /**
   * 下载文件
   * @param url - 站点相对路径（如 CTFd 的 "/files/xxx"），适配器内部拼接 baseUrl
   * @param outputPath - 本地保存路径（如 ~/Downloads/xxx）
   */
  downloadFile(url: string, outputPath: string): Promise<DownloadResult>
}
