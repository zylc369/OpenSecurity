import {
  readFileSync,
  writeFileSync,
  existsSync,
  unlinkSync,
  mkdirSync,
  statSync,
} from "fs";
import { join, dirname } from "path";
import { homedir } from "os";
import { execSync } from "child_process";
import { fileURLToPath } from "url";
import type { Plugin } from "@opencode-ai/plugin";
import type { OpencodeClient } from "@opencode-ai/sdk";

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
const OPENCODE_ROOT = dirname(PLUGIN_DIR);

const DATA_DIR = join(homedir(), "bw-security-analysis");
const CONFIG_FILE = join(DATA_DIR, "config.json");
const ENV_CACHE_FILE = join(DATA_DIR, "env_cache.json");
const WORKSPACE_DIR = join(DATA_DIR, "workspace");
const TASK_SESSIONS_DIR = join(WORKSPACE_DIR, ".task_sessions");
const LOGS_DIR = join(DATA_DIR, "logs");
const DEFAULT_LOG = join(LOGS_DIR, "plugin_debug.log");
const MAX_LOG_SIZE = 5 * 1024 * 1024;
const KEEP_SIZE = 2 * 1024 * 1024;
const ENV_INJECTION_FREQUENCY = 5; // 每 N 次请求注入一次环境信息

const AGENT_BINARY_ANALYSIS = "binary-analysis";
const AGENT_MOBILE_ANALYSIS = "mobile-analysis";
const AGENT_WEB_ANALYSIS = "web-analysis";
const AGENT_AI_SECURITY_ANALYSIS = "ai-security-analysis";
const AGENT_SECURITY_ANALYSIS_EVOLVE = "security-analysis-evolve";
const AGENT_SECURITY_COORDINATOR = "security-coordinator";

const PRIMARY_AGENTS = [
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_AI_SECURITY_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
];

const AGENT_SCRIPT_DIRS: Record<string, string> = {};
for (const name of PRIMARY_AGENTS) {
  AGENT_SCRIPT_DIRS[name] = join(OPENCODE_ROOT, name);
}

const SHARED_DIR = join(OPENCODE_ROOT, AGENT_BINARY_ANALYSIS);

// ─── 分析持续性恢复 ──────────────────────────────────────────────
//
// 当安全分析 Agent 的主 session 空闲时，自动发送恢复消息。
// 避免 LLM 因上下文耗尽或自身判断而停止生成后，需要用户手动继续。
//
// 恢复条件:
//   1. session.idle 事件触发
//   2. 该 session 的 agentName 属于 PRIMARY_AGENTS（排除子 session）
//   3. agentName 不是 security-analysis-evolve（进化 Agent 不做分析工作）
//   4. 未超过最大持续时间（默认 6 小时，可通过 .persistence.json 文件指定）
//   5. 最后一条 assistant 消息未被用户手动中断（error.name !== ABORTED_ERROR_NAME）
//
// 持续性状态文件 ($TASK_DIR/.persistence.json):
//   {
//     "max_duration_hours": 6,      // 最大持续时间（小时），默认 6
//     "resume_count": 3,            // 已发送恢复消息的次数
//     "last_resume_at": "2026-06-13T10:30:00.000Z"  // 最近一次恢复时间
//   }

const MAX_DURATION_DEFAULT = 6 * 60 * 60 * 1000; // 6 小时，单位毫秒
const MAX_RESUMES = 50; // 最大恢复次数，防止分析完成后无限循环恢复
const PERSISTENCE_FILE = ".persistence.json";
const ABORTED_ERROR_NAME = "MessageAbortedError";
const RESUME_PROMPT =
  "你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论，并在最后单独一行输出 >>>COMPLETE<<< 。如果尚未完成，请自主继续分析，不要停下来向用户提问。";
const COMPLETION_MARKER = ">>>COMPLETE<<<";

// ─── 分析持续性恢复：状态文件读写 ──────────────────────────────

interface PersistenceData {
  max_duration_hours: number;
  resume_count: number;
  last_resume_at: string | null;
}

function readPersistenceData(sessionID: string): PersistenceData | null {
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) return null;
  const filePath = join(taskDir, PERSISTENCE_FILE);
  try {
    const content = readFileSync(filePath, "utf-8").trim();
    const data = JSON.parse(content) as PersistenceData;
    if (
      typeof data.max_duration_hours === "number" &&
      data.max_duration_hours > 0 &&
      data.max_duration_hours <= 24
    ) {
      return {
        max_duration_hours: data.max_duration_hours,
        resume_count: typeof data.resume_count === "number" ? data.resume_count : 0,
        last_resume_at: data.last_resume_at ?? null,
      };
    }
    debugLog(
      `readPersistenceData: invalid max_duration_hours in ${filePath}, using default`,
      sessionID,
    );
  } catch {
    // 文件不存在或 JSON 解析失败，使用默认值
  }
  return null;
}

function getMaxDuration(sessionID: string): number {
  const data = readPersistenceData(sessionID);
  if (data) {
    return Math.floor(data.max_duration_hours * 3600 * 1000);
  }
  return MAX_DURATION_DEFAULT;
}

// 检查最后一条 assistant 消息是否被用户手动中断
// session.idle 无法区分 LLM 自然结束和用户手动停止，两者都会触发 idle。
// 但手动中断的 assistant 消息会带有 error.name = "MessageAbortedError"。
// 通过 client.session.messages API 获取消息列表并检查最后一条 assistant 消息。
async function checkLastMessageAborted(sessionID: string): Promise<boolean> {
  if (!opencodeClient) return false;
  try {
    const response = await opencodeClient.session.messages({
      path: { id: sessionID },
    });
    if (response.error || !response.data) return false;
    const messages = response.data;
    if (!Array.isArray(messages) || messages.length === 0) return false;
    // 找最后一条 assistant 消息
    const lastAssistant = [...messages]
      .reverse()
      .find(
        (m: { info?: { role?: string } }) =>
          m?.info?.role === "assistant",
      );
    if (!lastAssistant) return false;
    // 检查 error.name 是否为 MessageAbortedError
    // OpenCode 的 prompt.ts 中 finalizeInterruptedAssistant 会设置:
    //   msg.error = MessageV2.fromError(new DOMException("Aborted", "AbortError"), { aborted: true })
    // Assistant schema 中 error 字段在 info 上（与 role 同级）
    const info = (lastAssistant as { info?: { error?: { name?: string } } }).info;
    return info?.error?.name === ABORTED_ERROR_NAME;
  } catch (e) {
    debugLog(
      `checkLastMessageAborted: 查询异常 sessionID=${sessionID} error=${e}`,
      sessionID,
    );
    return false;
  }
}

