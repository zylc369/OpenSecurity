import { spawnSync } from "child_process";

/**
 * 标准化的子进程执行结果。
 * 贴近 Node.js spawnSync 的返回结构，便于业务代码从 spawnSync 迁移。
 */
export interface ProcessResult {
  /** 进程退出码；被信号终止或超时时为 null */
  status: number | null;
  /** 终止进程的信号名（Unix 概念）；Windows 上始终为 null */
  signal: string | null;
  /** stdout 内容（已转字符串） */
  stdout: string;
  /** stderr 内容（已转字符串） */
  stderr: string;
  /** 启动失败或运行异常时的错误对象；正常时为 null */
  error: Error | null;
}

export interface RunProcessOptions {
  /** 超时时间（毫秒）；不传则不限制 */
  timeout?: number;
}

/**
 * 跨平台执行子进程，返回标准化结果。永不 reject（包括子进程启动失败、
 * 运行崩溃、超时等情况都通过 error 字段返回），调用方可以放心 await。
 *
 * 平台分支：
 * - Windows：用 Bun.spawn（异步）绕开 spawnSync 的 bug。
 *   现象：OpenCode 进程内 spawnSync（无论目标 exe 是 python.exe 还是
 *     cmd.exe、是否 shell:true）约 50% 概率 4-9ms 立即返回 ETIMEDOUT
 *     （未真正等 timeout 满）。独立 Node/Bun 脚本无法复现——触发条件
 *     与 OpenCode 主进程内部状态相关，未完全定位。
 *   历史：曾误归到 Bun issue #32011
 *     （https://github.com/oven-sh/bun/issues/32011），但 #32011 症状
 *     是稳定挂起 5 秒、shell:true 可修；本环境的症状是 4-9ms 立即假超时、
 *     shell:true 无效——不是同一个 bug。
 * - Unix：直接用 Node.js spawnSync。Unix 上 spawnSync 工作正常，无需绕开。
 *
 * 设计权衡：函数签名统一为 async（即使 Unix 路径是同步实现）。
 * TypeScript 不允许同一函数既 sync 又 async，统一 async 让业务代码
 * 不用关心平台差异。Unix 路径付出一次 await 代价，但不需处理 stream。
 */
export async function runProcess(
  exe: string,
  args: string[],
  options: RunProcessOptions = {},
): Promise<ProcessResult> {
  // ── Unix 路径：直接用 spawnSync ──────────────────────────────────
  if (process.platform !== "win32") {
    const r = spawnSync(exe, args, {
      encoding: "utf8",
      timeout: options.timeout,
    });
    return {
      status: r.status,
      signal: r.signal,
      stdout: r.stdout ?? "",
      stderr: r.stderr ?? "",
      error: r.error ?? null,
    };
  }

  // ── Windows 路径：Bun.spawn 异步，手动管理超时 ────────────────────
  const TIMEOUT_MS = options.timeout;
  let proc: any;
  try {
    // Bun 全局：OpenCode 跑在 Bun runtime（用 globalThis as any 避开 TS 类型报错）
    proc = (globalThis as any).Bun.spawn({
      cmd: [exe, ...args],
      stdout: "pipe",
      stderr: "pipe",
      stdin: "ignore",
    });
  } catch (e) {
    return {
      status: null,
      signal: null,
      stdout: "",
      stderr: "",
      error: e as Error,
    };
  }

  return await new Promise<ProcessResult>((resolve) => {
    let settled = false;
    let timeoutHandle: ReturnType<typeof setTimeout> | null = null;

    const finish = (res: ProcessResult) => {
      if (settled) return;
      settled = true;
      if (timeoutHandle) clearTimeout(timeoutHandle);
      resolve(res);
    };

    // 超时分支：到达 timeout 强制 kill 并返回错误
    if (TIMEOUT_MS !== undefined) {
      timeoutHandle = setTimeout(() => {
        try { proc.kill(); } catch {}
        finish({
          status: null,
          signal: null, // Windows 没有 Unix 信号概念，硬编码会误导日志
          stdout: "",
          stderr: "",
          error: new Error(`Bun.spawn 超时（${TIMEOUT_MS}ms）`),
        });
      }, TIMEOUT_MS);
    }

    // 正常分支：消费 stdout/stderr 流 + 等退出码
    (async () => {
      try {
        // Bun.spawn 的 stdout/stderr 是 ReadableStream，用 Response 读为文本
        const stdoutPromise = new Response(proc.stdout).text();
        const stderrPromise = new Response(proc.stderr).text();
        const exitCode = await proc.exited; // Promise<number>
        const stdout = await stdoutPromise;
        const stderr = await stderrPromise;
        finish({ status: exitCode, signal: null, stdout, stderr, error: null });
      } catch (e) {
        finish({
          status: null,
          signal: null,
          stdout: "",
          stderr: "",
          error: e as Error,
        });
      }
    })();
  });
}
