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

export const MAX_DURATION_DEFAULT = 6 * 60 * 60 * 1000; // 6 小时，单位毫秒
export const MAX_RESUMES = 50; // 最大恢复次数，防止分析完成后无限循环恢复
export const PERSISTENCE_FILE = ".persistence.json";
export const ABORTED_ERROR_NAME = "MessageAbortedError";
export const COMPLETION_MARKER = ">>>COMPLETE<<<";
// 多条语义等价的恢复提示词：每次随机选用且不与上次相同，
// 避免反复发送同一文本导致 LLM 习惯性"皮掉"、不再继续分析。
export const RESUME_PROMPTS: string[] = [
  `你之前的分析是否已经完成了？**你必须要如实回答和执行**：\n` +
  `- 如果已经完成：请直接输出最终结论，然后在最后一行精确输出这个标记（原样复制，不要修改）：${COMPLETION_MARKER}\n` +
  `- 如果尚未完成：不论任何原因只要未完成，你都必须自主继续分析，不要停下来向用户提问。复盘一下之前的分析内容、结果，然后继续分析，直到完成为止。未完成的情况下绝对不允许输出 ${COMPLETION_MARKER} 标记。`,

  `请确认此前的分析工作是否已经全部完成。**必须如实回答并严格执行**：\n` +
  `- 若已完成：直接给出最终结论，并在末尾单独一行原样输出该标记（切勿改动）：${COMPLETION_MARKER}\n` +
  `- 若未完成：无论出于何种原因，都必须自行接着分析下去，不得向用户提问。先回顾之前的分析内容与结论，再继续推进直至全部完成。未完成时严禁输出 ${COMPLETION_MARKER}。`,

  `你先前的分析完成了吗？**务必如实回答并照做**：\n` +
  `- 已完成的话：请直接产出最终结论，随后在最后一行一字不差地输出以下标记（不得修改）：${COMPLETION_MARKER}\n` +
  `- 尚未完成的话：不管什么原因，你都要自主把分析继续下去，不要停下来问用户。梳理一下已有的分析内容与结果，接着往下做，直到真正完成。只要还没完成，就绝对不可以输出 ${COMPLETION_MARKER}。`,

  `请判断此前的分析是否已结束。**你必须诚实回答并按以下执行**：\n` +
  `- 已结束：请直接陈述最终结论，并在最后一行精确地原样输出这个标记（不要做任何修改）：${COMPLETION_MARKER}\n` +
  `- 未结束：任何情况下只要还没做完，都得自主继续分析，不允许停下来征求用户意见。请复盘此前分析的内容和结果，然后继续，直到彻底完成。尚未完成时绝不允许输出 ${COMPLETION_MARKER}。`,

  `分析任务完成了吗？**请如实回答并严格执行如下要求**：\n` +
  `- 倘若已完成：直接输出最终结论，最后单独一行原样复制此标记（一字不改）：${COMPLETION_MARKER}\n` +
  `- 倘若未完成：不论任何缘由，你都必须独立继续分析，切勿停下来询问用户。回顾前面的分析内容与结果，继续推进直到完成。在未完成时，绝不可输出 ${COMPLETION_MARKER}。`,
];

// ─── venv ──────────────────────────────────────────────────────

export const VENV_DIR = join(DATA_DIR, ".venv");

export const VENV_PYTHON_CANDIDATES = [
  join(VENV_DIR, "python.exe"), // conda env Windows 根目录
  join(VENV_DIR, "Scripts", "python.exe"), // venv Windows 标准位置
  join(VENV_DIR, "bin", "python"), // Linux/macOS 标准位置（venv / conda 共享）
  join(VENV_DIR, "Scripts", "python3.exe"), // Windows（python3 别名）
  join(VENV_DIR, "bin", "python3"), // Linux/macOS（python3）
];

// ─── 时间线 ────────────────────────────────────────────────────

export const MAX_TIMELINE_BUFFER = 50;