// 获取最后一条 assistant 消息的文本内容（用于检测完成标记）
async function getLastAssistantText(sessionID: string): Promise<string | null> {
  if (!opencodeClient) return null;
  try {
    const response = await opencodeClient.session.messages({
      path: { id: sessionID },
    });
    if (response.error || !response.data) return null;
    const messages = response.data;
    if (!Array.isArray(messages) || messages.length === 0) return null;
    const lastAssistant = [...messages]
      .reverse()
      .find(
        (m: { info?: { role?: string } }) =>
          m?.info?.role === "assistant",
      );
    if (!lastAssistant) return null;
    const parts = (
      lastAssistant as {
        parts?: Array<{ type?: string; text?: string }>;
      }
    ).parts;
    if (!parts || !Array.isArray(parts)) return null;
    return parts
      .filter((p) => p.type === "text" && p.text)
      .map((p) => p.text!)
      .join("\n");
  } catch (e) {
    debugLog(
      `getLastAssistantText: 查询异常 sessionID=${sessionID} error=${e}`,
      sessionID,
    );
    return null;
  }
}

function recordResumeAttempt(sessionID: string): void {
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) {
    debugLog(
      `recordResumeAttempt: no taskDir for sessionID=${sessionID}`,
      sessionID,
    );
    return;
  }
  const filePath = join(taskDir, PERSISTENCE_FILE);
  const existing = readPersistenceData(sessionID);
  const data: PersistenceData = {
    max_duration_hours: existing?.max_duration_hours ?? MAX_DURATION_DEFAULT / (3600 * 1000),
    resume_count: (existing?.resume_count ?? 0) + 1,
    last_resume_at: new Date().toISOString(),
  };
  try {
    writeFileSync(filePath, JSON.stringify(data, null, 2));
    debugLog(
      `recordResumeAttempt: written resume_count=${data.resume_count} to ${filePath}`,
      sessionID,
    );
  } catch (e) {
    debugLog(
      `recordResumeAttempt: failed to write ${filePath} error=${e}`,
      sessionID,
    );
  }
}

function getLogFilePath(agentName: string | undefined): string {
  if (agentName && PRIMARY_AGENTS.includes(agentName)) {
    return join(LOGS_DIR, `${agentName}.log`);
  }
  return DEFAULT_LOG;
}

function trimLogFile(logFile: string): void {
  try {
    if (existsSync(logFile) && statSync(logFile).size > MAX_LOG_SIZE) {
      const content = readFileSync(logFile, "utf-8");
      const keep = content.slice(-KEEP_SIZE);
      const firstNewline = keep.indexOf("\n");
      writeFileSync(
        logFile,
        firstNewline >= 0 ? keep.slice(firstNewline + 1) : keep,
      );
    }
  } catch {}
}

function writeLog(logFile: string, msg: string): void {
  try {
    mkdirSync(dirname(logFile), { recursive: true });
    trimLogFile(logFile);
    const now = new Date();
    const ts =
      now.toLocaleString("zh-CN", { hour12: false }) +
      `.${String(now.getMilliseconds()).padStart(3, "0")}`;
    writeFileSync(logFile, `[${ts}] ${msg}\n`, { flag: "a" });
  } catch {}
}

interface ToolConfig {
  path: string;
  agents?: string[];
  required?: boolean;
  version_cmd?: string[];
  description?: string;
}

interface ConfigData {
  ida_path?: string;
  tools?: Record<string, ToolConfig>;
}

interface EnvData {
  data?: {
    venv_python?: string;
    compiler?: {
      available: boolean;
      type: string;
      path: string;
      vcvarsall?: string;
    };
    packages?: Record<string, { available: boolean; version: string }>;
    tools?: Record<string, { available: boolean; version: string | null }>;
  };
}

interface TaskSessionMapping {
  task_dir: string;
}

// getTaskDir 内存缓存（避免每次 debugLog 都读文件系统）
const taskDirCache = new Map<string, string | null>();

function readJsonSafe<T>(filePath: string, sessionID?: string): T | null {
  try {
    if (existsSync(filePath)) {
      return JSON.parse(readFileSync(filePath, "utf-8")) as T;
    }
  } catch (e) {
    debugLog(`readJsonSafe failed: ${filePath} error=${e}`, sessionID);
  }
  return null;
}

function getTaskDir(sessionID: string): string | null {
  // 先查缓存（只缓存有值的结果，null 不缓存——映射文件可能后续被创建）
  const cached = taskDirCache.get(sessionID);
  if (cached) return cached;

  try {
    const filePath = join(TASK_SESSIONS_DIR, `${sessionID}.json`);
    const data = readJsonSafe<TaskSessionMapping>(filePath);
    const result = data?.task_dir;
    if (result) {
      taskDirCache.set(sessionID, result);
      return result;
    }
    debugLog(`getTaskDir: 未找到映射 sessionID=${sessionID} filePath=${filePath}`, sessionID);
    return null;
  } catch (e) {
    debugLog(`getTaskDir: 读取异常 sessionID=${sessionID} error=${e}`, sessionID);
    return null;
  }
}

function removeTaskSession(sessionID: string): void {
  taskDirCache.delete(sessionID);
  try {
    const filePath = join(TASK_SESSIONS_DIR, `${sessionID}.json`);
    if (existsSync(filePath)) {
      debugLog(`removeTaskSession: deleting ${filePath}`, sessionID);
      unlinkSync(filePath);
    }
  } catch (e) {
    debugLog(
      `removeTaskSession failed: sessionID=${sessionID} error=${e}`,
      sessionID,
    );
  }
}

function getToolsForAgent(
  agentName: string,
  config: ConfigData,
): Array<ToolConfig & { name: string }> {
  if (!config.tools) return [];
  return Object.entries(config.tools)
    .filter(([, tool]) => !tool.agents || tool.agents.includes(agentName))
    .map(([name, tool]) => ({ name, ...tool }));
}

// ─── Python 虚拟环境管理 ──────────────────────────────────────────────
//
// Plugin 启动时确保 ~/bw-security-analysis/.venv 存在且可用。
// $PYTHON_CMD 指向 venv Python 绝对路径，所有 agent 统一使用。
// venv 创建需要系统 Python（通过 findSystemPython 检测）。
// 整个流程在 Plugin 加载时执行一次，失败则抛异常终止加载。

const VENV_DIR = join(DATA_DIR, ".venv");

// venv 内 Python 可能的路径（覆盖所有平台，按常见度排序）
const VENV_PYTHON_CANDIDATES = [
  join(VENV_DIR, "Scripts", "python.exe"), // Windows 标准位置
  join(VENV_DIR, "bin", "python"), // Linux/macOS 标准位置
  join(VENV_DIR, "Scripts", "python3.exe"), // Windows（python3 别名）
  join(VENV_DIR, "bin", "python3"), // Linux/macOS（python3）
];

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
const PYTHON_CMD = ensureVenvPython();

// 根据实际 agent 名获取脚本目录；子 agent（如 "general"）不在映射表中时，
// 回退到 agentName 对应的目录；均无映射则返回 undefined
function getScriptDir(
  agentName: string | undefined,
  fallbackAgent?: string,
): string | undefined {
  return (
    AGENT_SCRIPT_DIRS[agentName || ""] ||
    AGENT_SCRIPT_DIRS[fallbackAgent || ""] ||
    undefined
  );
}

const AGENTS_DIR = join(OPENCODE_ROOT, "agents");
const AGENTS_RULES_DIR = join(OPENCODE_ROOT, "agents-rules");

