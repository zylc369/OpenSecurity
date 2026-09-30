/**
 * 配置页纯函数（分组 / 可写过滤 / 平铺分列；服务端 categories 数组驱动）。
 *
 * 规则:
 *   • 分组顺序 = categories 数组顺序（服务端枚举定义序）
 *   • 组内顺序 = entries 键序 = 服务端声明序（与分类顺序同源权威——
 *     后端 _all_fields 清单拼接序天然 required 在前、同类配置相邻声明即
 *     相邻展示; 调整展示顺序在后端声明处做）
 *   • 零条目的分类剔除（服务端已保证，此处防御性兜底）
 *   • 条目 category_code 不在 categories 列表中 → 静默丢弃（契约异常防御）
 *
 * 不在前端本地排序: 曾用 label.localeCompare 组内排序——中文 locale 下按拼音
 * 重排（"超…"与"权…"被拆到首尾）、跨机器顺序随客户端 locale 漂移不可复现。
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
 * 页面可保存子集: 仅属于本页面（meta entries 声明）且非 readonly 的键。
 *
 * 值接口已按场景返回生效值（surface 轴），但过滤仍必要——readonly 键
 * （写接口 422）与未声明键的防御性剔除，与服务端 _guard_surface 校验
 * 对齐（双保险）。
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
 * 保存子集: 仅与基准值（base = 加载时的生效值）不同的键（先经 writableUpdates
 * 的页面/readonly 过滤，值统一 trim 后比较与提交）。
 *
 * 值接口返回生效值（未配置键含声明默认）——全量回传会把默认值冻结进 .ai_env
 * （服务端后续调默认不再跟随），故只提交变化键; "改回默认同值"不写盘。
 */
export function dirtyUpdates(
  values: Record<string, string>,
  base: Record<string, string>,
  entries: ConfigMetaMap,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(writableUpdates(values, entries))) {
    const trimmed = (v ?? "").trim();
    if ((base[k] ?? "") !== trimmed) out[k] = trimmed;
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
