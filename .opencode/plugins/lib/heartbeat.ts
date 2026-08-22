/**
 * 心跳发送器（Plugin 端）。
 *
 * 协议: 每 HEARTBEAT_INTERVAL_MS(10s) POST /api/heartbeat {pid: opencode pid}；
 * 控制端 HeartbeatTask 超过 60s 未收到 → 移除；心跳表空过启动宽限 → 控制台自杀
 * （services/heartbeat.py）。
 *
 * 关键实现约束：
 *   • setInterval 必须 unref()——否则 interval 挂住 opencode 事件循环，
 *     opencode 变僵尸进程 + 心跳永不停 → 控制台永不死
 *   • 心跳 Promise 链必须 catch——unhandled rejection 会炸宿主
 *   • start() 幂等——多 session/hook 重复触发不产生多个 interval
 */
import { controlFetch } from "./control-http";
import { HEARTBEAT_INTERVAL_MS } from "./constants";
import { debugLog } from "./logging";

export class HeartbeatSender {
  private timer: ReturnType<typeof setInterval> | null = null;
  private sending = false; // 上一跳未完成时跳过本轮（防重入堆积）

  /** 是否正在发送心跳。 */
  get running(): boolean {
    return this.timer !== null;
  }

  /** 启动心跳。幂等：已在跳则直接返回。成功启动后立即发首跳。 */
  async start(): Promise<void> {
    if (this.timer) return;
    debugLog(`HeartbeatSender: 启动（pid=${process.pid}，间隔 ${HEARTBEAT_INTERVAL_MS}ms，首跳立即）`);
    await this.sendOnce();
    this.timer = setInterval(() => {
      // 双保险: sendOnce 内部已全 catch，此处再兜一层防未预期路径
      this.sendOnce().catch(() => {});
    }, HEARTBEAT_INTERVAL_MS);
    this.timer.unref?.(); // 关键：不挂住 opencode 事件循环
    if (!this.timer.unref) {
      debugLog(`HeartbeatSender: 当前运行时 interval 不支持 unref，心跳仍将继续`);
    }
  }

  /** 停止心跳（测试/关停用）。 */
  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
      debugLog(`HeartbeatSender: 停止`);
    }
  }

  /** 发送一跳。异常全吞（控制台暂时不可达时下一周期重试）。 */
  private async sendOnce(): Promise<void> {
    if (this.sending) return;
    this.sending = true;
    try {
      const res = await controlFetch("/api/heartbeat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pid: process.pid }),
      });
      if (!res.ok) {
        debugLog(`HeartbeatSender: 心跳响应异常 status=${res.status}`);
      }
    } catch (e) {
      debugLog(`HeartbeatSender: 心跳发送失败（下周期重试）: ${(e as Error)?.message}`);
    } finally {
      this.sending = false;
    }
  }
}

/** 模块级单例。 */
export const heartbeatSender = new HeartbeatSender();