// ─── 占位符展开 ──────────────────────────────────────────────────────
//
// Agent .md 文件中可以用 {{buwai-rule:片段名}} 引用 agents-rules/ 下的通用片段。
// Plugin 在 system.transform hook 中展开占位符，LLM 收到的是完整 prompt。
//
// 缓存策略：mtime 检测（statSync + mtimeMs 对比），文件改动后下次调用即生效。
// 依赖顺序：session 检查 → 占位符展开（每次）→ 环境信息注入（每次）

interface SnippetCacheEntry {
  content: string | null;
  mtime: number;
}
const snippetCache = new Map<string, SnippetCacheEntry>();

interface FrontmatterCacheEntry {
  result: boolean;
  mtime: number;
}
const frontmatterCache = new Map<string, FrontmatterCacheEntry>();

// 解析 YAML frontmatter（仅扁平 key-value，不处理嵌套结构）
// 示例输入：---\nmode: primary\nbuwai-extension-id: binary-analysis\n---\n
// 返回：{ mode: "primary", "buwai-extension-id": "binary-analysis" }
function parseFrontmatter(content: string): Record<string, string> {
  // 匹配 --- 开头和结尾之间的内容（兼容 \r\n 和 \n）
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!match) return {};
  const result: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    // 只匹配顶层 key: value（缩进行如 "  external_directory:" 被跳过）
    const kv = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/);
    if (kv) result[kv[1]] = kv[2].trim();
  }
  return result;
}

// 检查 agent .md 是否声明了 buwai-extension-id（有此字段才做占位符展开）
// 结果按 agentFile 路径缓存，mtime 变了才重新读取
function hasBuwaiExtensionId(agentFile: string): boolean {
  try {
    const stat = statSync(agentFile);
    const cached = frontmatterCache.get(agentFile);
    if (cached && cached.mtime === stat.mtimeMs) return cached.result;
    const content = readFileSync(agentFile, "utf-8");
    const fm = parseFrontmatter(content);
    const result = "buwai-extension-id" in fm;
    frontmatterCache.set(agentFile, { result, mtime: stat.mtimeMs });
    return result;
  } catch {
    return false;
  }
}

// 加载 agents-rules/<name>.md 片段文件，带 mtime 缓存
// 返回 null 表示文件不存在（调用方保留占位符原文）
function loadSnippet(name: string): string | null {
  const filePath = join(AGENTS_RULES_DIR, `${name}.md`);
  try {
    const stat = statSync(filePath);
    const cached = snippetCache.get(name);
    if (cached && cached.mtime === stat.mtimeMs) return cached.content;
    const content = readFileSync(filePath, "utf-8").trim();
    snippetCache.set(name, { content, mtime: stat.mtimeMs });
    return content;
  } catch {
    debugLog(`Snippet not found: ${filePath}`);
    return null;
  }
}

function getCompactionReminder(agentName: string | undefined): string {
  if (agentName) {
    const promptPath = join(AGENTS_DIR, `${agentName}.md`);
    const scriptsDir = getScriptDir(agentName);
    const restoreVars = scriptsDir
      ? `$OPENCODE_ROOT、$AGENT_DIR、$SHARED_DIR、$TASK_DIR`
      : `$OPENCODE_ROOT、$TASK_DIR`;
    return `## 压缩恢复指令（压缩时必须保留）

上下文刚被压缩。继续分析前必须：
1. 重新读取 agent prompt（${promptPath}）获取完整规则
2. 恢复 ${restoreVars} 等关键变量（见 agent prompt 的"变量丢失自愈"章节）`;
  }
  return `## 压缩恢复指令（压缩时必须保留）

上下文刚被压缩。继续分析前必须：
1. 请告知当前使用的是哪个 Agent（如 ${AGENT_BINARY_ANALYSIS}、${AGENT_MOBILE_ANALYSIS}、${AGENT_WEB_ANALYSIS}）
2. 根据 Agent 名读取 ${AGENTS_DIR}/<agent-name>.md
3. 恢复 $OPENCODE_ROOT、$AGENT_DIR、$SHARED_DIR、$TASK_DIR 等关键变量`;
}

function getCompactionContext(agentName: string | undefined): string {
  let context = `## 分析状态（压缩时必须保留）

当总结此会话时，如果包含分析相关内容，你必须保留以下信息：

### 1. 分析目标
- 目标文件路径和类型
- 文件架构

### 2. 已完成的分析
- 已识别的关键函数/类及其地址/名称和用途
- 已发现的分析结论
- 当前分析阶段和待完成步骤
- 失败记录（已尝试方向，避免重复）
- 验证结果和置信度
- 用户显式约束`;

  if (agentName === AGENT_BINARY_ANALYSIS) {
    context += `

### IDA 分析状态
- IDA 数据库路径
- 已执行的 idat 查询和结果摘要`;
  }

  if (agentName === AGENT_MOBILE_ANALYSIS) {
    context += `

### 移动端分析状态
- 已解包路径
- 已识别的 native 库列表（.so / .dylib）
- 当前设备连接状态（device_id、frida_server 运行/端口）`;
  }

  if (agentName === AGENT_WEB_ANALYSIS) {
    context += `

### Web 分析状态
- 目标 URL 和/或源码目录路径
- 已识别的技术栈和框架版本
- 已发现的攻击面和攻击链进度
- 已测试的攻击方向和结果`;
  }

  if (agentName === AGENT_SECURITY_COORDINATOR) {
    context += `

### Coordinator 编排状态
- 父任务目录路径
- 已完成的子任务列表（Agent 名、关键发现摘要）
- 待执行的子任务列表（Agent 名、任务描述）
- 当前执行阶段（分析/分发/聚合）`;
  }

  return context;
}

