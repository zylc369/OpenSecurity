/**
 * 环境检测模块（两层，缺一不可）。
 *
 * 第一层：venv + Python 依赖自举检查（命令行调 detect_py_deps.py scan）
 *   - venv 不存在 → 提示跑 install.sh（自举入口）
 *   - venv 存在但必需包缺失 → 同样提示跑 install.sh（用户唯一确定的修复动作）
 *   - 通过 → 控制台必然能启动（fastapi/uvicorn 等全在必需集内），进第二层
 *
 * 第二层：控制台 GET /api/deps/{agent} 全分类检测
 *   - 聚合 Python 包 / 外部工具 / 编译器 / Docker / 模型 五分类
 *   - 判定语义（required 缺失拦 / optional 缺失不拦）在服务端收口
 *   - 有问题 → 返回 console_url 引导用户到控制台操作
 *
 * interpretScanExit / interpretDepsSummary: 纯函数，便于测试。
 */
import { join } from "path";
import { getControlPort } from "./control-manager";
import { runProcess } from "./spawn";
import { debugLog } from "./logging";
import { SHARED_DIR, OPENCODE_ROOT } from "./constants";

export type EnvironmentCheckResult = {
  ready: boolean;
  message: string; // ready=false: 阻塞消息；ready=true: 空或可选依赖警告
};

/** 控制台 /api/deps 响应的 summary 字段（服务端 routes/deps.py 定义）。 */
export type DepsSummary = {
  agent: string;
  ready: boolean;
  required_missing: string[];
  optional_missing: string[];
  console_url: string;
};

/** 等待控制台就绪的最长时间（预热与控制台 spawn 并发启动）。 */
const CONTROL_WAIT_MS = 45000;
/** 轮询间隔。 */
const POLL_INTERVAL_MS = 800;
/** /api/deps 单次请求超时（检测含 subprocess 探测，留足余量）。 */
const REQUEST_TIMEOUT_MS = 30000;
/** detect_py_deps.py scan 子命令超时（含 subprocess 探测 sage 特例）。 */
const SCAN_TIMEOUT_MS = 30000;

/** detect_py_deps.py 路径（唯一清单 + scan 子命令）。 */
const DETECT_PY_DEPS = join(
  OPENCODE_ROOT,
  "control",
  "backend",
  "services",
  "detect_py_deps.py",
);

/** install.sh 调用提示（按平台）。 */
export function installShCommand(): string {
  const isWin = process.platform === "win32";
  const cmd = isWin
    ? `powershell -ExecutionPolicy Bypass -File "${join(OPENCODE_ROOT, "install.ps1")}"`
    : `bash "${join(OPENCODE_ROOT, "install.sh")}"`;
  return cmd;
}

/**
 * 解析 detect_py_deps scan 的退出码 → 第一层结果。
 * 纯函数，便于测试。
 *
 * exit 0   = 必需包全在（放行进第二层）
 * exit 1   = 有缺失（stdout 已含缺失清单，stdout 缺失时给通用提示）
 * status=null = spawn 失败/超时（python 不存在、脚本丢失）——这是检测
 *            链路故障不是"环境没问题"，拦截并如实报告（fail-closed：
 *            把"不知道"当"有问题"处理，绝不静默放行——否则第一层
 *            会因任何调用方 bug 被无声跳过）
 * 其他码   = 脚本异常退出——同样拦截报告（错误信息进消息，用户可反馈）
 */
export function interpretScanExit(
  status: number | null,
  stdout: string,
  error?: string | null,
): EnvironmentCheckResult {
  if (status === 0) {
    return { ready: true, message: "" };
  }
  if (status === 1) {
    // stdout 是 [+] / [-] 混合清单，只提取缺失行给用户看
    const missing = stdout
      .split("\n")
      .filter((l) => l.startsWith("[-]"))
      .map((l) => l.replace(/^\[-\]\s*/, "").split(/\s{2,}/)[0])
      .filter(Boolean);
    const list = missing.length > 0 ? `（缺失：${missing.join("、")}）` : "";
    return {
      ready: false,
      message:
        `[环境自举检查未通过] Python 必需依赖不完整${list}\n` +
        `请运行安装脚本（安装全部必需依赖）：\n` +
        `  ${installShCommand()}\n` +
        `安装完成后重新发送消息。`,
    };
  }
  // spawn 失败 / 脚本异常退出：如实拦截（不吞错、不静默放行）
  const reason = status === null
    ? `无法执行检测命令${error ? `：${error}` : "（python 或检测脚本不可用）"}`
    : `检测脚本异常退出（exit ${status}${error ? `：${error}` : ""}）`;
  return {
    ready: false,
    message:
      `[环境自举检查故障] ${reason}\n` +
      `这可能是环境安装不完整或插件配置问题。可先尝试：\n` +
      `  ${installShCommand()}\n` +
      `仍失败请查看日志：~/bw-security-analysis/logs/plugin_debug.log`,
  };
}

