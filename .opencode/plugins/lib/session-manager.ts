import type { OpencodeClient } from "@opencode-ai/sdk";
import { SECURITY_AGENTS } from "./constants";
import { debugLog } from "./logging";
import { Result } from "./result";

export class SessionData {
  /** session 创建时间戳（毫秒）。调试参考，不用于业务逻辑 */
  readonly createdAt: number;
  /** 当前 agent 名（如 "binary-analysis"）。由 chat.message 更新。保证非空——createFromAPI 在缺失时抛异常 */
  agentName: string;
  /** 父 session ID。如果是编排 agent 创建的子 session 则有值。当前未使用，预留 */
  readonly parentSessionID?: string;
  /** system.transform hook 触发次数。用于控制环境信息注入频率（前 3 次必注入，之后按频率注入） */
  systemTransformCount = 0;
  /** 用户最后发消息的时间戳（毫秒）。chat.message 时更新。用于 auto-resume 超时判断：从最后一次用户交互开始计时，而非 session 创建时间 */
  lastUserMessageAt: number;
  /** agent 切换标记。upsert 检测到 agentName 变化时置为旧 agent 名，system.transform 读取后清空 */
  agentSwitchedFrom: string | null = null;
  /** 主动终止标记。chat.message 里预装检查不通过 → 主动 abort 时置 true，event hook 恢复逻辑据此跳过 maybeResumeAnalysis */
  activelyTerminated: boolean | null = null;

  constructor(agentName: string, parentSessionID?: string) {
    this.createdAt = Date.now();
    this.lastUserMessageAt = this.createdAt;
    this.agentName = agentName;
    this.parentSessionID = parentSessionID;
  }

  isSecurityAgent(): boolean {
    return SECURITY_AGENTS.includes(this.agentName);
  }

  /** 当前未使用，预留给编排 agent 子任务方案 */
  isChildSession(): boolean {
    return !!this.parentSessionID;
  }
}

export class SessionDataManager {
  private sessions = new Map<string, SessionData>();
  private pending = new Map<string, Promise<SessionData>>();
  private client: OpencodeClient | null;

  constructor(client: OpencodeClient | null) {
    this.client = client;
  }

  /**
   * 创建 session（幂等：已存在则直接返回）。
   * 仅供 session.created 调用。返回 Result，失败不抛异常（session.created 是 fire-and-forget，抛了也被 void 吞掉）。
   */
  async create(sessionID: string): Promise<Result<SessionData>> {
    try {
      const session = await this.createInternal(sessionID);
      return Result.ok(session);
    } catch (e) {
      debugLog(`SessionDataManager.create 失败 sessionID=${sessionID} error=${e}`, sessionID);
      return Result.fail<SessionData>(String(e));
    }
  }

  /**
   * 更新 session 数据（agentName + lastUserMessageAt）。
   * 仅供 chat.message 调用。session 不存在时先创建（插件重启兜底），创建失败抛异常（中断 prompt，用户看到 toast）。
   */
  async upsert(sessionID: string, agentName: string): Promise<SessionData> {
    const session = await this.createInternal(sessionID); // 已存在则返回，不存在则创建（失败抛异常）
    session.lastUserMessageAt = Date.now();
    if (session.agentName !== agentName) {
      session.agentSwitchedFrom = session.agentName;
      session.agentName = agentName;
    }
    return session;
  }

  /** 只返回 Security Agent 的 session。只查不创建。 */
  requireSecurityAgent(
    hookName: string,
    sessionID?: string,
  ): SessionData | undefined {
    if (!sessionID) {
      debugLog(`[${hookName}] 跳过 — 无 sessionID`);
      return undefined;
    }
    const session = this.get(sessionID);
    if (!session) {
      debugLog(`[${hookName}] 跳过 — session 未创建（等待 chat.message）, sessionID=${sessionID}`);
      return undefined;
    }
    if (!session.isSecurityAgent()) {
      debugLog(
        `[${hookName}] 跳过 — 非 Security Agent agent=${session.agentName} sessionID=${sessionID}`,
        sessionID,
      );
      return undefined;
    }
    return session;
  }

  /** 同步获取（不触发创建）。 */
  get(sessionID: string): SessionData | undefined {
    return this.sessions.get(sessionID);
  }

  /** 删除（session.deleted 时调用）。同时清理 pending Map。 */
  delete(sessionID: string): void {
    this.sessions.delete(sessionID);
    this.pending.delete(sessionID);
  }

  /** 私有：幂等创建 + 并发去重。已存在则返回，不存在则从 API 创建。失败抛异常。 */
  private async createInternal(sessionID: string): Promise<SessionData> {
    const existing = this.sessions.get(sessionID);
    if (existing) return existing;

    const inFlight = this.pending.get(sessionID);
    if (inFlight) return await inFlight;

    const promise = this.createFromAPI(sessionID);
    this.pending.set(sessionID, promise);
    try {
      return await promise;
    } finally {
      this.pending.delete(sessionID);
    }
  }

  /** 私有：从 API 创建 SessionData。唯一的 new SessionData() 调用点。失败抛异常。 */
  private async createFromAPI(sessionID: string): Promise<SessionData> {
    if (!this.client) {
      throw new Error(`SessionDataManager: client 未初始化，无法创建 sessionID=${sessionID}`);
    }
    const response = await this.client.session.get({
      path: { id: sessionID },
    });
    if (response.error || !response.data) {
      throw new Error(`SessionDataManager: API 错误 sessionID=${sessionID} error=${JSON.stringify(response.error)}`);
    }
    const sessionInfo = response.data;
    const agentName = (sessionInfo as { agent?: string })?.agent;
    if (!agentName) {
      throw new Error(`SessionDataManager: API 未返回 agent 字段 sessionID=${sessionID}`);
    }
    const parentSessionID = (sessionInfo as { parentID?: string })?.parentID;
    const session = new SessionData(agentName, parentSessionID);
    this.sessions.set(sessionID, session);
    debugLog(
      `SessionDataManager: 创建 sessionID=${sessionID} agent=${agentName} parentID=${parentSessionID || "无"}`,
      sessionID,
    );
    return session;
  }
}
