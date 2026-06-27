import { join } from "path";
import { statSync, readFileSync } from "fs";
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

// 解析 YAML frontmatter（仅扁平 key-value，不处理嵌套结构）
function parseFrontmatter(content: string): Record<string, string> {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!match) return {};
  const result: Record<string, string> = {};
  for (const line of match[1].split(/\r?\n/)) {
    const kv = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/);
    if (kv) result[kv[1]] = kv[2].trim();
  }
  return result;
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