async function buildEnvSection(
  agentName: string | undefined,
  config: ConfigData,
  envInfo: EnvData["data"],
  sessionID?: string,
): Promise<string> {
  try {
    const fallbackAgent = getAgentName(sessionID);
    const scriptsDir = getScriptDir(agentName, fallbackAgent);

    let envSection = `\n## 全局环境和目录位置信息\n**Agent需要这些信息，它们非常关键。如果Agent忽略这些信息，Agent的运行将不符合预期！**\n`;
    envSection += `- 项目的OpenCode配置根目录 ($OPENCODE_ROOT)路径，即项目的\`.opencode\`路径，它里面包含项目的所有Agents、Plugins、知识库、工具、脚本: ${OPENCODE_ROOT}\n`;

    if (scriptsDir) {
      envSection += `- Agent 目录 ($AGENT_DIR)路径，它是当前Agent所在目录，里面有专用于当前Agent的知识、工具和脚本: ${scriptsDir}\n`;
    }

    envSection += `- 共享目录 ($SHARED_DIR)路径，它里面有共享的通用的知识、工具和脚本: ${SHARED_DIR}\n`;
    const idaPath = config.ida_path || "未配置";
    if (idaPath !== "未配置") {
      const idatPath = join(idaPath, "idat");
      envSection += `- IDA Pro: ${idaPath}\n`;
      envSection += `- IDAT ($IDAT): ${idatPath}\n`;
    } else {
      envSection += `- IDA Pro: 未配置\n`;
    }
    envSection += `- Python ($PYTHON_CMD): ${PYTHON_CMD}\n`;

    if (envInfo) {
      const compiler = envInfo.compiler;
      if (compiler?.available) {
        envSection += `- 编译器: ${compiler.type} (${compiler.path})\n`;
        if (compiler.vcvarsall) {
          envSection += `- vcvarsall: ${compiler.vcvarsall}\n`;
        }
      } else {
        envSection += `- 编译器: 未检测到\n`;
      }
      if (envInfo.packages) {
        const pkgs = Object.entries(envInfo.packages)
          .filter(([, v]) => v.available)
          .map(([k, v]) => `${k}@${v.version}`)
          .join(", ");
        envSection += `- Python 包: ${pkgs}\n`;
      }
    }

    // 注入外部工具（按 agent 过滤；agent 未知时不过滤，注入全部）
    if (config.tools) {
      const tools = agentName
        ? getToolsForAgent(agentName, config)
        : Object.entries(config.tools).map(([name, tool]) => ({
            name,
            ...tool,
          }));
      const envTools = envInfo?.tools || {};
      for (const tool of tools) {
        const toolStatus = envTools[tool.name];
        if (toolStatus?.available) {
          const ver = toolStatus.version || "可用";
          envSection += `- ${tool.description || tool.name}: ${tool.path} (${ver})\n`;
        }
      }
    }

    return envSection;
  } catch (e) {
    debugLog(
      `全局环境和目录位置信息加载发生异常, sessionID=${sessionID} error=${e}`,
      sessionID,
    );
    await abortSession(
      sessionID ?? "",
      `全局环境和目录位置信息加载发生异常: ${e}`,
    );
    return "";
  }
}

// ─── session 管理 ──────────────────────────────────────────────────────
//
// 数据结构
// - createdAt:   session 初始化时间（ensureSession 设置）
// - agentName:   当前实际使用的 agent 名（chat.message 设置，如 "binary-analysis"）
//
// 恢复策略
// 插件重启后内存 Map 清空，OpenCode 不会为已有 session 重发 session.created 事件。
// ensureSession 通过 client API 按需查询 session info（含 parentID），
// 递归解析父链恢复 agentName。每个 session 在每个进程生命周期内最多触发
// 一次 API 调用，后续访问纯内存读取，零开销。
interface SessionData {
  createdAt: number;
  agentName?: string;
  systemTransformCount: number;
}

const sessions = new Map<string, SessionData>();
// 缓存已确认非 PRIMARY_AGENT 的 session，避免反复调 session.get API
const nonPrimarySessions = new Set<string>();

// OpenCode client，在 Plugin 函数中初始化
let opencodeClient: OpencodeClient | null = null;

// 并发去重：同一 sessionID 的并发 ensureSession 调用共享同一个 Promise
const pendingEnsures = new Map<string, Promise<SessionData | undefined>>();

function getAgentName(sessionID?: string): string | undefined {
  return sessionID ? sessions.get(sessionID)?.agentName : undefined;
}

function debugLog(msg: string, sessionID?: string): void {
  // 优先写到任务目录下的 logs/plugin.log，没有任务目录则走集中日志
  const taskDir = sessionID ? getTaskDir(sessionID) : null;
  if (taskDir) {
    writeLog(join(taskDir, "logs", "plugin.log"), msg);
  } else {
    const logFile = getLogFilePath(getAgentName(sessionID));
    writeLog(logFile, msg);
  }
}

/**
 * 终止会话：先 showToast 显示原因，再 abort 中断执行。
 * 用于 shell.env 等 hook 检测到严重错误时调用。
 */
async function abortSession(sessionID: string, reason: string): Promise<void> {
  debugLog(`abortSession: sessionID=${sessionID} reason=${reason}`, sessionID);
  if (!opencodeClient) {
    debugLog(`abortSession: opencodeClient 未初始化，无法终止`, sessionID);
    return;
  }
  try {
    await opencodeClient.tui.showToast({
      body: {
        title: "致命错误",
        message: reason,
        variant: "error",
        duration: 15000,
      },
    });
  } catch (e) {
    debugLog(`abortSession: showToast 失败 error=${e}`, sessionID);
  }
  if (!sessionID) {
    debugLog(`abortSession: 无 sessionID，跳过 abort（仅 showToast）`);
    return;
  }
  try {
    await opencodeClient.session.abort({ path: { id: sessionID } });
    debugLog(`abortSession: 已终止 sessionID=${sessionID}`, sessionID);
  } catch (e) {
    debugLog(`abortSession: abort 失败 sessionID=${sessionID} error=${e}`, sessionID);
  }
}

/**
 * - 已在 Map 中 → 直接返回（零开销）
 * - 不在 Map 中 → 调用 OpenCode client API 查询 session info，
 *   递归解析父链继承 agentName，写入 Map 后返回。
 * - 同一 session 的并发调用共享同一个 Promise，避免重复 API 请求。
 */
async function ensureSession(
  sessionID: string,
): Promise<SessionData | undefined> {
  const existing = sessions.get(sessionID);
  if (existing) return existing;

  const pending = pendingEnsures.get(sessionID);
  if (pending) return pending;

  const promise = doEnsureSession(sessionID);
  pendingEnsures.set(sessionID, promise);
  try {
    return await promise;
  } finally {
    pendingEnsures.delete(sessionID);
  }
}

async function doEnsureSession(
  sessionID: string,
): Promise<SessionData | undefined> {
  if (!opencodeClient) {
    debugLog(`doEnsureSession: client 未初始化, sessionID=${sessionID}`);
    return undefined;
  }

  try {
    const response = await opencodeClient.session.get({
      path: { id: sessionID },
    });

    debugLog(
      `doEnsureSession: client 响应 response=${JSON.stringify(response)}`,
      sessionID,
    );

    if (response.error) {
      debugLog(
        `doEnsureSession: API 错误 sessionID=${sessionID} error=${JSON.stringify(response.error)}`,
      );
      return undefined;
    }
    const sessionInfo = response.data;
    if (!sessionInfo) {
      debugLog(`doEnsureSession: API 返回空数据 sessionID=${sessionID}`);
      return undefined;
    }

    const agentName = (sessionInfo as { agent?: string })?.agent;

    const session: SessionData = {
      createdAt: Date.now(),
      agentName,
      systemTransformCount: 0,
    };
    sessions.set(sessionID, session);
    debugLog(
      `doEnsureSession: 恢复 sessionID=${sessionID} agentName=${agentName || "无"} parentID=${sessionInfo.parentID || "无"}`,
      sessionID,
    );
    return session;
  } catch (e) {
    debugLog(
      `doEnsureSession: 异常 sessionID=${sessionID} error=${e}`,
      sessionID,
    );
    return undefined;
  }
}

/**
 * 统一的 hook 入口守卫：
 * 1. 优先从 Map 中查找 session（chat.message 已注册）
 * 2. Map miss 时，通过 session.get API 查询当前 session 的 agent
 *    - 如果是 PRIMARY_AGENT，恢复到 Map 中并返回
 *    - 否则跳过
 *
 * 修复：agent 中途切换后 chat.message 可能不重新触发，
 * 导致 Map 中无数据但实际 agent 已变为 PRIMARY_AGENT。
 */
