/**
 * 权限询问超时自动拒绝。
 *
 * 用户离开时权限询问（以 external_directory 为主）会一直挂起等待点击，
 * 分析流程停摆。本模块对指定类型的权限询问计时，超时未处理则自动拒绝，
 * 并附引导反馈（经拒绝接口的 message 字段生成 CorrectedError.feedback，
 * 随被拒工具的错误结果送达模型——不创建新消息、不中断会话）。
 *
 * 事件双兼容: permission.asked/replied（v1）与 permission.v2.asked/replied（v2）。
 * 拒绝通道三级（探测降级，全部经 ctx.client 统一收口——baseUrl/认证复用）:
 *   ① client.permission.reply（未来 SDK 面，支持 feedback）
 *   ② client._client.post（hey-api 底层方法，任意端点; 当前主路径，支持 feedback）
 *   ③ client.postSessionIdPermissionsPermissionId（v1 SDK 生成方法兜底，无 feedback）
 *
 * 配置（控制台配置页 → .ai_env → /api/config 生效值读取——默认值唯一权威在
 * 服务端 ConfigField.default_value，插件不持有默认值副本）:
 *   PERMISSION_ASK_TIMEOUT_SEC   超时秒数; 未取到生效值/非法（非正数）→ 功能不启用（记日志）
 *   PERMISSION_ASK_TIMEOUT_TYPES 生效类型（逗号分隔）; 未取到 → 不启用任何类型（记日志）
 */
import { ctx } from "./context";
import { debugLog } from "./logging";
import { getCachedConfig } from "./control-config";
import {
  ENV_KEY_PERMISSION_TIMEOUT_SEC,
  ENV_KEY_PERMISSION_TIMEOUT_TYPES,
  PERMISSION_TIMEOUT_REJECT_MESSAGE,
} from "./constants";

/** 权限询问事件的最小信息集（v1/v2 字段差异在提取层归一） */
export interface PermissionAskInfo {
  requestID: string;
  sessionID: string;
  permissionType: string;
}

/**
 * 从 permission.asked / permission.v2.asked 事件 properties 提取归一信息。
 * v1 字段: permission; v2 字段: action。缺任一必需字段返回 null。
 */
export function extractPermissionAskInfo(
  props: Record<string, unknown>,
): PermissionAskInfo | null {
  const requestID = typeof props?.id === "string" ? props.id : null;
  const sessionID =
    typeof props?.sessionID === "string" ? props.sessionID : null;
  const permissionType =
    typeof props?.permission === "string"
      ? props.permission
      : typeof props?.action === "string"
        ? props.action
        : null;
  if (!requestID || !sessionID || !permissionType) return null;
  return { requestID, sessionID, permissionType };
}

/**
 * 超时毫秒数: 服务端生效值（配置值或声明默认，经 /api/config 返回）。
 * 未取到生效值或非法（非正数秒）→ 0（不启用，记排查日志）——
 * 默认值唯一权威在服务端，插件取不到值即 fail-safe。
 */
export function getPermissionTimeoutMs(
  configReader: () => Record<string, string> = getCachedConfig,
): number {
  const raw = (configReader()[ENV_KEY_PERMISSION_TIMEOUT_SEC] ?? "").trim();
  if (raw === "") {
    debugLog(
      `权限超时: ${ENV_KEY_PERMISSION_TIMEOUT_SEC} 未取到生效值（服务端未声明默认或控制台不可达），功能不启用`,
    );
    return 0;
  }
  const sec = Number(raw);
  if (!Number.isFinite(sec)) {
    debugLog(
      `权限超时: ${ENV_KEY_PERMISSION_TIMEOUT_SEC}=${raw} 非法（应为正数秒或 0），功能不启用`,
    );
    return 0;
  }
  if (sec === 0) return 0; // 0=关闭（文档化语义——正常关闭，不打异常告警）
  if (sec < 0) {
    debugLog(
      `权限超时: ${ENV_KEY_PERMISSION_TIMEOUT_SEC}=${raw} 非法（负数），按关闭处理`,
    );
    return 0;
  }
  return sec * 1000;
}

