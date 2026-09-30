/**
 * 配置页纯函数（分组 / 可写过滤 / 平铺分列；服务端 categories 数组驱动）。
 *
 * 规则:
 *   • 分组顺序 = categories 数组顺序（服务端枚举定义序）
 *   • 零条目的分类剔除（服务端已保证，此处防御性兜底）
 *   • 组内排序: required 优先 + label 字典序（沿用配置页既有排序规则）
 *   • 条目 category_code 不在 categories 列表中 → 静默丢弃（契约异常防御）
 */

import type { ConfigMetaMap, ConfigCategoryView } from "../types";

export interface GroupedCategory {
  code: string;
  desc: string;
  /** 组内有序条目键 */
  keys: string[];
}

export function groupByCategory(
  entries: ConfigMetaMap,
  categories: ConfigCategoryView[],
): GroupedCategory[] {
  const result: GroupedCategory[] = [];
  for (const cat of categories) {
    const keys = Object.entries(entries)
      .filter(([, m]) => m.category_code === cat.code)
      .sort((a, b) =>
        Number(b[1].required) - Number(a[1].required) ||
        a[1].label.localeCompare(b[1].label))
      .map(([k]) => k);
    if (keys.length > 0) {
      result.push({ code: cat.code, desc: cat.desc, keys });
    }
  }
  return result;
}

/** 分组查找便捷函数（页面当前分类 → 分组对象; 无条目返回 null）。 */
export function findGroup(
  groups: GroupedCategory[],
  code: string,
): GroupedCategory | null {
  return groups.find((g) => g.code === code) ?? null;
}

/**
 * 页面可保存子集: 仅属于本页面（meta entries）且非 readonly 的键。
 *
 * GET /api/config 返回全量值（含其他 surface 的键），整包回传会被服务端
 * surface 写校验 422——保存前必须过滤（服务端校验的前端镜像，双保险）。
 */
export function writableUpdates(
  values: Record<string, string>,
  entries: ConfigMetaMap,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    const m = entries[k];
    if (m && !m.readonly) out[k] = v;
  }
  return out;
}

/**
 * 平铺卡高度估算（仅用于列分配——相对大小决定贪心结果，无需像素精确）:
 *   卡头 + 内边距 ≈ 62; 每字段（label/控件行）≈ 46; hint 每行 ≈ 20（约 42 字/行）。
 */
export function estimateTileHeight(
  g: GroupedCategory,
  entries: ConfigMetaMap,
): number {
  let h = 62;
  for (const k of g.keys) {
    const hint = entries[k]?.hint ?? "";
    h += 46 + (hint ? 20 * Math.ceil(hint.length / 42) : 0);
  }
  return h;
}

/**
 * 平铺列分配——瀑布流同策略: 最短列优先（高度并列取最左列），各列收尾齐平。
 *
 * 为什么不用 CSS 多列（column-count）: 多列是列优先平衡且卡片不可切割——某列
 * 一旦放入高卡就提前结束，后续卡全部堆到下一列，出现「左列空、右列堆」失衡。
 */
export function masonryDistribute(
  groups: GroupedCategory[],
  entries: ConfigMetaMap,
  cols: number,
): GroupedCategory[][] {
  const n = Math.max(1, Math.floor(cols));
  const buckets: GroupedCategory[][] = Array.from({ length: n }, () => []);
  const heights = new Array<number>(n).fill(0);
  for (const g of groups) {
    let idx = 0;
    for (let i = 1; i < n; i++) {
      if (heights[i] < heights[idx]) idx = i;
    }
    buckets[idx].push(g);
    heights[idx] += estimateTileHeight(g, entries) + 14; // 14 = 列内卡片间距
  }
  return buckets;
}
