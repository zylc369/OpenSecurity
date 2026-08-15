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
  return dirname(startDir); // 回退
}

export const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
// OPENCODE_ROOT 支持环境变量覆盖（bun -e / 测试场景下 import.meta.url 不准）。
// 默认通过 findOpenCodeRoot 从 PLUGIN_DIR 向上查找。
export const OPENCODE_ROOT =
  process.env.OPENCODE_ROOT || findOpenCodeRoot(PLUGIN_DIR);

// DATA_DIR 支持环境变量覆盖（与控制台 config.py 对等）。
// 默认 ~/bw-security-analysis（生产环境用户路径）。
// 测试可通过 DATA_DIR=/tmp/xxx 隔离。
export const DATA_DIR =
  process.env.DATA_DIR || join(homedir(), "bw-security-analysis");
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

// 通过 PentAGI searcher/memorist 进化新增的子 agent（2026-07-09）。
// 以原始字符串形式保留，因为它们不属于历史的 SECURITY_AGENTS 列表
// （后者用于控制环境信息注入 + 会话生命周期钩子）。
export const AGENT_SEARCHER = "searcher";
export const AGENT_MEMORIST = "memorist";

export const SECURITY_ANALYSIS_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_CRYPTO_ANALYSIS,
];

export const SECURITY_AGENTS = [
  ...SECURITY_ANALYSIS_AGENTS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
];

export const BASIC_GENERAL_AGENTS = [AGENT_SEARCHER, AGENT_MEMORIST];

// evolve 从注册名单摘除（知识双轨分离设计）：
// - 摘除后 evolve 的工具执行/LLM 响应不再写 events/memory（isRegisteredAgent 链拦截）
// - 但不从 SECURITY_AGENTS 拿掉：那边承担日志、timeline、父链查找等可观测性职责
// - evolve 的环境注入不受影响（system.transform 用 sessionManager.get，无名单门控）
export const ALL_REGISTERED_AGENTS = [
  ...BASIC_GENERAL_AGENTS,
  ...SECURITY_AGENTS,
].filter((agent) => agent !== AGENT_SECURITY_ANALYSIS_EVOLVE);

// 所有参与跨 agent 委派的 agent。插件会向每个成员的系统提示词中注入
// 一个"可委派 Agent"区块（从每个 agent 的 .md frontmatter description 中收集）。
//
// 组成：5 个领域分析 agent + searcher + memorist。
// 设计上排除：
//   - security-analysis-evolve（开发工具，不是分析 agent）
//   - security-coordinator（保留以向后兼容，但不在此列表中）
// 这并非 SECURITY_AGENTS 的超集——两个列表在 5 个领域 agent 上有重叠，
// 但各自都包含对方没有的成员。
export const AGENTS_WITH_DELEGATION_RULES = [
  ...BASIC_GENERAL_AGENTS,
  ...SECURITY_ANALYSIS_AGENTS,
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

// .ai_env 中控制 maybeResumeAnalysis 开关的变量名。
// 取值规则：未找到/非 0 非 false 的任意值 → 启用；值为 "0" 或 tolower 后 "false" → 禁用。
export const ENV_KEY_RESUME_ANALYSIS = "RESUME_ANALYSIS_ENABLED";

// ─── venv ──────────────────────────────────────────────────────

// venv 与 DATA_DIR 解耦：测试用沙箱 DATA_DIR 时仍可指向真实 venv（省 1GB+ 依赖安装）。
export const VENV_DIR =
  process.env.OPENSECURITY_VENV_DIR || join(DATA_DIR, ".venv");

export const VENV_PYTHON_CANDIDATES = [
  join(VENV_DIR, "python.exe"), // conda env Windows 根目录
  join(VENV_DIR, "Scripts", "python.exe"), // venv Windows 标准位置
  join(VENV_DIR, "bin", "python"), // Linux/macOS 标准位置（venv / conda 共享）
  join(VENV_DIR, "Scripts", "python3.exe"), // Windows（python3 别名）
  join(VENV_DIR, "bin", "python3"), // Linux/macOS（python3）
];

// ─── 时间线 ────────────────────────────────────────────────────

export const MAX_TIMELINE_BUFFER = 50;

// ─── 控制台（opencode-control）──────────────────────────────────
//
// 控制台架构改造后，embed_server 融合到控制台。下述常量收口所有控制台相关命名。

/** 控制台后端 server.py 路径 */
export const CONTROL_SCRIPT = join(
  OPENCODE_ROOT,
  "control",
  "backend",
  "server.py",
);

/** 控制台端口文件路径（与控制台后端 config.py 的 PORT_FILE 一致） */
export const CONTROL_PORT_FILE = join(DATA_DIR, ".opencode-control.port");

/** 控制台 users 文件路径（与控制台后端 config.py 的 USERS_FILE 一致） */
export const CONTROL_USERS_FILE = join(DATA_DIR, ".opencode-control.users");

/** Plugin spawn 控制台后，通过此环境变量把端口传给 MCP server（embed_client.py 读） */
export const ENV_CONTROL_PORT = "OPENCODE_CONTROL_PORT";

/** ServiceRegistry 中控制台启动状态的服务名（控制台 spawn + /health 200） */
export const CONTROL_STARTUP_SERVICE = "control_startup";

/** ServiceRegistry 中控制台扫描完成的服务名（第三~五层扫描完成） */
export const CONTROL_SCAN_SERVICE = "control_scan";

/** 控制台启动超时（毫秒）。包括 spawn + 端口文件出现 + 模型加载（最坏 30s） */
export const CONTROL_STARTUP_TIMEOUT_MS = 60_000;

/** 控制台扫描超时（毫秒）。Docker 检测 + 工具检测 */
export const CONTROL_SCAN_TIMEOUT_MS = 90_000;

/** 端口文件等待超时（毫秒）。控制台 spawn 后写端口文件的时间 */
export const CONTROL_PORT_FILE_WAIT_MS = 5_000;
