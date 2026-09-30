/**
 * 控制台配置 API 客户端（Plugin 端）。
 *
 * 收口原则：Plugin 不直接读 .ai_env（控制台 config_store 是唯一读写方）。
 * 通过 HTTP GET /api/config?surface=config 拉配置生效值 + 内存缓存（TTL + SWR）。
 * （值接口以场景为轴必填 surface; 插件消费的键全部在 config 场景）
 *
 * 使用场景：
 *   • shell.env hook 注入 IDA_PRO_HOME 到 agent 子进程（同步走缓存）
 *   • persistence.ts 恢复校验读 RESUME_ANALYSIS_ENABLED（异步直读）
 *   • reflection.ts 反思开关/间隔判定（同步走缓存）
 *
 * API 语义（正交两分）：
 *   • fetchConfig()  —— 无缓存直读：每次拉最新，成功顺带喂缓存，失败 throw
 *     （旧缓存保留）。低频 + 要新鲜的异步场景用（本地 IPC 毫秒级）。
 *   • getCachedConfig() —— 同步 TTL 缓存：TTL 内返缓存；过期返旧值 +
 *     fire-and-forget 后台刷新（SWR，同步方永不阻塞）；失败保留旧值。
 *     高频同步场景用（shell.env 每轮 bash 触发）。
 *
 * 失败语义（2026/9/14 事故教训：曾静默吞异常返回空对象，导致消费方
 * 无法区分"未配置"与"读不到"，RESUME_ANALYSIS_ENABLED fail-open 放行）：
 *   • fetchConfig 失败 throw——调用方显式 catch 降级或让异常终止流程
 *   • 后台刷新失败保留旧值（只 debugLog，不 throw——fire-and-forget）
 */
import { controlFetch } from "./control-http";
import { debugLog } from "./logging";

/** 缓存 TTL（毫秒）。过期后同步调用走 SWR：返旧值 + 后台刷新。 */
const CONFIG_CACHE_TTL_MS = 30_000;

let cachedConfig: Record<string, string> | null = null;
let cachedAt = 0;
/** 后台刷新 in-flight 标志：防止 TTL 过期后高频同步调用并发重复拉取。 */
let backgroundRefreshInFlight = false;

/**
 * 无缓存直读控制台配置（总是最新）。
 * 成功: 更新 TTL 缓存并返回。
 * 失败: throw（旧缓存保留）。
 */
export async function fetchConfig(): Promise<Record<string, string>> {
  const resp = await controlFetch("/api/config?surface=config", { timeoutMs: 3000 });
  if (!resp.ok) {
    debugLog(`fetchConfig 失败: /api/config?surface=config HTTP ${resp.status}`);
    throw new Error(`fetchConfig 失败: /api/config?surface=config HTTP ${resp.status}`);
  }
  cachedConfig = await resp.json() as Record<string, string>;
  cachedAt = Date.now();
  debugLog(`fetchConfig: 拉到 ${Object.keys(cachedConfig).length} 项配置`);
  return cachedConfig;
}

/** 测试钩子: 将缓存时间戳置零强制过期（触发 SWR 分支的真实后台刷新）。 */
export function forceExpireCacheForTest(): void {
  cachedAt = 0;
}

/**
 * 同步获取缓存的配置（TTL + SWR，不阻塞）。
 *
 * - TTL 未过期 → 返回缓存
 * - TTL 过期 / 缓存为 null → 立即返回旧值（或空对象）+
 *   fire-and-forget 后台 fetchConfig（in-flight 防并发）→ 下轮即新值
 * - 后台刷新失败 → 保留旧值 + debugLog（同步方无感知）
 *
 * 用于 shell.env / checkpoint 判定等不能 await 的高频场景。
 */
export function getCachedConfig(): Record<string, string> {
  if (backgroundRefreshInFlight) return cachedConfig ?? {};
  const expired = cachedConfig === null || Date.now() - cachedAt > CONFIG_CACHE_TTL_MS;
  if (expired) {
    debugLog(
      `getCachedConfig: 缓存${cachedConfig === null ? "为空" : "过期"}（age=${Date.now() - cachedAt}ms > TTL=${CONFIG_CACHE_TTL_MS}），返旧值 + 后台刷新`,
    );
    backgroundRefreshInFlight = true;
    fetchConfig()
      .catch((e) => {
        // 保留旧值——控制台短暂不可用时缓存兜底，同步消费方无感
        debugLog(`getCachedConfig: 后台刷新失败（保留旧值）: ${e}`);
      })
      .finally(() => {
        backgroundRefreshInFlight = false;
      });
  }
  return cachedConfig ?? {};
}
