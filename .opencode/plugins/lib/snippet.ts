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

interface FrontmatterCacheEntry {
  result: boolean;
  mtime: number;
}
const frontmatterCache = new Map<string, FrontmatterCacheEntry>();

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

// 检查 agent .md 是否声明了 buwai-extension-id（有此字段才做占位符展开）
export function hasBuwaiExtensionId(agentFile: string): boolean {
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
