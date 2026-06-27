import type { OpencodeClient } from "@opencode-ai/sdk";
import type { SessionDataManager } from "./session-manager";

/**
 * 全局上下文：统一管理 Plugin 级全局状态。
 * 所有模块通过 ctx 访问 client、directory、sessionManager，
 * 避免全局变量散落在各模块。
 *
 * 字段使用 !: （确定赋值断言）：声明时暂不赋值，由 init() 在 Plugin 函数启动时赋值。
 * init() 在所有 hook 注册之前执行，因此 hook 内访问时字段一定已初始化。
 */
class PluginContext {
  client!: OpencodeClient;
  directory!: string;
  sessionManager!: SessionDataManager;

  /** Plugin 函数启动时调用，必须在任何 hook 触发之前完成 */
  init(
    client: OpencodeClient,
    directory: string,
    sessionManager: SessionDataManager,
  ): void {
    this.client = client;
    this.directory = directory;
    this.sessionManager = sessionManager;
  }
}

export const ctx = new PluginContext();
