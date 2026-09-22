import { join } from "path";
import { statSync, readFileSync } from "fs";
import * as yaml from "js-yaml";
import { AGENTS_RULES_DIR } from "./constants";
import { debugLog } from "./logging";

interface SnippetCacheEntry {
  content: string | null;
  mtime: number;
}
const snippetCache = new Map<string, SnippetCacheEntry>();

/** 占位符语法源：`{{buwai-rule:<名>}}`（<名> 限 [a-zA-Z0-9_-]）；展开方用 new RegExp(SOURCE, "g") */
export const BUWAI_RULE_PLACEHOLDER_SOURCE = "\\{\\{buwai-rule:([a-zA-Z0-9_-]+)\\}\\}";
/** 占位符前缀快筛（includes 判断）；语法变更时与 SOURCE 同步 */
export const BUWAI_RULE_PLACEHOLDER_PREFIX = "{{buwai-rule:";

/** agent 文件探测结果：一次读取同时得到存在性 / 扩展标记 / 可展开占位符 */
export interface AgentFileInspection {
  exists: boolean;
  hasExtensionId: boolean;
  hasPlaceholders: boolean;
}

interface InspectionCacheEntry {
  inspection: AgentFileInspection;
  mtime: number;
}
const inspectionCache = new Map<string, InspectionCacheEntry>();

// 解析 YAML frontmatter（使用 js-yaml，支持多行/引号/嵌套等完整 YAML 语法）
function parseFrontmatter(content: string): Record<string, any> {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!match) return {};
  try {
    const parsed = yaml.load(match[1]);
    return (parsed && typeof parsed === "object") ? (parsed as Record<string, any>) : {};
  } catch {
    return {};
  }
}

// 探测 agent .md：存在性 + buwai-extension-id 声明 + 是否有可展开占位符。
// 项目 agent（isProjectAgent=true）文件缺失、或任何非 ENOENT 读取异常 → [ERROR]；
// 非项目 agent（内置 build/plan/general 等）无对应文件是常态，静默（跳过由调用方记录）
export function inspectAgentFile(
  agentFile: string,
  isProjectAgent: boolean,
): AgentFileInspection {
  try {
    const stat = statSync(agentFile);
    const cached = inspectionCache.get(agentFile);
    if (cached && cached.mtime === stat.mtimeMs) return cached.inspection;
    const content = readFileSync(agentFile, "utf-8");
    const inspection: AgentFileInspection = {
      exists: true,
      hasExtensionId: "buwai-extension-id" in parseFrontmatter(content),
      hasPlaceholders: new RegExp(BUWAI_RULE_PLACEHOLDER_SOURCE).test(content),
    };
    inspectionCache.set(agentFile, { inspection, mtime: stat.mtimeMs });
    return inspection;
  } catch (e) {
    const err = e as NodeJS.ErrnoException;
    if (err?.code === "ENOENT") {
      if (isProjectAgent) {
        debugLog(
          `[ERROR] inspectAgentFile: 项目 Agent 文件缺失，占位符不会展开: ${agentFile}`,
        );
      }
    } else {
      debugLog(
        `[ERROR] inspectAgentFile 异常: ${agentFile} — ${err?.code ?? ""} ${err?.message ?? e}`,
      );
    }
    return { exists: false, hasExtensionId: false, hasPlaceholders: false };
  }
}

// 加载 agents-rules/<name>.md 片段文件，带 mtime 缓存
export function loadSnippet(name: string): string | null {
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

/**
 * 加载动态片段。
 */
export function resolveDynamicRuleSnippetName(
  securityAgentName: string | null | undefined, dynamicTag: string): string | null {
  if (!securityAgentName) {
    return null;
  }

  const index = dynamicTag.indexOf("_");
  if (index < 0) {
    debugLog(`解析动态规则片段: 没有片段名: ${dynamicTag}`)
    return null;
  }

  if (dynamicTag.length === 1) {
    debugLog(`解析动态规则片段: 片段名不合法: ${dynamicTag}`)
    return null;
  }

  const snippetNamePrefix = dynamicTag.substring(index + 1);
  debugLog(`解析动态规则片段: 片段名前缀: ${snippetNamePrefix}`)
  const snippetName = `dynamic-by-agent-${snippetNamePrefix}-${securityAgentName}`
  debugLog(`解析动态规则片段: 片段名: ${snippetName}`)
  return snippetName;
}
