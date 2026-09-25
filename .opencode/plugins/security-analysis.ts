import { readFileSync, readdirSync, existsSync, unlinkSync } from "fs";
import { join, dirname, delimiter } from "path";
import { tmpdir, homedir } from "os";
import type { Plugin } from "@opencode-ai/plugin";
import type { Event } from "@opencode-ai/sdk";
import {
  PLUGIN_DIR,
  OPENCODE_ROOT,
  DATA_DIR,
  WORDLISTS_DIR,
  TOOLS_CMD_DIR,
  TOOLS_HOME_DIR,
  WORKSPACE_DIR,
  TASK_SESSIONS_DIR,
  LOGS_DIR,
  DEFAULT_LOG,
  ENV_INJECTION_FREQUENCY,
  AGENT_BINARY_ANALYSIS,
  AGENT_MOBILE_ANALYSIS,
  AGENT_WEB_ANALYSIS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
  LEDGER_INJECT_MAX_TOKENS,
  SECURITY_AGENTS,
  SECURITY_ANALYSIS_AGENTS,
  PROJECT_AGENTS,
  AGENT_SCRIPT_DIRS,
  SHARED_DIR,
  AGENTS_DIR,
  CONTROL_STARTUP_SERVICE,
} from "./lib/constants";
import { cognition } from "./lib/cognition";
import { ctx } from "./lib/context";
import { SessionData, SessionDataManager } from "./lib/session-manager";
import { debugLog } from "./lib/logging";
import TaskSessionPersistence, {
  LEDGER_TEMPLATE,
} from "./lib/task-session-persistence";
import {
  shouldTriggerCheckpoint,
  renderCheckpointText,
} from "./lib/checkpoint";
import { getPythonCmd, getInstallHint, getCompilerName } from "./lib/venv";
import { isControlHealthy, startControl } from "./lib/control-manager";
import { controlFetch } from "./lib/control-http";
import { refreshConfig, getCachedConfig } from "./lib/control-config";

/** 从缓存读配置值（同步，不触发 HTTP）。如果缓存为空返回 null。 */
function getCachedConfigValue(key: string): string | null {
  return getCachedConfig()[key] ?? null;
}
import {
  BUWAI_RULE_PLACEHOLDER_PREFIX,
  BUWAI_RULE_PLACEHOLDER_SOURCE,
  inspectAgentFile,
  loadSnippet,
  resolveDynamicRuleSnippetName as resolveDynamicByAgentSnippetName,
} from "./lib/snippet";
import { maybeResumeAnalysis } from "./lib/persistence";
import { recordTimeline, flushTimeline } from "./lib/timeline";
import {
  checkDepsViaControl,
  type EnvironmentCheckResult,
} from "./lib/env-check";
import { McpManager } from "./lib/mcp-manager";

// 根据 agent 名获取脚本目录；不在映射表中时返回 undefined
function getScriptDir(agentName: string | undefined): string | undefined {
  return AGENT_SCRIPT_DIRS[agentName || ""] || undefined;
}

const nodeBinPath: { path: string | null; isCached: boolean } = {
  path: null,
  isCached: false,
};

/**
 * node 官方目录的 PATH 注入路径; null = 本机 node 合格，不注入。
 *
 * 不变量: tools/node/node-v* 存在 ⟺ 安装器判定本机 node 不可用
 * （PATH 无 node 或版本 < 18.17 时 detect_tools 才解包; 本机 node 合格则目录不存在，
 *  NodeRecipe skip 分支会清理残留维护此不变量）。
 * darwin/linux 注入 <dir>/bin（node 与 npm/npx 软链同目录，shebang 自洽）;
 * win 注入 <dir> 根目录（npm.cmd 优先同目录 node.exe，官方已内置兜底）。
 */
/**
 * 固定目录类工具的 PATH 注入（adb 等 DirRecipe 产物）; null = 本机已有，不注入。
 *
 * 不变量: tools/<dir>/ 存在 ⟺ 安装时 PATH 无该工具（detect_tools skip 分支清理残留维护）。
 * 目录内含 marker 文件即注入该目录本身（adb/fastboot 等官方布局平铺在目录内）。
 */
function resolveToolDirPath(
  dirName: string,
  marker: string,
  sessionID: string,
): string | null {
  const dir = join(TOOLS_HOME_DIR, dirName);
  const markerFile = process.platform === "win32" ? `${marker}.exe` : marker;
  try {
    if (existsSync(join(dir, markerFile))) {
      debugLog(`resolveToolDirPath(${dirName}): 注入 ${dir}`, sessionID);
      return dir;
    }
    debugLog(
      `resolveToolDirPath(${dirName}): 无 ${markerFile}（本机已有或未安装），不注入`,
      sessionID,
    );
    return null;
  } catch {
    return null;
  }
}

// android-platform-tools 注入路径缓存: 首次解析后固定（工具安装/清理发生在会话外的 install.sh）
const androidPlatformToolsPath: { path: string | null; isCached: boolean } = {
  path: null,
  isCached: false,
};

/** android-platform-tools（adb/fastboot）目录的 PATH 注入; null = 本机已有 adb，不注入。 */
function resolveAndroidPlatformToolsPath(sessionID: string): string | null {
  if (androidPlatformToolsPath.isCached) {
    return androidPlatformToolsPath.path;
  }
  try {
    androidPlatformToolsPath.path = resolveToolDirPath(
      "android-platform-tools",
      "adb",
      sessionID,
    );
    return androidPlatformToolsPath.path;
  } finally {
    androidPlatformToolsPath.isCached = true;
  }
}