/**
 * 生效类型集合: 服务端生效值（逗号分隔; 英文/中文逗号均容错）。
 * 未取到生效值 → 空集（不启用任何类型，记排查日志）。
 */
export function getPermissionTimeoutTypes(
  configReader: () => Record<string, string> = getCachedConfig,
): Set<string> {
  const raw = (configReader()[ENV_KEY_PERMISSION_TIMEOUT_TYPES] ?? "").trim();
  if (raw === "") {
    debugLog(
      `权限超时: ${ENV_KEY_PERMISSION_TIMEOUT_TYPES} 未取到生效值（服务端未声明默认或控制台不可达），不启用任何类型`,
    );
    return new Set();
  }
  return new Set(
    raw
      .replaceAll("，", ",")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

/** SDK client 的权限回复面窄化（SDK 类型未覆盖; 探测式降级用） */
type ReplyCapableClient = {
  permission?: {
    reply?: (input: {
      requestID: string;
      reply: string;
      message?: string;
    }) => Promise<unknown>;
  };
  /** hey-api 底层 client（生成方法内部即调它; 复用 baseUrl/认证/拦截器） */
  _client?: {
    post?: (options: {
      url: string;
      headers?: Record<string, string>;
      body?: unknown;
    }) => Promise<{
      data?: unknown;
      error?: unknown;
      response?: { status?: number };
    }>;
  };
  postSessionIdPermissionsPermissionId?: (input: {
    path: { id: string; permissionID: string };
    body: { response: string };
  }) => Promise<unknown>;
};

/** 权限询问超时管理器（定时器状态私有化; 插件实例化一个，随 dispose 清理） */
export class PermissionTimeoutManager {
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly configReader: () => Record<string, string>;

  constructor(configReader: () => Record<string, string> = getCachedConfig) {
    this.configReader = configReader;
  }

  /** 事件入口: permission.asked / permission.v2.asked——按配置布防超时 */
  onAsked(props: Record<string, unknown>): void {
    if (!props || typeof props !== "object") {
      debugLog(`权限超时: 事件属性缺失，跳过布防 props=${String(props)}`);
      return;
    }
    const info = extractPermissionAskInfo(props);
    if (!info) {
      debugLog(
        `权限超时: 事件字段缺失，跳过布防 props=${JSON.stringify(props).slice(0, 200)}`,
      );
      return;
    }
    const timeoutMs = getPermissionTimeoutMs(this.configReader);
    if (timeoutMs <= 0) return; // 0=关闭（不布防）
    if (
      !getPermissionTimeoutTypes(this.configReader).has(info.permissionType)
    ) {
      return; // 类型不在生效范围
    }
    this.clear(info.requestID); // 幂等: 同 requestID 重复布防先清
    this.timers.set(
      info.requestID,
      setTimeout(() => {
        this.timers.delete(info.requestID);
        void this.reject(info);
      }, timeoutMs),
    );
    debugLog(
      `权限超时: 已布防 requestID=${info.requestID} type=${info.permissionType} timeoutMs=${timeoutMs}`,
      info.sessionID,
    );
  }

  /** 事件入口: permission.replied / permission.v2.replied——请求已被处理，撤销布防 */
  onReplied(props: Record<string, unknown>): void {
    if (!props || typeof props !== "object") {
      debugLog(`权限超时: replied 事件属性缺失，跳过 props=${String(props)}`);
      return;
    }
    const requestID =
      typeof props.requestID === "string" ? props.requestID : null;
    if (!requestID) {
      debugLog(
        `权限超时: replied 事件无 requestID，跳过 props=${JSON.stringify(props).slice(0, 200)}`,
      );
      return;
    }
    const revoked = this.timers.has(requestID);
    this.clear(requestID);
    debugLog(
      `权限超时: replied ${revoked ? "已撤销布防" : "无 pending（未布防或已超时处理）"} requestID=${requestID}`,
      typeof props.sessionID === "string" ? props.sessionID : null,
    );
  }

  /** 清空全部定时器（插件 dispose 时调用） */
  dispose(): void {
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
  }

  private clear(requestID: string): void {
    const timer = this.timers.get(requestID);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(requestID);
    }
  }

  /**
   * 超时拒绝: 三级通道探测降级。
   * 方法体整体兜底——定时器回调内绝不抛 unhandled rejection。
   */
  private async reject(info: PermissionAskInfo): Promise<void> {
    const tag = `权限超时: 自动拒绝 requestID=${info.requestID} type=${info.permissionType}`;
    try {
      const client = ctx.client as unknown as ReplyCapableClient;

      // ① v2 SDK 面（未来版本注入 client 带 permission.reply 时自动启用）
      if (typeof client?.permission?.reply === "function") {
        try {
          await client.permission.reply({
            requestID: info.requestID,
            reply: "reject",
            message: PERMISSION_TIMEOUT_REJECT_MESSAGE,
          });
          debugLog(`${tag}（通道① client.permission.reply）`, info.sessionID);
          return;
        } catch (e) {
          debugLog(
            `${tag} 通道①失败: ${(e as Error)?.message ?? String(e)}`,
            info.sessionID,
          );
        }
      }

      // ② hey-api 底层 post（当前主路径; 支持 feedback 文案; 复用 client 的 baseUrl/认证）
      try {
        if (await this.rejectViaClientRaw(info.requestID)) {
          debugLog(
            `${tag}（通道② client._client.post /permission/{id}/reply）`,
            info.sessionID,
          );
          return;
        }
      } catch (e) {
        debugLog(
          `${tag} 通道②异常: ${(e as Error)?.message ?? String(e)}`,
          info.sessionID,
        );
      }

      // ③ v1 SDK 兜底（无 feedback，保证至少拒绝成功）
      if (typeof client?.postSessionIdPermissionsPermissionId === "function") {
        try {
          await client.postSessionIdPermissionsPermissionId({
            path: { id: info.sessionID, permissionID: info.requestID },
            body: { response: "reject" },
          });
          debugLog(`${tag}（通道③ v1 SDK 兜底，无反馈文案）`, info.sessionID);
          return;
        } catch (e) {
          debugLog(
            `${tag} 通道③失败: ${(e as Error)?.message ?? String(e)}`,
            info.sessionID,
          );
        }
      }

      debugLog(`${tag} 全部通道失败`, info.sessionID);
    } catch (e) {
      // 兜底: 任何意外异常都只落日志（定时器回调不能抛）
      debugLog(
        `${tag} 意外异常: ${(e as Error)?.message ?? String(e)}`,
        info.sessionID,
      );
    }
  }

  /**
   * 经 ctx.client 的 hey-api 底层 post 调用拒绝端点（带反馈文案）。
   * 与 SDK 生成方法同一 client 实例——baseUrl/认证/拦截器统一复用（请求收口）。
   * 404 视为"请求已处理"（用户点击与超时竞态）——视为完成，不再降级。
   */
  private async rejectViaClientRaw(requestID: string): Promise<boolean> {
    const raw = (ctx.client as unknown as ReplyCapableClient)?._client;
    if (typeof raw?.post !== "function") return false;
    const result = await raw.post({
      url: `/permission/${requestID}/reply`,
      headers: { "Content-Type": "application/json" },
      body: {
        reply: "reject",
        message: PERMISSION_TIMEOUT_REJECT_MESSAGE,
      },
    });
    const status = result?.response?.status ?? 0;
    if (status !== 200 && status !== 404) {
      debugLog(`权限超时: 底层 post 拒绝响应异常 status=${status}`);
      return false;
    }
    return true;
  }
}
