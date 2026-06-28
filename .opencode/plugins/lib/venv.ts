import { execSync } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { VENV_DIR, VENV_PYTHON_CANDIDATES } from "./constants";
import { debugLog } from "./logging";

// 验证 Python 可用性（执行 print('OK') 检查）
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

// 从已有 conda env 中检测可用的 Python（不假设路径，逐个验证）
// conda env 的文件结构与 venv 完全一致，候选路径相同
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

// 验证 conda 命令可用（执行 --version 检查）
function verifyConda(cmd: string): boolean {
  try {
    execSync(`"${cmd}" --version`, {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 5000,
      encoding: "utf-8",
    });
    return true;
  } catch(e) {
    debugLog(`verifyConda: ${cmd} failed verification: ${e}`);
    return false;
  }
}

// 跨平台检测 conda：先查 PATH，再查常见安装路径
function findConda(): string | null {
  // 1. PATH 里的 conda
  if (verifyConda("conda")) {
    debugLog(`findConda: found in PATH`);
    return "conda";
  }

  // 2. 常见安装路径（miniforge3 / miniconda3）
  const home = homedir();
  const candidates =
    process.platform === "win32"
      ? [
          join(home, "miniforge3", "Scripts", "conda.exe"),
          join(home, "miniconda3", "Scripts", "conda.exe"),
        ]
      : [
          join(home, "miniforge3", "bin", "conda"),
          join(home, "miniconda3", "bin", "conda"),
          "/opt/homebrew/Caskroom/miniforge/base/condabin/conda", // brew install --cask miniforge
          "/opt/miniforge3/bin/conda",
          "/opt/miniconda3/bin/conda",
        ];

  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue;
    if (verifyConda(candidate)) {
      debugLog(`findConda: found at ${candidate}`);
      return candidate;
    }
  }

  debugLog(`findConda: conda not found in PATH or common locations`);
  return null;
}

// 确保 conda env 存在并返回 python 路径（失败返回 null，不 throw）
function ensureCondaEnvPython(): string | null {
  const methodName = "ensureCondaEnvPython";
  // 1. 已有 env → 检测可用的 Python
  const existing = findVenvPython();
  if (existing) {
    debugLog(`${methodName}: ${existing} verified`);
    return existing;
  }

  // 2. 需要创建 env → 先检测 conda
  const conda = findConda();
  if (!conda) {
    debugLog(`${methodName}: conda not found, cannot create env`);
    return null;
  }

  // 3. 创建 conda env（python=3.13）
  debugLog(`${methodName}: creating conda env with ${conda}`);
  try {
    execSync(`"${conda}" create -p "${VENV_DIR}" python=3.13 -y`, {
      stdio: ["pipe", "pipe", "pipe"],
      timeout: 300000, // 5 分钟
      encoding: "utf-8",
    });
  } catch (e) {
    debugLog(`${methodName}: conda create failed: ${e}`);
    return null;
  }

  // 4. 创建后重新检测
  const created = findVenvPython();
  if (created) {
    debugLog(`${methodName}: ${created} created and verified`);
    return created;
  }

  debugLog(`${methodName}: env created but python not found`);
  return null;
}

// 惰性缓存的 Python 命令路径
let cachedPythonCmd: string | null = null;

// 获取 Python 命令路径（惰性初始化 + 缓存）
// 首次调用时检测/创建 conda env，后续直接返回缓存值
// 返回 null 表示 conda 不可用且 env 不存在
export function getPythonCmd(): string | null {
  if (cachedPythonCmd) {
    return cachedPythonCmd;
  }
  cachedPythonCmd = ensureCondaEnvPython();
  return cachedPythonCmd;
}

// 返回平台相关的 miniforge 安装指引（供 checkEnvironment 使用）
export function getCondaInstallHint(): string {
  const platform = process.platform;
  let installCmd: string;
  if (platform === "darwin") {
    installCmd = "curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-$(uname -m).sh && bash Miniforge3-MacOSX-$(uname -m).sh";
  } else if (platform === "win32") {
    installCmd = "从 https://github.com/conda-forge/miniforge#download 下载安装包";
  } else {
    installCmd = "参考 https://github.com/conda-forge/miniforge#download";
  }
  return (
    `[环境未就绪] conda 未安装，无法创建 Python 虚拟环境。请先安装 Miniforge：\n` +
    `- ${installCmd}\n\n` +
    `安装后重启终端，重新发送消息。`
  );
}
