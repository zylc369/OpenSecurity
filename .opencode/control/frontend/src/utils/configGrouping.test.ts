/**
 * configGrouping 纯函数测试: 顺序/剔除/组内排序/契约防御/平铺分列。
 */
import { describe, expect, it } from "vitest";
import {
  groupByCategory, findGroup, writableUpdates, dirtyUpdates,
  estimateTileHeight, masonryDistribute,
} from "./configGrouping";
import type { GroupedCategory } from "./configGrouping";
import type { ConfigMetaMap, ConfigCategoryView, ConfigMetaItem } from "../types";

function item(over: Partial<ConfigMetaItem>): ConfigMetaItem {
  return {
    label: "", type: "text", hint: "", required: false,
    default_value: "", value: "", readonly: false,
    category_code: "other", category_desc: "其他", ...over,
  };
}

const cats: ConfigCategoryView[] = [
  { code: "tools", desc: "工具" },
  { code: "models", desc: "模型" },
  { code: "other", desc: "其他" },
];

describe("groupByCategory", () => {
  it("分组顺序严格 = categories 数组序（非字典序）", () => {
    const entries: ConfigMetaMap = {
      Z_LAST: item({ category_code: "tools", label: "Z" }),
      A_FIRST: item({ category_code: "models", label: "A" }),
    };
    const groups = groupByCategory(entries, cats);
    expect(groups.map((g) => g.code)).toEqual(["tools", "models"]);
  });

  it("零条目分类剔除（服务端已保证，防御兜底）", () => {
    const entries: ConfigMetaMap = {
      ONLY_ONE: item({ category_code: "models", label: "M" }),
    };
    const groups = groupByCategory(entries, cats);
    expect(groups.map((g) => g.code)).toEqual(["models"]);
  });

  it("组内顺序 = entries 声明序（服务端权威，不本地排序）", () => {
    const entries: ConfigMetaMap = {
      z_first: item({ category_code: "tools", label: "超" }),
      a_mid: item({ category_code: "tools", label: "安", required: true }),
      m_last: item({ category_code: "tools", label: "权" }),
    };
    const groups = groupByCategory(entries, cats);
    // 不按 label 拼音/码点、不按 required 重排——保持服务端声明序
    //（required 在前由后端清单拼接序保证，非前端职责）
    expect(groups[0]?.keys).toEqual(["z_first", "a_mid", "m_last"]);
  });

  it("category_code 不在 categories 列表 → 静默丢弃", () => {
    const entries: ConfigMetaMap = {
      X: item({ category_code: "ghost", label: "X" }),
      Y: item({ category_code: "tools", label: "Y" }),
    };
    const groups = groupByCategory(entries, cats);
    expect(groups.flatMap((g) => g.keys)).toEqual(["Y"]);
  });

  it("writableUpdates: 只留本页面可写键（过滤其他 surface 与 readonly）", () => {
    const entries: ConfigMetaMap = {
      OWN: item({ label: "own" }),
      RO: item({ label: "ro", readonly: true }),
    };
    const values: Record<string, string> = {
      OWN: "1", RO: "1", REMOTE_KEY: "x", UNKNOWN: "y",
    };
    expect(writableUpdates(values, entries)).toEqual({ OWN: "1" });
  });

  it("dirtyUpdates: 仅提交与基准不同的键（trim 后比较; 防默认值冻结进 .ai_env）", () => {
    const entries: ConfigMetaMap = {
      A: item({ label: "a" }),
      B: item({ label: "b" }),
      RO: item({ label: "ro", readonly: true }),
    };
    const base: Record<string, string> = { A: "300", B: "x" };
    const values: Record<string, string> = {
      A: "400",      // 变化 → 提交
      B: "x",        // 未变 → 不提交
      RO: "y",       // readonly → 过滤
    };
    expect(dirtyUpdates(values, base, entries)).toEqual({ A: "400" });
    // 改回默认同值 + 首尾空格 → 不写盘
    expect(dirtyUpdates({ ...values, A: " 300 " }, base, entries))
      .toEqual({});
    // 基准缺的键（新值）→ 提交
    expect(dirtyUpdates({ C_NEW: "v" } as Record<string, string>, base, { C_NEW: item({ label: "c" }) }))
      .toEqual({ C_NEW: "v" });
  });

  it("findGroup 命中与空态", () => {
    const groups = groupByCategory(
      { Y: item({ category_code: "tools", label: "Y" }) }, cats);
    expect(findGroup(groups, "tools")?.desc).toBe("工具");
    expect(findGroup(groups, "models")).toBeNull();
  });
});

describe("平铺分列（estimateTileHeight / masonryDistribute）", () => {
  const mk = (code: string, keys: string[]): GroupedCategory => ({
    code, desc: code, keys,
  });

  it("estimateTileHeight: 无 hint = 62 + 46/字段; hint 每行 +20（42 字/行）", () => {
    const entries: ConfigMetaMap = {
      k1: item({}),
      k2: item({ hint: "a".repeat(43) }), // 43 字 → 2 行
    };
    expect(estimateTileHeight(mk("a", ["k1"]), entries)).toBe(108);
    expect(estimateTileHeight(mk("a", ["k2"]), entries)).toBe(62 + 46 + 40);
  });

  it("最短列优先: 高卡之后的卡回填矮列，不堆到后列", () => {
    const entries: ConfigMetaMap = {
      k1: item({}), k2: item({}), k3: item({}), k4: item({}), k5: item({}),
    };
    const gs = [
      mk("a", ["k1"]),             // 108
      mk("b", ["k2", "k3"]),       // 154
      mk("c", ["k1", "k2", "k3"]), // 200——高卡
      mk("d", ["k4"]),             // 108
      mk("e", ["k5"]),             // 108
    ];
    const cols = masonryDistribute(gs, entries, 2);
    expect(cols.map((b) => b.map((g) => g.code)))
      .toEqual([["a", "c"], ["b", "d", "e"]]);
  });

  it("列高并列时取最左列", () => {
    const entries: ConfigMetaMap = { k: item({}) };
    const gs = [mk("a", ["k"]), mk("b", ["k"]), mk("c", ["k"])];
    // a→c0(122); b→c1(122); c: c0/c1 并列 → 最左 c0
    const cols = masonryDistribute(gs, entries, 2);
    expect(cols.map((b) => b.map((g) => g.code))).toEqual([["a", "c"], ["b"]]);
  });

  it("1 列 = 全部原序; 列数 > 组数时保留空列", () => {
    const entries: ConfigMetaMap = { k: item({}) };
    const gs = [mk("a", ["k"]), mk("b", ["k"])];
    expect(masonryDistribute(gs, entries, 1).map((b) => b.map((g) => g.code)))
      .toEqual([["a", "b"]]);
    const wide = masonryDistribute(gs, entries, 4);
    expect(wide).toHaveLength(4);
    expect(wide.map((b) => b.map((g) => g.code)))
      .toEqual([["a"], ["b"], [], []]);
  });
});
