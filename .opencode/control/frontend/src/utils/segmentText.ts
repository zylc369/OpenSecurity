/**
 * 听书分段器（TTS 段级协议的客户端切分——Legado 业内模式）。
 *
 * 规则（需求 2026-10-15-tts-console-rebuild §1.5）:
 *  - 切点只落"句末"——句子永不劈开（TTS 后割裂的根源是句中断点）
 *  - 强断点: 换行 / 。！？…!? 以及英文句号 .（小数点防误切: 前后皆数字则跳过）
 *  - 句内符号（，、；：——）不作为断点
 *  - 引号内句末标点是合法断点（对话小说必须——不做引号配对保护）
 *  - 贪心合并句块到目标段长（DEFAULT_NEXT_LEN; 加句后 ≥target 即收段）
 *  - 预检收段: 当前段 ≥半目标且吞下句会超 150% 目标时先收（防超长拖拽）
 *  - 兜底: 单句超 max(target*1.5, 120) 在逗号/顿号处硬切（韵律小损防超长段——
 *    超长句生成时长会突破前段播放窗口, 是无缝链的最大威胁）
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
 * 从 pos 扫描一个句块（惰性原语——splitSentences 与 SegmentFeeder 共享，
 * 保证两条路径的句边界逐字符一致）。
 * 句末符后的连续同类收尾（!!!/？？？/……）与闭引号并入当前句;
 * 纯空白块内部消化（不返回）; 无更多内容返回 null。
 * 返回的 sent 已 trim。 */
export function scanSentence(
  text: string, pos: number,
): { sent: string; nextPos: number } | null {
  if (pos >= text.length) return null;
  let cur = "";
  let i = pos;
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
      const sent = cur.trim();
      if (sent.length > 0) return { sent, nextPos: j };
      cur = "";  // 纯空白块（如连续换行）→ 继续扫下一块
      i = j;
      continue;
    }
    i++;
  }
  const sent = cur.trim();
  return sent.length > 0 ? { sent, nextPos: text.length } : null;
}

/**
 * 第一遍: 全文 → 句块数组（每块以句末标点（可带闭引号收尾）——scanSentence 循环）。
 * 段首尾空白丢弃（TTS 不读空白）。 */
