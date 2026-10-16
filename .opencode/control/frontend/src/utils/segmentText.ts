/**
 * 听书分段器（TTS 段级协议的客户端切分——Legado 业内模式）。
 *
 * 规则（需求 2026-10-15-tts-console-rebuild §1.5）:
 *  - 切点只落"句末"——句子永不劈开（TTS 后割裂的根源是句中断点）
 *  - 强断点: 换行 / 。！？…!? 以及英文句号 .（小数点防误切: 前后皆数字则跳过）
 *  - 句内符号（，、；：——）不作为断点
 *  - 引号内句末标点是合法断点（对话小说必须——不做引号配对保护）
 *  - 贪心合并句块到目标段长（DEFAULT_NEXT_LEN; 加句后 ≥target 即收段）
 *  - 兜底: 单句超 max(target*2, 160) 在逗号/顿号处硬切（韵律小损防超长段）
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
 * 渐进分段（首响优化）: 首段 20 字 ≈2s 出声(生成~1.5-2s);
 * ramp 20→80→180→300(数学衔接: 每段播放时长 ≥ 下段生成时长——
 * 20字/5s音 → 80字/5s生成 ✓; 80字/16s音 → 180字/12s生成 ✓; …全链无断档)。
 * 首句过长时允许在逗号处提前断首段（首响优先——见 cutFirstComma）。
 * @param target 目标段长（默认 80）
 * @param hardMax 单句超此长触发逗号兜底（0=自动: max(target*2, 160)）
 * @param firstTargets 前几段的目标长（默认 [20, min(80), min(180)] 按 target 派生）
 */
export const DEFAULT_FIRST_LEN = 20;   // 首段字数默认（改这里一处生效全前端）
export const DEFAULT_NEXT_LEN = 80;    // 常规段字数默认（改这里一处生效全前端）
// 注: 前几段目标序列的唯一权威是 rampFor()——不再维护硬编码数组(联动遗漏教训)

/** 首段逗号级切分: 首句超过 goal*1.5 时在 ≥goal 的首个逗号处断（首响优先）。
 *  返回断点(不含)或 -1=不切。 */
function cutFirstComma(sentence: string, goal: number): number {
  if (sentence.length <= goal * 1.5) return -1;
  for (let i = goal; i < sentence.length; i++) {
    if (sentence[i] === "，" || sentence[i] === "；") return i + 1;
  }
  return -1;
}

/**
 * 首段字数 → 渐进段长序列（测试台"分段设置"用）。
 * 爬坡约束: 第 N 段播放时长 ≥ 第 N+1 段生成时长（否则段界断档等待）。
 * 速度模型: 音频 ≈ 0.17-0.24s/字（短段偏慢）; 生成+质检 ≈ 0.07-0.08s/字 + 0.7s
 *  → 下段字数上限 ≈ (本段字数×0.2 − 0.7) / 0.07 ≈ 本段字数×2.3 − 10。
 * 取整为: 第二段 max(2f, 40), 第三段 max(4f, 80)（均封顶 target）。
 *  f=20 → [20, 40, 80]（默认）; f=30 → [30, 60, 80]; f=60 → [60, 80, 80]
 */
export function rampFor(firstLen: number, target = DEFAULT_NEXT_LEN): number[] {
  const f = Math.max(1, Math.round(firstLen));
  const b = Math.max(Math.round(f * 2), 40);
  const c = Math.max(Math.round(f * 4), 80);
  return [f, Math.min(b, target), Math.min(c, target)];
}

export function segmentText(
  text: string, target = DEFAULT_NEXT_LEN, hardMax = 0,
  firstTargets: readonly number[] = rampFor(DEFAULT_FIRST_LEN, target),
): string[] {
  const hm = hardMax > 0 ? hardMax : Math.max(target * 2, 160); // 兜底阈值随常规段联动
  const sentences = splitSentences(text);
  const pieces: string[] = [];
  for (const s of sentences) {
    if (s.length > hm) pieces.push(...splitOversize(s, Math.floor(hm / 2)));
    else pieces.push(s);
  }
  // 首段逗号级切分: 首句过长时在逗号处提前断（长首句不再拖慢首响）
  if (pieces.length > 0 && firstTargets.length > 0) {
    const cut = cutFirstComma(pieces[0], firstTargets[0]);
    if (cut > 0) pieces.splice(0, 1, pieces[0].slice(0, cut), pieces[0].slice(cut));
  }
  const segs: string[] = [];
  let cur = "";
  const goalNow = () => segs.length < firstTargets.length
    ? firstTargets[segs.length]
    : target;
  for (const p of pieces) {
    // 预检收段（防贪心拖拽超长）: 当前段已接近目标（≥75%）且吞下此句会
    // 显著超标（>135%）时先收——超长段生成慢会拖垮"下段生成 ≤ 本段播放"的
    // 无缝链（如 76 字差 4 字吞 55 字句 → 131 字 → 生成 7.5s > 首段 5.8s 播放）
    if (cur.length > 0 && cur.length >= goalNow() * 0.75
        && cur.length + p.length > goalNow() * 1.35) {
      segs.push(cur);
      cur = "";
    }
    cur += p;
    if (cur.length >= goalNow()) {
      segs.push(cur);
      cur = "";
    }
  }
  if (cur.trim()) {
    // 短尾段并回前段(防"孤尾"): 尾段不足目标一半且合并后不超兜底上界时并入
    const tail = cur;
    const prev = segs[segs.length - 1];
    const mergeLimit = Math.max(target * 2, 160);
    if (prev !== undefined && tail.length < target * 0.5
        && prev.length + tail.length <= mergeLimit) {
      segs[segs.length - 1] = prev + tail;
    } else {
      segs.push(tail);
    }
  }
  return segs;
}