function resolveNodeBinPath(sessionID: string): string | null {
  if (nodeBinPath.isCached) {
    return nodeBinPath.path;
  }
  const nodeRoot = join(TOOLS_HOME_DIR, "node");
  try {
    const verDir = readdirSync(nodeRoot).find((e) => /^node-v/.test(e));
    if (!verDir) {
      debugLog(
        `resolveNodeBinPath: 目录内无 node-v*（本机 node 合格）: ${nodeRoot}`,
        sessionID,
      );
      return null;
    }
    const base = join(nodeRoot, verDir);
    const bin = process.platform === "win32" ? base : join(base, "bin");
    debugLog(`resolveNodeBinPath: 注入 ${bin}`, sessionID);
    nodeBinPath.path = bin;
    return bin;
  } catch {
    debugLog(
      `resolveNodeBinPath: 目录不存在（本机 node 合格）: ${nodeRoot}`,
      sessionID,
    );
    return null;
  } finally {
    nodeBinPath.isCached = true;
  }
}

function getCompactionContext(): string {
  let context = `## 分析状态（压缩时必须保留）

当总结此会话时，如果包含分析相关内容，你必须保留以下信息：

### 1. 分析目标
- 目标路径（文件路径 / URL / 源码目录 / APK·IPA 路径等）
- 目标架构 / 技术栈 / 框架版本

### 2. 环境状态
- 工具与环境配置（IDA 数据库路径、设备连接状态/Frida 端口、解包路径、SageMath 会话、目标服务地址等）
- 已执行的工具查询及结果摘要（idat 查询结果、Frida hook 结果、SageMath 计算结果、HTTP 请求/响应等）
- 任何运行中的进程或服务

### 3. 已完成的分析
- 已识别的关键函数 / 类 / 组件及其地址 / 名称和用途
- 已识别的 native 库（.so / .dylib / .dll）、框架、加密算法或保护机制
- 已发现的分析结论和漏洞
- 已发现的攻击面和攻击链进度（含已测试的攻击方向和结果）
- 当前分析阶段和待完成步骤
- 失败记录（已尝试方向，避免重复）
- 验证结果和置信度
- 用户显式约束

### 4. ${cognition.sections.conclusions}与${cognition.fields.untestedList}
- 每条结论必须保留【${cognition.evidenceLevelSpec} + ${cognition.fields.verifiedScope} + ${cognition.fields.untestedList}】，禁止把未验证结论表述为已确认
- "${cognition.sections.untested}"清单与"${cognition.sections.changelog}"必须原样保留
- 禁止保留无条件的"${cognition.universalDenyMarkers.join("/")}"类结论；如需保留，必须同时保留其${cognition.fields.untestedList}（分析台账 $ROOT_TASK_DIR/${cognition.ledgerFilename} 的内容已随本提示一并提供——超约 ${LEDGER_INJECT_MAX_TOKENS} token 时截断并附全文路径；结论与未测清单照其原文保留，不要改写或精简）`;

  return context;
}

/** 估算 token 数：ASCII 4 字符 ≈ 1 token；非 ASCII（CJK 等）1 字符 ≈ 1 token——保守上估，宁少勿多 */
function estimateTokens(text: string): number {
  let ascii = 0;
  let wide = 0;
  for (const ch of text) {
    if ((ch.codePointAt(0) ?? 0) < 0x80) ascii++;
    else wide++;
  }
  return Math.ceil(ascii / 4) + wide;
}

/**
 * 构建"分析台账原文"压缩注入块（认知干预系统：压缩时原样穿越）。
 * 仅（五分析 agent + 有任务目录 + 台账文件非空）时返回内容；
 * 超 LEDGER_INJECT_MAX_TOKENS token（估算）截断并附全文路径；其余情况返回 null（调用方不 push = 不注入）。
 */
function buildLedgerContextBlock(session: SessionData): string | null {
  const sessionID = session.sessionID;
  const ledgerTaskDir = session.rootTaskDir || session.getTaskDir();

  if (!ledgerTaskDir) {
    debugLog(`[buildLedgerContextBlock]无任务目录，跳过台账注入`, sessionID);
    return null;
  }

  if (!SECURITY_ANALYSIS_AGENTS.includes(session.agentName)) {
    debugLog(`[buildLedgerContextBlock]非分析 agent 跳过台账注入`, sessionID);
    return null;
  }

  // 台账文件路径
  const ledgerPath = join(ledgerTaskDir, cognition.ledgerFilename);
  try {
    const ledgerRaw = readFileSync(ledgerPath, "utf-8");
    if (!ledgerRaw.trim()) {
      debugLog(
        `[buildLedgerContextBlock] 台账为空，跳过 ${ledgerPath}`,
        sessionID,
      );
      return null;
    }

    const ledgerLines = ledgerRaw.split(/\r?\n/);
    // token 预算截断：逐行累计估算，只取完整行（保持 markdown 结构，不做行内切断）
    const keptLines: string[] = [];
    let usedTokens = 0;
    for (const line of ledgerLines) {
      const lineTokens = estimateTokens(line) + 1; // +1 ≈ 行尾换行
      if (usedTokens + lineTokens > LEDGER_INJECT_MAX_TOKENS) break;
      keptLines.push(line);
      usedTokens += lineTokens;
    }

    let truncated = keptLines.length < ledgerLines.length;
    if (keptLines.length === 0) {
      // 首行即超预算的病态情形：截断首行，保证注入不为空
      keptLines.push(ledgerLines[0].slice(0, LEDGER_INJECT_MAX_TOKENS) + "…");
      usedTokens = estimateTokens(keptLines[0]);
      truncated = true;
    }
    const capped = keptLines.join("\n");
    const truncatedNote = truncated
      ? `\n…（已截断，共 ${ledgerLines.length} 行；全文见：${ledgerPath}）`
      : "";
    debugLog(
      `[buildLedgerContextBlock] 注入分析台账 ${ledgerPath} (${keptLines.length}/${ledgerLines.length} 行，约 ${usedTokens} token) sessionID=${sessionID}`,
      sessionID,
    );
    return `## 分析台账（未经总结的原始记录，必须保留）\n${capped}${truncatedNote}`;
  } catch {
    debugLog(
      `[buildLedgerContextBlock] 台账不存在，跳：${ledgerPath}`,
      sessionID,
    );
    return null;
  }
}

