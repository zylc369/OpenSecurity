import {
  writeFileSync,
  readFileSync,
  statSync,
  existsSync,
  openSync,
  closeSync,
} from "fs";
import { join, dirname, delimiter } from "path";
import { tmpdir } from "os";
import * as yaml from "js-yaml";
import type { Plugin } from "@opencode-ai/plugin";
import type { Event } from "@opencode-ai/sdk";
import {
  PLUGIN_DIR,
  OPENCODE_ROOT,
  DATA_DIR,
  ENV_CACHE_FILE,
  WORKSPACE_DIR,
  TASK_SESSIONS_DIR,
  LOGS_DIR,
  DEFAULT_LOG,
  ENV_INJECTION_FREQUENCY,
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  AGENT_SECURITY_COORDINATOR,
  SECURITY_AGENTS,
  AGENTS_WITH_DELEGATION_RULES,
  AGENT_SEARCHER,
  AGENT_MEMORIST,
  AGENT_SCRIPT_DIRS,
  SHARED_DIR,
  AGENTS_DIR,
} from "./lib/constants";
import { ctx } from "./lib/context";
import { SessionData, SessionDataManager } from "./lib/session-manager";
import { debugLog } from "./lib/logging";
import TaskSessionPersistence from "./lib/task-session-persistence";
import { getPythonCmd, getInstallHint } from "./lib/venv";
import {
  hasBuwaiExtensionId,
  loadSnippet,
  resolveDynamicRuleSnippetName as resolveDynamicByAgentSnippetName,
} from "./lib/snippet";
import { maybeResumeAnalysis } from "./lib/persistence";
import { recordTimeline, flushTimeline } from "./lib/timeline";
import { runDetectEnv, type EnvironmentCheckResult } from "./lib/env-check";
import { McpManager } from "./lib/mcp-manager";

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
    ida_pro?: {
      available: boolean;
      path: string | null;
      idat_path?: string | null;
    };
    tools?: Record<
      string,
      {
        available: boolean;
        version: string | null;
        description?: string;
        resolved_path?: string | null;
      }
    >;
  };
}

// 根据 agent 名获取脚本目录；不在映射表中时返回 undefined
function getScriptDir(agentName: string | undefined): string | undefined {
  return AGENT_SCRIPT_DIRS[agentName || ""] || undefined;
}

