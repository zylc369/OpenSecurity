import { join, dirname } from "path";
import { mkdirSync, writeFileSync } from "fs";
import { LOGS_DIR, MAX_TIMELINE_BUFFER } from "./constants";
import { debugLog } from "./logging";
import { getTaskDir } from "./task-session";

export type TimelineEventType =
  | "tool.before"
  | "tool.after"
  | "session.status"
  | "session.error"
  | "heartbeat";

export interface TimelineEvent {
  timestamp: number;
  type: TimelineEventType;
  tool?: string;
  detail?: string;
  duration?: number;
}

const timelineBuffers = new Map<string, TimelineEvent[]>();

// 进程退出时同步 flush 所有未写入的 buffer（覆盖 Ctrl+C / process.exit 场景）
process.on("exit", () => {
  for (const [sessionID, buffer] of timelineBuffers) {
    if (buffer.length > 0) flushTimeline(sessionID);
  }
});

function formatTimelineEntry(event: TimelineEvent): string {
  const date = new Date(event.timestamp);
  const ts = date.toLocaleString("zh-CN", { hour12: false });
  const obj: Record<string, unknown> = {
    ts: event.timestamp,
    type: event.type,
  };
  if (event.tool) obj.tool = event.tool;
  if (event.detail) obj.detail = event.detail;
  if (event.duration !== undefined) obj.duration = event.duration;
  return `[${ts}] ${JSON.stringify(obj)}`;
}

export function flushTimeline(sessionID: string): void {
  const buffer = timelineBuffers.get(sessionID);
  if (!buffer || buffer.length === 0) return;

  const taskDir = getTaskDir(sessionID);
  const logFile = taskDir
    ? join(taskDir, "logs", "timeline.log")
    : join(LOGS_DIR, `timeline-${sessionID}.log`);

  try {
    const lines = buffer.map(formatTimelineEntry).join("\n") + "\n";
    mkdirSync(dirname(logFile), { recursive: true });
    writeFileSync(logFile, lines, { flag: "a" });
  } catch (e) {
    debugLog(`flushTimeline failed: ${e}`, sessionID);
  }

  buffer.length = 0;
}

export function recordTimeline(
  sessionID: string,
  event: TimelineEvent,
  flush = false,
): void {
  let buffer = timelineBuffers.get(sessionID);
  if (!buffer) {
    buffer = [];
    timelineBuffers.set(sessionID, buffer);
  }
  buffer.push(event);

  if (buffer.length >= MAX_TIMELINE_BUFFER || flush) {
    flushTimeline(sessionID);
  }
}
