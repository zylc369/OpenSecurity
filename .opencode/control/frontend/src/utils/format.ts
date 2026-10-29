/**
 * 共享格式化工具（跨 section 复用的时间/时长展示原语）。
 */

/** 秒数 → 人话时长（"45 秒" / "3 分" / "2 时 5 分"）。null → "—"。 */
export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  if (sec < 60) return `${Math.round(sec)} 秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h} 时 ${m} 分`;
}

/** Unix 时间戳（秒） → 相对时间（"X 秒前" / "X 分前" / "X 时 Y 分前"）。空/未来 → "—"。 */
export function relTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  const sec = Math.max(0, Date.now() / 1000 - ts);
  return sec < 60 ? `${Math.round(sec)} 秒前` : `${fmtDuration(sec)}前`;
}
