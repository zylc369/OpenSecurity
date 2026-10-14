/**
 * 听书分段器（TTS 段级协议的客户端切分——Legado 业内模式）。
 *
 * 规则（需求 2026-10-15-tts-console-rebuild §1.5）:
 *  - 切点只落"句末"——句子永不劈开（TTS 后割裂的根源是句中断点）
 *  - 强断点: 换行 / 。！？…!? 以及英文句号 .（小数点防误切: 前后皆数字则跳过）
 *  - 句内符号（，、；：——）不作为断点
 *  - 引号内句末标点是合法断点（对话小说必须——不做引号配对保护）
 *  - 贪心合并句块到目标段长（~300 字; 加句后 ≥target 即收段）
 *  - 兜底: 单句超 hardMax（600 字）在逗号/顿号处硬切（韵律小损防超长段）
 */

/** 句末终止字符（英文句号单独处理——小数点防误切） */
const SENT_ENDERS = new Set(["。", "！", "？", "…", "!", "?", "\n"]);
/** 句末符后可并入当前句的收尾符（闭引号/闭书名号——"饭好了。"的引号不劈开） */
// 注意只含「闭」引号——U+201C(“)是开引号不能并入(会把下句开头吞进上句);
// ASCII 直引号(" ')开闭歧义, 保守不含
const CLOSERS = new Set(["”", "’", "」", "』", "）", ")", "》"]);

function isDigit(ch: string | undefined): boolean {
  return ch !== undefined && ch >= "0" && ch <= "9";
}

/**
 * 第一遍: 全文 → 句块数组（每块以句末标点（可带闭引号收尾）。
 * 句末符后的连续同类收尾（!!!/？？？/……）与闭引号并入当前句;
 * 段首尾空白丢弃（TTS 不读空白）。 */
export function splitSentences(text: string): string[] {
  const raw: string[] = [];
  let cur = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    cur += ch;
    const isEnder = ch === "."
      ? !(isDigit(text[i - 1]) && isDigit(text[i + 1]))
      : SENT_ENDERS.has(ch);
    if (isEnder) {
      // 吞并后续: 连续句末符(!!!/？？？/……) 与闭引号("」』等)
      let j = i + 1;
      while (j < text.length) {
        const nc = text[j];
        const ncIsEnder = nc === "."
          ? !(isDigit(text[j - 1]) && isDigit(text[j + 1]))
          : SENT_ENDERS.has(nc);
        if (ncIsEnder || CLOSERS.has(nc)) {
          cur += nc;
          j++;
        } else {
          break;
        }
      }
      raw.push(cur);
      cur = "";
      i = j;
    } else {
      i++;
    }
  }
  if (cur.trim()) raw.push(cur);
  return raw.map((s) => s.trim()).filter((s) => s.length > 0);
}

/** 超长句兜底: 在逗号/顿号处切成 ≤max 的片（保持标点在片尾）。 */
function splitOversize(sentence: string, max: number): string[] {
  const parts: string[] = [];
  let cur = "";
  const softs = new Set(["，", ",", "、"]);
  for (const ch of sentence) {
    cur += ch;
    if (cur.length >= max && softs.has(ch)) {
      parts.push(cur);
      cur = "";
    }
  }
  if (cur) parts.push(cur);
  // 仍超（无任何软标点的极端串）按 max 硬切
  const final: string[] = [];
  for (const p of parts) {
    for (let i = 0; i < p.length; i += max) final.push(p.slice(i, i + max));
  }
  return final;
}

/**
 * 第二遍: 句块贪心合并 → 段数组。
 * @param target 目标段长（加句后 ≥target 即收段; 默认 300）
 * @param hardMax 单句超此长触发逗号兜底（默认 600）
 */
export function segmentText(text: string, target = 300, hardMax = 600): string[] {
  const sentences = splitSentences(text);
  const pieces: string[] = [];
  for (const s of sentences) {
    if (s.length > hardMax) pieces.push(...splitOversize(s, Math.floor(hardMax / 2)));
    else pieces.push(s);
  }
  const segs: string[] = [];
  let cur = "";
  for (const p of pieces) {
    cur += p;
    if (cur.length >= target) {
      segs.push(cur);
      cur = "";
    }
  }
  if (cur.trim()) segs.push(cur);
  return segs;
}