/**
 * 第一层：venv + Python 依赖自举检查。
 * 命令行调 detect_py_deps.py scan（venv 建立前也可运行——纯 stdlib）。
 * 纯函数语义——永远 resolve，不 reject。
 */
export async function checkPyDepsViaCli(
  pythonCmd: string,
  sessionID: string,
): Promise<EnvironmentCheckResult> {
  const r = await runProcess(
    pythonCmd,
    [DETECT_PY_DEPS, "scan", "--agent", "all"],
    { timeout: SCAN_TIMEOUT_MS, env: { OPENCODE_ROOT } },
  );
  // error 与 status 都进解析（fail-closed：链路故障绝不静默放行）
  debugLog(
    `checkPyDepsViaCli: status=${r.status} error=${r.error?.message ?? "无"}` +
      ` stderr_tail=${(r.stderr || "").trim().slice(-200)}`,
    sessionID,
  );
  return interpretScanExit(r.status, r.stdout || "", r.error?.message);
}

/**
 * 解析控制台 summary → EnvironmentCheckResult。
 * 纯函数，便于测试。
 *
 * ready=true → 放行（optional 缺失仅 debugLog，不注入——控制台可查）
 * ready=false → 终止消息：缺失清单 + console_url（用户打开控制台修复）
 */
export function interpretDepsSummary(s: DepsSummary): EnvironmentCheckResult {
  if (s.ready) {
    if (s.optional_missing && s.optional_missing.length > 0) {
      debugLog(
        `optional_missing（不阻塞）: ${s.optional_missing.join("; ")}`,
        undefined,
      );
    }
    return { ready: true, message: "" };
  }
  const req = (s.required_missing || []).join("、");
  return {
    ready: false,
    message:
      `[环境检测未通过] 缺失必需依赖 ${s.required_missing?.length ?? 0} 项：${req}\n` +
      `打开控制台查看并修复：${s.console_url}\n` +
      `（Python 依赖可逐项一键安装；外部工具/Docker/模型的处理指引见控制台对应分区）\n` +
      `修复完成后重新发送消息。`,
  };
}

async function fetchDeps(
  port: number,
  agent: string,
): Promise<DepsSummary | null> {
  try {
    const resp = await fetch(
      `http://127.0.0.1:${port}/api/deps/${encodeURIComponent(agent)}`,
      { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
    );
    if (!resp.ok) {
      debugLog(`fetchDeps: HTTP ${resp.status} agent=${agent}`, undefined);
      return null;
    }
    const data = (await resp.json()) as { summary?: DepsSummary };
    return data.summary ?? null;
  } catch (e) {
    debugLog(
      `fetchDeps: 请求失败 agent=${agent}: ${(e as Error)?.message ?? e}`,
      undefined,
    );
    return null;
  }
}

/**
 * 环境检测（两层串联）：第一层 CLI 自举检查 → 第二层控制台全分类检测。
 * 纯函数语义——永远 resolve，不 reject。
 *
 * 第一层不过 → install.sh 提示（不再进第二层——控制台起不来时
 * /api/deps 无意义）；第一层过 → 控制台可启动，第二层做权威判定。
 *
 * 控制台等待：预热（plugin setup）与控制台 spawn 并发启动，
 * 先轮询端口文件 + /health 直到就绪（CONTROL_WAIT_MS 内），
 * 避免把"控制台还在启动"误判为"控制台不可达"。
 */
export async function checkDepsViaControl(
  agent: string,
  sessionID: string,
  pythonCmd: string,
): Promise<EnvironmentCheckResult> {
  // ── 第一层：venv + Python 依赖（CLI，控制台启动的前提） ──
  const layer1 = await checkPyDepsViaCli(pythonCmd, sessionID);
  if (!layer1.ready) {
    return layer1;
  }

  // ── 第二层：控制台五分类检测 ──
  const deadline = Date.now() + CONTROL_WAIT_MS;
  let port: number | null = null;
  let summary: DepsSummary | null = null;

  while (Date.now() < deadline) {
    port = await getControlPort();
    if (port) {
      // /health 200/503 都说明进程活着且 API 可服务（503=模型加载中，deps 不依赖模型）
      summary = await fetchDeps(port, agent);
      if (summary) break;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }

  if (!summary) {
    return {
      ready: false,
      message:
        `[环境检测失败] 控制台依赖检测接口不可达（agent=${agent}）。\n` +
        `控制台可能仍在启动或已异常退出，请查看日志：~/bw-security-analysis/logs/\n` +
        `或重启 opencode 后重试。`,
    };
  }
  const result = interpretDepsSummary(summary);
  debugLog(
    `checkDepsViaControl: agent=${agent} sessionID=${sessionID}` +
      ` ready=${result.ready} required=${summary.required_missing?.length ?? 0}` +
      ` optional=${summary.optional_missing?.length ?? 0}`,
    sessionID,
  );
  return result;
}