async function requireSessionWithPrimary(
  hookName: string,
  sessionID?: string,
): Promise<SessionData | undefined> {
  if (!sessionID) {
    debugLog(`${hookName}: 跳过 — 无 sessionID`);
    return undefined;
  }

  const existing = sessions.get(sessionID);
  if (existing) return existing;

  // 已确认非 PRIMARY_AGENT，跳过（避免重复 API 调用）
  if (nonPrimarySessions.has(sessionID)) {
    debugLog(
      `${hookName}: 跳过 — 已缓存为非 PRIMARY sessionID=${sessionID}`,
      sessionID,
    );
    return undefined;
  }

  // Map miss — 尝试从 API 恢复（覆盖 agent 切换场景）
  if (!opencodeClient) {
    debugLog(`${hookName}: Map miss → opencodeClient 未初始化，无法恢复`);
    return undefined;
  }
  try {
    const response = await opencodeClient.session.get({
      path: { id: sessionID },
    });
    const sessionInfo = response?.data;
    const agentName = (sessionInfo as { agent?: string } | undefined)?.agent;

    if (agentName && PRIMARY_AGENTS.includes(agentName)) {
      debugLog(
        `${hookName}: Map miss → API 恢复成功 sessionID=${sessionID} agent=${agentName}`,
        sessionID,
      );
      const session: SessionData = {
        createdAt: Date.now(),
        agentName,
        systemTransformCount: 0,
      };
      sessions.set(sessionID, session);
      return session;
    }

    // 缓存为非 PRIMARY，后续直接跳过
    nonPrimarySessions.add(sessionID);
    debugLog(
      `${hookName}: Map miss → API 返回非 PRIMARY agent=${agentName || "无"} sessionID=${sessionID}`,
      sessionID,
    );
  } catch (e) {
    debugLog(
      `${hookName}: Map miss → API 查询异常 sessionID=${sessionID} error=${e}`,
      sessionID,
    );
  }

  return undefined;
}

// ─── 时间线日志 ──────────────────────────────────────────────────────
//
// 记录工具执行和 session 事件的时间线，供事后复盘分析。
// 内存 buffer → 文件 flush 策略，避免每次事件都写磁盘。

type TimelineEventType =
  | "tool.before"
  | "tool.after"
  | "session.status"
  | "session.error"
  | "heartbeat";

interface TimelineEvent {
  timestamp: number;
  type: TimelineEventType;
  tool?: string;
  detail?: string;
  duration?: number;
}

const MAX_TIMELINE_BUFFER = 500;
const timelineBuffers = new Map<string, TimelineEvent[]>();

// 工具开始执行时间戳（tool.execute.before → tool.execute.after 配对计算耗时）
const toolStartTimes = new Map<string, number>();

function formatTimelineEntry(event: TimelineEvent): string {
  const date = new Date(event.timestamp);
  const ts = date.toLocaleString("zh-CN", { hour12: false });
  const obj: Record<string, unknown> = {
    ts: event.timestamp,
    type: event.type,
  };
  if (event.tool) obj.tool = event.tool;
  if (event.detail) obj.detail = event.detail;
  if (event.duration !== undefined) obj.duration = event.duration;
  return `[${ts}] ${JSON.stringify(obj)}`;
}

function flushTimeline(sessionID: string): void {
  const buffer = timelineBuffers.get(sessionID);
  if (!buffer || buffer.length === 0) return;

  const taskDir = getTaskDir(sessionID);
  const logFile = taskDir
    ? join(taskDir, "logs", "timeline.log")
    : join(LOGS_DIR, `timeline-${sessionID}.log`);

  try {
    const lines = buffer.map(formatTimelineEntry).join("\n") + "\n";
    mkdirSync(dirname(logFile), { recursive: true });
    writeFileSync(logFile, lines, { flag: "a" });
  } catch (e) {
    debugLog(`flushTimeline failed: ${e}`, sessionID);
  }

  buffer.length = 0;
}

function recordTimeline(
  sessionID: string,
  event: TimelineEvent,
  flush = false,
): void {
  let buffer = timelineBuffers.get(sessionID);
  if (!buffer) {
    buffer = [];
    timelineBuffers.set(sessionID, buffer);
  }
  buffer.push(event);

  // buffer 满时自动 flush
  if (buffer.length >= MAX_TIMELINE_BUFFER || flush) {
    flushTimeline(sessionID);
  }
}

