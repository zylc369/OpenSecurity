#!/usr/bin/env python3
"""清理 events（Neo4j）和 knowledge（SQLite）数据库的全部数据。

用法：
    python clean_databases.py              # 清理两个数据库
    python clean_databases.py --events     # 只清理 events
    python clean_databases.py --knowledge  # 只清理 knowledge
    python clean_databases.py --dry-run    # 只查看数据量不删除
"""
import argparse
import os
import subprocess as sp
import sys
from pathlib import Path

NEO4J_CONTAINER = "neo4j-events"
NEO4J_USER = "neo4j"
NEO4J_PASS = "neo4j_password"
KNOWLEDGE_DB = Path.home() / "bw-security-analysis" / "db" / "knowledge" / "knowledge.db"


def check_events_stats():
    """查看 events 数据库（Neo4j）的数据量。"""
    print("=== events 数据库（Neo4j）===")
    if not _docker_ready():
        print("  ⚠️ Docker 未运行或容器不存在，跳过")
        return

    queries = [
        ("Entity 节点", "MATCH (n:Entity) RETURN COUNT(*)"),
        ("Episodic 节点", "MATCH (n:Episodic) RETURN COUNT(*)"),
        ("其他节点", "MATCH (n) WHERE NOT n:Entity AND NOT n:Episodic RETURN COUNT(*)"),
        ("关系（边）", "MATCH ()-[r]->() RETURN COUNT(*)"),
        ("group_id 分区数", "MATCH (n) WHERE n.group_id IS NOT NULL RETURN COUNT(DISTINCT n.group_id)"),
    ]
    for label, query in queries:
        r = sp.run(
            ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
             "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain", query],
            capture_output=True, text=True, timeout=10,
        )
        count = r.stdout.strip().split("\n")[-1].strip() if r.stdout.strip() else "?"
        print(f"  {label}: {count}")


def clean_events():
    """清理 events 数据库（Neo4j）的全部数据。"""
    print("清理 events 数据库（Neo4j）...")
    if not _docker_ready():
        print("  ⚠️ Docker 未运行或容器不存在，跳过")
        return

    # 删除所有节点和关系
    r = sp.run(
        ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
         "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain",
         "MATCH (n) DETACH DELETE n"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode == 0:
        print("  ✅ 已删除所有节点和关系")
    else:
        print(f"  ❌ 删除失败: {r.stderr.strip()}")

    # 删除所有索引和约束（Graphiti 创建的）
    r = sp.run(
        ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
         "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain",
         "SHOW INDEXES YIELD name RETURN collect(name)"],
        capture_output=True, text=True, timeout=10,
    )
    # 逐个删除索引
    index_names_str = r.stdout.strip().split("\n")[-1].strip() if r.stdout.strip() else "[]"
    import json
    try:
        index_names = json.loads(index_names_str)
    except Exception:
        index_names = []
    for name in index_names:
        sp.run(
            ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
             "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain",
             f"DROP INDEX {name} IF EXISTS"],
            capture_output=True, text=True, timeout=10,
        )
    if index_names:
        print(f"  ✅ 已删除 {len(index_names)} 个索引")

    # 删除所有约束
    r = sp.run(
        ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
         "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain",
         "SHOW CONSTRAINTS YIELD name RETURN collect(name)"],
        capture_output=True, text=True, timeout=10,
    )
    constraint_names_str = r.stdout.strip().split("\n")[-1].strip() if r.stdout.strip() else "[]"
    try:
        constraint_names = json.loads(constraint_names_str)
    except Exception:
        constraint_names = []
    for name in constraint_names:
        sp.run(
            ["docker", "exec", NEO4J_CONTAINER, "cypher-shell",
             "-u", NEO4J_USER, "-p", NEO4J_PASS, "--format", "plain",
             f"DROP CONSTRAINT {name} IF EXISTS"],
            capture_output=True, text=True, timeout=10,
        )
    if constraint_names:
        print(f"  ✅ 已删除 {len(constraint_names)} 个约束")


def check_knowledge_stats():
    """查看 knowledge 数据库（SQLite）的数据量。"""
    print("=== knowledge 数据库（SQLite）===")
    if not KNOWLEDGE_DB.exists():
        print(f"  ⚠️ 数据库文件不存在: {KNOWLEDGE_DB}")
        return

    import sqlite3
    db = sqlite3.connect(str(KNOWLEDGE_DB))
    total = db.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    by_type = db.execute("SELECT doc_type, COUNT(*) FROM answers GROUP BY doc_type ORDER BY COUNT(*) DESC").fetchall()
    print(f"  总记录数: {total}")
    for dt, c in by_type:
        print(f"    {dt}: {c} 条")
    db.close()


def clean_knowledge():
    """清理 knowledge 数据库（SQLite）的全部数据。"""
    print("清理 knowledge 数据库（SQLite）...")
    if not KNOWLEDGE_DB.exists():
        print(f"  ⚠️ 数据库文件不存在: {KNOWLEDGE_DB}")
        return

    import sqlite3
    import sqlite_vec

    db = sqlite3.connect(str(KNOWLEDGE_DB))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # 删除所有数据
    db.execute("DELETE FROM answer_vectors")
    db.execute("DELETE FROM answers")
    db.execute("DELETE FROM sqlite_sequence WHERE name IN ('answers', 'answer_vectors')")
    db.commit()

    # 验证
    remaining = db.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    db.close()

    if remaining == 0:
        print("  ✅ 已删除所有记录")
    else:
        print(f"  ❌ 仍有 {remaining} 条记录")


def _docker_ready():
    """检查 Docker daemon 运行 + neo4j-events 容器存在。"""
    try:
        sp.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except Exception:
        return False
    r = sp.run(
        ["docker", "ps", "--filter", f"name={NEO4J_CONTAINER}", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=5,
    )
    return r.stdout.strip() == NEO4J_CONTAINER


def main():
    parser = argparse.ArgumentParser(description="清理 events 和 knowledge 数据库")
    parser.add_argument("--events", action="store_true", help="只清理 events（Neo4j）")
    parser.add_argument("--knowledge", action="store_true", help="只清理 knowledge（SQLite）")
    parser.add_argument("--dry-run", action="store_true", help="只查看数据量不删除")
    args = parser.parse_args()

    # 默认清理两个
    clean_both = not args.events and not args.knowledge

    print("=" * 50)
    if args.dry_run:
        print("数据库数据量统计（dry-run 模式）")
    else:
        print("数据库清理")
    print("=" * 50)

    # 查看数据量
    if clean_both or args.events:
        check_events_stats()
    if clean_both or args.knowledge:
        check_knowledge_stats()
        print()

    if args.dry_run:
        print("\n（dry-run 模式，不执行删除）")
        return

    # 确认
    print()
    confirm = input("确认删除以上所有数据？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    print()
    if clean_both or args.events:
        clean_events()
    if clean_both or args.knowledge:
        clean_knowledge()

    print("\n✅ 清理完成")


if __name__ == "__main__":
    main()
