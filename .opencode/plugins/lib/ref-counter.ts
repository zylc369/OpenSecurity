/**
 * 引用计数模块（Plugin 端）。
 *
 * users 文件由本模块（Plugin）和控制台端 services/ref_counter.py 双方读写。
 * 格式严格一致（共享协议）：
 *   pid=12345 start_time=1783000000
 *   pid=12346 start_time=1783000005
 *
 * 设计原则：
 *   • 不持文件锁（靠原子 rename 保证并发安全）
 *   • 进程退出时（process.on exit）同步减引用
 *   • PID 复用防护：用 start_time 校验
 *
 * 与控制台端的关系：
 *   • Plugin 加自己 PID 到 users → 控制台自杀检测时不杀
 *   • Plugin 退出时减自己 PID → 减到 0 时控制台周期清洗后自杀
 *   • Plugin SIGKILL 时 exit handler 不执行 → 控制台周期清洗兜底
 */
import { readFileSync, writeFileSync, renameSync, existsSync, mkdirSync } from "fs";
import { dirname } from "path";
import { getProcessStartTime, isProcessAliveSync } from "./process-utils";
import { CONTROL_USERS_FILE } from "./constants";
import { debugLog } from "./logging";

/** users 文件单条记录。 */
export interface UserEntry {
  pid: number;
  startTime: number;
}

/**
 * 解析 users 文件。
 * 容错：格式错的行跳过，文件不存在返回空数组。
 */
export function parseUsers(content: string): UserEntry[] {
  const entries: UserEntry[] = [];
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("pid=")) continue;
    try {
      const parts = trimmed.split(/\s+/);
      const fields = new Map<string, string>();
      for (const p of parts) {
        const [k, v] = p.split("=", 2);
        if (k && v !== undefined) fields.set(k, v);
      }
      const pid = parseInt(fields.get("pid") || "", 10);
      const startTime = parseFloat(fields.get("start_time") || "0");
      if (!isNaN(pid)) {
        entries.push({ pid, startTime });
      }
    } catch {
      continue;
    }
  }
  return entries;
}

/** 序列化 users 文件。 */
export function formatUsers(entries: UserEntry[]): string {
  return entries.map((e) => `pid=${e.pid} start_time=${e.startTime}`).join("\n") + "\n";
}

/** 读 users 文件。不存在返回空数组。 */
export function readUsers(): UserEntry[] {
  if (!existsSync(CONTROL_USERS_FILE)) return [];
  try {
    return parseUsers(readFileSync(CONTROL_USERS_FILE, "utf-8"));
  } catch (e) {
    debugLog(`readUsers 读取失败: ${(e as Error).message}`);
    return [];
  }
}

/**
 * 原子写 users 文件。
 *
 * 实现：临时文件 + rename（POSIX 原子保证）。
 * Node.js 的 renameSync 在 Windows 上也是原子操作（MoveFileEx with REPLACE_EXISTING）。
 *
 * 并发安全：临时文件用 PID 后缀，避免两个 opencode 同时写时互相覆盖 tmp。
 */
export function atomicWriteUsers(entries: UserEntry[]): void {
  const content = formatUsers(entries);
  // 用 PID 后缀避免多 opencode 并发写时的 tmp 文件冲突
  const tmp = `${CONTROL_USERS_FILE}.${process.pid}.tmp`;
  try {
    // 确保父目录存在
    const parent = dirname(CONTROL_USERS_FILE);
    if (!existsSync(parent)) {
      mkdirSync(parent, { recursive: true });
    }
    try {
      writeFileSync(tmp, content, { flag: "wx" });
    } catch {
      // tmp 已存在则覆盖（同一 PID 重复写时可能发生）
      writeFileSync(tmp, content);
    }
    renameSync(tmp, CONTROL_USERS_FILE);
  } catch (e) {
    debugLog(`atomicWriteUsers 写入失败: ${(e as Error).message}`);
    throw e;
  }
}

/**
 * 添加 opencode 自己的 PID 到 users 文件。
 *
 * 原子性：读-改-写不是原子的，但通过原子 rename 保证最终一致性。
 * 并发场景：两个 opencode 同时启动时，可能各自基于旧文件改，
 * 后写的覆盖先写的——但因为是"添加自己 PID"，最多丢失对方的 PID，
 * 下次启动或控制台周期清洗会兜底（不会出现错误 kill）。
 */
export function addSelfToUsers(): void {
  const myPid = process.pid;
  const myStartTime = getProcessStartTime(myPid) || 0;
  const entries = readUsers();
  // 去重：如果已存在，先删掉
  const filtered = entries.filter((e) => e.pid !== myPid);
  filtered.push({ pid: myPid, startTime: myStartTime });
  atomicWriteUsers(filtered);
  debugLog(`addSelfToUsers: pid=${myPid} startTime=${myStartTime}, 总引用 ${filtered.length}`);
}

/**
 * 从 users 文件删除 opencode 自己的 PID。
 *
 * 用于 process.on("exit") 同步减引用。
 * 删除后如果 users 空，调用方应该 SIGTERM 控制台 + 删端口文件。
 *
 * Returns:
 *   true = users 删除后为空（调用方应 kill 控制台）
 *   false = users 还有其他引用（控制台继续运行）
 */
export function removeSelfFromUsers(): boolean {
  const myPid = process.pid;
  const entries = readUsers();
  const filtered = entries.filter((e) => e.pid !== myPid);
  atomicWriteUsers(filtered);
  const isEmpty = filtered.length === 0;
  debugLog(
    `removeSelfFromUsers: pid=${myPid}, 剩余引用 ${filtered.length}, empty=${isEmpty}`,
  );
  return isEmpty;
}

/**
 * 清洗 users 文件：移除死 PID（启动时调用）。
 *
 * 用于 opencode 启动时清理上次崩溃的残留（如 SIGKILL 后 users 残留）。
 */
export function cleanupDeadUsers(): UserEntry[] {
  const entries = readUsers();
  const alive = entries.filter(
    (e) => isProcessAliveSync(e.pid, e.startTime || undefined),
  );
  if (alive.length !== entries.length) {
    atomicWriteUsers(alive);
    debugLog(`cleanupDeadUsers: ${entries.length} → ${alive.length}`);
  }
  return alive;
}