function getCompactionContext(agentName: string): string {
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
  envInfo: EnvData["data"],
  session: SessionData,
): Promise<string> {
  const sessionID = session.sessionID;
  try {
    const scriptsDir = getScriptDir(agentName);

    let envSection = `\n## 全局环境和目录位置信息\n**Agent需要这些信息，它们非常关键。如果Agent忽略这些信息，Agent的运行将不符合预期！**\n`;
    envSection += `> 括号内 \`$XXX\` 为 bash 命令中可直接引用的环境变量名（由 Plugin 注入），不要在命令里写死路径。\n`;
    envSection += `- 项目的OpenCode配置根目录 ($OPENCODE_ROOT)路径，即项目的\`.opencode\`路径，它里面包含项目的所有Agents、Plugins、知识库、工具、脚本: ${OPENCODE_ROOT}\n`;

    if (scriptsDir) {
      envSection += `- Agent 目录($AGENT_DIR)路径，它是当前Agent所在目录，里面有专用于当前Agent的知识、工具和脚本: ${scriptsDir}\n`;
    }

    const taskDir = session.getTaskDir();
    if (taskDir) {
      envSection += `- 当前会话的任务目录($TASK_DIR)路径，当前会话的所有中间输出文件在此目录下: ${taskDir}`;
    } else {
      debugLog(`全局环境和目录位置信息 - 任务目录不存在`, sessionID);
    }

    const rootTaskDir = session.getTaskDir();
    if (!session.isRootAgent && rootTaskDir) {
      envSection += `- 根会话的任务目录($ROOT_TASK_DIR)路径: ${rootTaskDir}`;
    }

    envSection += `- 共享目录($SHARED_DIR)路径，它里面有共享的通用的知识、工具和脚本: ${SHARED_DIR}\n`;

    // OPENSECURITY_FLOW_ID：事件库分区标识
    envSection += `- 事件库 Flow ID ($OPENSECURITY_FLOW_ID): ${session.flowId}。标识当前分析任务的事件库分区。主任务和它启动的所有子任务共享同一个 Flow ID——子 agent 写入的事件（工具执行记录、LLM 响应）和父 agent 写入的事件存在同一个分区里，互相可搜索。调用事件库 MCP 的搜索工具时，将此值作为 group_id 参数传入，限定搜索范围到当前任务的事件，避免搜到其他无关任务的数据。\n`;
    const idaPro = envInfo?.ida_pro;
    if (idaPro?.available && idaPro.idat_path) {
      envSection += `- IDA Pro: ${idaPro.path}\n`;
      envSection += `- IDA Pro 命令行工具 idat ($IDAT): ${idaPro.idat_path}\n`;
    } else {
      envSection += `- IDA Pro: 未配置\n`;
    }
    const pythonCmd = getPythonCmd();
    if (pythonCmd) {
      envSection += `- Python ($PYTHON_CMD): ${pythonCmd}\n`;
    }

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

    // 注入外部工具（状态来自 env_cache.json，detect_env 已按 agent 过滤写入）
    const envTools = envInfo?.tools || {};
    for (const [name, toolStatus] of Object.entries(envTools)) {
      if (toolStatus.available) {
        const ver = toolStatus.version || "可用";
        const desc = toolStatus.description || name;
        const resolved = toolStatus.resolved_path || "";
        envSection += `- ${desc}: ${resolved} (${ver})\n`;
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
// - createdAt:   session 初始化时间（SessionDataManager 创建）
// - agentName:   当前实际使用的 agent 名（chat.message 设置，如 "binary-analysis"）
//
// 恢复策略
// 插件重启后内存 Map 清空，OpenCode 不会为已有 session 重发 session.created 事件。
// SessionDataManager.createFromAPI 通过 client API 按需查询 session info（含 parentID），
// 每个 session 在每个进程生命周期内最多触发一次 API 调用，后续访问纯内存读取，零开销。
/**
 * 终止会话：先 showToast 显示原因，再 abort 中断执行。
 * 用于 shell.env 等 hook 检测到严重错误时调用。
 */
async function abortSession(sessionID: string, reason: string): Promise<void> {
  debugLog(`abortSession: sessionID=${sessionID} reason=${reason}`, sessionID);
  if (!ctx.client) {
    debugLog(`abortSession: ctx.client 未初始化，无法终止`, sessionID);
    return;
  }
  try {
    await ctx.client.tui.showToast({
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
    await ctx.client.session.abort({ path: { id: sessionID } });
    debugLog(`abortSession: 已终止 sessionID=${sessionID}`, sessionID);
  } catch (e) {
    debugLog(
      `abortSession: abort 失败 sessionID=${sessionID} error=${e}`,
      sessionID,
    );
  }
}

// 工具开始执行时间戳（tool.execute.before → tool.execute.after 配对计算耗时）
const toolStartTimes = new Map<string, number>();

// 统一环境检测入口（chat.message 调用此函数）
// 检测顺序：PythonCmd 可用性 → 环境检测（全量+预装）
async function checkEnvironment(
  agent: string,
  sessionID: string,
): Promise<EnvironmentCheckResult> {
  // 确保 .ai_env 存在（首次启动时 Plugin 自动创建，避免 detect_env 报错）
  const aiEnvPath = join(OPENCODE_ROOT, ".ai_env");
  if (!existsSync(aiEnvPath)) {
    debugLog(
      `checkEnvironment: .ai_env 不存在，自动创建 sessionID=${sessionID}`,
      sessionID,
    );
    closeSync(openSync(aiEnvPath, "w"));
  }

  const pythonCmd = getPythonCmd();
  if (!pythonCmd) {
    return { ready: false, message: getInstallHint() };
  }

  return await runDetectEnv(agent, pythonCmd, sessionID);
}

// 终止 session 并保存错误信息到 sessionData（由 session.idle 事件取出输出）。
// 不调 session.prompt——从 chat.message 内部调会死锁。
async function reportErrorAndAbort(
  client: any,
  sessionID: string,
  sessionData: SessionData | null,
  message: string,
) {
  if (sessionData) {
    sessionData.activelyTerminated = true;
    sessionData.pendingErrorMessage = message;
    debugLog(
      `reportErrorAndAbort: sessionData 更新错误信息 sessionID=${sessionID} message=${message}`,
      sessionID,
    );
  } else {
    debugLog(
      `reportErrorAndAbort: sessionData 未提供，无法保存错误信息 sessionID=${sessionID} message=${message}`,
      sessionID,
    );
  }
  try {
    await client.session.abort({ path: { id: sessionID } });
  } catch (e) {
    debugLog(
      `reportErrorAndAbort: abort 失败 sessionID=${sessionID} err=${(e as Error)?.message}`,
      sessionID,
    );
  }
}

/**
 * 构造"可委派 agent 清单"段——所有 AGENTS_WITH_DELEGATION_RULES 成员都看得到。
 *
 * 从每个成员 agent .md 的 frontmatter description 字段自动收集，
 * 避免维护两套描述。当前 agent 自己也会列出（让 LLM 知道自己是谁）。
 */
function buildDelegationBlock(
  currentAgent: string,
  sessionID: string,
): string | null {
  const lines: string[] = [
    "",
    "## 可委派的 Agent",
    "",
    '遇到不属于你专长领域的子问题，用 **Task 工具**（`subagent_type` 参数）委派给对应专家 agent。把必要的上下文传给子 agent，不要只说"帮我查一下"。',
    "",
    "| subagent_type | 擅长 |",
    "|---------------|------|",
  ];

  let agentCount = 0;

  for (const agentName of AGENTS_WITH_DELEGATION_RULES) {
    if (agentName === currentAgent) {
      continue;
    }
    const desc = readAgentDescription(agentName, sessionID);
    if (desc) {
      lines.push(`| \`${agentName}\` | ${desc} |`);
      agentCount++;
    } else {
      debugLog(
        `buildDelegationBlock: ${agentName} description 读取失败，跳过`,
        sessionID,
      );
    }
  }

  if (agentCount <= 0) {
    debugLog("没有可以委派的子agents", sessionID);
    return null;
  }

  lines.push("");
  lines.push(
    '**委派规则**：把已发现的全部相关信息传给子 agent（文件路径、URL、参数、目标），要求返回**具体的可操作结果**（flag / payload / 报告路径），不是"建议"。拿到返回结果后**整合进你的分析继续**，不要停下来等用户。',
  );

  return lines.join("\n");
}

/**
 * 从 agent .md 的 frontmatter 读 description 字段。
 * 使用 js-yaml 解析，支持完整 YAML 语法（多行/引号/嵌套）。
 * 带 mtime 缓存——文件未修改时返回缓存值。
 * 失败返回 null。
 */
const descCache = new Map<string, { desc: string | null; mtime: number }>();

function readAgentDescription(
  agentName: string,
  sessionID: string,
): string | null {
  const agentFile = join(AGENTS_DIR, `${agentName}.md`);
  try {
    const stat = statSync(agentFile);
    const cached = descCache.get(agentName);
    if (cached && cached.mtime === stat.mtimeMs) return cached.desc;

    const content = readFileSync(agentFile, "utf-8");
    const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    let desc: string | null = null;
    if (match) {
      try {
        const fm = yaml.load(match[1]) as Record<string, any> | null;
        if (fm?.description && typeof fm.description === "string") {
          desc = fm.description.trim();
        }
      } catch {
        // YAML 解析失败，desc 保持 null
      }
    }
    descCache.set(agentName, { desc, mtime: stat.mtimeMs });
    return desc;
  } catch (e) {
    debugLog(
      `readAgentDescription: 读取 ${agentName} 失败: ${(e as Error)?.message}`,
      sessionID,
    );
    return null;
  }
}

function resolveDynamicSnippetName(
  session: SessionData,
  name: string,
): string | null {
  const sessionID = session.sessionID;

  debugLog(`Expanded snippet: 开始解析动态片段名`, sessionID);

  // 找到首个安全Agent
  const firstSecurityAgentSessionData =
    ctx.sessionManager.resolveFirstSecurityAgentSessionData(
      session.parentSessionID,
    );
  const agentName = firstSecurityAgentSessionData?.agentName;

  let snippetName: string | null = null;
  if (name.startsWith("dynamic-by-agent_")) {
    snippetName = resolveDynamicByAgentSnippetName(agentName, name);
  } else {
    debugLog(`Expanded snippet: 不支持的动态片段, name=${name}`, sessionID);
  }

  debugLog(
    `Expanded snippet dynamic-by-agent: securityAgentName=${agentName}, snippetName=${snippetName}`,
    sessionID,
  );
  return snippetName;
}

function expandedSnippet(
  session: SessionData,
  output: { system: string[] },
): void {
  const sessionID = session.sessionID;
  const agentName = session.agentName;
  debugLog(
    `system.transform: 开始占位符展开 sessionID=${sessionID} agent=${agentName}`,
    sessionID,
  );
  const agentFile = join(AGENTS_DIR, `${agentName}.md`);

  if (!hasBuwaiExtensionId(agentFile)) {
    debugLog(
      `[ERROR] system.transform: ${agentFile} 不包含 buwai-extension-id，跳过占位符展开`,
      sessionID,
    );
    return;
  }

  debugLog(
    `system.transform: 检测到 buwai-extension-id in ${agentFile}, performing snippet expansion`,
    sessionID,
  );

  // {{buwai-rule:片段名}} — 统一占位符展开
  const regex = /\{\{buwai-rule:([a-zA-Z0-9_-]+)\}\}/g;
  for (let i = 0; i < output.system.length; i++) {
    if (!output.system[i].includes("{{buwai-rule:")) continue;
    output.system[i] = output.system[i].replace(regex, (_, name: string) => {
      let realName: string | null | undefined = name;
      let snippet: string | null = null;
      if (name.startsWith("dynamic-")) {
        realName = resolveDynamicSnippetName(session, name);
      }

      if (!realName) {
        debugLog(
          `Snippet name not found: name=${name},realName=${realName}`,
          sessionID,
        );
        return _;
      }

      // 静态片段：从 agents-rules/<name>.md 加载
      snippet = loadSnippet(realName);

      if (snippet === null || snippet === undefined) {
        debugLog(`Snippet not found: ${realName}`, sessionID);
        return _;
      }
      debugLog(
        `Expanded snippet: ${realName} (${snippet.length} chars)`,
        sessionID,
      );
      return snippet;
    });
  }
}

/**
 * 常驻事件写入 daemon 管理。
 *
 * daemon 是一个长驻 Python 进程（write_event_daemon.py），通过 stdin 管道接收事件。
 * 首次调用 fireAndForgetEvent 时懒启动，后续复用。
 * daemon 初始化完成后输出 "READY" 到 stdout，plugin 收到后才开始写事件。
 * opencode 退出时通过 SIGTERM 关闭 daemon。
 */
let writerDaemon: import("child_process").ChildProcess | null = null;
let daemonReady = false; // daemon 是否已输出 READY
let pendingEvents: string[] = []; // daemon 未就绪时暂存的事件（上限 50）
let exitHandlerRegistered = false;

function ensureWriterDaemon(): void {
  if (writerDaemon && !writerDaemon.killed) {
    return;
  }

  const python = getPythonCmd();
  if (!python) {
    debugLog(`ensureWriterDaemon: Python 未就绪`);
    return;
  }

  const script = join(
    OPENCODE_ROOT,
    "mcp-servers",
    "events",
    "write_event_daemon.py",
  );
  if (!existsSync(script)) {
    debugLog(`ensureWriterDaemon: daemon 脚本不存在 ${script}`);
    return;
  }

  daemonReady = false;

  try {
    const { spawn } = require("child_process");
    writerDaemon = spawn(python, [script], {
      stdio: ["pipe", "pipe", "pipe"], // stdin/stdout/stderr 全 pipe
      env: { ...process.env },
    });

    // daemon stdout → 等 READY 信号
    if (writerDaemon.stdout) {
      writerDaemon.stdout.on("data", (data: Buffer) => {
        const line = data.toString().trim();
        if (line === "READY" && !daemonReady) {
          daemonReady = true;
          debugLog(
            `ensureWriterDaemon: daemon READY，flush ${pendingEvents.length} 个暂存事件`,
          );
          // flush 暂存事件
          for (const evt of pendingEvents) {
            try {
              writerDaemon?.stdin?.write(evt);
            } catch {}
          }
          pendingEvents = [];
        }
      });
    }

    // daemon stderr → debugLog（实时管道，排查用）
    if (writerDaemon.stderr) {
      writerDaemon.stderr.on("data", (data: Buffer) => {
        const lines = data.toString().trim().split("\n");
        for (const line of lines) {
          if (line.trim()) debugLog(`writer-daemon: ${line.trim()}`);
        }
      });
    }

    writerDaemon.on("error", (e: Error) => {
      debugLog(`ensureWriterDaemon: daemon error: ${e.message}`);
      writerDaemon = null;
      daemonReady = false;
    });

    writerDaemon.on("exit", (code: number | null, signal: string | null) => {
      debugLog(
        `ensureWriterDaemon: daemon exited code=${code} signal=${signal}`,
      );
      if (code !== 0) {
        debugLog(
          `ensureWriterDaemon: daemon 异常退出，${pendingEvents.length} 个暂存事件丢失`,
        );
        pendingEvents = [];
      }
      writerDaemon = null;
      daemonReady = false;
    });

    // opencode 退出时关闭 daemon（只注册一次）
    if (!exitHandlerRegistered) {
      process.on("exit", () => {
        if (writerDaemon && !writerDaemon.killed) {
          writerDaemon.kill("SIGTERM");
        }
      });
      exitHandlerRegistered = true;
    }

    debugLog(
      `ensureWriterDaemon: daemon 已启动 pid=${writerDaemon.pid}，等待 READY...`,
    );
  } catch (e) {
    debugLog(`ensureWriterDaemon: spawn 失败: ${(e as Error)?.message}`);
    writerDaemon = null;
  }
}

/**
 * 异步写入事件到 Graphiti 事件库（fire-and-forget，不阻塞主流程）。
 * 通过 daemon stdin 管道写入 line-delimited JSON（含 timestamp 保证时序）。
 * daemon 未就绪时暂存（上限 50），就绪后自动 flush。
 * 失败只记日志，不影响 agent 运行。
 */
function fireAndForgetEvent(
  name: string,
  body: string,
  source: string,
  groupId: string,
): void {
  ensureWriterDaemon();

  const event =
    JSON.stringify({
      name,
      body,
      source,
      group_id: groupId,
      timestamp: Date.now(),
    }) + "\n";

  if (!writerDaemon || !writerDaemon.stdin || writerDaemon.stdin.destroyed) {
    debugLog(`fireAndForgetEvent: daemon 不可用，跳过 name=${name}`);
    return;
  }

  if (daemonReady) {
    // daemon 已就绪 → 直接写
    try {
      const canWrite = writerDaemon.stdin.write(event);
      if (!canWrite) {
        debugLog(`fireAndForgetEvent: stdin 背压，事件可能延迟 name=${name}`);
      }
    } catch (e) {
      debugLog(
        `fireAndForgetEvent: stdin 写入失败 name=${name} err=${(e as Error)?.message}`,
      );
    }
  } else {
    // daemon 未就绪 → 暂存（上限 50，超出丢弃最早的）
    if (pendingEvents.length >= 50) {
      pendingEvents.shift();
      debugLog(`fireAndForgetEvent: 暂存队列已满（50），丢弃最早事件`);
    }
    pendingEvents.push(event);
  }
}

/**
 * 删除指定 flowId 的所有事件库数据（fire-and-forget）。
 * 通过 write_event_daemon 的 stdin 发送 delete 消息，daemon 复用已有 Neo4j 连接执行删除。
 * daemon 不可用时只记日志，不影响 session 删除流程。
 */
function deleteGraphitiEvents(flowId: string): void {
  if (!writerDaemon || !writerDaemon.stdin || writerDaemon.stdin.destroyed) {
    debugLog(`deleteGraphitiEvents: daemon 不可用，跳过 flowId=${flowId}`);
    return;
  }

  const msg = JSON.stringify({ action: "delete", group_id: flowId }) + "\n";
  try {
    const canWrite = writerDaemon.stdin.write(msg);
    if (canWrite) {
      debugLog(`deleteGraphitiEvents: 已发送 delete flowId=${flowId}`);
    } else {
      debugLog(
        `deleteGraphitiEvents: stdin 背压，delete 可能延迟 flowId=${flowId}`,
      );
    }
  } catch (e) {
    debugLog(
      `deleteGraphitiEvents: stdin 写入失败 flowId=${flowId} err=${(e as Error)?.message}`,
    );
  }
}

/**
 * 常驻 memory writer daemon 管理（对齐 PentAGI executor.go storeToolResult）。
 * 工具执行后自动把结果写入 knowledge 向量库（doc_type=memory）。
 */
let memoryDaemon: import("child_process").ChildProcess | null = null;
let memoryDaemonReady = false;
const KNOWLEDGE_DAEMON_SCRIPT = join(
  OPENCODE_ROOT,
  "mcp-servers",
  "knowledge",
  "memory_writer_daemon.py",
);

function ensureMemoryDaemon(): void {
  if (memoryDaemon && !memoryDaemon.killed) {
    return;
  }

  const python = getPythonCmd();
  if (!python) {
    debugLog(`ensureMemoryDaemon: Python 未就绪`);
    return;
  }

  try {
    memoryDaemon = spawn(python, [KNOWLEDGE_DAEMON_SCRIPT], {
      stdio: ["pipe", "pipe", "pipe"],
      detached: false,
    });

    memoryDaemon.stdout?.on("data", (data: Buffer) => {
      const output = data.toString().trim();
      if (output === "READY") {
        memoryDaemonReady = true;
        debugLog(`memory daemon: READY`);
      }
    });

    memoryDaemon.stderr?.on("data", (data: Buffer) => {
      debugLog(`memory daemon: ${data.toString().trim()}`);
    });

    memoryDaemon.on("exit", (code) => {
      debugLog(`memory daemon: exited code=${code}`);
      memoryDaemon = null;
      memoryDaemonReady = false;
    });

    if (!exitHandlerRegistered) {
      exitHandlerRegistered = true;
      process.on("exit", () => {
        memoryDaemon?.kill("SIGTERM");
      });
    }

    debugLog(`memory daemon: spawning ${python} ${KNOWLEDGE_DAEMON_SCRIPT}`);
  } catch (e) {
    debugLog(`ensureMemoryDaemon: spawn 失败 err=${(e as Error)?.message}`);
  }
}

/**
 * 异步写入工具执行结果到 knowledge 向量库（doc_type=memory）。
 * 对齐 PentAGI executor.go:519 storeToolResult。
 * fire-and-forget，失败只记日志，不影响 agent 运行。
 */
function fireAndForgetMemory(
  toolName: string,
  args: unknown,
  output: string,
): void {
  ensureMemoryDaemon();

  if (!memoryDaemon || !memoryDaemon.stdin || memoryDaemon.stdin.destroyed) {
    debugLog(`fireAndForgetMemory: daemon 不可用，跳过 tool=${toolName}`);
    return;
  }

  // 对齐 PentAGI executor.go:530 的格式
  const text = `### Incoming arguments\n\n\`\`\`json\n${JSON.stringify(args).slice(0, 2000)}\n\`\`\`\n\n#### Tool result\n\n${(output || "").slice(0, 2000)}\n`;
  const question = `${toolName} execution`;

  const entry =
    JSON.stringify({
      question,
      answer: text,
      type: toolName,
    }) + "\n";

  if (memoryDaemonReady) {
    try {
      memoryDaemon.stdin.write(entry);
    } catch (e) {
      debugLog(
        `fireAndForgetMemory: stdin 写入失败 tool=${toolName} err=${(e as Error)?.message}`,
      );
    }
  } else {
    debugLog(`fireAndForgetMemory: daemon 未就绪，跳过 tool=${toolName}`);
  }
}

export const SecurityAnalysisPlugin: Plugin = async (input) => {
  const { client, directory } = input;

  // 初始化全局上下文（必须在任何 hook 触发之前完成）
  const sessionManager = new SessionDataManager(client);
  ctx.init(client, directory, sessionManager);

  debugLog(`=== SecurityAnalysisPlugin loaded ===`);
  debugLog(`  PLUGIN_DIR: ${PLUGIN_DIR}`);
  debugLog(`  OPENCODE_ROOT: ${OPENCODE_ROOT}`);
  debugLog(`  DATA_DIR: ${DATA_DIR}`);
  debugLog(`  ENV_CACHE_FILE: ${ENV_CACHE_FILE}`);
  debugLog(`  WORKSPACE_DIR: ${WORKSPACE_DIR}`);
  debugLog(`  TASK_SESSIONS_DIR: ${TASK_SESSIONS_DIR}`);
  debugLog(`  LOGS_DIR: ${LOGS_DIR}`);
  debugLog(`  DEFAULT_LOG: ${DEFAULT_LOG}`);
  debugLog(`  directory param: ${directory}`);
  debugLog(`  env_cache exists: ${existsSync(ENV_CACHE_FILE)}`);
  debugLog(`  ctx.client: ${!!ctx.client}`);
  debugLog(
    `  PYTHON_CMD: ${getPythonCmd() ?? "未初始化（等待首次 chat.message 触发）"}`,
  );

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

  // ── 动态注册 MCP server（跨平台，不写死路径）──
  // fire-and-forget：必须不 await。OpenCode Plugin API 限制——plugin.setup 在 Effect runtime
  // 内 await（vendor plugin/promise.ts:90），如果 setup 内 await client.mcp.add()，而
  // mcp.add 又依赖同一个 Effect runtime → 死锁（实测 60s+ 卡住，无 McpManager 日志）。
  // vendor project/bootstrap.ts 也用 Effect.forkDetach 让 init() 是 fire-and-forget。
  //
  // 时序保障：knowledge MCP 已改为 lifespan lazy 加载，握手从 15s 降到 ~5s；
  // fire-and-forget 后 ~7s 内 MCP 工具就可调用（实测）。
  // 错误隔离：mcp-manager.ts:registerOne 已 try/catch 单 server 失败。
  const mcpManager = new McpManager(client);
  mcpManager.registerAll().catch((e) => {
    debugLog(`[McpManager] registerAll 失败: ${e?.message ?? e}`);
  });

  return {
    tool: {},

    // 用户发送消息时触发（awaited，宿主等待完成）
    // 职责：记录 agentName
    // 注意：chat.message 是唯一能直接从 input.agent 获取 agent 名的 hook
    //       system.transform / tool.execute.before 的 input 无 agent
    //       但 SessionDataManager.requireSecurityAgent 可通过 session.get API 间接获取
    "chat.message": async (input, output) => {
      const { sessionID, agent } = input;
      let sessionData: SessionData | null = null;
      try {
        if (!agent) {
          const errMsg = `chat.message: input 缺少 agent 字段 sessionID=${sessionID}`;
          debugLog(errMsg, sessionID);
          await reportErrorAndAbort(ctx.client, sessionID, null, errMsg);
          return;
        }

        // 判断是否为 resume prompt 回声（synthetic message）。
        // maybeResumeAnalysis 发 prompt 后同步设 resumeMarker；resume prompt 触发 chat.message 时它还非空。
        // 用它区分：synthetic 回声不刷新 lastUserMessageAt（否则 max_duration 超时检查形同虚设）。
        // 为了补偿opencode重启后会话数据丢失的问题。
        const existingResult = await ctx.sessionManager.create(sessionID);
        if (existingResult.data?.pendingErrorCallbackMessage) {
          existingResult.data.pendingErrorCallbackMessage = false;
          debugLog(
            `chat.message: 错误信息回调，不继续执行 sessionID=${sessionID}`,
            sessionID,
          );
          return;
        }

        sessionData = await ctx.sessionManager.upsert(sessionID, agent, output);

        // 发送了消息，清理发送恢复消息的定时器

        debugLog(
          `chat.message: sessionID=${sessionID} agent=${agent}`,
          sessionID,
        );

        // 环境检测：不 ready → 存错误信息到 sessionData + 终止（不 throw，不调 session.prompt）
        const envCheck = await checkEnvironment(agent, sessionID);
        if (!envCheck.ready) {
          debugLog(
            `chat.message: 环境检测未通过 agent=${agent}，输出错误并终止`,
            sessionID,
          );
          await reportErrorAndAbort(
            ctx.client,
            sessionID,
            sessionData,
            envCheck.message,
          );
          return;
        }
        sessionData.pendingErrorMessage = null;
      } catch (e) {
        // 兜底：chat.message 里的任何意外异常都不能 throw（会变 defect → 用户空白）
        const msg = (e as Error)?.message ?? String(e);
        debugLog(
          `chat.message: 意外异常 sessionID=${sessionID} err=${msg}`,
          sessionID,
        );
        try {
          await reportErrorAndAbort(
            ctx.client,
            sessionID,
            sessionData,
            `[chat.message 异常] ${msg}`,
          );
        } catch {
          // reportErrorAndAbort 本身也失败了，只能靠日志
        }
      }
    },

    // 上下文压缩前触发（awaited）
    // 职责：注入环境摘要 + 分析状态保留提示 + TASK_DIR，防止压缩丢失关键信息
    "experimental.session.compacting": async (input, output) => {
      try {
        const sid = input.sessionID;
        const session = ctx.sessionManager.requireSecurityAgent(
          "compacting",
          sid,
        );
        if (!session) {
          debugLog(
            `compacting: 跳过 — 非 Security Agent, sessionID=${sid}`,
            sid,
          );
          return;
        }
        const agentName = session.agentName;
        // 置压缩标识：system.transform 检测到后强制注入环境信息（不靠频率），注入后清理
        session.justCompacted = true;
        debugLog(
          `compacting: sessionID=${sid} agent=${agentName} (justCompacted=true)`,
          sid,
        );
        const compactionCtx = getCompactionContext(agentName);
        output.context.push(compactionCtx);

        debugLog(`=== compacting 注入内容开始 ===`, sid);
        debugLog(`sid:${sid}\n`, sid);
        debugLog(`agent:${agentName}\n`, sid);
        debugLog(`compactionCtx:\n${compactionCtx}\n`, sid);
        debugLog(`=== compacting 注入内容结束 ===`, sid);

        if (sid) {
          // 分析持续性恢复：压缩后如果分析尚未完成，AI 应继续自主分析
          if (
            SECURITY_AGENTS.includes(session.agentName) &&
            session.agentName !== AGENT_SECURITY_ANALYSIS_EVOLVE
          ) {
            output.context.push(`## 分析持续性（压缩后必须遵守）
  这是安全分析会话，分析可能尚未完成。压缩后请继续执行未完成的分析步骤，不要输出状态报告后停下来等待用户。如果分析已完成，直接输出最终结论即可。`);
          }
        }
      } catch (e) {
        debugLog(
          `compacting: 意外异常 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
          input.sessionID,
        );
      }
    },

    // 每次 LLM 请求前触发（awaited）
    // 职责：按 agent 注入环境信息到系统提示
    // 注意：output.system 每次请求都重建，不会累积
    //       前 2 次必注入（标题生成 #1 + 主聊天 #2），之后每 X 次注入一次
    "experimental.chat.system.transform": async (input, output) => {
      try {
        const sessionID = input.sessionID;

        if (!sessionID) {
          debugLog(`system.transform: 会话ID不存在`, sessionID);
          return;
        }

        // ── 通用层：所有会话 ──
        output.system.push(
          `\n## 临时文件放置\n` +
            `如需写临时文件，写到 ${join(tmpdir(), "opencode")}/ 下。\n` +
            `> 该目录权限已放行，不会触发权限申请。`,
        );

        // ── 获取 session（先试 SECURITY_AGENTS，再试 searcher/memorist subagent）──
        const session = ctx.sessionManager.requireRegisteredAgent(
          "system.transform",
          sessionID,
        );
        if (!session) {
          debugLog(
            `[WARN] system.transform: 跳过 — 非注册 agent, sessionID=${sessionID}`,
            sessionID,
          );
          return;
        }

        const isRootAgent = session.isRootAgent;

        const agentName = session.agentName;

        // ── 占位符展开（所有识别的 agent 都执行）──
        expandedSnippet(session, output);

        if (isRootAgent) {
          debugLog(`system.transform: 根Agent agent=${agentName}`, sessionID);
          const switchedFrom = session.agentSwitchedFrom;
          if (switchedFrom) {
            output.system.unshift(
              `## Agent切换\n**注意，发生Agent切换：**Agent 已从 ${switchedFrom} 切换到 ${agentName}。请立即按照 ${agentName} 的规则工作，丢弃前一个 Agent 的角色设定。`,
            );
            session.agentSwitchedFrom = null;
          } else {
            output.system.unshift(`当前 Agent: ${agentName}`);
          }
        }

        // ── buildEnvSection（所有识别的 agent 都执行）──
        session.systemTransformCount++;
        const shouldInject =
          session.systemTransformCount <= 3 ||
          session.systemTransformCount % ENV_INJECTION_FREQUENCY === 0 ||
          session.justCompacted;

        if (!shouldInject) {
          debugLog(
            `[INFO] system.transform: #${session.systemTransformCount} 跳过环境信息注入 agent=${agentName}`,
            sessionID,
          );
          return;
        }

        const envData = TaskSessionPersistence.readEnvCache<EnvData>(sessionID);
        const envInfo = envData?.data;

        const envSection = await buildEnvSection(agentName, envInfo, session);
        output.system.push(envSection);

        // 注入"可委派 agent 清单"——只对 AGENTS_WITH_DELEGATION_RULES 成员生效
        // 让调用方知道有哪些 agent 可以委派（含 searcher/memorist + 其他领域 agent）
        if (AGENTS_WITH_DELEGATION_RULES.includes(agentName)) {
          const delegationBlock = buildDelegationBlock(agentName, sessionID);
          if (delegationBlock) {
            output.system.push(delegationBlock);
            debugLog(
              `[INFO] system.transform: 注入委派清单 agent=${agentName} length=${delegationBlock.length}`,
              sessionID,
            );
          }
        }

        // 清理压缩标识
        if (session.justCompacted) {
          session.justCompacted = false;
          debugLog(
            `[INFO] system.transform: 清理 justCompacted sessionID=${sessionID}`,
            sessionID,
          );
        }
        debugLog(
          `[INFO] system.transform: #${session.systemTransformCount} 注入环境信息 sessionID=${sessionID}, agent=${agentName}, length=${envSection.length}, envSection=\n${envSection}`,
          sessionID,
        );
      } catch (e) {
        debugLog(
          `[ERROR] system.transform: 意外异常 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
          input.sessionID,
        );
      }
    },

    // Bash 工具执行前通过 shell.env hook 注入环境变量（awaited）
    // 使用 shell.env 而非修改 command 字符串，避免 LLM 在上下文中看到
    // 注入的变量后模仿累积（导致 SESSION_ID='...' AGENT_NAME='...' 重复十几次）
    "shell.env": async (input, output) => {
      try {
        const sessionID = input.sessionID;
        if (!sessionID) {
          debugLog(`shell.env: 致命错误 — 无 sessionID, cwd=${input.cwd}`);
          await abortSession(
            "",
            `shell.env 触发但无 sessionID (cwd=${input.cwd})，session 初始化异常`,
          );
          return;
        }
        debugLog(
          `shell.env: 触发 sessionID=${sessionID} cwd=${input.cwd} callID=${input.callID ?? "无"}`,
          sessionID,
        );
        const session = ctx.sessionManager.requireRegisteredAgent(
          "shell.env",
          sessionID,
        );
        if (!session) {
          debugLog(
            `shell.env: 跳过 — 非注册 agent sessionID=${sessionID}`,
            sessionID,
          );
          return;
        }

        const agentName = session.agentName;

        // 基础变量（全局常量，始终可注入）
        output.env.SESSION_ID = sessionID;
        output.env.AGENT_NAME = agentName;
        // PYTHON_CMD（惰性获取，chat.message 已确保环境就绪后此处非 null）
        const pythonCmd = getPythonCmd();
        if (pythonCmd) {
          output.env.PYTHON_CMD = pythonCmd;
          // PATH: 前置 venv/bin，使 venv 的 CLI 工具(sage 等)直接可用
          const venvBin = dirname(pythonCmd);
          // filter(Boolean) 过滤空值，避免末尾分隔符(空 PATH 条目会被解释为当前目录，有 PATH injection 风险)
          // delimiter 跨平台: POSIX=':' Windows=';'（与 constants.ts 的 Windows 支持一致）
          output.env.PATH = [venvBin, process.env.PATH]
            .filter(Boolean)
            .join(delimiter);
        }
        output.env.OPENCODE_ROOT = OPENCODE_ROOT;
        output.env.SHARED_DIR = SHARED_DIR;

        // AGENT_DIR（根据当前 agent 计算）
        const scriptDir = getScriptDir(agentName);
        if (scriptDir) {
          output.env.AGENT_DIR = scriptDir;
        }

        // TASK_DIR（从 task session mapping 读取，可能为空）
        const taskDir = session.getTaskDir();
        if (taskDir) {
          output.env.TASK_DIR = taskDir;
        }

        // OPENSECURITY_FLOW_ID（事件库分区标识，agent 调搜索工具时作为 group_id 传入）
        output.env.OPENSECURITY_FLOW_ID = session.flowId;

        // IDAT（从 env_cache.json 的 ida_pro.idat_path 读取，detect_env 检测后写入）
        const envData = TaskSessionPersistence.readEnvCache<EnvData>(sessionID);
        const idatPath = envData?.data?.ida_pro?.idat_path;
        if (idatPath) {
          output.env.IDAT = idatPath;
        }

        debugLog(
          `shell.env: 已注入` +
            ` SESSION_ID=${sessionID}` +
            ` AGENT_NAME=${agentName}` +
            ` PYTHON_CMD=${pythonCmd ?? "未初始化"}` +
            ` OPENCODE_ROOT=${OPENCODE_ROOT}` +
            ` AGENT_DIR=${scriptDir ?? "无"}` +
            ` SHARED_DIR=${output.env.SHARED_DIR}` +
            ` TASK_DIR=${taskDir ?? "无"}` +
            ` OPENSECURITY_FLOW_ID=${session.flowId}` +
            ` IDAT=${output.env.IDAT ?? "无"}` +
            ` PATH=${output.env.PATH ? "已注入venv/bin" : "无"}`,
          sessionID,
        );
      } catch (e) {
        debugLog(
          `shell.env: 意外异常 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
          input.sessionID,
        );
      }
    },

    // 工具执行前触发（awaited）
    // 职责：记录时间线（环境变量注入已迁移到 shell.env hook；任务初始化+环境检测由 chat.message 的 checkEnvironment 兜底）
    "tool.execute.before": async (input, output) => {
      try {
        const sid = input.sessionID;
        const session = ctx.sessionManager.requireRegisteredAgent(
          "tool.execute.before",
          sid,
        );
        if (!session) {
          debugLog(
            `tool.execute.before: 跳过 — 非注册 Agent, sessionID=${sid}`,
            sid,
          );
          return;
        }
        debugLog(
          `tool.execute.before: tool=${input.tool} sessionID=${sid}`,
          sid,
        );

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
      } catch (e) {
        debugLog(
          `tool.execute.before: 意外异常 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
          input.sessionID,
        );
      }
    },

    // 工具执行后触发（fire-and-forget）
    // 职责：记录工具执行结果 + 写入事件库
    "tool.execute.after": async (input, output) => {
      try {
        const sid = input.sessionID;
        const session = ctx.sessionManager.requireRegisteredAgent(
          "tool.execute.after",
          sid,
        );
        if (!session) {
          debugLog(
            `tool.execute.after: 跳过 — 非注册 agent, sessionID=${sid}`,
            sid,
          );
          return;
        }

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

        // 写入事件库（对齐 PentAGI performer.go:198 storeToolExecutionToGraphiti）
        // 排除 Task 工具（对齐 PentAGI 排除 AgentToolType）
        if (toolName !== "task") {
          const agentName = session.agentName;
          const body = `Tool: ${toolName}\nArguments: ${JSON.stringify(input.args).slice(0, 2000)}\nInvoked by: ${agentName} Agent\nStatus: success\nResult: ${(output.output || "").slice(0, 2000)}\nContext: Session ${sid}`;
          fireAndForgetEvent(
            `${toolName} execution`,
            body,
            `${agentName} tool execution`,
            session.flowId,
          );

          // 写入 knowledge 向量库 memory（对齐 PentAGI executor.go:519 storeToolResult）
          fireAndForgetMemory(toolName, input.args, output.output || "");
        }

        debugLog(`tool.execute.after: tool=${toolName}`, sid);
      } catch (e) {
        debugLog(
          `tool.execute.after: 意外异常 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
          input.sessionID,
        );
      }
    },

    // LLM 响应完成时触发（fire-and-forget）
    // 职责：写入事件库（对齐 PentAGI performer.go:170 storeAgentResponseToGraphiti）
    "experimental.text.complete": async (input, output) => {
      try {
        const sid = input.sessionID;
        const session = ctx.sessionManager.get(sid);
        if (!session) return;

        const agentName = session.agentName;
        const text = output.text || "";
        if (!text.trim()) return;

        const body = `Agent: ${agentName}\nResponse: ${text.slice(0, 4000)}\nContext: Session ${sid}`;
        fireAndForgetEvent(
          `${agentName} agent response`,
          body,
          `${agentName} response`,
          session.flowId,
        );
      } catch (e) {
        debugLog(
          `text.complete: 写入事件库失败 sessionID=${input.sessionID} err=${(e as Error)?.message}`,
        );
      }
    },

    // session 生命周期事件（fire-and-forget，宿主不等待完成）
    // 职责：清理 session 数据 + 记录生命周期日志
    // 注意：session.created 触发 SessionDataManager.create 创建 SessionData
    //       但仍记录日志以保持可观测性
    event: async (input: { event: Event }) => {
      try {
        const { event } = input;
        const props = event.properties as Record<string, any>;
        const sessionID: string | undefined = props.info?.id ?? props.sessionID;

        if (event.type === "session.created") {
          if (sessionID) {
            const result = await ctx.sessionManager.create(sessionID);
            if (result.success) {
              debugLog(
                `event: session.created id=${sessionID} agent=${result.data!.agentName} parentID=${result.data!.parentSessionID || "无"}`,
                sessionID,
              );
            }
          } else {
            debugLog(
              `event: session.created 无 sessionID，无法创建 SessionData`,
            );
          }
        }

        // 删除 session：统一清理所有状态 + task session 文件 + graphiti 事件数据
        if (event.type === "session.deleted") {
          if (sessionID) {
            debugLog(`event: session.deleted id=${sessionID}`, sessionID);

            // 先取 flowId（sessionManager.delete 会从内存 Map 移除 SessionData）
            const session = ctx.sessionManager.get(sessionID);
            const flowId = session?.flowId;

            flushTimeline(sessionID);
            ctx.sessionManager.delete(sessionID);
            removeTaskSession(sessionID);

            // 清理 graphiti 事件数据（fire-and-forget，失败只记日志）
            if (flowId) {
              deleteGraphitiEvents(flowId);
            }
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
          const session = ctx.sessionManager.get(sessionID);
          if (session?.activelyTerminated) {
            debugLog(
              `session.idle: 主动终止（预装检查），跳过恢复，activelyTerminated=${session?.activelyTerminated}`,
              sessionID,
            );
            // 如果有待输出的错误信息，在 session 空闲时通过 session.prompt 输出（从 chat.message 内部调会死锁）
            session.activelyTerminated = false;
            if (session?.pendingErrorMessage) {
              const errMsg = session.pendingErrorMessage;
              session.pendingErrorMessage = null;
              try {
                debugLog(
                  `session.idle: 输出待处理的错误信息：${errMsg}`,
                  sessionID,
                );
                session.pendingErrorCallbackMessage = true;
                await ctx.client.session.prompt({
                  path: { id: sessionID },
                  body: {
                    parts: [{ type: "text", text: errMsg }],
                    noReply: true,
                  },
                });
              } catch (e) {
                debugLog(
                  `session.idle: 输出错误信息失败: ${(e as Error)?.message || e}`,
                  sessionID,
                );
              }
            }
          } else {
            await maybeResumeAnalysis(sessionID);
          }
        }

        // session 状态变化和错误（非 idle）
        if (
          sessionID &&
          SECURITY_AGENTS.includes(
            ctx.sessionManager.get(sessionID)?.agentName || "",
          )
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
      } catch (e) {
        debugLog(
          `event: 意外异常 event=${JSON.stringify(input.event)} err=${(e as Error)?.message}`,
          input.event.properties?.info?.id,
        );
      }
    },
  };
};
