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
// 字典统一目录（WordlistRecipe 落点; shell.env 注入 $WORDLISTS_DIR; 容器 wrapper 挂载源）
export const WORDLISTS_DIR = join(DATA_DIR, "wordlists");
// 外部工具目录（detect_tools.py 的 CMD_DIR/TOOLS_HOME_DIR 对等落点）。
// 必须经 DATA_DIR 派生（勿硬编码 homedir 拼接）——保持 env 覆盖/测试沙箱一致性。
// 两者是 DATA_DIR 下的平级兄弟目录（无包含关系）:
//   CMD  = 命令目录（可执行入口: wrapper + 单二进制，PATH 注入点，按名调用）
//   HOME = 工具的家（本体文件: 运行时/克隆仓库/jar，如 node/、dotnet/、android-platform-tools/）
export const TOOLS_CMD_DIR = join(DATA_DIR, "bin");
export const TOOLS_HOME_DIR = join(DATA_DIR, "tools");

export const LOGS_DIR = join(DATA_DIR, "logs");
export const DEFAULT_LOG = join(LOGS_DIR, "plugin_debug.log");
// 控制台子进程 stdout/stderr 落盘（spawn stdio 接管）。
// 此前 stdio 三路 ignore 导致 crash traceback / kill 信号物理不可见——
// 10-12 秒三连死事故（2026/9/14 22:25-22:31）无法定位根因的直接教训。
export const CONTROL_STDOUT_LOG = join(LOGS_DIR, "control-stdout.log");
export const CONTROL_STDERR_LOG = join(LOGS_DIR, "control-stderr.log");
export const MAX_LOG_SIZE = 5 * 1024 * 1024;
export const KEEP_SIZE = 2 * 1024 * 1024;

// ─── Agent 常量 ────────────────────────────────────────────────

export const AGENT_BINARY_ANALYSIS = "binary-analysis";
export const AGENT_MOBILE_ANALYSIS = "mobile-analysis";
export const AGENT_WEB_ANALYSIS = "web-analysis";
export const AGENT_AI_SECURITY_ANALYSIS = "ai-security-analysis";
export const AGENT_CRYPTO_ANALYSIS = "crypto-analysis";
export const AGENT_SECURITY_ANALYSIS_EVOLVE = "security-analysis-evolve";

export const AGENT_SEARCHER = "searcher";
export const AGENT_MEMORIST = "memorist";
export const AGENT_FRESH_EYES = "fresh-eyes";

// 成员 × 集合矩阵（✓ = 属于该集合；各集合的语义与消费点见其定义处注释）:
//
// | agent                    | GENERAL_SUB | SECURITY_ANALYSIS | SECURITY | REGISTERED |
// |--------------------------|-------------|-------------------|----------|------------|
// | searcher                 | ✓           |                   |          | ✓          |
// | memorist                 | ✓           |                   |          | ✓          |
// | fresh-eyes               | ✓           |                   |          | ✓          |
// | binary-analysis          |             | ✓                 | ✓        | ✓          |
// | mobile-analysis          |             | ✓                 | ✓        | ✓          |
// | web-analysis             |             | ✓                 | ✓        | ✓          |
// | ai-security-analysis     |             | ✓                 | ✓        | ✓          |
// | crypto-analysis          |             | ✓                 | ✓        | ✓          |
// | security-analysis-evolve |             |                   | ✓        | 有意排除   |

// 领域分析 agent（5 个）。消费点：根会话任务目录 + ledger.md 模板创建
//（task-session-persistence.ts）；认知检查点计数/注入、压缩时台账注入
//（security-analysis.ts）；启动时的环境检测预热。
export const SECURITY_ANALYSIS_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_CRYPTO_ANALYSIS,
];

// 承担可观测性职责的 agent。消费点：独立日志文件（logging.ts）、时间线记录、
// requireSecurityAgent 门控（compacting / 分析持续性持久化）、父链回溯
//（searcher/memorist 据此加载 domain-sources 片段）、脚本目录映射。
export const SECURITY_AGENTS = [
  ...SECURITY_ANALYSIS_AGENTS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
];