export function splitSentences(text: string): string[] {
  const raw: string[] = [];
  let pos = 0;
  for (;;) {
    const sc = scanSentence(text, pos);
    if (sc === null) break;
    raw.push(sc.sent);
    pos = sc.nextPos;
  }
  return raw;
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
 * 渐进分段（首响优化）: 首段 20 字 ≈3.5s 出声;
 * ramp 20→40→80(数学衔接: 每段播放时长 ≥ 下段生成时长——
 * 20字/3.5s音 → 40字/3.5s生成 ✓; 40字/9s音 → 80字/6s生成 ✓; …全链无断档)。
 * 首句过长时允许在逗号处提前断首段（首响优先——见 cutFirstComma）。
 * @param target 目标段长（默认 80）
 * @param hardMax 单句超此长触发逗号兜底（0=自动: max(target*1.5, 120)）
 * @param firstTargets 前几段的目标长（默认 rampFor 派生，如 [20, 40, 80]）
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
  const hm = hardMax > 0 ? hardMax : Math.max(target * 1.5, 120); // 兜底阈值随常规段联动
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
    // 预检收段（防贪心拖拽超长）: 当前段已过半目标（拆出它不算碎段）且
    // 吞下此句会显著超目标（>150%）时先收——超长段生成慢会拖垮
    // "下段生成 ≤ 本段播放"的无缝链（如 76 字差 4 字吞 55 字句 → 131 字）。
    // 小 cur（<半目标）不拆: 拆出小段反而拖垮后续（14+14→14|14 劣于 28）。
    const g = goalNow();
    if (cur.length > 0 && cur.length >= g * 0.5
        && cur.length + p.length > g * 1.5) {
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

/**
 * 惰性分段器（真实听书场景: 选起点 → 向后连续读——"总数"概念不存在）。
 *
 * 与 segmentText 全量版共享全部子步骤（scanSentence/贪心/预检/cutFirstComma/
 * splitOversize），段序列逐段一致（等价性由测试断言）。
 *
 * 实现要点——"延迟交付（lookahead 1）": 尾段并回只可能修改"最后一段"，
 * 故每段确定后先留在 settled（≤1 个未冻结段），出现更晚段时即冻结交付;
 * 文本结束时对尾段执行并回后再全部交付。内存 O(窗口)，永不回看全文。
 */
export interface SegmentFeeder {
  /** 产出下一段（null=文本结束）。惰性: 只扫描到本段所需的文本。 */
  next(): string | null;
  /** 已产出（交付给调用方）的段数——纯增量语义。 */
  readonly producedCount: number;
}

export function createSegmentFeeder(
  text: string, target = DEFAULT_NEXT_LEN, hardMax = 0,
  firstTargets: readonly number[] = rampFor(DEFAULT_FIRST_LEN, target),
): SegmentFeeder {
  const hm = hardMax > 0 ? hardMax : Math.max(target * 1.5, 120);
  let pos = 0;
  const pendingPieces: string[] = [];  // 超长切分/首段 cut 产生的片队列
  let firstCutDone = false;            // 首片逗号级切分仅一次（对齐全量版 pieces[0]）
  let sentenceDone = false;            // 句子源耗尽
  let cur = "";                        // 正在累积的段
  const settled: string[] = [];        // 已确定但"最后一段"仍可能被尾并回修改
  let settledCount = 0;                // ≈ 全量版 segs.length（goal 档位依据）
  const outbox: string[] = [];         // 冻结段（不可再变）——next() 出口
  let delivered = 0;                   // 已交付段数

  const goalNow = (): number => settledCount < firstTargets.length
    ? firstTargets[settledCount]
    : target;

  const settle = (seg: string): void => {
    settled.push(seg);
    settledCount++;
    // 出现更晚的段 → 更早段不可再被尾并回修改 → 冻结交付
    while (settled.length >= 2) outbox.push(settled.shift() as string);
  };

  const nextPiece = (): string | null => {
    for (;;) {
      if (pendingPieces.length > 0) return pendingPieces.shift() as string;
      if (sentenceDone) return null;
      const sc = scanSentence(text, pos);
      if (sc === null) { sentenceDone = true; return null; }
      pos = sc.nextPos;
      let pieces = sc.sent.length > hm
        ? splitOversize(sc.sent, Math.floor(hm / 2))
        : [sc.sent];
      if (!firstCutDone && firstTargets.length > 0) {
        firstCutDone = true;
        const cut = cutFirstComma(pieces[0], firstTargets[0]);
        if (cut > 0) pieces = [pieces[0].slice(0, cut), pieces[0].slice(cut)];
      }
      pendingPieces.push(...pieces);
    }
  };

  const finishTail = (): void => {
    if (cur.trim()) {
      // 短尾段并回前段（防孤尾）——与全量版同规则
      const tail = cur;
      const prev = settled[settled.length - 1];
      const mergeLimit = Math.max(target * 2, 160);
      if (prev !== undefined && tail.length < target * 0.5
          && prev.length + tail.length <= mergeLimit) {
        settled[settled.length - 1] = prev + tail;
      } else {
        settled.push(tail);
        settledCount++;
      }
    }
    cur = "";
    while (settled.length > 0) outbox.push(settled.shift() as string);
  };

  return {
    next(): string | null {
      while (outbox.length === 0) {
        const p = nextPiece();
        if (p === null) { finishTail(); break; }
        // 贪心 + 预检（逐行复刻 segmentText 第二遍——含 goalNow 动态档位）
        const g = goalNow();
        if (cur.length > 0 && cur.length >= g * 0.5
            && cur.length + p.length > g * 1.5) {
          settle(cur);
          cur = "";
        }
        cur += p;
        if (cur.length >= goalNow()) {
          settle(cur);
          cur = "";
        }
      }
      if (outbox.length > 0) {
        delivered++;
        return outbox.shift() as string;
      }
      return null;
    },
    get producedCount(): number {
      return delivered;
    },
  };
}
