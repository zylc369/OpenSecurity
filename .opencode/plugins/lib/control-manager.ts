/**
 * 控制台启动管理。
 *
 * 职责（严格收口）：
 *   • 启动时检查现有控制台是否运行（IPC connect + /health）
 *   • 不运行则 spawn 新的控制台进程（detached:true + unref，让控制台脱离 opencode 生命周期）
 *   • 等待 IPC 通道就绪（/health 200/503）
 *   • 启动心跳（每 10s POST /api/heartbeat；控制台 60s 未收到 → 移除，
 *     心跳表空过宽限 → 控制台自杀。opencode 正常退出/SIGKILL 均停跳，无需 exit handler）
 *
 * IPC 语义：
 *   • 活性 = connect 固定 IPC 地址一次（Unix sock / Windows 管道）
 *   • 单例互斥 = 控制台端 IPC bind 内核排他
 *   • socket 文件由控制台进程自理（退出清理）；TS 侧不碰 IPC 资产
 *
 * 与 heartbeat.ts / ipc_listener.py + heartbeat.py（控制台端）协同。
 *
 * 不在本模块：
 *   • 配置读取（control-config.ts）
 *   • 三阶段 waitFor（在 security-analysis.ts 的 chat.message 内调度）
 */
import { spawn } from "child_process";
import { closeSync, existsSync, openSync } from "fs";
import {
  CONTROL_SCRIPT,
  CONTROL_STARTUP_TIMEOUT_MS,
  CONTROL_IPC_READY_WAIT_MS,
  CONTROL_STDERR_LOG,
  CONTROL_STDOUT_LOG,
  DATA_DIR,
  OPENCODE_ROOT,
  VENV_DIR,
  VENV_PYTHON_CANDIDATES,
} from "./constants";
import { controlFetch } from "./control-http";
import { heartbeatSender } from "./heartbeat";
import { debugLog } from "./logging";

/** venv Python 路径（惰性查找，缓存） */
let cachedVenvPython: string | null | undefined;

/** 查找 venv Python（与 venv.ts 的 findVenvPython 算法一致）。 */
function findVenvPython(): string | null {
  if (cachedVenvPython !== undefined) return cachedVenvPython;
  for (const candidate of VENV_PYTHON_CANDIDATES) {
    if (existsSync(candidate)) {
      cachedVenvPython = candidate;
      return candidate;
    }
  }
  cachedVenvPython = null;
  return null;
}
/** 检测控制台是否健康（IPC 请求 /health，仅 200 算健康）。
 *  2026/9/14 修正：此前 503（加载中）也算健康——导致 waitForIpcReady 在
 *  应用初始化未完成时就放行，startControl 返回 true 但 /api/config 等
 *  业务接口还答不了（退化成 fail-open 变体：消息照跑配置全空）。
 *  初始化期 503 由 waitForIpcReady 的轮询窗口（CONTROL_IPC_READY_WAIT_MS）
 *  如实等待到 200，超时则明确启动失败。 */
export async function isControlHealthy(): Promise<boolean> {
  try {
    const resp = await controlFetch("/health", { timeoutMs: 3000 });
    if (!resp.ok) {
      debugLog(`isControlHealthy 失败: /health HTTP ${resp.status}`);
      return false;
    }
    return true;
  } catch {
    return false; // 网络层失败日志由 controlFetch 内部记录
  }
}

/** 控制台实例身份（/health 的识别字段；供日志与测试断言"同一个实例"用）。 */
export interface ControlIdentity {
  pid: number;
  bootToken: string | null;
}

