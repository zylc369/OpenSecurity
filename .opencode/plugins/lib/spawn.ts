/**
 * 跨平台执行子进程，返回标准化结果。永不 reject（包括子进程启动失败、
 * 运行崩溃、超时等情况都通过 error 字段返回），调用方可以放心 await。
 *
 * 统一用 Bun.spawn（异步），两个平台同一套代码。
 * OpenCode 跑在 Bun runtime 上，Bun.spawn 全局可用。
 *
 * 历史：曾用 spawnSync（同步），但 async 函数里调用 spawnSync 会阻塞整个事件循环
 * （spawnSync 在返回 Promise 之前就同步执行完了）。并行预热 6 个检测时阻塞 ~27 秒，
 * 导致 OpenCode 启动黑屏。改用异步 Bun.spawn 后 6 个检测真正并行（~5 秒），不阻塞。
 */

/** 标准化的子进程执行结果。 */
export interface ProcessResult {
  /** 进程退出码；被信号终止或超时时遵循 POSIX 约定（128+signal_num，如 SIGTERM→143） */
  status: number | null;
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
  /** 额外的环境变量，合并到默认 env（process.env + UTF-8 配置）之上。
   *  调用方变量优先级高于默认变量。 */
  env?: Record<string, string>;
}

/**
 * 跨平台执行子进程，返回标准化结果。永不 reject。
 * 用 Bun.spawn（异步）避免阻塞事件循环。
 */
export async function runProcess(
  exe: string,
  args: string[],
  options: RunProcessOptions = {},
): Promise<ProcessResult> {
  // 强制 Python 子进程 UTF-8 输出，避免 Windows 上 stdout 重定向到管道时
  // 默认用 GBK(CP936) 编码、而读取端按 UTF-8 解码导致的中文乱码。
  // PYTHONUTF8=1（PEP 540，3.7+）覆盖所有 I/O；PYTHONIOENCODING 兜底 stdin/stdout/stderr。
  // Unix 上默认就是 UTF-8，加上是无害的防御性配置，保持两端行为一致。
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", ...options.env };

  return await new Promise<ProcessResult>((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const finish = (result: ProcessResult) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve(result);
    };

    // Bun.spawn 是全局 API（OpenCode 跑在 Bun runtime 上），用 globalThis as any 避开 TS 类型报错
    let proc: any;
    try {
      proc = (globalThis as any).Bun.spawn({
        cmd: [exe, ...args],
        env,
        stdout: "pipe",
        stderr: "pipe",
        stdin: "ignore",
      });
    } catch (e) {
      finish({
        status: null,
        stdout: "",
        stderr: "",
        error: e as Error,
      });
      return;
    }

    // 超时分支：到达 timeout 强制 kill 并返回错误
    if (options.timeout) {
      timer = setTimeout(() => {
        try {
          proc.kill();
        } catch {}
        finish({
          status: null,
          stdout: "",
          stderr: "",
          error: new Error(`Bun.spawn 超时（${options.timeout}ms）`),
        });
      }, options.timeout);
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
        finish({ status: exitCode, stdout, stderr, error: null });
      } catch (e) {
        finish({
          status: null,
          stdout: "",
          stderr: "",
          error: e as Error,
        });
      }
    })();
  });
}
