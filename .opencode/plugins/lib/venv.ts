import { execFileSync, spawnSync } from "child_process";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { VENV_PYTHON_CANDIDATES, OPENCODE_ROOT } from "./constants";
import { debugLog } from "./logging";

// 惰性缓存的 Python 命令路径
let cachedPythonCmd: string | null = null;

// 验证 Python 可用性（执行 print('OK') 检查）
function verifyPython(pathOrCmd: string): boolean {
  try {
    const output = execFileSync(pathOrCmd, ["-c", "print('OK')"], {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 5000,
      encoding: "utf-8",
    });
    return output.trim() === "OK";
  } catch {
    return false;
  }
}

// 检查 venv Python 是否存在（不创建，conda/venv 创建由 detect_env.py install 负责）
function findVenvPython(): string | null {
  for (const candidate of VENV_PYTHON_CANDIDATES) {
    if (!existsSync(candidate)) continue;
    if (verifyPython(candidate)) {
      return candidate;
    }
    debugLog(`findVenvPython: ${candidate} exists but failed verification`);
  }
  return null;
}

/**
 * 获取 Python 命令路径（惰性初始化 + 缓存）。
 * 只检查 venv 是否存在，不创建。venv 创建由 detect_env.py install 负责。
 * 返回 null 表示 venv 不存在，调用方应提示用户运行安装脚本。
 */
export function getPythonCmd(): string | null {
  if (cachedPythonCmd) {
    return cachedPythonCmd;
  }
  cachedPythonCmd = findVenvPython();
  if (!cachedPythonCmd) {
    debugLog(`getPythonCmd: venv 不存在，请运行安装脚本`);
  }
  return cachedPythonCmd;
}

/**
 * 返回安装脚本路径提示（供 checkEnvironment 使用）。
 * 用户看到此消息后应运行安装脚本，安装脚本会检测 conda + 创建 venv + 安装依赖。
 */
export function getInstallHint(): string {
  const isWin = process.platform === "win32";
  const script = isWin ? "install.ps1" : "install.sh";
  const cmd = isWin
    ? `powershell -ExecutionPolicy Bypass -File "${join(OPENCODE_ROOT, script)}"`
    : `bash "${join(OPENCODE_ROOT, script)}"`;
  return (
    `环境未就绪。请运行一键安装脚本：\n` +
    `  ${cmd}\n` +
    `安装完成后重新发送消息。`
  );
}

// ─── .ai_env 读取 ──────────────────────────────────────────────

/**
 * 读取 .ai_env 配置文件（KEY=VALUE 格式），解析为对象。
 * 忽略空行和 # 注释行。
 * 文件不存在或读取失败时返回空对象。
 * 注意：本函数只读 .ai_env 文件本身，不合并系统 env（与 detect_env.py 的 _load_ai_env 行为一致——
 *       detect_env.py 用 setdefault 让系统 env 优先，但 Plugin TS 侧不需要这个优先级，
 *       因为 shell.env 注入时系统 env 已在 process.env 中可直接取）。
 */
export function readAiEnv(): Record<string, string> {
  const result: Record<string, string> = {};
  const aiEnvPath = join(OPENCODE_ROOT, ".ai_env");
  try {
    if (!existsSync(aiEnvPath)) return result;
    const content = readFileSync(aiEnvPath, "utf-8");
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx <= 0) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      const value = trimmed.slice(eqIdx + 1).trim();
      if (key) result[key] = value;
    }
  } catch (e) {
    debugLog(`readAiEnv: 读取 ${aiEnvPath} 失败: ${(e as Error)?.message}`);
  }
  return result;
}

// ─── IDA Pro idat 路径（惰性缓存） ────────────────────────────

let cachedIdatPath: string | null = null;

/**
 * 获取 IDA Pro 的 idat 可执行文件路径（惰性初始化 + 缓存）。
 * 从 .ai_env 的 IDA_PRO_HOME 读取，拼接 idat（Windows 加 .exe），校验文件存在。
 * 返回 null 表示 IDA Pro 未配置或路径无效。
 * 对齐 getPythonCmd() 的缓存模式。
 */
export function getIdatPath(): string | null {
  if (cachedIdatPath) return cachedIdatPath;

  const aiEnv = readAiEnv();
  const idaHome = aiEnv.IDA_PRO_HOME;
  if (!idaHome) {
    debugLog(`getIdatPath: IDA_PRO_HOME 未配置`);
    cachedIdatPath = null;
    return null;
  }

  const exe = process.platform === "win32" ? "idat.exe" : "idat";
  const idatPath = join(idaHome, exe);
  if (existsSync(idatPath)) {
    debugLog(`getIdatPath: 找到 idat at ${idatPath}`);
    cachedIdatPath = idatPath;
  } else {
    debugLog(`getIdatPath: ${idatPath} 不存在（IDA_PRO_HOME=${idaHome}）`);
    cachedIdatPath = null;
  }
  return cachedIdatPath;
}

// ─── 编译器名（惰性缓存） ─────────────────────────────────────

let cachedCompilerName: string | null = null;

/**
 * 获取 PATH 中可用的编译器名（惰性初始化 + 缓存）。
 * 候选顺序：clang → gcc → cc（Unix）或 clang → gcc → cl（Windows）。
 * 返回编译器名（Unix: "clang"/"gcc"/"cc"；Windows: "clang.exe"/"gcc.exe"/"cl.exe"）或 null（未找到）。
 * 仅做 PATH 检测，不涉及 Windows MSVC/vcvarsall 复杂逻辑
 * （那部分由 detect_env.py fail-fast 覆盖）。
 * 对齐 getPythonCmd() 的缓存模式。
 */
export function getCompilerName(): string | null {
  if (cachedCompilerName) return cachedCompilerName;

  const isWin = process.platform === "win32";
  const cmd = isWin ? "where" : "which";
  const candidates = isWin
    ? ["clang.exe", "gcc.exe", "cl.exe"]
    : ["clang", "gcc", "cc"];

  for (const name of candidates) {
    try {
      const r = spawnSync(cmd, [name], {
        stdio: ["pipe", "pipe", "pipe"],
        encoding: "utf-8",
        timeout: 3000,
      });
      if (r.status === 0 && (r.stdout || "").trim()) {
        debugLog(`getCompilerName: 找到 ${name}`);
        cachedCompilerName = name;
        return cachedCompilerName;
      }
    } catch (e) {
      debugLog(`getCompilerName: 检测 ${name} 异常: ${(e as Error)?.message}`);
    }
  }

  debugLog(`getCompilerName: PATH 中未找到编译器`);
  cachedCompilerName = null;
  return null;
}
