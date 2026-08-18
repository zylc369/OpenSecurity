"""真链路 E2E 回归套件（无 fake、无 mock）。

覆盖整改 34/35/36 的真实验证路径，供改动 events/knowledge 链路后运行：

  python3 tests/test_e2e_real.py            # 全量（依赖真 Docker + DeepSeek + 生产控制台）
  python3 tests/test_e2e_real.py knowledge  # 按名过滤子串

前置条件：
  - 生产控制台在跑（读 $DATA_DIR/.opencode-control.port）
  - Docker daemon 可用（neo4j-events 卷数据保留）
  - DEEPSEEK_API_KEY 已配置（.ai_env）

设计：
  - 等待外部系统（DeepSeek 提取/Neo4j 落库/容器自愈）用密集轮询提前退出，
    不用固定 sleep（整改 36 的教训：固定 sleep 是时间浪费）
  - 每个测试独立 group_id（e2er-<pid>-<tag>），结束清理，不污染生产库
  - 与 test_control.py（fake 单测层）分离：本套件全真依赖，失败即真问题
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis")))
PORT_FILE = DATA_DIR / ".opencode-control.port"
KNOWLEDGE_DB = DATA_DIR / "db" / "knowledge" / "knowledge.db"
RUN_ID = f"e2er-{os.getpid()}"

_results: list[tuple[str, bool, str]] = []


def test(name: str):
    def decorator(fn):
        def wrapper():
            t0 = time.time()
            try:
                fn()
                _results.append((name, True, ""))
                print(f"  ✓ {name} ({time.time()-t0:.0f}s)")
            except Exception as e:
                _results.append((name, False, f"{type(e).__name__}: {e}"))
                print(f"  ✗ {name} ({time.time()-t0:.0f}s): {e}")
        wrapper._is_test = True
        wrapper._name = name
        return wrapper
    return decorator


def assert_true(cond: bool, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg)


# ── 基础设施 ─────────────────────────────────────────────


def control_base() -> str:
    port = int(PORT_FILE.read_text().strip().split("\n")[0])
    return f"http://127.0.0.1:{port}"


def post(path: str, body: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        f"{control_base()}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def poll(fn, timeout: float, first_interval: float = 2.0, max_interval: float = 8.0,
         desc: str = "条件") -> object:
    """密集轮询提前退出：fn() 真值即返回；超时抛 AssertionError。

    间隔从 first_interval 递增到 max_interval（外部系统启动慢但多数时候
    几秒就绪——固定 sleep 会在快场景浪费）。
    """
    deadline = time.time() + timeout
    interval = first_interval
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
        interval = min(interval * 1.5, max_interval)
    raise AssertionError(f"轮询超时（{timeout:.0f}s）: {desc}，最后值: {last!r}")


def wait_health(timeout: float = 120) -> None:
    def _ok():
        try:
            with urllib.request.urlopen(f"{control_base()}/api/health", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False
    poll(_ok, timeout, desc="控制台 /health 200")


def neo4j_cypher(query: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "neo4j-events", "cypher-shell",
         "-u", "neo4j", "-p", "neo4j_password", query],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"cypher 失败: {r.stderr[:200]}")
    return r.stdout


def neo4j_count(group_id: str, label: str | None = None) -> int:
    where = f"n.group_id='{group_id}'"
    if label:
        where += f" AND '{label}' IN labels(n)"
    out = neo4j_cypher(f"MATCH (n) WHERE {where} RETURN count(n)")
    return int(out.strip().split("\n")[-1])


def knowledge_cleanup(flow_prefix: str) -> None:
    import sqlite_vec
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM answers WHERE flow_id LIKE ?", (f"{flow_prefix}%",)).fetchall()]
    if ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM answer_vectors WHERE rowid IN ({ph})", ids)
        conn.execute(f"DELETE FROM answers WHERE id IN ({ph})", ids)
        conn.commit()
    conn.close()


# ── MCP 壳 stdio 真调用 ──────────────────────────────────


def mcp_shell_tool(shell: str, tool: str, args: dict, timeout: int = 240) -> dict:
    """起壳进程 → initialize → call_tool → 返回 dict（含壳/控制台/全链路）。"""
    code = f"""
