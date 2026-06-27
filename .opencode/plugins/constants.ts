import { join, dirname } from "path";
import { homedir } from "os";
import { fileURLToPath } from "url";

// ─── 路径常量 ──────────────────────────────────────────────────

export const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
export const OPENCODE_ROOT = dirname(PLUGIN_DIR);

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
export const AGENT_SECURITY_ANALYSIS_EVOLVE = "security-analysis-evolve";
export const AGENT_SECURITY_COORDINATOR = "security-coordinator";

export const PRIMARY_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
];

export const AGENT_SCRIPT_DIRS: Record<string, string> = {};
for (const name of PRIMARY_AGENTS) {
  AGENT_SCRIPT_DIRS[name] = join(OPENCODE_ROOT, name);
}

export const SHARED_DIR = join(OPENCODE_ROOT, AGENT_BINARY_ANALYSIS);

export const AGENTS_DIR = join(OPENCODE_ROOT, "agents");
export const AGENTS_RULES_DIR = join(OPENCODE_ROOT, "agents-rules");

// ─── 环境信息注入 ──────────────────────────────────────────────

export const ENV_INJECTION_FREQUENCY = 5; // 每 N 次请求注入一次环境信息

// ─── 分析持续性恢复 ────────────────────────────────────────────

export const MAX_DURATION_DEFAULT = 6 * 60 * 60 * 1000; // 6 小时，单位毫秒
export const MAX_RESUMES = 50; // 最大恢复次数，防止分析完成后无限循环恢复
export const PERSISTENCE_FILE = ".persistence.json";
export const ABORTED_ERROR_NAME = "MessageAbortedError";
export const COMPLETION_MARKER = ">>>COMPLETE<<<";
export const RESUME_PROMPT =
  `你之前的分析是否已经完成了？\n` +
  `- 如果已经完成：请直接输出最终结论，然后在最后一行精确输出这个标记（原样复制，不要修改）：${COMPLETION_MARKER}\n` +
  `- 如果尚未完成：请自主继续分析，不要停下来向用户提问。`;

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
