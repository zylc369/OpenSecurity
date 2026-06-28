import { writeFileSync, existsSync } from "fs";
import { join } from "path";
import { spawnSync } from "child_process";
import type { Plugin } from "@opencode-ai/plugin";
import type { Event } from "@opencode-ai/sdk";
import {
  PLUGIN_DIR,
  OPENCODE_ROOT,
  DATA_DIR,
  CONFIG_FILE,
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
  AGENT_SCRIPT_DIRS,
  SHARED_DIR,
  AGENTS_DIR,
} from "./lib/constants";
import { ctx } from "./lib/context";
import { SessionData, SessionDataManager } from "./lib/session-manager";
import { debugLog } from "./lib/logging";
import { readJsonSafe, getTaskDir, removeTaskSession } from "./lib/task-session";
import { getPythonCmd, getCondaInstallHint } from "./lib/venv";
import { hasBuwaiExtensionId, loadSnippet } from "./lib/snippet";
import { maybeResumeAnalysis } from "./lib/persistence";
import { recordTimeline, flushTimeline } from "./lib/timeline";

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

function getToolsForAgent(
  agentName: string,
  config: ConfigData,
): Array<ToolConfig & { name: string }> {
  if (!config.tools) return [];
  return Object.entries(config.tools)
    .filter(([, tool]) => !tool.agents || tool.agents.includes(agentName))
    .map(([name, tool]) => ({ name, ...tool }));
}

// 根据 agent 名获取脚本目录；不在映射表中时返回 undefined
function getScriptDir(
  agentName: string | undefined,
): string | undefined {
  return AGENT_SCRIPT_DIRS[agentName || ""] || undefined;
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
    const scriptsDir = getScriptDir(agentName);

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
    debugLog(`abortSession: abort 失败 sessionID=${sessionID} error=${e}`, sessionID);
  }
}

// 工具开始执行时间戳（tool.execute.before → tool.execute.after 配对计算耗时）
const toolStartTimes = new Map<string, number>();

// 环境检测结果
type EnvironmentCheckResult = {
  ready: boolean;
  message: string; // ready=true 时为空；否则是给用户看的错误消息
};

// 预装依赖检查：调 detect_env --check-preinstall <agent>，返回结构化结果。
// 纯函数——永远返回，不 throw（包括 detect_env 崩溃的情况）。
function checkPreinstall(agent: string, pythonCmd: string, sessionID: string): EnvironmentCheckResult {
  const detectEnv = join(SHARED_DIR, "scripts", "detect_env.py");
  const r = spawnSync(pythonCmd, [detectEnv, "--check-preinstall", agent], {
    encoding: "utf8",
    timeout: 8000,
  });
  debugLog(
    `check-preinstall 结果: agent=${agent} status=${r.status} signal=${r.signal}` +
      ` error=${r.error?.message ?? "无"}` +
      ` stdout=${(r.stdout || "").slice(0, 500)}` +
      ` stderr=${(r.stderr || "").slice(0, 300)}`,
    sessionID,
  );
  if (r.error) {
    return { ready: false, message: `[预装检查失败] 无法执行 detect_env（${agent}）：${r.error.message}` };
  }
  if (r.status !== 0) {
    return { ready: false, message: `[预装检查失败] detect_env 退出码 ${r.status}（${agent}）：${(r.stdout || r.stderr || "").slice(0, 200)}` };
  }
  let result: { success?: boolean; errors?: Array<{ package?: string; install_hint?: string }> };
  try {
    result = JSON.parse(r.stdout);
  } catch (e) {
    const msg = (e as Error)?.message ?? String(e);
    return { ready: false, message: `[预装检查失败] detect_env 输出非合法 JSON（${agent}）：${msg}` };
  }
  if (result.success !== true) {
    const hints = Array.isArray(result.errors)
      ? result.errors.map((e) => e.install_hint).filter(Boolean).join("\n")
      : "";
    return {
      ready: false,
      message: hints
        ? `[预装依赖缺失] ${agent} 需要的预装依赖未就绪。请先安装：\n${hints}\n装完后重新发送消息。`
        : `[预装检查未通过] ${agent}：detect_env 返回 success 非 true 但无 errors`,
    };
  }
  return { ready: true, message: "" };
}