/**
 * 认知契约自检（镜像点一致性 + 插值渲染冒烟）。
 * 启动时调用一次；漂移 → 日志 WARN + TUI toast，不阻塞启动。
 * 手动即时验证（无独立脚本）：
 *   bun -e "const m=await import('./plugins/lib/cognition.ts'); console.log(m.cognition.verifyMirrors())"
 */
async function verifyCognitionSelfCheck(): Promise<void> {
  try {
    const problems = cognition.verifyMirrors();

    // 渲染冒烟：插值属性名笔误只会在渲染时暴露
    try {
      const compaction = getCompactionContext();
      if (!compaction.includes(cognition.universalDenyMarkers.join("/")))
        problems.push("压缩注入渲染缺否定词表");
      if (!compaction.includes(cognition.evidenceLevelSpec))
        problems.push("压缩注入渲染缺证据等级口径");
      const checkpoint = renderCheckpointText({
        checkpointCount: 0,
        elapsedMinutes: 0,
        toolCallCount: 0,
        commandCallCount: 0,
      });
      if (!checkpoint.includes(cognition.ledgerFilename))
        problems.push("检查点渲染缺台账文件名");
      if (!LEDGER_TEMPLATE.includes(cognition.fields.untestedList))
        problems.push("台账模板缺未测清单字段");
    } catch (e) {
      problems.push(`渲染冒烟异常: ${(e as Error)?.message}`);
    }

    if (problems.length === 0) {
      debugLog("认知契约自检：一致");
      return;
    }
    debugLog(
      `[WARN] 认知契约漂移（${problems.length} 项）: ${problems.join(" | ")}`,
    );
    if (ctx.client) {
      try {
        await ctx.client.tui.showToast({
          body: {
            title: "认知契约漂移",
            message: `${problems.length} 项不一致（详见 plugin_debug.log）：${problems[0]}`,
            variant: "warning",
            duration: 15000,
          },
        });
      } catch (e) {
        debugLog(`认知契约 toast 失败: ${(e as Error)?.message}`);
      }
    }
  } catch (e) {
    debugLog(`认知契约自检异常: ${(e as Error)?.message}`);
  }
}

