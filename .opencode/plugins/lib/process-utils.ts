/**
 * 进程检测工具（TS 端，与控制台 services/process_lock.py 算法一致）。
 *
 * 收口原则：Plugin 端的 PID 检测 + 启动时间获取统一在本模块。
 */
import { spawnSync } from "child_process";
import { debugLog } from "./logging";

/** 端口文件解析结果。 */
export interface ControlPortInfo {
  port: number;
  pid: number;
  startTime: number;
}

/**
 * 检测进程是否存活（跨平台）。
 *
 * Node.js 的 process.kill(pid, 0) 跨平台一致：
 *   Unix: kill(pid, 0) 系统调用
 *   Windows: OpenProcess + GetExitCodeProcess
 *
 * 可选 startTime 校验防 PID 复用：如果 startTime 不匹配，视为 PID 被复用，返回 false。
 */
export function isProcessAliveSync(pid: number, startTime?: number): boolean {
  if (pid <= 0) return false;
  try {
    process.kill(pid, 0);
  } catch (e) {
    // ESRCH = 进程不存在
    if ((e as NodeJS.ErrnoException).code === "ESRCH") return false;
    // EPERM = 权限错误（进程存在但属于其他用户），视为存活
    if ((e as NodeJS.ErrnoException).code === "EPERM") return true;
    return false;
  }

  // 启动时间校验（防 PID 复用）
  // 注意：startTime=0 视为"未提供"，宽容处理（不校验）
  if (startTime !== undefined && startTime > 0) {
    const actual = getProcessStartTime(pid);
    if (actual !== null && Math.abs(actual - startTime) > 1.0) {
      return false;
    }
  }
  return true;
}

/**
 * 获取进程启动时间戳（秒）。失败返回 null。
 *
 * 跨平台实现：
 *   Unix（macOS/Linux）: ps -p PID -o lstart=（强制 LC_ALL=C 避免中文 locale）
 *   Windows: PowerShell Get-Process
 */
export function getProcessStartTime(pid: number): number | null {
  if (process.platform === "win32") {
    return getStartTimeWindows(pid);
  }
  return getStartTimeUnix(pid);
}

function getStartTimeUnix(pid: number): number | null {
  try {
    // 强制 LC_ALL=C 避免 macOS 中文 locale 导致解析失败
    const r = spawnSync("ps", ["-p", String(pid), "-o", "lstart="], {
      encoding: "utf-8",
      timeout: 3000,
      env: { ...process.env, LC_ALL: "C" },
    });
    if (r.status !== 0 || !r.stdout || !r.stdout.trim()) return null;
    // ps 输出："Tue Jul 28 23:15:09 2026"
    const ts = Date.parse(r.stdout.trim());
    return isNaN(ts) ? null : Math.floor(ts / 1000);
  } catch (e) {
    debugLog(`getStartTimeUnix(${pid}) 失败: ${(e as Error).message}`);
    return null;
  }
}

function getStartTimeWindows(pid: number): number | null {
  try {
    const r = spawnSync(
      "powershell",
      ["-Command", `(Get-Process -Id ${pid}).StartTime.Ticks`],
      { encoding: "utf-8", timeout: 3000 },
    );
    if (r.status !== 0 || !r.stdout || !r.stdout.trim()) return null;
    // .NET Ticks 是 100ns 单位，从 0001-01-01 开始
    const ticks = parseInt(r.stdout.trim(), 10);
    if (isNaN(ticks)) return null;
    return Math.floor(ticks / 10_000_000 - 11_644_473_600);
  } catch (e) {
    debugLog(`getStartTimeWindows(${pid}) 失败: ${(e as Error).message}`);
    return null;
  }
}
