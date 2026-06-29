import { join, dirname } from "path";
import { homedir } from "os";
import { fileURLToPath } from "url";
import { existsSync } from "fs";

// ─── 路径常量 ──────────────────────────────────────────────────

// OpenCode 可能将依赖文件放到 lib/ 子目录，导致 import.meta.url 指向 lib/ 而非 plugins/。
// 向上查找 agents/ 目录确定真正的 .opencode/ 根，兼容单文件和多文件两种布局。
function findOpenCodeRoot(startDir: string): string {
  let dir = startDir;
  for (let i = 0; i < 5; i++) {
    if (existsSync(join(dir, "agents"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return dirname(startDir); // fallback
}

export const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
export const OPENCODE_ROOT = findOpenCodeRoot(PLUGIN_DIR);

export const DATA_DIR = join(homedir(), "bw-security-analysis");
export const CONFIG_FILE = join(DATA_DIR, "config.json");
export const ENV_CACHE_FILE = join(DATA_DIR, "env_cache.json");
export const WORKSPACE_DIR = join(DATA_DIR, "workspace");
export const TASK_SESSIONS_DIR = join(WORKSPACE_DIR, ".task_sessions");

export const LOGS_DIR = join(DATA_DIR, "logs");
export const DEFAULT_LOG = join(LOGS_DIR, "plugin_debug.log");
export const MAX_LOG_SIZE = 5 * 1024 * 1024;
export const KEEP_SIZE = 2 * 1024 * 1024;

// ─── Agent 常量 ────────────────────────────────────────────────

export const AGENT_BINARY_ANALYSIS = "binary-analysis";
export const AGENT_MOBILE_ANALYSIS = "mobile-analysis";
export const AGENT_WEB_ANALYSIS = "web-analysis";
export const AGENT_AI_SECURITY_ANALYSIS = "ai-security-analysis";
export const AGENT_CRYPTO_ANALYSIS = "crypto-analysis";
export const AGENT_SECURITY_ANALYSIS_EVOLVE = "security-analysis-evolve";
export const AGENT_SECURITY_COORDINATOR = "security-coordinator";

export const SECURITY_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_CRYPTO_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
];

export const AGENT_SCRIPT_DIRS: Record<string, string> = {};
for (const name of SECURITY_AGENTS) {
  AGENT_SCRIPT_DIRS[name] = join(OPENCODE_ROOT, name);
}

export const SHARED_DIR = join(OPENCODE_ROOT, AGENT_BINARY_ANALYSIS);

export const AGENTS_DIR = join(OPENCODE_ROOT, "agents");
export const AGENTS_RULES_DIR = join(OPENCODE_ROOT, "agents-rules");

// ─── 环境信息注入 ──────────────────────────────────────────────

export const ENV_INJECTION_FREQUENCY = 5; // 每 N 次请求注入一次环境信息

// ─── 分析持续性恢复 ────────────────────────────────────────────

export const MAX_DURATION_DEFAULT = 8 * 60 * 60 * 1000; // X 小时，单位毫秒
export const MAX_RESUMES = 80; // 最大恢复次数，防止分析完成后无限循环恢复
export const RESUME_COOLDOWN_STEP_MS = 1000; // 冷却起始值和递增步长（1秒起，每次+1秒）
export const RESUME_COOLDOWN_MAX_MS = 10 * 1000; // 冷却上限（10秒）
export const ABORTED_ERROR_NAME = "MessageAbortedError";

// ─── venv ──────────────────────────────────────────────────────

export const VENV_DIR = join(DATA_DIR, ".venv");

export const VENV_PYTHON_CANDIDATES = [
  join(VENV_DIR, "Scripts", "python.exe"), // Windows 标准位置
  join(VENV_DIR, "bin", "python"), // Linux/macOS 标准位置
  join(VENV_DIR, "Scripts", "python3.exe"), // Windows（python3 别名）
  join(VENV_DIR, "bin", "python3"), // Linux/macOS（python3）
];

// ─── 时间线 ────────────────────────────────────────────────────

export const MAX_TIMELINE_BUFFER = 50;
