import { execFileSync } from "child_process";
import { existsSync } from "fs";
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
