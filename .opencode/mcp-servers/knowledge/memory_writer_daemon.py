#!/usr/bin/env python3
"""常驻 memory 写入 daemon：从 stdin 读取 line-delimited JSON，写入 knowledge DB。

被 plugin (security-analysis.ts) 的 fireAndForgetMemory 调用：
  - plugin 首次调用时 spawn 此 daemon，保持 stdin 管道开放
  - 后续工具执行结果通过 stdin 按行写入 JSON
  - stdin EOF（plugin 退出）→ 退出

加载 SentenceTransformer + MemoryDB 一次，后续复用。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = Path(os.environ.get("KNOWLEDGE_DB_PATH") or (Path.home() / "bw-security-analysis" / "db" / "knowledge" / "knowledge.db"))


def main():
    from db import MemoryDB
    from sentence_transformers import SentenceTransformer

    print("[*] memory writer daemon 启动中...", file=sys.stderr, flush=True)
    embedder = SentenceTransformer("BAAI/bge-m3")
    db = MemoryDB(DB_PATH, embedder)
    print("[+] memory writer ready", file=sys.stderr, flush=True)
    print("READY", flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            question = entry.get("question", "").strip()
            answer = entry.get("answer", "").strip()
            tool_type = entry.get("type", "").strip()
            flow_id = entry.get("flow_id") or None
            if not question or not answer:
                print(f"[!] 跳过空记录: question 或 answer 为空", file=sys.stderr, flush=True)
                continue
            if not tool_type:
                print(f"[!] 跳过记录: type（工具名）为空", file=sys.stderr, flush=True)
                continue
            # tool_type（工具名如 "bash"）拼进 question 前缀，保留来源信息
            question_tagged = f"[{tool_type}] {question}"
            db.store(
                question=question_tagged,
                content=answer,
                doc_type="memory",
                flow_id=flow_id,
            )
        except json.JSONDecodeError as e:
            print(f"[!] invalid JSON: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[!] store failed: {e}", file=sys.stderr, flush=True)

    db.close()
    print("[+] memory writer closed", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
