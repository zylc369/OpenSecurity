import { describe, expect, it } from "vitest";
import { normalizeStairs, parseStairs, rampFor, segmentText, splitSentences } from "./segmentText";

describe("splitSentences 句末切分", () => {
  it("中文句号/问号/叹号断句", () => {
    expect(splitSentences("第一句。第二句？第三句！")).toEqual([
      "第一句。", "第二句？", "第三句！",
    ]);
  });
  it("英文标点断句", () => {
    expect(splitSentences("Hello world. Really? Yes!")).toEqual([
      "Hello world.", "Really?", "Yes!",
    ]);
  });
  it("小数点不误切", () => {
    expect(splitSentences("圆周率是3.14还有很多位。")).toEqual([
      "圆周率是3.14还有很多位。",
    ]);
  });
  it("省略号断句(单字符省略号)", () => {
    expect(splitSentences("他说…然后沉默了。")).toEqual(["他说…", "然后沉默了。"]);
  });
  it("换行是最优先断点", () => {
    expect(splitSentences("第一行没有标点\n第二行。")).toEqual([
      "第一行没有标点", "第二行。",
    ]);
  });
  it("连续叹号并入同句", () => {
    expect(splitSentences("太好了!!!真的吗？")).toEqual(["太好了!!!", "真的吗？"]);
  });
  it("逗号不断句(句内)", () => {
    expect(splitSentences("今天天气真好，我们出去玩。")).toEqual([
      "今天天气真好，我们出去玩。",
    ]);
  });
  it("空句块被丢弃(纯空白不产段)", () => {
    expect(splitSentences("第一句。\n\n\n第二句。")).toEqual(["第一句。", "第二句。"]);
  });
});

describe("segmentText 贪心分段", () => {
  it("短句合并到目标段长", () => {
    // 10 个 20 字句 → target 100 → 期望 2 段(各 ~100 字)
    const s = "这是一个测试句子的第部分内容哦。".repeat(1); // 15 字/句
    const text = Array.from({ length: 20 }, (_, i) => `第${i}句${s}`).join("");
    const segs = segmentText(text, 100);
    expect(segs.length).toBeGreaterThanOrEqual(2);
    for (const seg of segs) {
      // 每段以句末标点结尾(句子未被劈开)
      expect(seg).toMatch(/[。！？…!?\n]$/);
    }
    // 段的拼接无损(全文可复原)
    expect(segs.join("")).toBe(text);
  });
  it("单句超 hardMax 触发逗号兜底", () => {
    const long = "前缀，" + "无标点超长内容".repeat(100) + "，中段，" + "尾部内容".repeat(50) + "。";
    const segs = segmentText(long, 300, 600);
    expect(segs.length).toBeGreaterThan(1);
    expect(segs.join("")).toBe(long);
  });
  it("空文本返回空数组", () => {
    expect(segmentText("")).toEqual([]);
    expect(segmentText("   \n  ")).toEqual([]);
  });
  it("真实图书样例(对话引号内句末可断)", () => {
    const LQ = "\u201C"; // 弯开引号 “
    const RQ = "\u201D"; // 弯闭引号 ”
    const text = `${LQ}饭好了。${RQ}她说。${LQ}马上来！${RQ}孩子们喊道。\n崔桂英笑了…`;
    const sents = splitSentences(text);
    expect(sents).toContain(`${LQ}饭好了。${RQ}`);  // 闭引号并入句尾
    expect(sents).toContain(`她说。`);
  });
});

describe("rampFor 分段设置缩放(v2: 梯形 n×f 封顶 target)", () => {
  it("首段 30 字梯形序列", () => {
    expect(rampFor(30, 300)).toEqual([30, 60, 90, 120, 150, 180, 210, 240, 270, 300]);
  });
  it("首段 60/100 字梯形序列", () => {
    expect(rampFor(60, 300)).toEqual([60, 120, 180, 240, 300]);
    expect(rampFor(100, 300)).toEqual([100, 200, 300]);
  });
  it("首段 10 字 → 10 步进全档; 默认 20→[20,40,60,80]", () => {
    const r = rampFor(10, 300);
    expect(r[0]).toBe(10);
    expect(r[r.length - 1]).toBe(300);
    expect(r.length).toBe(30);
    expect(rampFor(20, 80)).toEqual([20, 40, 60, 80]);
  });
});

