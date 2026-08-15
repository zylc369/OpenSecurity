/**
 * 页面分类常量收口。
 *
 * 唯一维护点：分类 key、显示名、计数单位词。
 * 消费方：锚点导航、卡片标题、环境就绪 Popover、E2E 断言。
 * 规则（用户反馈固化）：
 *   • 显示名在 Popover / 卡片标题 / 锚点 三处必须一字不差
 *   • 顺序 = 本数组顺序（页面分区顺序）
 *   • Tag 计数格式统一 `{ok}/{total} {unit}`
 */
export interface CategoryDef {
  key: CategoryKey;
  title: string;
  /** 计数单位词（如 "1/1 镜像" 的 "镜像"） */
  unit: string;
}

export type CategoryKey = "docker" | "models" | "deps" | "tools" | "config";

export const CATEGORIES: readonly CategoryDef[] = [
  { key: "docker", title: "Docker", unit: "镜像" },
  { key: "models", title: "模型", unit: "就绪" },
  { key: "deps", title: "Python 依赖", unit: "已装" },
  { key: "tools", title: "外部工具", unit: "可用" },
  { key: "config", title: "配置", unit: "完整" },
] as const;