// 统一环境检测入口（chat.message 调用此函数，不直接调 checkPreinstall）
// 检测顺序：conda env 可用性 → 预装依赖
function checkEnvironment(agent: string, sessionID: string): EnvironmentCheckResult {
  const pythonCmd = getPythonCmd();
  if (!pythonCmd) {
    return { ready: false, message: getCondaInstallHint() };
  }
  return checkPreinstall(agent, pythonCmd, sessionID);
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
    debugLog(`reportErrorAndAbort: sessionData 更新错误信息 sessionID=${sessionID} message=${message}`, sessionID);
  } else {
    debugLog(`reportErrorAndAbort: sessionData 未提供，无法保存错误信息 sessionID=${sessionID} message=${message}`, sessionID);
  }
  try {
    await client.session.abort({ path: { id: sessionID } });
  } catch (e) {
    debugLog(`reportErrorAndAbort: abort 失败 sessionID=${sessionID} err=${(e as Error)?.message}`, sessionID);
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
  debugLog(`  CONFIG_FILE: ${CONFIG_FILE}`);
  debugLog(`  ENV_CACHE_FILE: ${ENV_CACHE_FILE}`);
  debugLog(`  WORKSPACE_DIR: ${WORKSPACE_DIR}`);
  debugLog(`  TASK_SESSIONS_DIR: ${TASK_SESSIONS_DIR}`);
  debugLog(`  LOGS_DIR: ${LOGS_DIR}`);
  debugLog(`  DEFAULT_LOG: ${DEFAULT_LOG}`);
  debugLog(`  directory param: ${directory}`);
  debugLog(`  config exists: ${existsSync(CONFIG_FILE)}`);
  debugLog(`  env_cache exists: ${existsSync(ENV_CACHE_FILE)}`);
  debugLog(`  ctx.client: ${!!ctx.client}`);
  debugLog(`  PYTHON_CMD: ${getPythonCmd() ?? "未初始化（等待首次 chat.message 触发）"}`);

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
    //       但 SessionDataManager.requireSecurityAgent 可通过 session.get API 间接获取
    "chat.message": async (input) => {
      const { sessionID, agent } = input;
      let sessionData: SessionData | null = null;
      try {
        if (!agent) {
          const errMsg = `chat.message: input 缺少 agent 字段 sessionID=${sessionID}`;
          debugLog(errMsg, sessionID);
          await reportErrorAndAbort(ctx.client, sessionID, null, errMsg);
          return;
        }

        sessionData = await ctx.sessionManager.upsert(sessionID, agent);
        debugLog(`chat.message: sessionID=${sessionID} agent=${agent}`, sessionID);

      // 环境检测：不 ready → 存错误信息到 sessionData + 终止（不 throw，不调 session.prompt）
      const envCheck = checkEnvironment(agent, sessionID);
      if (!envCheck.ready) {
        debugLog(`chat.message: 环境检测未通过 agent=${agent}，输出错误并终止`, sessionID);
        await reportErrorAndAbort(ctx.client, sessionID, sessionData, envCheck.message);
        return;
      }
      sessionData.activelyTerminated = false;
      sessionData.pendingErrorMessage = null;
      } catch (e) {
        // 兜底：chat.message 里的任何意外异常都不能 throw（会变 defect → 用户空白）
        const msg = (e as Error)?.message ?? String(e);
        debugLog(`chat.message: 意外异常 sessionID=${sessionID} err=${msg}`, sessionID);
        try {
          await reportErrorAndAbort(ctx.client, sessionID, sessionData, `[chat.message 异常] ${msg}`);
        } catch {
          // reportErrorAndAbort 本身也失败了，只能靠日志
        }
      }
    },

    // 上下文压缩前触发（awaited）
    // 职责：注入环境摘要 + 分析状态保留提示 + TASK_DIR，防止压缩丢失关键信息
    "experimental.session.compacting": async (input, output) => {
      const sid = input.sessionID;
      const session = ctx.sessionManager.requireSecurityAgent("compacting", sid);
      if (!session) {
        debugLog(`compacting: 跳过 — 非 Security Agent, sessionID=${sid}`, sid);
        return;
      }
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
        if (SECURITY_AGENTS.includes(session.agentName) && session.agentName !== AGENT_SECURITY_ANALYSIS_EVOLVE) {
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
      const sessionID = input.sessionID;
      const session = ctx.sessionManager.requireSecurityAgent(
        "system.transform",
        sessionID,
      );
      if (!session) {
        debugLog(
          `[WARN] system.transform: 跳过 — 非 Security Agent, sessionID=${sessionID}`,
          sessionID,
        );
        return;
      }

      const agentName = session.agentName;

      // 占位符展开（每次 LLM 调用都执行）
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
        }
      } else {
        debugLog(
          `[ERROR] system.transform: ${agentFile} 不包含 buwai-extension-id，跳过占位符展开`,
          sessionID,
        );
      }

      // 每次都注入 Plugin 完整性检查 + Agent 身份
      // 放在 output.system 最前面，确保 LLM 优先看到
      // 如果 Plugin 未加载，这段不会出现，agent 应立即停止并告知用户
      debugLog(
        `system.transform: 注入 Plugin 完整性检查和 Agent 身份 sessionID=${sessionID} agent=${agentName}`,
        sessionID,
      );
      const switchedFrom = session.agentSwitchedFrom;
      const systemPromptPart1 = "[系统完整性] Plugin 已加载。";
      const systemPromptPart2 = "如果你看不到这段标记，说明 Plugin 未加载，当前会话缺少关键功能（环境信息、工具配置、占位符展开）。请立即告知用户并停止分析。";
      if (switchedFrom) {
        output.system.unshift(
          `${systemPromptPart1}⚠️ Agent 已从 ${switchedFrom} 切换到 ${agentName}。请立即按照 ${agentName} 的规则工作，丢弃前一个 Agent 的角色设定。${systemPromptPart2}`,
        );
        session.agentSwitchedFrom = null;
      } else {
        output.system.unshift(
          `${systemPromptPart1}当前 Agent: ${agentName}。${systemPromptPart2}`,
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
      const session = ctx.sessionManager.requireSecurityAgent("shell.env", sessionID);
      if (!session) {
        debugLog(`shell.env: 跳过 — 非 Security Agent sessionID=${sessionID}`, sessionID);
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
      }
      output.env.OPENCODE_ROOT = OPENCODE_ROOT;
      output.env.SHARED_DIR = SHARED_DIR;

      // AGENT_DIR（根据当前 agent 计算）
      const scriptDir = getScriptDir(agentName);
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
          ` PYTHON_CMD=${pythonCmd ?? "未初始化"}` +
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
      const session = ctx.sessionManager.requireSecurityAgent(
        "tool.execute.before",
        sid,
      );
      if (!session) {
        debugLog(`tool.execute.before: 跳过 — 非 Security Agent, sessionID=${sid}`, sid);
        return;
      }
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
      const session = ctx.sessionManager.requireSecurityAgent(
        "tool.execute.after",
        sid,
      );
      if (!session) {
        debugLog(`tool.execute.after: 跳过 — 非 Security Agent, sessionID=${sid}`, sid);
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

      debugLog(`tool.execute.after: tool=${toolName}`, sid);
    },

    // session 生命周期事件（fire-and-forget，宿主不等待完成）
    // 职责：清理 session 数据 + 记录生命周期日志
    // 注意：session.created 触发 SessionDataManager.create 创建 SessionData
    //       但仍记录日志以保持可观测性
    event: async (input: { event: Event }) => {
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
          debugLog(`event: session.created 无 sessionID，无法创建 SessionData`);
        }
      }

      // 删除 session：统一清理所有状态 + task session 文件
      if (event.type === "session.deleted") {
        if (sessionID) {
          debugLog(`event: session.deleted id=${sessionID}`, sessionID);
          flushTimeline(sessionID);
          ctx.sessionManager.delete(sessionID);
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
        const session = ctx.sessionManager.get(sessionID);
        if (session?.activelyTerminated || session?.activelyTerminated === null) {
          debugLog(`session.idle: 主动终止（预装检查），跳过恢复，activelyTerminated=${session?.activelyTerminated}`, sessionID);
          // 如果有待输出的错误信息，在 session 空闲时通过 session.prompt 输出（从 chat.message 内部调会死锁）
          session.activelyTerminated = false;
          if (session?.pendingErrorMessage) {
            const errMsg = session.pendingErrorMessage;
            session.pendingErrorMessage = null;
            try {
              debugLog(`session.idle: 输出待处理的错误信息：${errMsg}`, sessionID);
              await ctx.client.session.prompt({
                path: { id: sessionID },
                body: { parts: [{ type: "text", text: errMsg }], noReply: true },
              });
            } catch (e) {
              debugLog(`session.idle: 输出错误信息失败: ${(e as Error)?.message}`, sessionID);
            }
          }
        } else {
          await maybeResumeAnalysis(sessionID);
        }
      }

      // session 状态变化和错误（非 idle）
      if (
        sessionID &&
        SECURITY_AGENTS.includes(ctx.sessionManager.get(sessionID)?.agentName || "")
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