import asyncio, json, sys
sys.path.insert(0, ".opencode/mcp-servers")
sys.path.insert(0, ".opencode/mcp-servers/{shell}")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=[".opencode/mcp-servers/{shell}/server.py"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("{tool}", {json.dumps(args, ensure_ascii=False)})
            print("RESULT_JSON:" + res.content[0].text)

asyncio.run(main())
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=timeout, cwd=BACKEND_DIR.parents[2])
    for line in r.stdout.split("\n"):
        if line.startswith("RESULT_JSON:"):
            raw = line[len("RESULT_JSON:"):]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # 非所有壳都返回 JSON 文本（ocr 壳返回纯文本）——包一层保持 dict 返回
                return {"text": raw}
    raise RuntimeError(f"壳无输出: {r.stdout[-200:]} {r.stderr[-300:]}")


# ── 测试用例 ─────────────────────────────────────────────


@test("knowledge 全链: 壳 store 脱敏落库 → search 命中 → memory flow 隔离")
def test_knowledge_roundtrip():
    flow = f"{RUN_ID}-know"
    d = mcp_shell_tool("knowledge", "store_knowledge", {
        "question": f"{RUN_ID} 如何检测主机开放端口",
        # content 与 question 语义强关联（nmap/端口/主机），保证 cosine 远超 0.2 阈值
        # （弱关联内容会导致分数在阈值边缘抖动，断言不稳定）
        "content": "检测主机开放端口的方法: 用 nmap -sS 对主机 172.16.3.9 做全端口扫描，-p- 参数覆盖 65535 端口", "message": "e2e-real"})
    assert_true(d.get("stored") is True, f"store 失败: {d}")

    d = mcp_shell_tool("knowledge", "search_knowledge", {
        "questions": [f"{RUN_ID} 如何检测主机开放端口"], "message": "e2e-real"})
    assert_true(d["count"] >= 1, f"未命中: {d}")
    assert_true("<IP>" in d["results"][0]["answer"], f"脱敏失效: {d['results'][0]['answer'][:80]}")

    d = mcp_shell_tool("knowledge", "search_in_memory", {
        "questions": ["执行过什么"], "flow_id": f"{RUN_ID}-no-such", "message": "e2e-real"})
    assert_true(d["count"] == 0, f"flow 隔离失效: {d}")
    # store_knowledge 是全局行（flow_id=None），按 question 前缀清理
    import sqlite_vec
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM answers WHERE question LIKE 'e2er-%'").fetchall()]
    if ids:
        ph = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM answer_vectors WHERE rowid IN ({ph})", ids)
        conn.execute(f"DELETE FROM answers WHERE id IN ({ph})", ids)
        conn.commit()
    conn.close()


@test("events 全链: 写入 → DeepSeek 提取 → 搜索/BFS/diverse → 删除清零")
def test_events_roundtrip():
    gid = f"{RUN_ID}-ev"
    body = ("Tool: bash\nResult: 用 frida hook com.example.e2eapp 的 SSL pinning，"
            "绕过证书校验抓到明文流量，目标 10.9.9.9，配合 objection 工具")
    post("/api/events/entry", {"name": "bash execution", "body": body,
                               "source": "e2e-real", "group_id": gid,
                               "timestamp": int(time.time() * 1000)})
    # 轮询 DeepSeek 提取 + 落库（实测 10-60s）
    poll(lambda: neo4j_count(gid) >= 3, timeout=120, desc="实体提取落库")

    d = mcp_shell_tool("events", "entity_search", {
        "query": "frida 工具", "group_id": gid, "node_labels": ["Tool"], "message": "e2e-real"})
    assert_true(not d.get("error"), str(d.get("error")))
    tools = [n["name"] for n in d["nodes"]]
    assert_true(any("frida" in n.lower() for n in tools), f"无 frida 实体: {tools}")
    center = next(n for n in d["nodes"] if "frida" in n["name"].lower())

    # BFS（bug1 修复的回归锚点：origin 参数 + 真边）
    d = mcp_shell_tool("events", "entity_relationships_search", {
        "query": "frida 关系", "group_id": gid, "center_node_uuid": center["uuid"],
        "max_depth": 2, "message": "e2e-real"})
    assert_true(not d.get("error"), str(d.get("error")))
    assert_true(len(d["edges"]) > 0, "BFS 无边（bug1 回归？）")

    # diverse（cross_encoder 真分数）
    d = mcp_shell_tool("events", "diverse_results_search", {
        "query": "SSL pinning 绕过", "group_id": gid, "diversity_level": "high", "message": "e2e-real"})
    assert_true(not d.get("error"), str(d.get("error")))
    assert_true(len(d["edges"]) > 0 and any(abs(x) > 0.001 for x in d["edge_scores"]),
                "diverse 无结果或分数全零")

    post("/api/events/delete", {"group_id": gid})
    poll(lambda: neo4j_count(gid) == 0, timeout=60, desc="删除清零")