export const SecurityAnalysisPlugin: Plugin = async (input) => {
  const { client, directory } = input;
  opencodeClient = client;

  debugLog(`=== SecurityAnalysisPlugin loaded ===`);
  debugLog(`  PLUGIN_DIR: ${PLUGIN_DIR}`);
  debugLog(`  OPENCODE_ROOT: ${OPENCODE_ROOT}`);
  debugLog(`  DATA_DIR: ${DATA_DIR}`);
  debugLog(`  CONFIG_FILE: ${CONFIG_FILE}`);
  debugLog(`  ENV_CACHE_FILE: ${ENV_CACHE_FILE}`);
  debugLog(`  WORKSPACE_DIR: ${WORKSPACE_DIR}`);
  debugLog(`  TASK_SESSIONS_DIR: ${TASK_SESSIONS_DIR}`);
  debugLog(`  LOGS_DIR: ${LOGS_DIR}`);
  debugLog(`  DEFAULT_LOG: ${DEFAULT_LOG}`);
  debugLog(`  directory param: ${directory}`);
  debugLog(`  config exists: ${existsSync(CONFIG_FILE)}`);
  debugLog(`  env_cache exists: ${existsSync(ENV_CACHE_FILE)}`);
  debugLog(`  opencodeClient: ${!!opencodeClient}`);
  debugLog(`  PYTHON_CMD: ${PYTHON_CMD}`);

  // 写心跳文件，供 agent 检测 Plugin 是否正常加载
  const heartbeatFile = join(DATA_DIR, ".plugin-heartbeat");
  try {
    const heartbeat = {
      pid: process.pid,
      loadedAt: new Date().toISOString(),
      version: "1.0.0",
    };
    writeFileSync(heartbeatFile, JSON.stringify(heartbeat, null, 2));
    debugLog(`  心跳文件已写入: ${heartbeatFile}`);
  } catch (e) {
    debugLog(`  心跳文件写入失败: ${e}`);
  }

  return {
    tool: {},

    // 用户发送消息时触发（awaited，宿主等待完成）
    // 职责：记录 agentName
    // 注意：chat.message 是唯一能直接从 input.agent 获取 agent 名的 hook
    //       system.transform / tool.execute.before 的 input 无 agent
    //       但 requireSessionWithPrimary 可通过 session.get API 间接获取
    "chat.message": async (input) => {
      const agent = (input as { agent?: string })?.agent;
      // DEBUG: 诊断 OpenCode hook input 结构（确认后可删除）
      debugLog(
        `DEBUG chat.message INPUT keys=${Object.keys(input || {}).join(",")} agent=${agent ?? "无"}`,
      );
      const sessionID = (input as { sessionID?: string })?.sessionID;
      if (!sessionID) {
        debugLog(`chat.message: 跳过 — 无 sessionID, agent=${agent}`);
        return;
      }

      let isValidAgent = true;
      if (!agent) {
        debugLog("chat.message: 跳过 — 无 agent", sessionID);
        isValidAgent = false;
      } else if (!PRIMARY_AGENTS.includes(agent)) {
        debugLog(
          `chat.message: 跳过 — agent=${agent} 不在 PRIMARY_AGENTS 中, sessionID=${sessionID}`,
          sessionID,
        );
        isValidAgent = false;
      }

      if (!isValidAgent) {
        sessions.delete(sessionID);
        nonPrimarySessions.add(sessionID);
        return;
      }

      // 清除非主缓存（agent 可能已切换回 PRIMARY）
      nonPrimarySessions.delete(sessionID);

      // 确保 session 存在（重启后懒恢复）
      const session = await ensureSession(sessionID);
      if (!session) return;

      session.agentName = agent;
      debugLog(
        `chat.message: sessionID=${sessionID} agent=${agent}`,
        sessionID,
      );
    },

    // 上下文压缩前触发（awaited）
    // 职责：注入环境摘要 + 分析状态保留提示 + TASK_DIR，防止压缩丢失关键信息
    "experimental.session.compacting": async (input, output) => {
      const sid = input?.sessionID;
      const session = await requireSessionWithPrimary("compacting", sid);
      if (!session) return;
      const agentName = session.agentName;
      debugLog(
        `compacting: sessionID=${sid} agent=${agentName}`,
        sid,
      );
      const config = readJsonSafe<ConfigData>(CONFIG_FILE, sid);
      const envData = readJsonSafe<EnvData>(ENV_CACHE_FILE, sid);
      const envInfo = envData?.data;

      const envSection = await buildEnvSection(agentName, config || {}, envInfo, sid);
      output.context.push(envSection);
      const compactionCtx = getCompactionContext(agentName);
      const compactionReminder = getCompactionReminder(agentName);
      output.context.push(compactionCtx);
      output.context.push(compactionReminder);

      debugLog(`=== compacting 注入内容开始 ===`, sid);
      debugLog(`sid:${sid}\n`, sid);
      debugLog(`agent:${agentName}\n`, sid);
      debugLog(`envSection:\n${envSection}\n`, sid);
      debugLog(`compactionCtx:\n${compactionCtx}\n`, sid);
      debugLog(`compactionReminder:\n${compactionReminder}`, sid);
      debugLog(`=== compacting 注入内容结束 ===`, sid);

      if (sid) {
        const taskDir = getTaskDir(sid);
        if (taskDir) {
          debugLog(`compacting: TASK_DIR recovered=${taskDir}`, sid);
          output.context.push(`## TASK_DIR（不可省略 — 压缩后必须保留）
当前会话的任务目录: ${taskDir}
所有中间输出文件在此目录下。后续分析必须使用此路径作为 $TASK_DIR。
如果用户明确要求使用新的任务目录，重新执行"任务目录约定"中的创建命令即可切换。`);
        } else {
          debugLog(`compacting: TASK_DIR not found for sessionID=${sid}`, sid);
        }

        // 分析持续性恢复：压缩后如果分析尚未完成，AI 应继续自主分析
        if (session.agentName && PRIMARY_AGENTS.includes(session.agentName) && session.agentName !== AGENT_SECURITY_ANALYSIS_EVOLVE) {
          output.context.push(`## 分析持续性（压缩后必须遵守）
这是安全分析会话，分析可能尚未完成。压缩后请继续执行未完成的分析步骤，不要输出状态报告后停下来等待用户。如果分析已完成，直接输出最终结论即可。`);
        }
      }
    },

    // 每次 LLM 请求前触发（awaited）
    // 职责：按 agent 注入环境信息到系统提示
    // 注意：output.system 每次请求都重建，不会累积
    //       前 2 次必注入（标题生成 #1 + 主聊天 #2），之后每 X 次注入一次
    "experimental.chat.system.transform": async (input, output) => {
      const sessionID = (input as { sessionID?: string })?.sessionID;
      // DEBUG: 诊断 OpenCode hook input 结构（确认后可删除）
      debugLog(
        `system.transform INPUT keys=${Object.keys(input || {}).join(",")} agent=${(input as { agent?: string })?.agent ?? "未传入"} sessionID=${sessionID}`,
        sessionID,
      );
      const session = await requireSessionWithPrimary(
        "system.transform",
        sessionID,
      );
      if (!session) {
        debugLog(
          `[WARN] system.transform: 跳过 — 无有效 session, sessionID=${sessionID}`,
          sessionID,
        );
        return;
      }

      const agentName = session.agentName;

      // 占位符展开（每次 LLM 调用都执行）
      if (agentName) {
        debugLog(
          `system.transform: 开始占位符展开 sessionID=${sessionID} agent=${agentName}`,
          sessionID,
        );
        const agentFile = join(AGENTS_DIR, `${agentName}.md`);
        if (hasBuwaiExtensionId(agentFile)) {
          debugLog(
            `system.transform: 检测到 buwai-extension-id in ${agentFile}, performing snippet expansion`,
            sessionID,
          );

          // 匹配 {{buwai-rule:片段名}} — 片段名仅允许字母数字连字符下划线
          const regex = /\{\{buwai-rule:([a-zA-Z0-9_-]+)\}\}/g;
          for (let i = 0; i < output.system.length; i++) {
            // 快速跳过不含占位符的字符串，避免无谓的正则匹配
            if (!output.system[i].includes("{{buwai-rule:")) continue;
            output.system[i] = output.system[i].replace(regex, (_, name) => {
              const snippet = loadSnippet(name);
              if (snippet === null) {
                debugLog(`Snippet not found: ${name}`, sessionID);
                return _; // 保留原始占位符文本，不删除
              }
              debugLog(
                `Expanded snippet: ${name} (${snippet.length} chars)`,
                sessionID,
              );
              return snippet;
            });
            // DEBUG: 打印替换完成后的完整内容，验证通过后注释掉
            // debugLog(`=== system[${i}] after expansion (${output.system[i].length} chars) ===\n${output.system[i]}`, sessionID);
          }
        } else {
          debugLog(
            `[ERROR] system.transform: ${agentFile} 不包含 buwai-extension-id，跳过占位符展开`,
            sessionID,
          );
        }
      }

      // 每次都注入 Plugin 完整性检查 + Agent 身份
      // 放在 output.system 最前面，确保 LLM 优先看到
      // 如果 Plugin 未加载，这段不会出现，agent 应立即停止并告知用户
      if (agentName) {
        debugLog(
          `system.transform: 注入 Plugin 完整性检查和 Agent 身份 sessionID=${sessionID} agent=${agentName}`,
          sessionID,
        );
        output.system.unshift(
          `[系统完整性] Plugin 已加载。当前 Agent: ${agentName}。如果你看不到这段标记，说明 Plugin 未加载，当前会话缺少关键功能（环境信息、工具配置、占位符展开）。请立即告知用户并停止分析。`,
        );
      } else {
        debugLog(
          `[WARN] system.transform: 无 agentName，跳过环境信息注入，但继续执行占位符展开`,
          sessionID,
        );
      }

      const config = readJsonSafe<ConfigData>(CONFIG_FILE, sessionID);
      if (!config) {
        debugLog(
          `[ERROR] system.transform: config.json 不存在（${CONFIG_FILE}），终止会话`,
          sessionID,
        );
        await abortSession(
          sessionID ?? "",
          `config.json 不存在（${CONFIG_FILE}），环境未初始化，应该由 AI 调用 detect_env.py 脚本完成初始化工作，但是 AI 没有做到这一点`,
        );
        return;
      }
      debugLog(
        `[INFO] system.transform: config.json 加载成功 sessionID=${sessionID}`,
        sessionID,
      );

      // 环境信息注入频率：
      // 前 3 次都注入（新会话 step=1 时标题生成请求先触发 #1，主聊天 #2，首次工具调用 #3，
      //   都需要拿到环境信息才能正确解析 $SHARED_DIR 等变量）
      // 之后每 X 次注入一次（节省 token）
      session.systemTransformCount++;
      const shouldInject =
        session.systemTransformCount <= 3 ||
        session.systemTransformCount % ENV_INJECTION_FREQUENCY === 0;
      // const shouldInject = true; // 目前调试阶段每次都注入，确认稳定后改回按频率注入

      if (!shouldInject) {
        debugLog(
          `[INFO] system.transform: #${session.systemTransformCount} 跳过环境信息注入 sessionID=${sessionID} agent=${agentName}`,
          sessionID,
        );
        return;
      }

      const envData = readJsonSafe<EnvData>(ENV_CACHE_FILE, sessionID);
      const envInfo = envData?.data;

      const envSection = await buildEnvSection(agentName, config, envInfo, sessionID);
      output.system.push(envSection);
      debugLog(
        `[INFO] system.transform: #${session.systemTransformCount} 注入环境信息 sessionID=${sessionID}, agent=${agentName}, length=${envSection.length}, envSection=\n${envSection}`,
        sessionID,
      );
    },

    // Bash 工具执行前通过 shell.env hook 注入环境变量（awaited）
    // 使用 shell.env 而非修改 command 字符串，避免 LLM 在上下文中看到
    // 注入的变量后模仿累积（导致 SESSION_ID='...' AGENT_NAME='...' 重复十几次）
    "shell.env": async (input, output) => {
      const sessionID = input.sessionID;
      if (!sessionID) {
        debugLog(`shell.env: 致命错误 — 无 sessionID, cwd=${input.cwd}`);
        await abortSession("", `shell.env 触发但无 sessionID (cwd=${input.cwd})，session 初始化异常`);
        return;
      }
      debugLog(`shell.env: 触发 sessionID=${sessionID} cwd=${input.cwd} callID=${input.callID ?? "无"}`, sessionID);
      const session = await requireSessionWithPrimary("shell.env", sessionID);
      if (!session) {
        debugLog(`shell.env: 跳过 — 非 PRIMARY sessionID=${sessionID}`, sessionID);
        return;
      }

      const agentName = session.agentName;
      if (!agentName) {
        debugLog(`shell.env: 致命错误 — agentName 为空 sessionID=${sessionID}`, sessionID);
        await abortSession(sessionID, `shell.env: sessionID=${sessionID} 的 agentName 为空，session 初始化异常`);
        return;
      }

      // 基础变量（全局常量，始终可注入）
      output.env.SESSION_ID = sessionID;
      output.env.AGENT_NAME = agentName;
      output.env.PYTHON_CMD = PYTHON_CMD;
      output.env.OPENCODE_ROOT = OPENCODE_ROOT;
      output.env.SHARED_DIR = SHARED_DIR;

      // AGENT_DIR（根据当前 agent 计算）
      const scriptDir = getScriptDir(agentName, session.agentName);
      if (scriptDir) {
        output.env.AGENT_DIR = scriptDir;
      }

      // TASK_DIR（从 task session mapping 读取，可能为空）
      const taskDir = getTaskDir(sessionID);
      if (taskDir) {
        output.env.TASK_DIR = taskDir;
      }

      // IDAT（从 config.json 读取 ida_path + /idat）
      const config = readJsonSafe<ConfigData>(CONFIG_FILE, sessionID);
      if (config?.ida_path) {
        output.env.IDAT = join(config.ida_path, "idat");
      }

      debugLog(
        `shell.env: 已注入` +
          ` SESSION_ID=${sessionID}` +
          ` AGENT_NAME=${agentName}` +
          ` PYTHON_CMD=${PYTHON_CMD}` +
          ` OPENCODE_ROOT=${OPENCODE_ROOT}` +
          ` AGENT_DIR=${scriptDir ?? "无"}` +
          ` SHARED_DIR=${output.env.SHARED_DIR}` +
          ` TASK_DIR=${taskDir ?? "无"}` +
          ` IDAT=${output.env.IDAT ?? "无"}`,
        sessionID,
      );
    },

    // 工具执行前触发（awaited）
    // 职责：
    //   1. config.json 不存在时拦截命令（兜底：system.transform 已 abort，此处防竞争条件）
    //   2. 记录时间线（环境变量注入已迁移到 shell.env hook）
    "tool.execute.before": async (input, output) => {
      const sid = input.sessionID;
      const session = await requireSessionWithPrimary(
        "tool.execute.before",
        sid,
      );
      if (!session) return;
      debugLog(`tool.execute.before: tool=${input.tool} sessionID=${sid}`, sid);

      // 时间线记录：工具开始执行（记录注入前的原始命令）
      const originalCmd = output.args?.command;
      recordTimeline(sid, {
        timestamp: Date.now(),
        type: "tool.before",
        tool: input.tool,
        detail:
          typeof originalCmd === "string"
            ? originalCmd.slice(0, 80)
            : undefined,
      });
      // 记录开始时间用于计算耗时
      toolStartTimes.set(input.callID, Date.now());

      if (input.tool.toLowerCase() !== "bash") return;
      const cmd = output.args?.command;
      if (typeof cmd !== "string" || !cmd) return;

      // config.json 不存在时：只放行初始化相关命令，拦截其他所有命令
      const configExists = existsSync(CONFIG_FILE);
      if (!configExists) {
        const isInitCommand =
          cmd.includes("create_task_dir") ||
          cmd.includes("detect_env") ||
          cmd.includes("config.json");
        if (!isInitCommand) {
          const isPowerShell = !!process.env.PSModulePath;
          const blockedMsg =
            `[被 Plugin 拦截] 致命错误 config.json 不存在，禁止执行分析命令。` +
            `请先运行数据初始化：$PYTHON_CMD "$SHARED_DIR/scripts/detect_env.py"`;
          output.args.command = isPowerShell
            ? `Write-Error '${blockedMsg}'; exit 1`
            : `echo '${blockedMsg}' >&2; exit 1`;
          debugLog(
            `tool.execute.before: BLOCKED (no config.json) cmd=${cmd.slice(0, 80)}`,
            sid,
          );
          return;
        }
      }
    },

    // 工具执行后触发（fire-and-forget）
    // 职责：记录工具执行结果，供 evolve agent 事后验证
    "tool.execute.after": async (input, output) => {
      const sid = input.sessionID;
      const session = await requireSessionWithPrimary(
        "tool.execute.after",
        sid,
      );
      if (!session) return;

      const toolName = input.tool;

      // 时间线记录：工具执行完成（计算耗时）
      const startTime = toolStartTimes.get(input.callID);
      toolStartTimes.delete(input.callID);
      recordTimeline(sid, {
        timestamp: Date.now(),
        type: "tool.after",
        tool: toolName,
        duration: startTime ? Date.now() - startTime : undefined,
      });

      debugLog(`tool.execute.after: tool=${toolName}`, sid);
    },

    // session 生命周期事件（fire-and-forget，宿主不等待完成）
    // 职责：清理 session 数据 + 记录生命周期日志
    // 注意：session.created 不再做 session 初始化（由 ensureSession 按需完成），
    //       但仍记录日志以保持可观测性
    event: async (input) => {
      const { event } = input;
      const props = event.properties || {};
      const sessionID: string | undefined = props.info?.id ?? props.sessionID;

      if (event.type === "session.created") {
        const parentID = (props?.info as { parentID?: string } | undefined)
          ?.parentID;
        debugLog(
          `event: session.created id=${sessionID} parentID=${parentID || "无"}`,
          sessionID,
        );
      }

      // 删除 session：统一清理所有状态 + task session 文件
      if (event.type === "session.deleted") {
        if (sessionID) {
          debugLog(`event: session.deleted id=${sessionID}`, sessionID);
          sessions.delete(sessionID);
          nonPrimarySessions.delete(sessionID);
          removeTaskSession(sessionID);
        }
      }

      // 压缩完成：仅记录日志（状态恢复由 compacting hook 在压缩前注入）
      if (event.type === "session.compacted") {
        debugLog(`event: session.compacted id=${sessionID}`, sessionID);
      }

      // session idle: 尝试恢复安全分析 + flush 时间线
      if (event.type === "session.idle" && sessionID) {
        // 时间线记录
        recordTimeline(sessionID, {
          timestamp: Date.now(),
          type: "session.status",
          detail: "session.idle",
        });
        flushTimeline(sessionID);

        // ─── 分析持续性恢复 ────────────────────────────────────
        // 安全分析 Agent 的主 session 空闲时，自动发送恢复消息。
        // 子 session（Task 工具创建，agent 为 "general" 等）不会触发恢复，
        // 被 requireSessionWithPrimary 过滤掉。
        // security-analysis-evolve Agent 不触发恢复（进化 Agent 不做分析工作）。
        // 没有 taskDir 的 session 不触发恢复（简单问答，不是正式分析任务）。
        // 用户手动中断（Escape/Ctrl+C）时不恢复 — 通过检查最后一条 assistant
        // 消息的 error.name === "MessageAbortedError" 来判断。
        try {
          const session = await requireSessionWithPrimary(
            "session.idle",
            sessionID,
          );
          if (!session) {
            debugLog(
              `session.idle: 跳过恢复 — 非 PRIMARY sessionID=${sessionID}`,
              sessionID,
            );
          } else if (
            session.agentName === AGENT_SECURITY_ANALYSIS_EVOLVE
          ) {
            debugLog(
              `session.idle: 跳过恢复 — evolve agent 不做分析工作, sessionID=${sessionID}`,
              sessionID,
            );
          } else {
            const taskDir = getTaskDir(sessionID);
            if (!taskDir) {
              debugLog(
                `session.idle: 跳过恢复 — 无 taskDir（非正式分析任务）, sessionID=${sessionID}`,
                sessionID,
              );
            } else {
              const elapsed = Date.now() - session.createdAt;
              const maxDuration = getMaxDuration(sessionID);
              if (elapsed >= maxDuration) {
                debugLog(
                  `session.idle: 跳过恢复 — 已超时 sessionID=${sessionID} elapsed=${Math.floor(elapsed / 60000)}m max=${Math.floor(maxDuration / 60000)}m`,
                  sessionID,
                );
              } else if (opencodeClient) {
                // 检查最后一条 assistant 消息是否被用户手动中断
                // session.idle 无法区分手动停止和 LLM 自然停止，
                // 但被中断的 assistant 消息会带有 error.name = "MessageAbortedError"
                const wasAborted = await checkLastMessageAborted(sessionID);
                if (wasAborted) {
                  debugLog(
                    `session.idle: 跳过恢复 — 用户手动中断, sessionID=${sessionID}`,
                    sessionID,
                  );
                } else {
                  // 检查上一轮响应是否包含完成标记（agent 显式声明分析已完成）
                  const lastText = await getLastAssistantText(sessionID);
                  if (lastText && lastText.includes(COMPLETION_MARKER)) {
                    debugLog(
                      `session.idle: 跳过恢复 — 检测到完成标记 ${COMPLETION_MARKER}, sessionID=${sessionID}`,
                      sessionID,
                    );
                  } else {
                    const persistenceData = readPersistenceData(sessionID);
                    const resumeCount = persistenceData?.resume_count ?? 0;
                    if (resumeCount >= MAX_RESUMES) {
                      debugLog(
                        `session.idle: 跳过恢复 — 已达最大恢复次数 ${MAX_RESUMES} sessionID=${sessionID}`,
                        sessionID,
                      );
                    } else {
                      debugLog(
                        `session.idle: 恢复分析 sessionID=${sessionID} agent=${session.agentName} elapsed=${Math.floor(elapsed / 60000)}m max=${Math.floor(maxDuration / 60000)}m resume_count=${resumeCount}`,
                        sessionID,
                      );
                      await opencodeClient.session.promptAsync({
                        path: { id: sessionID },
                        body: {
                          agent: session.agentName,
                          parts: [{ type: "text" as const, text: RESUME_PROMPT, synthetic: true }],
                        },
                      });
                      recordResumeAttempt(sessionID);
                      debugLog(
                        `session.idle: 恢复消息已发送 sessionID=${sessionID}`,
                        sessionID,
                      );
                    }
                  }
                }
              } else {
                  debugLog(
                    `session.idle: 跳过恢复 — opencodeClient 未初始化`,
                    sessionID,
                  );
                }
            }
          }
        } catch (e) {
          debugLog(
            `session.idle: 恢复异常 sessionID=${sessionID} error=${e}`,
            sessionID,
          );
        }
      }

      // session 状态变化和错误（非 idle）
      if (
        sessionID &&
        PRIMARY_AGENTS.includes(sessions.get(sessionID)?.agentName || "")
      ) {
        if (event.type === "session.status") {
          recordTimeline(sessionID, {
            timestamp: Date.now(),
            type: "session.status",
            detail: event.type,
          });
        }

        if (event.type === "session.error" && props.error) {
          recordTimeline(sessionID, {
            timestamp: Date.now(),
            type: "session.error",
            detail: String(props.error).slice(0, 80),
          });
        }

        // 心跳：Shell 有输出更新时记录（表示有活跃的工具执行）
        if (
          event.type === "message.part.updated" &&
          props.part?.type === "text"
        ) {
          recordTimeline(sessionID, {
            timestamp: Date.now(),
            type: "heartbeat",
          });
        }
      }
    },
  };
};
