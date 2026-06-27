import { execSync } from "child_process";
import { existsSync } from "fs";
import { VENV_DIR, VENV_PYTHON_CANDIDATES } from "./constants";
import { debugLog } from "./logging";

// 实际运行 Python 代码验证可用性（不依赖 exit code，不假设路径）
function verifyPython(pathOrCmd: string): boolean {
  try {
    const output = execSync(`"${pathOrCmd}" -c "print('OK')"`, {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 5000,
      encoding: "utf-8",
    });
    return output.trim() === "OK";
  } catch {
    return false;
  }
}

// 从 venv 中检测可用的 Python（不假设路径，逐个验证）
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

// 检测系统 Python 命令（仅用于创建 venv）
function findSystemPython(): string {
  const candidates =
    process.platform === "win32"
      ? ["python", "python3"]
      : ["python3", "python"];

  for (const cmd of candidates) {
    if (verifyPython(cmd)) return cmd;
  }
  throw new Error(
    `未找到可用的系统 Python。请安装 Python 3.8+ 后重试。\n` +
      `已尝试: ${candidates.join(", ")}`,
  );
}

function ensureVenvPython(): string {
  // 1. 已有 venv → 检测可用的 Python
  const existing = findVenvPython();
  if (existing) {
    debugLog(`ensureVenvPython: ${existing} verified`);
    return existing;
  }

  // 2. 需要创建 venv
  const systemPython = findSystemPython();
  debugLog(`ensureVenvPython: creating venv with ${systemPython}`);

  try {
    execSync(`"${systemPython}" -m venv "${VENV_DIR}"`, {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 120000,
      encoding: "utf-8",
    });
  } catch (e) {
    throw new Error(
      `创建 Python 虚拟环境失败: ${(e as Error).message}\n` +
        `请手动运行: ${systemPython} -m venv "${VENV_DIR}"`,
    );
  }

  // 3. 创建后重新检测（不假设路径，用同一套检测逻辑）
  const created = findVenvPython();
  if (created) {
    debugLog(`ensureVenvPython: ${created} created and verified`);
    return created;
  }
  throw new Error(
    `虚拟环境创建成功但未检测到可用的 Python。\n` +
      `请删除 "${VENV_DIR}" 后重试。`,
  );
}

// Plugin 加载时立即确保 venv 可用；失败则整个 Plugin 加载失败
export const PYTHON_CMD = ensureVenvPython();