@test("容器 stopped 自愈: docker stop → 一次搜索调用自动恢复")
def test_container_selfheal():
    subprocess.run(["docker", "stop", "neo4j-events"], capture_output=True, timeout=60)
    d = post("/api/events/time-search", {"query": "frida", "group_id": f"{RUN_ID}-heal"},
             timeout=300)
    assert_true(not d.get("error"), f"自愈失败: {str(d.get('error'))[:200]}")
    r = subprocess.run(["docker", "ps", "--filter", "name=neo4j-events",
                        "--format", "{{.Status}}"], capture_output=True, text=True, timeout=15)
    assert_true(r.stdout.strip().startswith("Up"), f"容器未恢复: {r.stdout}")


@test("并发写入: 8 条并发 → 推理锁串行 → 全部落库且控制台存活（bug6 回归锚点）")
def test_concurrent_writes():
    gid = f"{RUN_ID}-conc"
    def post_one(i: int) -> bool:
        return post("/api/events/entry", {
            "name": "bash execution",
            "body": f"Result: 并发回归 #{i}——扫描 10.8.8.{i}，工具 sqlmap，CVE-2026-30{i}",
            "source": "e2e-real", "group_id": gid,
            "timestamp": int(time.time() * 1000)})["queued"]
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(post_one, range(8)))
    assert_true(all(results), f"入队失败: {results}")
    poll(lambda: neo4j_count(gid, "Episodic") >= 8, timeout=180, desc="8 episodes 落库")
    # 控制台存活（修复前此处进程已 SIGABRT）
    wait_health(timeout=15)
    post("/api/events/delete", {"group_id": gid})
    poll(lambda: neo4j_count(gid) == 0, timeout=60, desc="并发数据清理")


@test("memory 坏库重建: EXCLUSIVE 锁期条目丢弃 → 解锁后自动重建")
def test_memory_rebuild():
    flow = f"{RUN_ID}-rb"
    lock = subprocess.Popen([sys.executable, "-c", f"""
import sqlite3, time
c = sqlite3.connect({str(KNOWLEDGE_DB)!r}, timeout=1)
c.execute('BEGIN EXCLUSIVE')
time.sleep(18)
c.rollback(); c.close()
"""])
    time.sleep(2)  # 等锁生效
    post("/api/memory/entry", {"question": "rebuild A（锁库期）", "answer": "应丢弃",
                               "type": "bash", "flow_id": flow})
    lock.wait(timeout=30)
    post("/api/memory/entry", {"question": "rebuild B（解锁后）", "answer": "应重建成功",
                               "type": "bash", "flow_id": flow})
    def _check():
        import sqlite_vec
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        rows = conn.execute("SELECT question FROM answers WHERE flow_id=?",
                            (flow,)).fetchall()
        conn.close()
        return rows == [("[bash] rebuild B（解锁后）",)] or None
    poll(_check, timeout=60, desc="B 落库且 A 已丢弃")
    knowledge_cleanup(flow)


def main() -> int:
    print("=" * 60)
    print(f"真链路 E2E 套件 RUN_ID={RUN_ID}")
    print("=" * 60)
    wait_health()
    # 开头清扫历史残留（上次失败跑可能遗留 e2er-* 数据，保证套件幂等）
    try:
        neo4j_cypher("MATCH (n) WHERE n.group_id STARTS WITH 'e2er' DETACH DELETE n")
        knowledge_cleanup(f"{RUN_ID.rsplit('-', 1)[0]}-")
    except Exception as e:
        print(f"⚠ 历史残留清扫失败（不阻塞）: {e}")
    tests = [(name, fn) for name, fn in globals().items()
             if callable(fn) and getattr(fn, "_is_test", False)]
    name_filter = sys.argv[1] if len(sys.argv) > 1 else ""
    ran = 0
    for name, fn in tests:
        if name_filter and name_filter not in getattr(fn, "_name", ""):
            continue
        ran += 1
        fn()
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"通过 {passed} / 失败 {len(_results) - passed} / 总计 {len(_results)}")
    if len(_results) != ran:
        print(f"⚠ 过滤后应跑 {ran} 实跑 {len(_results)}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