describe("分段参数不变量(联动防回归)", () => {
  const NOVEL = "这儿孙满堂的甜蜜，两口子还没来得及品砸出味儿来，可家里的米缸眼瞅着就要掏见底了。俗话说半大小子吃垮老子，包括女娃娃在内，都正是长身体的时候，贼能吃，那肚皮个个都跟无底洞似的，崔桂英家开饭主食都得用缸来盛，而且一缸还不够，灶上还温着一锅。两口子虽说早已孙辈成群，可年纪并不算大，且按当下农村规矩，除非你生病卧床失去劳动能力，否则只要你还有力气下田，无论多老，也没资格享受来自儿女的餐饭供奉。“别抢，别抢，饿死鬼投胎啊都是，都给我排好队！”孩子们拿着碗来接，崔桂英负责打粥。最后一个过来的是一个十岁的小男孩，他身穿牛仔吊带裤，脚上是时兴凉鞋，皮肤白嫩，面带腼腆。和周围兄弟姐妹们那种玩得脏兮兮鼻涕吸溜吸溜的模样，有些格格不入。“小远侯，来，给你放这里吃。”";

  it("target=80: 首段≤30 / 每段≤160 / 无损 (v2: 软断允许中间段 <80)", () => {
    const segs = segmentText(NOVEL, 80);
    expect(segs.length).toBeGreaterThanOrEqual(3);
    expect(segs[0].length).toBeLessThanOrEqual(30);
    for (const s of segs) expect(s.length).toBeLessThanOrEqual(160);
    expect(segs.join("")).toBe(NOVEL);
  });

  it("rampFor: 任意 target 下每项不超 max(首段, target)——180 联动回归守卫", () => {
    for (const t of [80, 120, 300]) {
      for (const f of [10, 20, 30, 60, 100]) {
        for (const v of rampFor(f, t)) {
          expect(v).toBeLessThanOrEqual(Math.max(f, t));
        }
      }
    }
  });

  it("预检+守门: 小句累积遇超长句不拖拽(v2 防回归)", () => {
    const S20 = "甲".repeat(19) + "。";     // 整句 20 字
    const S19 = "乙".repeat(18) + "。";     // 整句 19 字
    const LONG = "丙".repeat(159) + "。";   // 单句 160 字（超 hm=120 → 兜底切 60/60/40）
    const t = S20.repeat(5) + S19 + LONG;
    const segs = segmentText(t, 80);
    // v2: 59 字后遇超长片在硬限处断(120)——不再出现 119+ 合并超长
    expect(segs.map((s) => s.length)).toEqual([20, 40, 59, 120, 40]);
    expect(segs.join("")).toBe(t);
  });

  it("超长句兜底随 target 联动(单句 300+ 无句号 → 每片 ≤ 2*target)", () => {
    const long = "第，" + "很长内容".repeat(80) + "。";
    const segs = segmentText(long, 80);
    for (const s of segs) expect(s.length).toBeLessThanOrEqual(160);
  });

  it("首段长句逗号级切分(首响优先)", () => {
    // 尾段需 >=半目标(40字) 以免被"短尾并回"二次合并, 保证独立观测逗号切分
    const head = "这儿孙满堂的甜蜜，两口子还没来得及品砸出味儿来，可家里的米缸眼瞅着就要掏见底了。";
    const tail = "可家里的米缸眼瞅着就要掏见底了。孩子们还在院子里追着闹腾，灶上的火也得看紧了别烧干锅。";
    const segs = segmentText(head + tail, 80);
    expect(segs[0]).toBe("这儿孙满堂的甜蜜，两口子还没来得及品砸出味儿来，"); // 逗号级切分: 逗号保留前段尾
    expect(segs.length).toBeGreaterThanOrEqual(2);
  });
});

describe("阶梯输入解析(normalizeStairs/parseStairs)", () => {
  it("解析与规范化(排序去重)", () => {
    expect(parseStairs("20,40,60,80")).toEqual([20, 40, 60, 80]);
    expect(parseStairs("80, 20，40")).toEqual([20, 40, 80]); // 全角逗号/乱序 → 排序去重
    expect(parseStairs("20,,40")).toEqual([20, 40]);
    expect(normalizeStairs([30, 60])).toEqual([30, 60]);
  });
  it("非法输入回 null(UI 回退安全)", () => {
    expect(parseStairs("")).toBeNull();
    expect(parseStairs("abc")).toBeNull();
    expect(parseStairs("20,-5")).toBeNull();
    expect(normalizeStairs([])).toBeNull();
    expect(normalizeStairs([1, 2, 3, 4, 5, 6, 7, 8, 9])).toBeNull(); // >8 档
  });
});