// 通用辅助子 agent（非领域分析）：情报检索 / 长期记忆 / 无记忆评审。
export const GENERAL_SUB_AGENTS = [
  AGENT_SEARCHER,
  AGENT_MEMORIST,
  AGENT_FRESH_EYES,
];

// 项目内 agent 全集（agents/ 目录下均有定义文件）：领域分析 + 通用辅助 + evolve。
// 消费点：占位符展开的"文件缺失即异常"判定（snippet.ts inspectAgentFile）。
export const PROJECT_AGENTS = [...GENERAL_SUB_AGENTS, ...SECURITY_AGENTS];

// 注册进 events/memory 采集与工具时间线的 agent（= PROJECT_AGENTS 去掉 evolve）。
// 消费点：events/memory 写入（tool.execute.after / text.complete）、
// tool.execute.before/after 时间线、根会话任务目录创建门控（session-manager）。
// evolve 有意排除：开发工具，其工具执行与 LLM 回复不写入事件/记忆库。
export const ALL_REGISTERED_AGENTS = PROJECT_AGENTS.filter(
  (agent) => agent !== AGENT_SECURITY_ANALYSIS_EVOLVE,
);

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

// 控制台配置中控制"认知检查点"开关的变量名（读写方：控制台 config_store；插件经配置缓存读取）。
// 取值规则：未找到/非 0 非 false 的任意值 → 启用（默认开启）；"0" 或 tolower 后 "false" → 禁用。
// 改配置后重启 opencode 生效。
export const ENV_KEY_COGNITION_CHECKPOINT = "COGNITION_CHECKPOINT_ENABLED";

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

// ─── 认知检查点（反公理固化）────────────────────────────────────

/** 检查点触发：每 N 次工具调用一次 */
export const CHECKPOINT_TOOL_INTERVAL = 20;
/** 检查点触发：时间间隔（毫秒；与工具调用数先到者触发） */
export const CHECKPOINT_TIME_INTERVAL_MS = 40 * 60 * 1000;
/** 台账原样注入压缩上下文的 token 预算（估算；超预算按行截断并附全文路径） */
export const LEDGER_INJECT_MAX_TOKENS = 4000;

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

/** 控制台 IPC：Unix Domain Socket 路径（macOS/Linux；与控制台 config.py 一致） */
export const CONTROL_UNIX_SOCKET = join(DATA_DIR, "opensecurity-control.sock");

/** 控制台 IPC：Windows 命名管道名（与控制台 config.py 一致；随机后缀防撞名） */
export const CONTROL_WIN_PIPE = "\\\\.\\pipe\\opensecurity-control-482964";

/** 当前平台是否 Windows */
export const IS_WINDOWS = process.platform === "win32";

/** 心跳间隔（毫秒）。与控制台 config.py 的 HEARTBEAT_TIMEOUT_SEC(60s) 协议配对：
 *  控制台超过 60s 未收到本心跳 → 移除；心跳表空 → 控制台自杀 */
export const HEARTBEAT_INTERVAL_MS = 10_000;

/** ServiceRegistry 中控制台启动状态的服务名（控制台 spawn + IPC 就绪） */
export const CONTROL_STARTUP_SERVICE = "control_startup";

/** ServiceRegistry 中控制台扫描完成的服务名（第三~五层扫描完成） */
export const CONTROL_SCAN_SERVICE = "control_scan";

/** 控制台启动超时（毫秒）。包括 spawn + IPC 就绪 + 模型加载（最坏 30s） */
export const CONTROL_STARTUP_TIMEOUT_MS = 60_000;

/** 控制台扫描超时（毫秒）。Docker 检测 + 工具检测 */
export const CONTROL_SCAN_TIMEOUT_MS = 90_000;

/** IPC 就绪等待超时（毫秒）。控制台 spawn 后 IPC 通道可 connect 的时间 */
export const CONTROL_IPC_READY_WAIT_MS = 45_000;
// 2026/9/15 重建测试实测：全新 venv 冷启动（模型/graphiti 初始化）/health 503
// 持续 ~23s——旧值 8s 会在 503 期超时误判"启动失败"（一次性 resolve，
// 之后即使 200 也被 chat.message 永久拦截直到重启 opencode）。45s = 23s + 余量。
