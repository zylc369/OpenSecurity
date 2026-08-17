import { execFileSync, spawnSync } from "child_process";
import { existsSync, statSync } from "fs";
import { join } from "path";
import { VENV_PYTHON_CANDIDATES, OPENCODE_ROOT } from "./constants";
import { debugLog } from "./logging";

// ─── venv Python 查找（control-manager.ts 也调用此函数）─────────

/** 查找 venv Python（不创建，仅检测存在性 + 可执行性校验）。 */
export function findVenvPython(): string | null {
  for (const candidate of VENV_PYTHON_CANDIDATES) {
    if (!existsSync(candidate)) continue;
    if (verifyPython(candidate)) {
      return candidate;
    }
    debugLog(`findVenvPython: ${candidate} exists but failed verification`);
  }
  return null;
}

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

/**
 * 获取 Python 命令路径（惰性初始化 + 缓存）。
 * 只检查 venv 是否存在，不创建。venv 创建由 detect_py_deps.py install 子命令负责。
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

// ─── 编译器名（惰性缓存） ─────────────────────────────────────
// readAiEnv / getIdatPath 已删除——配置读取收口到 control-config.ts。
// 调用方应改用 getConfig("IDA_PRO_HOME") / getAllConfig() 拿配置。

let cachedCompilerName: string | null = null;

/**
 * 获取 PATH 中可用的编译器名（惰性初始化 + 缓存）。
 * 候选顺序：clang → gcc → cc（Unix）或 clang → gcc → cl（Windows）。
 * 返回编译器名（Unix: "clang"/"gcc"/"cc"；Windows: "clang.exe"/"gcc.exe"/"cl.exe"）或 null（未找到）。
 * 仅做 PATH 检测，不涉及 Windows MSVC/vcvarsall 复杂逻辑
 * （那部分由控制台 /api/deps 检测覆盖）。
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
