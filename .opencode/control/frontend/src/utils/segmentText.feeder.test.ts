/**
 * SegmentFeeder（惰性分段器）测试:
 *  ① 等价性——对同一文本, feeder 全量拉取逐段 === segmentText() 输出
 *  ② 惰性——791 万字下 next() 首调不扫全文（<5ms）
 *  ③ 边界——空文本/纯空白/无句末残句/超长句/首段 cut/尾段并回/参数变体
 */
import { describe, expect, it } from "vitest";
import { createSegmentFeeder, rampFor, segmentText } from "./segmentText";

/** 语料: 覆盖现有测试全部分类（用户文本/NOVEL/复现串/长尾/边界） */
const S13 = "够二十字的第一句内容哦哦哦。";
const S19 = "凑八十字段的内容内容内容内容内容。";
const S44 = "独立的尾巴内容这一段比较长会被保留下来作为单独的一段哦。";
const S20 = "甲".repeat(19) + "。";
const LONG = "丙".repeat(159) + "。";
const NOVEL = "这儿孙满堂的甜蜜，两口子还没来得及品砸出味儿来，可家里的米缸眼瞅着就要掏见底了。俗话说半大小子吃垮老子，包括女娃娃在内，都正是长身体的时候，贼能吃，那肚皮个个都跟无底洞似的，崔桂英家开饭主食都得用缸来盛，而且一缸还不够，灶上还温着一锅。两口子虽说早已孙辈成群，可年纪并不算大，且按当下农村规矩，除非你生病卧床失去劳动能力，否则只要你还有力气下田，无论多老，也没资格享受来自儿女的餐饭供奉。“别抢，别抢，饿死鬼投胎啊都是，都给我排好队！”孩子们拿着碗来接，崔桂英负责打粥。最后一个过来的是一个十岁的小男孩，他身穿牛仔吊带裤，脚上是时兴凉鞋，皮肤白嫩，面带腼腆。和周围兄弟姐妹们那种玩得脏兮兮鼻涕吸溜吸溜的模样，有些格格不入。“小远侯，来，给你放这里吃。”";

const CASES: { name: string; text: string }[] = [
  { name: "空文本", text: "" },
  { name: "纯空白", text: "  \n\n \u3000\u3000 " },
  { name: "无句末残句", text: "这是一段没有句号的文字" },
  { name: "单短句", text: "你好。" },
  { name: "用户文本", text: "“小远侯，来，给你放这里吃。”\n\n\n\u3000\u3000“谢谢奶奶。”\n\n\n\u3000\u3000崔桂英笑着摸了摸孩子的头，他是这一大帮亲孙子孙女里头，唯一一个外孙，不过现在也不算了。" },
  { name: "NOVEL", text: NOVEL },
  { name: "复现串(超长句拖拽)", text: S20.repeat(5) + S19 + LONG },
  { name: "长尾串", text: S13.repeat(2) + S19.repeat(5) + S44.repeat(2) },
  { name: "首段cut场景(长首句逗号)", text: "这是很长很长的第一句，它超过阈值，需要在逗号处切开。后面还有一句。" },
  { name: "多换行空白块", text: "第一句。\n\n\n\n第二句。\n\n第三句。" },
  { name: "英文句号小数点", text: "价格是 3.14 元。下一条。" },
];

function pullAll(feeder: { next(): string | null }): string[] {
  const out: string[] = [];
  for (;;) {
    const s = feeder.next();
    if (s === null) break;
    out.push(s);
  }
  return out;
}

describe("SegmentFeeder 等价性（与全量版逐段一致）", () => {
  for (const c of CASES) {
    it(`${c.name}`, () => {
      const expected = segmentText(c.text);
      const got = pullAll(createSegmentFeeder(c.text));
      expect(got).toEqual(expected);
      expect(got.join("")).toBe(expected.join(""));
    });
  }

  it("参数变体: target/firstTargets 组合", () => {
    for (const target of [40, 80, 120]) {
      for (const ft of [rampFor(20, target), [20, 40], [], [100]]) {
        const expected = segmentText(NOVEL, target, 0, ft);
        const got = pullAll(createSegmentFeeder(NOVEL, target, 0, ft));
        expect(got, `target=${target} ft=${JSON.stringify(ft)}`).toEqual(expected);
      }
    }
  });

  it("producedCount 与产出段数一致", () => {
    const feeder = createSegmentFeeder(NOVEL);
    let n = 0;
    for (;;) {
      const s = feeder.next();
      if (s === null) break;
      n++;
      expect(feeder.producedCount).toBe(n);
    }
    expect(n).toBe(segmentText(NOVEL).length);
  });
});

describe("SegmentFeeder 惰性", () => {
  it("791 万字: next() 首调不扫全文（阈值 50ms——CI 余量 10×）", () => {
    const big = (NOVEL + "\n").repeat(Math.ceil(7_910_000 / NOVEL.length));
    const feeder = createSegmentFeeder(big);
    const t0 = performance.now();
    const first = feeder.next();
    const dt = performance.now() - t0;
    expect(first).toBeTruthy();
    expect(first!.length).toBeLessThanOrEqual(32);  // 首段 ≈20 字档
    // 防"首调 O(n) 全扫"回归: 全扫 791 万字为百 ms 级; 本机基线 <5ms,
    // CI 共享 runner 波动（实测 6.9ms）——阈值取 50ms 留 10× 环境余量。
    expect(dt).toBeLessThan(50);
  });
});
