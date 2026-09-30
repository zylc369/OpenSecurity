/**
 * configGrouping 纯函数测试: 顺序/剔除/组内排序/契约防御。
 */
import { describe, expect, it } from "vitest";
import { groupByCategory, findGroup, writableUpdates } from "./configGrouping";
import type { ConfigMetaMap, ConfigCategoryView, ConfigMetaItem } from "../types";

function item(over: Partial<ConfigMetaItem>): ConfigMetaItem {
  return {
    label: "", type: "text", hint: "", required: false,
    default_value: "", readonly: false,
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

  it("组内排序: required 优先 + label 字典序", () => {
    const entries: ConfigMetaMap = {
      b_opt: item({ category_code: "tools", label: "B" }),
      a_req: item({ category_code: "tools", label: "A", required: true }),
      c_opt: item({ category_code: "tools", label: "C" }),
    };
    const groups = groupByCategory(entries, cats);
    expect(groups[0]?.keys).toEqual(["a_req", "b_opt", "c_opt"]);
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

  it("findGroup 命中与空态", () => {
    const groups = groupByCategory(
      { Y: item({ category_code: "tools", label: "Y" }) }, cats);
    expect(findGroup(groups, "tools")?.desc).toBe("工具");
    expect(findGroup(groups, "models")).toBeNull();
  });
});
