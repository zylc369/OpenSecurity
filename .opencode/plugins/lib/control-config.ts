/**
 * 控制台配置 API 客户端（Plugin 端）。
 *
 * 收口原则：Plugin 不直接读 .ai_env（控制台 config_store 是唯一读写方）。
 * 通过 HTTP GET /api/config 拉配置 + 内存缓存（用户改配置后重启 opencode 生效）。
 *
 * 使用场景：
 *   • shell.env hook 注入 IDA_PRO_HOME / DEEPSEEK_API_KEY 到 agent 子进程
 *   • persistence.ts 读 RESUME_ANALYSIS_ENABLED 控制会话恢复
 *
 * 缓存策略：
 *   • 启动时（控制台就绪后）拉一次，缓存到内存
 *   • 不主动刷新（配置变更频率极低）
 *   • 用户改配置后重启 opencode 生效
 */
import { CONTROL_PORT_FILE } from "./constants";
import { readControlPortFile } from "./control-manager";
import { debugLog } from "./logging";

let cachedConfig: Record<string, string> | null = null;

/**
 * 从控制台拉配置并缓存。
 * 失败时保留旧缓存（如果有），否则空对象。
 */
export async function refreshConfig(): Promise<void> {
  const info = readControlPortFile();
  if (!info) {
    debugLog(`refreshConfig: 端口文件不存在，控制台未启动？`);
    return;
  }
  try {
    const resp = await fetch(`http://127.0.0.1:${info.port}/api/config`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!resp.ok) {
      debugLog(`refreshConfig: HTTP ${resp.status}`);
      return;
    }
    cachedConfig = await resp.json() as Record<string, string>;
    debugLog(`refreshConfig: 拉到 ${Object.keys(cachedConfig).length} 项配置`);
  } catch (e) {
    debugLog(`refreshConfig 失败: ${(e as Error).message}`);
    // 失败时保留旧缓存
    if (!cachedConfig) cachedConfig = {};
  }
}

/**
 * 获取单个配置。
 * 第一次调用会触发 refreshConfig（如果缓存为空）。
 */
export async function getConfig(key: string): Promise<string | null> {
  if (!cachedConfig) await refreshConfig();
  return cachedConfig?.[key] ?? null;
}

/**
 * 获取全部配置（shell.env hook 用）。
 * 第一次调用会触发 refreshConfig。
 */
export async function getAllConfig(): Promise<Record<string, string>> {
  if (!cachedConfig) await refreshConfig();
  return cachedConfig ?? {};
}

/**
 * 同步获取缓存的配置（不触发 HTTP）。
 * 用于 exit handler 等不能 await 的场景。
 * 如果缓存为空返回空对象。
 */
export function getCachedConfig(): Record<string, string> {
  return cachedConfig ?? {};
}
