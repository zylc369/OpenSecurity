import { describe, expect, it } from "vitest";
import { rampFor, segmentText, splitSentences } from "./segmentText";

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

describe("rampFor 分段设置缩放", () => {
  it("首段 30 字 ≈ 默认序列", () => {
    expect(rampFor(30, 300)).toEqual([30, 81, 180]);
  });
  it("首段 60/100 字随比例放大且不超常规段长", () => {
    expect(rampFor(60, 300)).toEqual([60, 162, 300]);
    expect(rampFor(100, 300)).toEqual([100, 270, 300]);
  });
  it("首段最小值保底 80/180", () => {
    expect(rampFor(10, 300)).toEqual([10, 80, 180]);
  });
});