async function buildEnvSection(
  agentName: string | undefined,
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
      envSection += `- 当前会话的任务目录($TASK_DIR)路径（本会话工作目录：自己的中间产物写这里）: ${taskDir}`;
    } else {
      debugLog(`全局环境和目录位置信息 - 任务目录不存在`, sessionID);
    }

    const rootTaskDir = session.rootTaskDir;
    if (rootTaskDir) {
      envSection += `- 根任务目录($ROOT_TASK_DIR)路径（约定文件落点：分析台账、无记忆评审报告；根会话下等于 $TASK_DIR）: ${rootTaskDir}`;
    }

    envSection += `- 共享目录($SHARED_DIR)路径，它里面有共享的通用的知识、工具和脚本: ${SHARED_DIR}\n`;

    // OPENSECURITY_FLOW_ID：事件库分区标识
    envSection += `- 事件库 Flow ID ($OPENSECURITY_FLOW_ID): ${session.flowId}。标识当前分析任务的事件库分区。主任务和它启动的所有子任务共享同一个 Flow ID——子 agent 写入的事件（工具执行记录、LLM 响应）和父 agent 写入的事件存在同一个分区里，互相可搜索。调用事件库 MCP 的搜索工具时，将此值作为 group_id 参数传入，限定搜索范围到当前任务的事件，避免搜到其他无关任务的数据。\n`;

    // IDA Pro：通过控制台配置检测（不直接读 .ai_env）
    const idaHome = getCachedConfigValue("IDA_PRO_HOME");
    if (idaHome) {
      envSection += `- IDA Pro: 已配置（用 $IDAT 调用 idat）\n`;
    } else {
      envSection += `- IDA Pro: 未配置\n`;
    }

    const pythonCmd = getPythonCmd();
    if (pythonCmd) {
      envSection += `- Python ($PYTHON_CMD): ${pythonCmd}\n`;
      envSection += `- Python venv bin 目录（\`$PYTHON_CMD/bin\`, 已在 PATH 首位）: 完整路径是 \`${pythonCmd}/bin\`。内含 1000+ 可执行命令（sqlmap/dirsearch/frida/impacket 全家/secretsdump/one_gadget/ROPGadget/uncompyle6/vol 等），可直接按命令名调用，不必写完整路径\n`;
    }

    // 外部工具目录（detect_tools 自动安装产物 + 容器 wrapper; shell.env 已注入 PATH）
    envSection += `- 外部工具目录: 完整路径是 \`${TOOLS_CMD_DIR}\`（已在 PATH 中，venv 之后）。多数工具为原生安装（brew/apt/官方便携包: hashcat(Metal GPU)/nmap/hydra/john/ffmpeg/tshark/ghidra 等），少量走 docker wrapper（stegseek/boolector/linux 文件系统族等）——全部直接按命令名调用，不必写完整路径。docker wrapper 会自动挂载当前工作目录（可读写）和 \`$WORDLISTS_DIR\`，宿主路径自动翻译成容器路径，当本机命令用即可\n`;

    // 字典统一目录（$WORDLISTS_DIR 与 shell.env 注入保持一致; 路径约定恒定）
    envSection += `- 字典目录 ($WORDLISTS_DIR): 完整路径是 \`${WORDLISTS_DIR}\`。子目录: seclists/（全集字典，docker wrapper 的工具自动挂载到 /usr/share/seclists; 原生工具直接用 \`$WORDLISTS_DIR\` 路径）、rockyou.txt、cn/（中文精选: 安全设备默认口令/top 系列/登入账号）。使用字典时路径一律写 \`$WORDLISTS_DIR/xxx\`; 场景→字典选择详见 Read $OPENCODE_ROOT/binary-analysis/knowledge-base/wordlists-guide.md\n`;

    // 编译器（用 getCompilerName 检测 PATH 中的编译器，只告知可用性，不注入完整路径）
    const compilerName = getCompilerName();
    if (compilerName) {
      envSection += `- 编译器: ${compilerName}（在 PATH 中可用）\n`;
    } else {
      envSection += `- 编译器: 未检测到\n`;
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

// ─── 控制台启动管理 ──────────────────────────────────
//
// 控制台架构改造后，原 embed_server 启动逻辑迁移到 control-manager.ts。
// control-manager 负责：
//   1. 启动时检查现有控制台（IPC connect 即发现即校验）
//   2. 复用 or spawn 新控制台（detached:true + unref）
//   3. 启动心跳（每 10s 上报；控制台心跳表空过宽限自动自杀，无需 exit handler）
//
// ServiceRegistry 中 CONTROL_STARTUP_SERVICE 在 setup() 里 resolve（成功 or 失败），
// chat.message 通过 waitFor(CONTROL_STARTUP_SERVICE) 等待。

/**
 * 统一的控制台可用性检查（启动门禁 + 运行期存活复核）。
 *
 * 两层语义：
 *   1. waitFor(CONTROL_STARTUP_SERVICE)——启动期一次性门禁（setup 时 resolve，
 *      之后状态永不回退，无法感知运行期死亡）
 *   2. isControlHealthy()——实时 IPC /health probe，弥补第 1 层的盲区
 *
 * 返回 { ok: true } 或 { ok: false, error }。
 * 调用方拿 error 走 reportErrorAndAbort（用户可见报错）。
 * （2026/9/14 事故：控制台启动成功 10s 后死亡，service 仍 "success"，
 *   resume prompt 的 chat.message 门禁全放行——用户已禁用恢复仍被注入 5+ 轮。）
 */
async function ensureControlReady(): Promise<{ ok: boolean; error?: string }> {
  const controlStatus = await ctx.services.waitFor(CONTROL_STARTUP_SERVICE);
  if (controlStatus.status === "failed") {
    return {
      ok: false,
      error: controlStatus.error ?? "启动失败（未知原因）",
    };
  }
  // 启动成功过 → 运行期存活复核。启动门禁只认 200（waitForIpcReady 已等到
  // 200 才 resolve success），此后非 200 只可能是进程死亡——不存在"未就绪"。
  // UDS 本机 probe 正常 <10ms；进程已死时 connect 立即 ECONNREFUSED，
  // 不会等满 3s 超时。
  if (!(await isControlHealthy())) {
    return {
      ok: false,
      error:
        "控制台进程运行期死亡（IPC /health 不可达：被 kill 或崩溃，详见 logs/control-stderr.log 与 plugin_debug.log 的退出判定）",
    };
  }
  return { ok: true };
}

/**
 * 启动控制台并 resolve 到 ServiceRegistry。
 * 失败（venv 缺失、脚本不存在、spawn 失败、超时）→ resolve failed。
 */
async function startControlService(): Promise<void> {
  try {
    const ok = await startControl();
    if (ok) {
      ctx.services.resolve(CONTROL_STARTUP_SERVICE, "success", undefined);
      debugLog(`control_service 就绪（IPC 通道可达）`);
    } else {
      ctx.services.resolve(
        CONTROL_STARTUP_SERVICE,
        "failed",
        "startControl 返回 false（venv 未就绪 / 控制台脚本不存在 / spawn 失败 / IPC 就绪超时）",
      );
      debugLog(`control_service 启动失败：startControl 返回 false`);
    }
  } catch (e) {
    ctx.services.resolve(
      CONTROL_STARTUP_SERVICE,
      "failed",
      `startControl 异常: ${(e as Error)?.message}`,
    );
    debugLog(`control_service 异常: ${(e as Error)?.message}`);
  }
}

// ─── 环境检测：并行预热 + Promise cache ────────────────────────
//
// 启动时并行预热所有领域 agent + Coordinator 的环境检测。
// chat.message 命中 Promise cache 时直接 await（已完成则零开销）。
// 检测失败的 Promise 会在 chat.message 里被重新 set（异步重试，不阻塞当前 abort）。
const envCheckPromises = new Map<string, Promise<EnvironmentCheckResult>>();

/**
 * 单个 agent 的环境检测（封装为 Promise，供并行预热 + chat.message 复用）。
 * 两层（checkDepsViaControl 内部串联，缺一不可）：
 *   第一层 CLI：venv 缺失或必需包缺失 → install.sh 提示（此时控制台起不来）
 *   第二层 API：控制台 /api/deps 五分类 → 有问题给 console_url 引导
 * - venv 未就绪 → 返回 {ready: false, message: 安装提示}（venv 自举层）
 * - 任何异常 → catch 后返回 {ready: false, message: 异常信息}
 */
function preheatEnvCheck(agent: string): Promise<EnvironmentCheckResult> {
  const pythonCmd = getPythonCmd();
  if (!pythonCmd) {
    return Promise.resolve({ ready: false, message: getInstallHint() });
  }
  return checkDepsViaControl(agent, "preheat", pythonCmd).catch((e) => ({
    ready: false,
    message: `[预热异常] ${agent}: ${(e as Error)?.message ?? String(e)}`,
  }));
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
  const isProjectAgent = agentName ? PROJECT_AGENTS.includes(agentName) : false;
  const inspection = inspectAgentFile(agentFile, isProjectAgent);

  if (!inspection.exists) {
    debugLog(
      `system.transform: ${agentFile} 不存在，跳过占位符展开`,
      sessionID,
    );
    return;
  }
  if (!inspection.hasExtensionId) {
    if (inspection.hasPlaceholders) {
      debugLog(
        `[ERROR] system.transform: ${agentFile} 含占位符但未声明 buwai-extension-id，占位符不会展开（请在 frontmatter 声明）`,
        sessionID,
      );
    } else {
      debugLog(
        `system.transform: ${agentFile} 未声明 buwai-extension-id 且无占位符，跳过占位符展开`,
        sessionID,
      );
    }
    return;
  }

  debugLog(
    `system.transform: 检测到 buwai-extension-id in ${agentFile}, performing snippet expansion`,
    sessionID,
  );

  // 统一占位符展开（语法源见 snippet.ts）
  const regex = new RegExp(BUWAI_RULE_PLACEHOLDER_SOURCE, "g");
  for (let i = 0; i < output.system.length; i++) {
    if (!output.system[i].includes(BUWAI_RULE_PLACEHOLDER_PREFIX)) continue;
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
 * fire-and-forget 投递到控制台服务端。
 *
 * 事件库/knowledge 库写入收口到控制台：
 *   - POST /api/events/entry | /api/events/delete → Graphiti（控制台 event_store 线程）
 *   - POST /api/memory/entry                → knowledge 向量库（控制台 knowledge_store 线程）
 * 控制台端点入队即返 202；plugin 侧不 await、失败只记日志。
 * 控制台重启：controlFetch 每次实时 connect IPC 地址，自动跟随新实例。
 */
function postToControl(
  path: string,
  body: Record<string, unknown>,
  tag: string,
): void {
  controlFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeoutMs: 5000, // 控制台挂起态防 promise 永久悬空
  })
    .then((resp) => {
      if (!resp.ok) {
        debugLog(`postToControl: ${tag} 响应异常 status=${resp.status}`);
      }
    })
    .catch((e: Error) => {
      debugLog(`postToControl: ${tag} 发送失败 err=${e?.message}`);
    });
}

/**
 * 异步写入事件到 Graphiti 事件库（fire-and-forget，不阻塞主流程）。
 * 经控制台 /api/events/entry 投递（含 timestamp 保证时序）。
 * 失败只记日志，不影响 agent 运行。
 */
function fireAndForgetEvent(
  session: SessionData,
  name: string,
  body: string,
  source: string,
  groupId: string,
): void {
  if (!session.isInstrumentedAgent()) {
    return;
  }
  postToControl(
    "/api/events/entry",
    { name, body, source, group_id: groupId, timestamp: Date.now() },
    `event name=${name}`,
  );
}

/**
 * 删除指定 flowId 的所有事件库数据（fire-and-forget）。
 * 经控制台 /api/events/delete 投递；失败只记日志，不影响 session 删除流程。
 */
function deleteGraphitiEvents(flowId: string): void {
  postToControl(
    "/api/events/delete",
    { group_id: flowId },
    `delete flowId=${flowId}`,
  );
}

/**
 * 异步写入工具执行结果到 knowledge 向量库（doc_type=memory）。
 * 对齐 PentAGI executor.go:519 storeToolResult + registry.go:149 allowedStoringInMemoryTools。
 * 经控制台 /api/memory/entry 投递，fire-and-forget，失败只记日志，不影响 agent 运行。
 */

// 白名单：只有有信息价值的工具结果才存入 memory（对齐 PentAGI allowedStoringInMemoryTools）
const MEMORY_ALLOWED_TOOLS = new Set([
  "bash", // 命令输出有技术价值（对应 PentAGI Terminal）
  "read", // 文件内容可能有价值（对应 PentAGI File）
  "websearch", // 外部搜索结果（对应 PentAGI Google/DuckDuckGo）
  "webfetch", // 外部资料获取
  "task", // 子 agent 返回的精炼结果（对应 PentAGI Search/Coder/Pentester/Advice）
]);

function fireAndForgetMemory(
  session: SessionData,
  toolName: string,
  args: unknown,
  output: string,
  flowId: string,
): void {
  if (!session.isInstrumentedAgent()) {
    return;
  }
  // 白名单检查（对齐 PentAGI allowedStoringInMemoryTools）
  if (!MEMORY_ALLOWED_TOOLS.has(toolName)) {
    return;
  }

  // 对齐 PentAGI executor.go:530 的格式
  const text = `### Incoming arguments\n\n\`\`\`json\n${JSON.stringify(args).slice(0, 2000)}\n\`\`\`\n\n#### Tool result\n\n${(output || "").slice(0, 2000)}\n`;
  const question = `${toolName} execution`;

  postToControl(
    "/api/memory/entry",
    { question, answer: text, type: toolName, flow_id: flowId },
    `memory tool=${toolName}`,
  );
}

/**
 * 认知检查点：满足（根会话 + 五分析 agent + 有任务目录 + 触发判定）时返回注入文本并记账；
 * 否则返回 null（调用方不 push）。触发判定含特性开关（COGNITION_CHECKPOINT_ENABLED）。
 */
function cognitionCheckpoint(session: SessionData): string | null {
  if (!session.isRootAgent) {
    return null;
  }
  const agentName = session.agentName;
  if (!SECURITY_ANALYSIS_AGENTS.includes(agentName)) {
    return null;
  }

  if (!session.getTaskDir()) {
    return null;
  }

  const now = Date.now();
  if (!shouldTriggerCheckpoint(session, now)) {
    return null;
  }

  session.checkpointCount++;
  session.lastCheckpointToolCount = session.toolCallCount;
  session.lastCheckpointAt = now;

  const result = renderCheckpointText(session);
  const sessionID = session.sessionID;
  debugLog(
    `[INFO] system.transform: 注入认知检查点 #${session.checkpointCount} (tools=${session.toolCallCount}, cmds=${session.commandCallCount}, minutes=${session.elapsedMinutes}) sessionID=${sessionID}`,
    sessionID,
  );
  return result;
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
  debugLog(`  WORKSPACE_DIR: ${WORKSPACE_DIR}`);
  debugLog(`  TASK_SESSIONS_DIR: ${TASK_SESSIONS_DIR}`);
  debugLog(`  LOGS_DIR: ${LOGS_DIR}`);
  debugLog(`  DEFAULT_LOG: ${DEFAULT_LOG}`);
  debugLog(`  directory param: ${directory}`);
  debugLog(`  ctx.client: ${!!ctx.client}`);
  debugLog(
    `  PYTHON_CMD: ${getPythonCmd() ?? "未初始化（等待首次 chat.message 触发）"}`,
  );

  // ── 动态注册 MCP server（跨平台，不写死路径）──
  // fire-and-forget：必须不 await。OpenCode Plugin API 限制——plugin.setup 在 Effect runtime
  // 内 await（vendor plugin/promise.ts:90），如果 setup 内 await client.mcp.add()，而
  // mcp.add 又依赖同一个 Effect runtime → 死锁（实测 60s+ 卡住，无 McpManager 日志）。
  // vendor project/bootstrap.ts 也用 Effect.forkDetach 让 init() 是 fire-and-forget。
  //
  // 时序保障：knowledge/events MCP 均 lifespan lazy 加载（握手 ~5s）；
  // fire-and-forget 后 ~7s 内 MCP 工具就可调用（实测）。
  // 错误隔离：mcp-manager.ts:registerOne 已 try/catch 单 server 失败。
  const mcpManager = new McpManager(client);
  mcpManager.registerAll().catch((e) => {
    debugLog(`[McpManager] registerAll 失败: ${e?.message ?? e}`);
  });

  // ── 启动控制台（注册到 ServiceRegistry，chat.message 统一等待）──
  // 控制台是 embed_server 的超集（含 embed/rerank + 资源管理 + 配置管理）。
  // 不可用时不降级——chat.message 检测到 failed 后当环境检测失败处理。
  ctx.services.register(CONTROL_STARTUP_SERVICE);
  startControlService();

  // ── 并行预热环境检测（fire-and-forget）──
  const preheatAgents = [...SECURITY_ANALYSIS_AGENTS];
  for (const agent of preheatAgents) {
    envCheckPromises.set(agent, preheatEnvCheck(agent));
  }
  debugLog(
    `并行预热 ${preheatAgents.length} 个 agent 的环境检测: ${preheatAgents.join(", ")}`,
  );

  // ── 认知契约启动自检（镜像点一致性 + 插值渲染冒烟；不阻塞启动）──
  void verifyCognitionSelfCheck();

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
        // ── RECOVER-MODE 逃生舱（零依赖，最先执行）──
        // 消息文本以 `>>>RECOVER-MODE<<<` 开头 → 跳过本 hook 的一切拦截
        // （控制台可用性、环境检测、agent 检查等全部放行）。
        // 用途：插件自身 BUG 把消息入口拦死时，用户仍有通道让 agent 继续工作
        // （比如让 AI 修复插件代码）——该检查只依赖字符串前缀，不碰控制台/
        // 配置/ServiceRegistry 等任何可坏依赖。
        const firstText: string = (output?.parts ?? [])
          .filter((p) => p?.type === "text")
          .map((p) => (p as { text?: string }).text ?? "")
          .join("\n");
        if (firstText.trimStart().startsWith(">>>RECOVER-MODE<<<")) {
          const s = ctx.sessionManager.get(sessionID);
          s?.clearPendingResume(); // 清冷却定时器（RECOVER 消息 = 用户介入）
          debugLog(
            `chat.message: RECOVER-MODE 激活，跳过全部拦截 sessionID=${sessionID}`,
            sessionID,
          );
          return;
        }

        if (!agent) {
          // 无 agent 的消息 = 程序注入（session.idle 的错误回显走此路径，实测 8/8）。
          // 注入前置过 pendingErrorCallbackMessage 的话在此清除——该标记的设计消费点
          // 在下方检查处，但注入消息不带 agent 到不了那里；不清除会残留给
          // 下一条真实用户消息，导致其跳过全部检查被无条件放行。
          const injectedSession = ctx.sessionManager.get(sessionID);
          if (injectedSession?.pendingErrorCallbackMessage) {
            injectedSession.pendingErrorCallbackMessage = false;
            debugLog(
              `chat.message: 注入消息（无 agent）清除错误回调标记 sessionID=${sessionID}`,
              sessionID,
            );
          }
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
        // 标记消费点 A：注入的错误消息若带 agent（opencode 版本行为差异的兜底路径），
        // 在此消费并放行——不消费则控制台真失败场景会 报错→注入→报错 无限循环。
        // 正常用户消息到达此处时标记已被消费点 B（!agent 分支）清除，不会误放行。
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

        // ★ 统一初始化等待：控制台 + 环境检测 ★
        // 1. 控制台可用性（启动门禁 + 运行期存活复核——启动成功后被 kill
        //    的场景由 ensureControlReady 的 IPC probe 兜住，不再静默放行）
        const controlReady = await ensureControlReady();
        if (!controlReady.ok) {
          debugLog(
            `chat.message: 控制台不可用 agent=${agent} error=${controlReady.error}`,
            sessionID,
          );
          const errorMsg = `控制台不可用：${controlReady.error}`;
          await reportErrorAndAbort(
            ctx.client,
            sessionID,
            sessionData,
            errorMsg,
          );
          return;
        }

        // 控制台启动成功后，预热配置缓存。关键：shell.env hook 每轮用同步版
        // getCachedConfig() 注入环境变量（不能 await），缓存未预热时它拿到空对象
        // → IDA_PRO_HOME 等注入缺失。此处显式 refresh 填充缓存。
        await refreshConfig();

        // 2. 环境检测
        let envCheck: EnvironmentCheckResult | null = null;

        if (envCheckPromises.has(agent)) {
          // 分支 1: 命中预热 cache（检测走控制台 /api/deps，判定在服务端）
          envCheck = await envCheckPromises.get(agent)!;
          if (!envCheck.ready) {
            // 失败时重新 set 异步 preheat（fire-and-forget），让用户修复后下次有机会重试
            envCheckPromises.set(agent, preheatEnvCheck(agent));
          }
        }
        // 其他 agent → envCheck 保持 null，跳过环境检测

        if (envCheck && !envCheck.ready) {
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
        const compactionCtx = getCompactionContext();
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

        // ── 分析台账原样穿越（认知干预系统：压缩时原样注入根任务目录的 ledger.md）──
        // 台账是"结论/未测条件"的唯一记录处；压缩由总结器重写会洗掉限定词，这里原样注入。
        const ledgerBlock = buildLedgerContextBlock(session);
        if (ledgerBlock) {
          output.context.push(ledgerBlock);
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
        const session = ctx.sessionManager.get(sessionID);
        if (!session) {
          debugLog(
            `[WARN] system.transform: 跳过 — 非仪表化 agent, sessionID=${sessionID}`,
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

        // ── 认知检查点（独立于环境注入频率；仅根会话 + 五分析 agent + 有任务目录）──
        const cognitionCheckpointResult = cognitionCheckpoint(session);
        if (cognitionCheckpointResult) {
          output.system.push(cognitionCheckpointResult);
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

        const envSection = await buildEnvSection(agentName, session);
        output.system.push(envSection);

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
        const session = ctx.sessionManager.get(sessionID);
        if (!session) {
          debugLog(
            `shell.env: 跳过 — 非仪表化 agent sessionID=${sessionID}`,
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
          // 字典统一目录（路径约定恒定，无条件注入——不依赖安装状态; AI 用 $WORDLISTS_DIR/xxx 引用字典）
          output.env.WORDLISTS_DIR = WORDLISTS_DIR;
          // PATH: 前置 venv/bin（venv CLI 工具 sage/sqlmap 等）+ ~/bw-security-analysis/bin
          // （detect_tools.py 自动安装的外部工具: nuclei/ffuf/bkcrack/wrapper 等）
          const venvBin = dirname(pythonCmd);
          const toolBin = TOOLS_CMD_DIR;
          const nodeBin = resolveNodeBinPath(sessionID);
          const adbBin = resolveAndroidPlatformToolsPath(sessionID);
          debugLog(
            `shell.env PATH 注入: venvBin=${venvBin} toolBin=${toolBin} nodeBin=${nodeBin ?? "-"} adbBin=${adbBin ?? "-"}`,
            sessionID,
          );
          // filter(Boolean) 过滤空值，避免末尾分隔符(空 PATH 条目会被解释为当前目录，有 PATH injection 风险)
          // delimiter 跨平台: POSIX=':' Windows=';'（与 constants.ts 的 Windows 支持一致）
          const pathEntries = [venvBin, toolBin];
          if (nodeBin) pathEntries.push(nodeBin);
          if (adbBin) pathEntries.push(adbBin);
          output.env.PATH = [...pathEntries, process.env.PATH]
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

        // ROOT_TASK_DIR（任务级约定文件目录：台账/评审报告；根会话下等于 TASK_DIR，子会话下指向根任务目录）
        const rootTaskDir = session.rootTaskDir;
        if (rootTaskDir) {
          output.env.ROOT_TASK_DIR = rootTaskDir;
        }

        // OPENSECURITY_FLOW_ID（事件库分区标识，agent 调搜索工具时作为 group_id 传入）
        output.env.OPENSECURITY_FLOW_ID = session.flowId;

        // IDAT：从控制台配置拿 IDA_PRO_HOME，拼接 idat 路径
        // 配置读取收口到 control-config（不直接读 .ai_env）
        const idaHome = getCachedConfigValue("IDA_PRO_HOME");
        if (idaHome) {
          const exe = process.platform === "win32" ? "idat.exe" : "idat";
          const idatPath = join(idaHome, exe);
          if (existsSync(idatPath)) {
            output.env.IDAT = idatPath;
            output.env.IDA_PRO_HOME = idaHome; // 部分 IDA 工具链需要这个变量
          }
        }

        // DEEPSEEK_API_KEY 和其他配置：通过 shell.env 注入到 agent 子进程
        const allConfigs = getCachedConfig();
        for (const [key, value] of Object.entries(allConfigs)) {
          // 不覆盖系统已有的环境变量（让用户 shell export 优先）
          if (!(key in output.env) && !key.startsWith("CONTROL_")) {
            output.env[key] = value;
          }
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
            ` ROOT_TASK_DIR=${output.env.ROOT_TASK_DIR ?? "无"}` +
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
    // 职责：记录时间线（环境变量注入已迁移到 shell.env hook；任务初始化+环境检测由 chat.message 的 preheatEnvCheck 兜底）
    "tool.execute.before": async (input, output) => {
      try {
        const sid = input.sessionID;
        const session = ctx.sessionManager.requireInstrumentedAgent(
          "tool.execute.before",
          sid,
        );
        if (!session) {
          debugLog(
            `tool.execute.before: 跳过 — 非仪表化 Agent, sessionID=${sid}`,
            sid,
          );
          return;
        }
        // ── 认知检查点计数（仅根会话 + 五分析 agent）──
        if (
          session.isRootAgent &&
          SECURITY_ANALYSIS_AGENTS.includes(session.agentName)
        ) {
          session.toolCallCount++;
          if (input.tool === "bash") {
            session.commandCallCount++;
          }
        }

        debugLog(
          `tool.execute.before: tool=${input.tool} sessionID=${sid} tools=${session.toolCallCount} cmds=${session.commandCallCount}`,
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
        const session = ctx.sessionManager.requireInstrumentedAgent(
          "tool.execute.after",
          sid,
        );
        if (!session) {
          debugLog(
            `tool.execute.after: 跳过 — 非仪表化 agent, sessionID=${sid}`,
            sid,
          );
          return;
        }

        const toolName = input.tool;

        // 时间线记录：工具执行完成（计算耗时 + 操作日志）
        const startTime = toolStartTimes.get(input.callID);
        toolStartTimes.delete(input.callID);
        // 从工具参数提取 message（对齐 PentAGI executor.go:510 getMessage）
        const toolArgs = input.args as Record<string, unknown> | undefined;
        const toolMessage =
          typeof toolArgs?.message === "string"
            ? toolArgs.message.trim().slice(0, 80)
            : "";
        recordTimeline(sid, {
          timestamp: Date.now(),
          type: "tool.after",
          tool: toolName,
          detail: toolMessage || undefined,
          duration: startTime ? Date.now() - startTime : undefined,
        });

        // 写入事件库（对齐 PentAGI performer.go:198 storeToolExecutionToGraphiti）
        // 排除 Task 工具（对齐 PentAGI 排除 AgentToolType）
        if (toolName !== "task") {
          const agentName = session.agentName;
          const body = `Tool: ${toolName}\nArguments: ${JSON.stringify(input.args).slice(0, 2000)}\nInvoked by: ${agentName} Agent\nStatus: success\nResult: ${(output.output || "").slice(0, 2000)}\nContext: Session ${sid}`;
          fireAndForgetEvent(
            session,
            `${toolName} execution`,
            body,
            `${agentName} tool execution`,
            session.flowId,
          );

          // 写入 knowledge 向量库 memory（对齐 PentAGI executor.go:519 storeToolResult）
          fireAndForgetMemory(
            session,
            toolName,
            input.args,
            output.output || "",
            session.flowId,
          );
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
          session,
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

            // 取消可能武装中的冷却恢复定时器——否则定时器到期会对已删除的
            // session 发恢复消息（孤儿定时器变体，maybeResumeAnalysis 重校验兜底外的显式清理）
            session?.clearPendingResume();

            flushTimeline(sessionID);
            ctx.sessionManager.delete(sessionID);
            // 必须删持久化映射文件：sessionManager.delete 只清内存 Map，
            // 残留文件会在插件重启时被 createFromAPI 复活成脏 session。
            // 注意：removeTaskSession 是 static 方法，必须经类调用——
            // 历史版本裸调 removeTaskSession(...) 无导入，ReferenceError 被
            // catch 吞掉，持久化文件实际从未删除过（静默失败）
            TaskSessionPersistence.removeTaskSession(sessionID);

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
        // Event 是 33 个变体的 union，只有 session.created 的 properties 有 info
        // （其余是 directory/sessionID 等）——直取 .info 类型不合法，统一 cast 后取
        const props = input.event.properties as Record<string, any>;
        debugLog(
          `event: 意外异常 event=${JSON.stringify(input.event)} err=${(e as Error)?.message}`,
          props?.info?.id ?? props?.sessionID,
        );
      }
    },
  };
};