/** 取控制台实例身份（pid + boot_token）。不可达返回 null。 */
export async function getControlIdentity(): Promise<ControlIdentity | null> {
  try {
    const resp = await controlFetch("/health", { timeoutMs: 3000 });
    if (!resp.ok && resp.status !== 503) return null;
    const data: any = await resp.json();
    if (typeof data?.pid === "number" && data.pid > 0) {
      return { pid: data.pid, bootToken: data?.boot_token ?? null };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 启动控制台（单飞入口）。
 *
 * 并发安全：进程内任意时刻至多一次真实启动在途——并发调用共享同一个 Promise，
 * 等待同一次结果，不重复 spawn。背景：曾出现 6 路并发调用（1 主流程 + 5 预热）
 * 各自 spawn，5 个 Python 进程抢 bind、4 个自杀退出（2026/8/20 08:06:25 事故日志）。
 *
 * 完成后清空在途引用：成功 → 下次调用走健康复用快路径；失败 → 下次调用可重试。
 * 包装层吞掉异常统一返回 false（调用方普遍无 try/catch，rethrow 会直接炸）。
 *
 * Returns:
 *   true 控制台就绪（IPC 可答 /health）
 *   false 启动失败（venv 缺失 / spawn 失败 / 超时）
 */
let inFlightStart: Promise<boolean> | null = null;

export function startControl(): Promise<boolean> {
  if (!inFlightStart) {
    inFlightStart = doStartControl()
      .catch((e) => {
        debugLog(`startControl: 未预期异常 ${(e as Error)?.message}`);
        return false;
      })
      .finally(() => {
        inFlightStart = null;
      });
  }
  return inFlightStart;
}

/**
 * 启动控制台（实际执行体，仅经 startControl 单飞入口调用）。
 *
 * 流程：
 *   1. 检测现有控制台：健康 → 复用 + 启动心跳；不健康 → spawn 新的
 *   2. spawn 新的：venv Python + detached:true + unref
 *   3. 等待 IPC 就绪（/health 200/503）
 *   4. 启动心跳（首跳立即）
 */
async function doStartControl(): Promise<boolean> {
  // 1. 检测现有控制台（IPC connect 即发现即校验——无文件、无 PID 四步检查）
  if (await isControlHealthy()) {
    const identity = await getControlIdentity();
    debugLog(
      `startControl: 已有控制台运行（IPC 通道可达，pid=${identity?.pid ?? "?"}），复用`,
    );
    await heartbeatSender.start(); // 幂等；首跳立即
    return true;
  }

  // 2. 找 venv Python
  const python = findVenvPython();
  if (!python) {
    debugLog(`startControl: venv Python 未找到（${VENV_DIR} 不存在）`);
    return false;
  }
  if (!existsSync(CONTROL_SCRIPT)) {
    debugLog(`startControl: 控制台脚本不存在 ${CONTROL_SCRIPT}`);
    return false;
  }

  // 3. spawn 控制台（detached:true + unref，让控制台脱离 opencode 生命周期）
  //    stdio 落盘：stdout/stderr 追加写 logs/control-stdout.log / control-stderr.log。
  //    exit 监听记录 (code, signal)——SIGKILL=外部强杀 / SIGTERM,SIGHUP=外部终止 /
  //    code=1+stderr traceback=Python crash / code=0+control.log"心跳表空"=正常自杀。
  //    unref 不影响 exit 事件派发（unref 只取消事件循环保活）。
  let stdoutFd: number | null = null;
  let stderrFd: number | null = null;
  try {
    stdoutFd = openSync(CONTROL_STDOUT_LOG, "a");
    stderrFd = openSync(CONTROL_STDERR_LOG, "a");
    const proc = spawn(python, [CONTROL_SCRIPT], {
      stdio: ["ignore", stdoutFd, stderrFd],
      detached: true, // 关键：脱离父进程
      env: {
        ...process.env,
        OPENCODE_ROOT: OPENCODE_ROOT, // 控制台读 .ai_env 用
        DATA_DIR: DATA_DIR, // 控制台定位 IPC socket 用
        HF_HUB_OFFLINE: "1", // 避免 SentenceTransformer 联网检查
        TRANSFORMERS_OFFLINE: "1",
      },
    });
    proc.unref(); // 让 opencode 事件循环不等待控制台
    const pid = proc.pid;
    // 数值时间戳（无时区歧义，仅用于差值计算；不出现在日志原文）
    const bootAtMs = Date.now();
    debugLog(
      `startControl: spawn pid=${pid}（stderr→${CONTROL_STDERR_LOG}）`,
    );
    proc.on("exit", (code, signal) => {
      const livedSec = ((Date.now() - bootAtMs) / 1000).toFixed(1);
      let verdict: string;
      if (signal === "SIGKILL") verdict = "外部强杀（kill -9）";
      else if (signal === "SIGTERM" || signal === "SIGHUP")
        verdict = `外部终止（${signal}，kill/终端挂断）`;
      else if (code === 1)
        verdict = "Python 异常退出（traceback 见 control-stderr.log）";
      else if (code === 0)
        verdict = "正常退出（若为自杀，control.log 应有『心跳表空』记录）";
      else verdict = `未知退出形态（code=${code} signal=${signal}）`;
      debugLog(
        `startControl: 控制台进程退出 pid=${pid} 存活=${livedSec}s 判定=${verdict}`,
      );
      // fd 关闭放 exit 回调：进程生命周期内 fd 必须有效
      try {
        if (stdoutFd !== null) closeSync(stdoutFd);
        if (stderrFd !== null) closeSync(stderrFd);
      } catch {
        /* fd 已失效（进程侧），忽略 */
      }
    });
  } catch (e) {
    try {
      if (stdoutFd !== null) closeSync(stdoutFd);
      if (stderrFd !== null) closeSync(stderrFd);
    } catch {
      /* ignore */
    }
    debugLog(`startControl: spawn 异常 ${(e as Error).message}`);
    return false;
  }

  // 4. 等 IPC 通道就绪（/health 可答；503 加载中也算就绪）
  const ready = await waitForIpcReady(CONTROL_IPC_READY_WAIT_MS);
  if (!ready) {
    debugLog(`startControl: IPC ${CONTROL_IPC_READY_WAIT_MS}ms 内未就绪`);
    return false;
  }

  // 5. 启动心跳（首跳立即——控制台刚起需要第一个引用防"空表自杀"）
  await heartbeatSender.start();

  debugLog(`startControl: 完成（IPC 就绪）`);
  return true;
}

/**
 * 等待 IPC 通道就绪。
 * - 超时窗口内 /health 可达（200/503）→ 返回 true
 * - 超时 → 返回 false
 */
async function waitForIpcReady(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isControlHealthy()) {
      return true;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