describe("尾并回(v2: 阈值=首段分段字数)", () => {
  it("<首段值(20)的尾段并入前段 / 中间 31 字段独立", () => {
    const segs = segmentText(NOVEL_FIXTURE, 80);
    expect(segs.map((s) => s.length)).toEqual([24, 63, 31, 100, 108]);
    expect(segs.join("")).toBe(NOVEL_FIXTURE);
  });
  it(">=首段值的尾段保留独立", () => {
    const S13 = "够二十字的第一句内容哦哦哦。";
    const S19 = "凑八十字段的内容内容内容内容内容。";
    const S44 = "独立的尾巴内容这一段比较长会被保留下来作为单独的一段哦。";
    const t = S13.repeat(2) + S19.repeat(5) + S44.repeat(2);
    const segs = segmentText(t, 80);
    expect(segs.map((s) => s.length)).toEqual([28, 51, 62, 28]); // 尾 28(>=20) 独立
    expect(segs.join("")).toBe(t);
  });
});

describe("分段器 v2 守门(软标点断 / 硬结束)", () => {
  it("无标点长串: 硬切(序列固定)且无损", () => {
    const t = "甲".repeat(500);
    const segs = segmentText(t);
    expect(segs.map((s) => s.length)).toEqual([60, 60, 60, 120, 120, 80]);
    expect(segs.join("")).toBe(t);
  });
  it("120/130 无标点边界", () => {
    expect(segmentText("甲".repeat(120)).map((s) => s.length)).toEqual([60, 60]);
    expect(segmentText("甲".repeat(130)).map((s) => s.length)).toEqual([60, 70]);
  });
  it("恰在软限内不触发(20+20=40)", () => {
    const t = "甲".repeat(21) + "。" + "乙".repeat(17) + "。";
    expect(segmentText(t).map((s) => s.length)).toEqual([40]);
  });
  it("超长句在软标点断(不整吞到句末)", () => {
    const long = "短句甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲甲！" +
      "长句内容内容内容内容内容内容内容内容内容内容，后半段还有更多内容内容内容内容内容内容内容内容。";
    const segs = segmentText(long);
    expect(segs.join("")).toBe(long);
    for (const s of segs) expect(s.length).toBeLessThanOrEqual(60);
  });
  it("数字间冒号/逗号不误切(12:30 / 1,000)", () => {
    const t = "等到了指定的时刻12:30再出发，另外花了1,000元买的东西。";
    const segs = segmentText(t, 20);
    expect(segs.join("")).toBe(t);
    for (const s of segs) expect(s.endsWith("12")).toBe(false);
  });
  it("单短句/引号收尾(回归)", () => {
    expect(segmentText("你好。")).toEqual(["你好。"]);
    expect(segmentText("“饭好了。”她说。“马上来！”")).toEqual(["“饭好了。”她说。“马上来！”"]);
  });
});

const NOVEL_FIXTURE = "这儿孙满堂的甜蜜，两口子还没来得及品砸出味儿来，可家里的米缸眼瞅着就要掏见底了。俗话说半大小子吃垮老子，包括女娃娃在内，都正是长身体的时候，贼能吃，那肚皮个个都跟无底洞似的，崔桂英家开饭主食都得用缸来盛，而且一缸还不够，灶上还温着一锅。两口子虽说早已孙辈成群，可年纪并不算大，且按当下农村规矩，除非你生病卧床失去劳动能力，否则只要你还有力气下田，无论多老，也没资格享受来自儿女的餐饭供奉。“别抢，别抢，饿死鬼投胎啊都是，都给我排好队！”孩子们拿着碗来接，崔桂英负责打粥。最后一个过来的是一个十岁的小男孩，他身穿牛仔吊带裤，脚上是时兴凉鞋，皮肤白嫩，面带腼腆。和周围兄弟姐妹们那种玩得脏兮兮鼻涕吸溜吸溜的模样，有些格格不入。“小远侯，来，给你放这里吃。”";
