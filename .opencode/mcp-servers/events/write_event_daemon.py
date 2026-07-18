#!/usr/bin/env python3
"""常驻事件写入 daemon：从 stdin 读取 line-delimited JSON，并发写入 Graphiti。

被 plugin (security-analysis.ts) 的 fireAndForgetEvent 调用：
  - plugin 首次调用时 spawn 此 daemon，保持 stdin 管道开放
  - 后续事件通过 stdin 按行写入 JSON（含 timestamp）
  - stdin EOF（plugin 退出）→ 排空队列 → 退出

并发模型：asyncio + Semaphore(5) + 无界 Queue
  - 最多 5 个 add_episode 并发（DeepSeek API 限流保护）
  - 超过 5 个排队等待
  - timestamp 由 plugin 传入 → reference_time 保证时序

启动时一次初始化：
  - create_graphiti()（连接 Neo4j）
  - build_indices_and_constraints()（建索引）
后续事件复用连接，不再重复初始化。
"""
import asyncio
import json
import signal
import sys
from datetime import datetime
from pathlib import Path

# 确保能 import graphiti_config
sys.path.insert(0, str(Path(__file__).parent))

MAX_CONCURRENT = 5


def log(msg: str):
    """stderr 日志（不污染 stdout）。"""
    print(msg, file=sys.stderr, flush=True)


async def worker(name: str, queue: asyncio.Queue, graphiti):
    """从队列取消息，根据 action 字段路由到 add_episode 或 delete_group。"""
    from graphiti_core.nodes import EpisodeType, EntityNode, EpisodicNode

    while True:
        event = await queue.get()
        try:
            action = event.get("action")

            if action == "delete":
                # 删除指定 group 的所有事件数据
                group_id = event.get("group_id", "")
                if not group_id:
                    log(f"[!] delete 消息缺少 group_id")
                else:
                    await EntityNode.delete_by_group_id(graphiti.driver, group_id)
                    await EpisodicNode.delete_by_group_id(graphiti.driver, group_id)
                    log(f"[+] group deleted: {group_id}")
            else:
                # 正常事件 → add_episode
                await graphiti.add_episode(
                    name=event["name"],
                    episode_body=event["body"],
                    source_description=event["source"],
                    reference_time=datetime.fromtimestamp(event["timestamp"] / 1000),
                    source=EpisodeType.message,
                    group_id=event["group_id"],
                )
                log(f"[+] episode added: {event['name']}")
        except Exception as e:
            log(f"[!] event failed: {event.get('name', event.get('action', '?'))} — {type(e).__name__}: {e}")
        finally:
            queue.task_done()


async def stdin_reader(queue: asyncio.Queue):
    """从 stdin 按行读取 JSON，放入队列。跨平台用 executor 做阻塞读。"""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break  # EOF (stdin 管道断裂)
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            await queue.put(event)
        except json.JSONDecodeError as e:
            log(f"[!] invalid JSON from stdin: {e}")


async def main():
    from graphiti_config import create_graphiti

    log("[*] writer daemon 启动中...")
    graphiti, err = create_graphiti()
    if err:
        log(f"[!] {err}")
        sys.exit(1)

    try:
        await graphiti.build_indices_and_constraints()
    except Exception as e:
        log(f"[!] build_indices_and_constraints 失败: {e}")
        sys.exit(1)

    log(f"[+] Graphiti 就绪，启动 {MAX_CONCURRENT} 个 worker")

    # 通知 plugin 可以开始写事件了
    print("READY", flush=True)

    queue = asyncio.Queue()

    # 启动 worker
    workers = [
        asyncio.create_task(worker(f"worker-{i}", queue, graphiti))
        for i in range(MAX_CONCURRENT)
    ]

    # SIGTERM → 取消所有 worker
    shutdown_event = asyncio.Event()

    def on_sigterm():
        log("[*] 收到 SIGTERM，正在关闭...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, on_sigterm)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler，用 signal.signal 兜底
            signal.signal(sig, lambda *_: on_sigterm())

    # 读 stdin 填充队列
    reader_task = asyncio.create_task(stdin_reader(queue))

    # 等 stdin EOF 或 SIGTERM
    await asyncio.wait(
        [asyncio.shield(reader_task), asyncio.create_task(shutdown_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # stdin EOF 或 SIGTERM → 停止读 stdin，等队列排空
    reader_task.cancel()
    try:
        sys.stdin.close()  # 解除 executor 线程中的 readline 阻塞
    except Exception:
        pass
    log("[*] 等待队列排空...")
    await queue.join()

    # 取消 worker
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

    await graphiti.close()
    log("[+] daemon 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
