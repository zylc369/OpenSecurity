"""opencode-control 后端 + Plugin 集成测试。

按需求文档 §4 验收标准设计测试用例，覆盖：
- 功能验收 F1-F12, F15, F16（F13/F14 前端测试，留待前端完成）
- 边界条件（心跳超时、启动宽限、原子写、端口 fallback）
- 端到端集成（Plugin spawn 控制台 → HTTP 调用 → 配置获取 → embed 推理）

运行方式：
  cd .opencode/control/backend
  OPENCODE_ROOT=<path> DATA_DIR=<path> python tests/test_control.py

每个测试独立运行（自带 setup + teardown），失败一个不影响其他。
"""
from __future__ import annotations

import os
import sys
import time
import socket
import subprocess
import threading
import signal
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

# 配置测试环境
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 测试专用 DATA_DIR（避免污染实际 ~/bw-security-analysis）
TEST_DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/control_test_data"))
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

# OPENCODE_ROOT 用真实路径（读真实 .ai_env）
OPENCODE_ROOT = Path(os.environ.get("OPENCODE_ROOT", ""))

# 强制环境变量
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
if OPENCODE_ROOT.exists():
    os.environ["OPENCODE_ROOT"] = str(OPENCODE_ROOT)
# CONTROL_TCP_PORT 随机高位：沙箱控制台与生产 9776 隔离（bind 冲突会直接退出）
os.environ.setdefault("CONTROL_TCP_PORT", str(__import__("random").randint(41000, 49000)))


# ─── 测试框架（极简）──────────────────────────────────────

_results: list[tuple[str, bool, str]] = []


def test(name: str):
    """测试装饰器：注册测试函数。"""
    def decorator(fn):
        def wrapper():
            try:
                fn()
                _results.append((name, True, ""))
                print(f"  ✓ {name}")
            except AssertionError as e:
                _results.append((name, False, str(e)))
                print(f"  ✗ {name}: {e}")
                import traceback
                traceback.print_exc()
            except Exception as e:
                import traceback
                traceback.print_exc()
                _results.append((name, False, f"{type(e).__name__}: {e}"))
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        wrapper._is_test = True
        return wrapper
    return decorator


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: actual={actual!r}, expected={expected!r}")


def assert_true(value, msg=""):
    if not value:
        raise AssertionError(f"{msg}: value is falsy ({value!r})")


def assert_false(value, msg=""):
    if value:
        raise AssertionError(f"{msg}: value is truthy ({value!r})")


# ─── 测试用例 ─────────────────────────────────────────────

# ============ 模块单元测试 ============

@test("process_lock.get_process_start_time: 跨平台获取")
def test_get_process_start_time():
    from services.process_lock import get_process_start_time
    st = get_process_start_time(os.getpid())
    assert_true(st is not None, "应该返回启动时间戳")
    assert_true(st > 1_000_000_000, f"时间戳应该 > 2001 年，实际 {st}")


@test("process_lock.atomic_write: 写入 + 读取一致")
def test_atomic_write():
    from services.process_lock import atomic_write
    test_file = TEST_DATA_DIR / "test_atomic.txt"
    atomic_write(test_file, "hello\nworld\n")
    content = test_file.read_text()
    assert_eq(content, "hello\nworld\n", "内容应该一致")
    test_file.unlink()


@test("process_lock.atomic_write: 父目录不存在时自动创建")
def test_atomic_write_mkdir():
    from services.process_lock import atomic_write
    test_file = TEST_DATA_DIR / "subdir" / "test_atomic.txt"
    if test_file.exists():
        test_file.unlink()
    atomic_write(test_file, "test")
    assert_true(test_file.exists(), "文件应该存在")
    test_file.unlink()
    test_file.parent.rmdir()


# ============ ipc_listener 测试 ============

@test("ipc_listener: Unix bind + probe + 残留自愈 + 并发等待语义")
def test_ipc_listener_unix():
    """bind → probe 通；死残留清理重建；已活实例场景 start 返回 False（复用）。"""
    from services.ipc_listener import IpcListener, ipc_probe_alive
    from config import ipc_unix_socket_path

    from services.ipc_listener import IpcStartStatus
    lst = IpcListener()
    assert_true(lst.start() is IpcStartStatus.LISTENING, "首次 bind 应返回 LISTENING")
    try:
        assert_true(ipc_probe_alive(timeout=1.0), "bind 后 probe 应通")
        # 已有活实例：新 IpcListener.start 应返回 EXISTING_INSTANCE（复用语义，不抛错）
        second = IpcListener()
        assert_true(
            second.start() is IpcStartStatus.EXISTING_INSTANCE,
            "活实例在时第二个 start 应返回 EXISTING_INSTANCE",
        )
    finally:
        lst.cleanup()
        ipc_unix_socket_path().unlink(missing_ok=True)

    # 死残留自愈：文件存在但无人监听 → probe 失败 → 再次 start 应清理并成功
    ipc_unix_socket_path().touch()
    assert_false(ipc_probe_alive(timeout=0.5), "死残留 probe 应失败")
    lst2 = IpcListener()
    assert_true(
        lst2.start() is IpcStartStatus.LISTENING,
        "死残留应被清理后重新 bind（LISTENING）",
    )
    lst2.cleanup()
    ipc_unix_socket_path().unlink(missing_ok=True)


@test("ipc_listener: bind 后可通过 uds 完成 HTTP 往返")
def test_ipc_listener_http_roundtrip():
    """最小 FastAPI + TCP + IPC 桥 → httpx(uds) 请求 /health。

    上游 uvicorn 用独立随机端口并注册进 FrontendPortRegistry
    （桥经注册中心找 upstream，与生产路径一致）。
    """
    import threading
    import httpx
    import uvicorn
    from services.frontend_port import frontend_ports
    from services.ipc_listener import IpcListener, cleanup_ipc_listener

    app = FastAPI()

    @app.get("/health")
    def _h():
        return {"ok": True}

    upstream_port = __import__("random").randint(41000, 49000)
    config = uvicorn.Config(app, host="127.0.0.1", port=upstream_port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(20):
        if server.started:
            break
        time.sleep(0.25)
    assert_true(server.started, "uvicorn 测试实例应启动")
    assert_true(
        frontend_ports.register_tcp(upstream_port),
        "上游端口应注册成功（有监听）",
    )

    from services.ipc_listener import IpcStartStatus
    listener = IpcListener()
    assert_true(listener.start() is IpcStartStatus.LISTENING, "IPC 监听应启动")
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(_ipc_sock())),
            base_url="http://localhost",
            timeout=5,
        ) as c:
            r = c.get("/health")
            assert_eq(r.status_code, 200, "uds HTTP 往返应 200")
            assert_true(r.json().get("ok") is True, "响应体应正确")
    finally:
        listener.cleanup()
        frontend_ports.unregister_tcp()
        server.should_exit = True
        t.join(timeout=5)  # 确保 TCP 完全释放，不泄漏到后续测试


def _ipc_sock():
    from config import ipc_unix_socket_path
    return ipc_unix_socket_path()
    from config import ipc_unix_socket_path
    return ipc_unix_socket_path()


# ============ heartbeat 测试 ============

@test("heartbeat: record + 幂等键 + active_count")
def test_heartbeat_record():
    from services.heartbeat import HeartbeatRegistry
    reg = HeartbeatRegistry()
    reg.record(11111)
    reg.record(22222)
    reg.record(11111)  # 同 pid 重复心跳 → 刷新而非新增
    assert_eq(reg.active_count(), 2, "同 pid 重复心跳应幂等")


@test("heartbeat.sweep: 超时未跳的条目被移除，活跃的保留")
def test_heartbeat_sweep():
    import services.heartbeat as hb
    from services.heartbeat import HeartbeatRegistry
    orig = hb.HEARTBEAT_TIMEOUT_SEC
    hb.HEARTBEAT_TIMEOUT_SEC = 0.3  # monkeypatch 小超时（sweep 读模块全局）
    try:
        reg = HeartbeatRegistry()
        reg.record(11111)
        time.sleep(0.5)          # 11111 超时
        reg.record(22222)        # 刚跳，活跃
        removed = reg.sweep()
        assert_eq(removed, 1, "应移除 1 个超时条目")
        assert_eq(reg.active_count(), 1, "应剩 1 个活跃条目")
    finally:
        hb.HEARTBEAT_TIMEOUT_SEC = orig


@test("heartbeat.HeartbeatTask: 宽限期内表空不自杀，过宽限后自杀")
def test_heartbeat_task_grace_and_suicide():
    import services.heartbeat as hb
    from services.heartbeat import HeartbeatRegistry, HeartbeatTask
    orig_interval, orig_grace = hb.HEARTBEAT_SWEEP_INTERVAL_SEC, hb.HEARTBEAT_GRACE_SEC
    hb.HEARTBEAT_SWEEP_INTERVAL_SEC = 0.1
    hb.HEARTBEAT_GRACE_SEC = 0.4
    fired = []
    try:
        # 宽限期内表空：不自杀
        reg1 = HeartbeatRegistry()
        t1 = HeartbeatTask(reg1, lambda: fired.append("early"))
        t1.start()
        time.sleep(0.25)  # < 0.4 宽限
        assert_eq(len(fired), 0, "宽限期内表空不应自杀")
        t1.stop()
        # 过宽限后表空：自杀
        reg2 = HeartbeatRegistry()
        t2 = HeartbeatTask(reg2, lambda: fired.append("late"))
        t2.start()
        time.sleep(0.7)  # > 0.4 宽限 + 多个 sweep 周期
        assert_true("late" in fired, "过宽限后表空应触发自杀回调")
        t2.stop()
    finally:
        hb.HEARTBEAT_SWEEP_INTERVAL_SEC = orig_interval
        hb.HEARTBEAT_GRACE_SEC = orig_grace


@test("heartbeat.HeartbeatTask: 宽限过后注册→停跳→必须等满超时才自杀（非表空即杀）")
def test_heartbeat_task_full_timeout_after_registration():
    """防语义曲化的锚点: 表空 ≠ 立即自杀。

    场景: 宽限期已过，opencode 注册后又退出。它的条目留在表里直到
    超时被 sweep 移除——移除那一刻才是自杀判定点，而非"最后一次心跳后
    宽限结束就杀"。若未来有人把宽限判定改成"距最后心跳"，此测试会抓住。
    """
    import services.heartbeat as hb
    from services.heartbeat import HeartbeatRegistry, HeartbeatTask
    orig_interval, orig_grace, orig_timeout = (
        hb.HEARTBEAT_SWEEP_INTERVAL_SEC, hb.HEARTBEAT_GRACE_SEC, hb.HEARTBEAT_TIMEOUT_SEC
    )
    hb.HEARTBEAT_SWEEP_INTERVAL_SEC = 0.1
    hb.HEARTBEAT_GRACE_SEC = 0.3
    hb.HEARTBEAT_TIMEOUT_SEC = 0.8
    fired = []
    try:
        # 时序: 宽限内先注册，宽限过后才停跳
        reg = HeartbeatRegistry()
        t0 = time.monotonic()
        task = HeartbeatTask(reg, lambda: fired.append(time.monotonic()))
        task.start()
        reg.record(11111)      # 宽限期内注册
        time.sleep(0.45)       # 过宽限(0.3)，但条目未到超时(0.8)——不得自杀
        assert_eq(len(fired), 0, "条目未超时前不得自杀（即使宽限已过）")
        time.sleep(0.6)        # 条目超时(0.8)被 sweep → 表空 → 自杀
        assert_eq(len(fired), 1, "条目超时移除后应自杀")
        suicide_at = fired[0] - t0
        assert_true(suicide_at >= 0.75, f"自杀应不早于条目超时时刻（实际 {suicide_at:.2f}s）")
        task.stop()
    finally:
        hb.HEARTBEAT_SWEEP_INTERVAL_SEC = orig_interval
        hb.HEARTBEAT_GRACE_SEC = orig_grace
        hb.HEARTBEAT_TIMEOUT_SEC = orig_timeout


@test("heartbeat: 多 opencode 时序——A 停跳被移除，B 持续跳则控制台不死")
def test_heartbeat_multi_user_timeline():
    import services.heartbeat as hb
    from services.heartbeat import HeartbeatRegistry, HeartbeatTask
    orig = (hb.HEARTBEAT_SWEEP_INTERVAL_SEC, hb.HEARTBEAT_GRACE_SEC, hb.HEARTBEAT_TIMEOUT_SEC)
    hb.HEARTBEAT_SWEEP_INTERVAL_SEC = 0.1
    hb.HEARTBEAT_GRACE_SEC = 0.3
    hb.HEARTBEAT_TIMEOUT_SEC = 0.5
    fired = []
    try:
        reg = HeartbeatRegistry()
        task = HeartbeatTask(reg, lambda: fired.append(1))
        task.start()
        reg.record(11111)  # A
        reg.record(22222)  # B
        time.sleep(0.25)   # 宽限内
        # A 停跳；B 每 0.15s 续跳
        import threading
        stop_b = threading.Event()

        def b_loop():
            while not stop_b.wait(0.15):
                reg.record(22222)

        bt = threading.Thread(target=b_loop, daemon=True)
        bt.start()
        time.sleep(1.2)   # A 早已超时移除；B 一直续跳
        assert_eq(len(fired), 0, "B 存活时控制台不得自杀")
        assert_eq(reg.active_count(), 1, "应只剩 B")
        # B 也停跳 → 全移除 → 自杀
        stop_b.set()
        bt.join(timeout=2)
        time.sleep(1.0)
        assert_eq(len(fired), 1, "B 停跳超时后应自杀")
        task.stop()
    finally:
        hb.HEARTBEAT_SWEEP_INTERVAL_SEC, hb.HEARTBEAT_GRACE_SEC, hb.HEARTBEAT_TIMEOUT_SEC = orig


@test("heartbeat 路由: 并发 POST 不丢注册（10 路同时跳）")
def test_heartbeat_route_concurrent():
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from routes.heartbeat import router
    from services.heartbeat import heartbeats

    # 直接压路由层（TestClient 走 ASGI，绕过 uds；heartbeats 是生产单例，
    # 测完手动清空防止影响其他测试）
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        with ThreadPoolExecutor(10) as ex:
            results = list(ex.map(
                lambda i: client.post("/api/heartbeat", json={"pid": 30000 + i}).status_code,
                range(10),
            ))
        assert_true(all(s == 200 for s in results), f"应全 200，实际 {results}")
        assert_eq(heartbeats.active_count(), 10, "10 个不同 pid 应全部入表")
        # 非法 pid 被拒（pydantic gt=0）
        assert_eq(client.post("/api/heartbeat", json={"pid": -1}).status_code, 422, "负 pid 应 422")
    finally:
        # 清空生产单例表（防泄漏到其他测试的 active 断言）
        with heartbeats._lock:
            heartbeats._entries.clear()

@test("config_store.read_all: 读到 4 项配置")
def test_config_read_all():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置或不存在")
    from services.config_store import read_all
    configs = read_all()
    assert_true("DEEPSEEK_API_KEY" in configs, "应该有 DEEPSEEK_API_KEY")
    assert_true("IDA_PRO_HOME" in configs, "应该有 IDA_PRO_HOME")


@test("config_store.write + delete: 不破坏原有注释")
def test_config_write_preserve_comments():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置")
    from services.config_store import read_all, write, delete
    ai_env_path = OPENCODE_ROOT / ".ai_env"
    original = ai_env_path.read_text()

    try:
        write({"TEST_CONTROL_KEY": "test_value"})
        content = ai_env_path.read_text()
        assert_true("# bw-security-analysis" in content, "原注释应该保留")
        assert_true("TEST_CONTROL_KEY=test_value" in content, "新 key 应该写入")

        delete("TEST_CONTROL_KEY")
        content = ai_env_path.read_text()
        assert_true("TEST_CONTROL_KEY" not in content, "key 应该被删除")
        assert_true("# bw-security-analysis" in content, "注释仍应保留")
    finally:
        # 还原
        ai_env_path.write_text(original)


@test("config_store.required_status: 必要配置状态")
def test_required_status():
    from config import _init_validators
    _init_validators()
    from services.config_store import required_status
    keys = {c.key for c in required_status()}
    assert_true("DEEPSEEK_API_KEY" in keys, "应有 DEEPSEEK_API_KEY")
    assert_true("IDA_PRO_HOME" in keys, "应有 IDA_PRO_HOME")


@test("config_store.validate_ida_pro_home: 存在路径")
def test_validate_ida_pro_home():
    from services.config_store import validate_ida_pro_home
    # 当前用户的 IDA_PRO_HOME
    from services.config_store import read
    ida_home = read("IDA_PRO_HOME")
    if ida_home:
        ok, msg = validate_ida_pro_home(ida_home)
        assert_true(ok, f"已配置的 IDA_PRO_HOME 应该有效: {msg}")


@test("config_store.validate_ida_pro_home: 不存在路径")
def test_validate_ida_pro_home_invalid():
    from services.config_store import validate_ida_pro_home
    ok, msg = validate_ida_pro_home("/nonexistent/path")
    assert_false(ok, "不存在路径应该无效")
    assert_true("不存在" in msg, f"错误信息应该包含'不存在': {msg}")


# ============ detect_tools 测试 ============

@test("detect_tools.scan_agent: mobile-analysis 工具")
def test_scan_mobile():
    from config import _init_validators
    _init_validators()
    from services.detect_tools import scan_agent
    tools = scan_agent("mobile-analysis")
    assert_true(len(tools) > 0, "应该有工具")
    names = [t.name for t in tools]
    assert_true("apktool" in names, "应该包含 apktool")
    assert_true("ida_pro" in names, "应该包含 ida_pro")


@test("detect_tools.scan_all: 所有 agent")
def test_scan_all():
    from services.detect_tools import scan_all
    all_tools = scan_all()
    assert_true("binary-analysis" in all_tools, "应有 binary-analysis")
    assert_true("mobile-analysis" in all_tools, "应有 mobile-analysis")


# ============ docker_manager 测试 ============

@test("docker_manager.check_status: Docker 安装 + daemon 状态")
def test_docker_status():
    from services.docker_manager import check_status
    status = check_status()
    assert_true(isinstance(status.installed, bool), "应该返回 installed 字段")
    assert_true(isinstance(status.daemon_running, bool), "应该返回 daemon_running 字段")


@test("docker_manager.scan_global: 返回完整结构")
def test_docker_scan_global():
    from services.docker_manager import scan_global
    result = scan_global()
    assert_true(result.docker.installed, "应有 docker 字段")
    assert_true(isinstance(result.containers, list), "应有 containers 字段")
    assert_true(isinstance(result.images, list), "应有 images 字段")


# ============ scanner 测试 ============

@test("scanner.scan_all: 全量扫描返回完整结果")
def test_scanner_full():
    import asyncio
    from config import _init_validators
    _init_validators()
    from services.scanner import get_scanner
    result = asyncio.run(get_scanner().scan_all(force_refresh=True))
    assert_true(len(result.agents) > 0, "应该有 agent 数据")
    assert_true(result.global_.docker is not None, "应该有 docker 数据")
    assert_true(result.global_.required_configs is not None, "应该有 configs 数据")
    assert_true(result.global_.models is not None, "应该有 models 数据")


@test("scanner.scan_all: 缓存命中（无 force_refresh 时返回缓存）")
def test_scanner_cache():
    import asyncio
    from services.scanner import get_scanner
    scanner = get_scanner()
    # 第一次扫描
    asyncio.run(scanner.scan_all(force_refresh=True))
    # 第二次应该命中缓存（时间应该更短）
    start = time.time()
    asyncio.run(scanner.scan_all())
    duration = time.time() - start
    assert_true(duration < 0.1, f"缓存命中应该 < 0.1s，实际 {duration:.3f}s")


# ============ 端到端：控制台启动 + HTTP API ============

class ControlProcess:
    """控制台进程管理（测试用）。"""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.client: httpx.Client | None = None

    def start(self):
        """启动控制台（首跳心跳防自杀）。"""
        env = os.environ.copy()
        cmd = [
            sys.executable,
            str(BACKEND_DIR / "server.py"),
        ]
        self.proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        # 等 IPC socket 出现 + /health 应答（uds 探测）
        from config import ipc_unix_socket_path
        sock_path = ipc_unix_socket_path()
        for _ in range(20):
            if sock_path.exists():
                try:
                    with httpx.Client(
                        transport=httpx.HTTPTransport(uds=str(sock_path)),
                        timeout=2,
                    ) as probe:
                        probe.get("http://localhost/health")
                        # 200/503 都算活着（503=模型加载中）；
                        # disconnected（uvicorn 未起）等异常继续轮询
                        self.client = httpx.Client(
                            transport=httpx.HTTPTransport(uds=str(sock_path)),
                            timeout=15,
                        )
                        # 首跳心跳防自杀（同时验证 /api/heartbeat 路由）
                        r = self.client.post(
                            "http://localhost/api/heartbeat",
                            json={"pid": os.getpid()},
                        )
                        assert r.status_code == 200, f"心跳路由应 200，实际 {r.status_code}"
                        return
                except Exception:
                    pass
            time.sleep(0.5)
        raise AssertionError("控制台启动超时（IPC 未就绪）")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            self.proc = None
        if self.client:
            self.client.close()
            self.client = None
        # 清理沙箱 IPC socket（控制台信号处理已删 sock，这里兜底）
        from config import ipc_unix_socket_path
        try:
            ipc_unix_socket_path().unlink(missing_ok=True)
        except OSError:
            pass


# ── E2E 共享控制台进程（模型只加载一次；端口/用户全局文件生命周期由首个启动者管理） ──
_SHARED_CP: "ControlProcess | None" = None


def get_shared_server() -> ControlProcess:
    """E2E 段共享控制台（懒加载；main() 退出时统一 stop）。

    只读/自清理用例共享同一进程，消灭每例 ~5s 的重复模型加载；
    需要独占全局状态的用例（端口耗尽）先 stop_shared_server()。
    """
    global _SHARED_CP
    if _SHARED_CP is None:
        _SHARED_CP = ControlProcess()
        _SHARED_CP.start()
    return _SHARED_CP


def stop_shared_server() -> None:
    global _SHARED_CP
    if _SHARED_CP is not None:
        _SHARED_CP.stop()
        _SHARED_CP = None


@test("E2E: 控制台启动 + /health + /embed")
def test_e2e_control_startup():
    cp = get_shared_server()
    import httpx
    # /health
    r = cp.client.get("http://localhost/health", timeout=10)
    assert_true(r.status_code in (200, 503), f"/health 应返回 200/503，实际 {r.status_code}")

    # 等模型加载
    for _ in range(30):
        r = cp.client.get("http://localhost/health", timeout=3)
        if r.status_code == 200:
            break
        time.sleep(1)

    # /embed
    r = cp.client.post(
        f"http://localhost/embed",
        json={"inputs": "hello world"},
        timeout=30,
    )
    assert_eq(r.status_code, 200, f"/embed 应返回 200，实际 {r.status_code}")
    data = r.json()
    assert_true(len(data) == 1, f"应返回 1 个向量，实际 {len(data)}")
    assert_eq(len(data[0]), 1024, f"向量维度应 1024，实际 {len(data[0])}")


@test("E2E: 控制台全局唯一（第二个进程 exit 2）")
def test_e2e_singleton():
    # 复用共享控制台作为"第一个进程"（独立起第二个短命进程验证 exit 2）
    cp = get_shared_server()
    env = os.environ.copy()
    proc2 = subprocess.Popen(
        [sys.executable, str(BACKEND_DIR / "server.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        proc2.wait(timeout=15)
        assert_eq(proc2.returncode, 2, f"第二个进程应该 exit 2，实际 {proc2.returncode}")
    finally:
        if proc2.poll() is None:
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except Exception:
                proc2.kill()


@test("E2E: GET /api/config 返回配置")
def test_e2e_get_config():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置")
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/config", timeout=5)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_true("DEEPSEEK_API_KEY" in data, "应有 DEEPSEEK_API_KEY")


@test("E2E: GET /api/config/required-status")
def test_e2e_required_status():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/config/required-status", timeout=5)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_true("DEEPSEEK_API_KEY" in data, "应有 DEEPSEEK_API_KEY 状态")


@test("E2E: GET /api/scan 全量扫描")
def test_e2e_scan():
    cp = get_shared_server()
    import httpx
    # 等模型加载（scanner 会查 model 状态）
    for _ in range(20):
        r = cp.client.get("http://localhost/health", timeout=3)
        if r.status_code == 200:
            break
        time.sleep(1)

    r = cp.client.get("http://localhost/api/scan", timeout=30)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_true("agents" in data, "应有 agents")
    assert_true("global" in data, "应有 global")


@test("E2E: GET /api/deps/mobile-analysis")
def test_e2e_deps():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/deps/mobile-analysis", timeout=10)
    assert_eq(r.status_code, 200)
    tools = r.json()
    assert_true(len(tools) > 0, "应有工具列表")


@test("E2E: GET /api/docker/status")
def test_e2e_docker():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/docker/status", timeout=10)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_true("docker" in data, "应有 docker 字段")


@test("E2E: GET /api/hardware 硬件信息")
def test_e2e_hardware():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/hardware", timeout=10)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_true("cpu" in data, "应有 cpu")
    assert_true("memory" in data, "应有 memory")
    assert_true("os" in data, "应有 os")
    assert_true("gpu" in data, "应有 gpu")


@test("E2E: PUT /api/config 写入 + 验证文件")
def test_e2e_config_write():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置")
    ai_env_path = OPENCODE_ROOT / ".ai_env"
    original = ai_env_path.read_text()
    cp = get_shared_server()
    import httpx
    r = cp.client.put(
        f"http://localhost/api/config",
        json={"configs": {"E2E_TEST_KEY": "e2e_value"}},
        timeout=5,
    )
    assert_eq(r.status_code, 200)
    # 验证文件实际改变
    content = ai_env_path.read_text()
    assert_true("E2E_TEST_KEY=e2e_value" in content, "文件应包含新 key")
    # 清理 + 还原
    ai_env_path.write_text(original)


@test("E2E: /api/install 白名单外拒绝")
def test_e2e_install_whitelist():
    cp = get_shared_server()
    import httpx
    r = cp.client.post(
        f"http://localhost/api/install",
        json={"package": "malicious-package-not-in-whitelist"},
        timeout=5,
    )
    assert_eq(r.status_code, 400, "白名单外应返回 400")


@test("ipc_listener: BIND_TIMEOUT——窗口耗尽且无活实例时返回真异常枚举")
def test_ipc_listener_bind_timeout():
    import services.ipc_listener as il

    lst = il.IpcListener()
    # monkeypatch：bind 恒失败 + 探测恒不通 + 缩短等待窗口
    orig_start, orig_probe, orig_wait = (
        il.IpcListener._do_start_platform, il.ipc_probe_alive, il.IPC_BIND_WAIT_SEC
    )
    il.IpcListener._do_start_platform = lambda self: None
    il.ipc_probe_alive = lambda **kw: False
    il.IPC_BIND_WAIT_SEC = 0.2
    try:
        from config import ipc_unix_socket_path
        ipc_unix_socket_path().unlink(missing_ok=True)  # 确保不触发"文件消失提前重试"
        status = lst.start()
        assert_true(
            status is il.IpcStartStatus.BIND_TIMEOUT,
            f"应返回 BIND_TIMEOUT，实际 {status}",
        )
    finally:
        il.IpcListener._do_start_platform = orig_start
        il.ipc_probe_alive = orig_probe
        il.IPC_BIND_WAIT_SEC = orig_wait


# ============ frontend_port（注册中心）测试 ============

@test("frontend_port: TCP 顺延 bind + 注册")
def test_frontend_port_fallback():
    import os
    import random as _rnd
    import socket
    from services.frontend_port import FrontendPortRegistry

    def _port_free(p: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    # 随机起点段可能撞系统临时端口：选前两个候选都空闲的起点（最多试 5 次）
    for _ in range(5):
        if _port_free(FrontendPortRegistry.tcp_candidates()[0]) and \
           _port_free(FrontendPortRegistry.tcp_candidates()[1]):
            break
        os.environ["CONTROL_TCP_PORT"] = str(_rnd.randint(41000, 49000))

    reg = FrontendPortRegistry()
    candidates = reg.tcp_candidates()
    assert_true(len(candidates) >= 2, "候选段至少 2 个")
    # 占住起点 → bind 应顺延到下一候选
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", candidates[0]))
    blocker.listen(1)
    try:
        sock = reg.bind_and_register_tcp()
        try:
            assert_eq(reg.tcp_port(), candidates[1], "应顺延并注册下一候选端口")
        finally:
            sock.close()
            reg.unregister_tcp()
        # 候选段全占 → RuntimeError
        blockers = [blocker]
        for p in candidates[1:]:
            b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            b.bind(("127.0.0.1", p))
            b.listen(1)
            blockers.append(b)
        try:
            reg2 = FrontendPortRegistry()
            raised = False
            try:
                reg2.bind_and_register_tcp()
            except RuntimeError:
                raised = True
            assert_true(raised, "候选段全占应 RuntimeError")
        finally:
            for b in blockers:
                b.close()
    finally:
        blocker.close()
@test("frontend_port: vite 注册 + console_url 计算分支")
def test_frontend_port_vite_and_url():
    from services.frontend_port import FrontendPortRegistry, _port_alive

    reg = FrontendPortRegistry()
    # 发布态（非 dev）：注册 TCP 后 console_url 指向该端口。
    # monkeypatch is_dev_mode：防 .ai_env 的 CONTROL_FRONTEND_DEV=1 + 生产 vite(5173) 干扰
    import services.frontend_port as _fp
    _orig_dev = _fp.is_dev_mode
    _fp.is_dev_mode = lambda: False
    import socket as _s
    srv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert_true(reg.register_tcp(port), "注册活端口应成功")
        url = reg.console_url()
        assert_true(url.endswith(f":{port}"), f"发布态 URL 应含注册端口，实际 {url}")
        # vite 注册死端口 → vite_port() 不得返回死注册值；返回则必须是真实监听端口
        # （环境里可能有真 vite 在 5173-5175——回退探测命中是设计行为，不算失败）
        reg.register_vite_port(1)  # 端口 1 无监听
        vp = reg.vite_port()
        if vp is not None:
            from services.frontend_port import _port_alive
            assert_true(vp != 1 and _port_alive(vp), f"回退值应为活端口，实际 {vp}")
    finally:
        srv.close()
        reg.unregister_tcp()
        _fp.is_dev_mode = _orig_dev
    # register_tcp 死端口 + verify → False
    assert_false(reg.register_tcp(1), "注册死端口（verify_alive）应失败")


# ============ 边界条件补充测试 ============

@test("config_store.write: 覆盖已存在 key")
def test_config_overwrite():
    if not OPENCODE_ROOT.exists(): return
    from services.config_store import read_all, write
    original = (OPENCODE_ROOT / ".ai_env").read_text()
    try:
        write({"TEST_OV": "v1"})
        assert_eq(read_all().get("TEST_OV"), "v1")
        write({"TEST_OV": "v2"})
        assert_eq(read_all().get("TEST_OV"), "v2", "覆盖后应新值")
    finally:
        (OPENCODE_ROOT / ".ai_env").write_text(original)


@test("config_store.write: 批量多个 key")
def test_config_multi_keys():
    if not OPENCODE_ROOT.exists(): return
    from services.config_store import read_all, write
    original = (OPENCODE_ROOT / ".ai_env").read_text()
    try:
        write({"TEST_M1": "v1", "TEST_M2": "v2", "TEST_M3": "v3"})
        cfg = read_all()
        assert_eq(cfg.get("TEST_M1"), "v1")
        assert_eq(cfg.get("TEST_M2"), "v2")
        assert_eq(cfg.get("TEST_M3"), "v3")
    finally:
        (OPENCODE_ROOT / ".ai_env").write_text(original)


@test("detect_tools: otool 平台过滤（非 macOS skipped）")
def test_tool_platform_filter():
    import sys as _sys
    from services.detect_tools import scan_tool, EXTERNAL_TOOLS
    otool = next((t for t in EXTERNAL_TOOLS if t.name == "otool"), None)
    if otool is None: return
    result = scan_tool(otool)
    if _sys.platform == "darwin":
        assert_false(result.skipped, "macOS otool 不应 skipped")
    else:
        assert_true(result.skipped, "非 macOS otool 应 skipped")


@test("detect_tools: GoReSym required=False（可选）")
def test_tool_optional():
    from services.detect_tools import scan_tool, EXTERNAL_TOOLS
    gosym = next((t for t in EXTERNAL_TOOLS if t.name == "GoReSym"), None)
    if gosym is None: return
    result = scan_tool(gosym)
    assert_false(result.required, "GoReSym 应 required=False")


@test("E2E: 浏览器 TCP 被占 → 顺延候选段（不 exit 3）")
def test_e2e_tcp_fallback():
    # 占住沙箱起点端口 → 控制台应顺延到下一候选并正常服务（IPC 应答）。
    # 先停共享（后续用例懒加载会自动重启，代价一次模型加载）
    stop_shared_server()
    import socket
    from config import ipc_unix_socket_path
    from services.frontend_port import frontend_ports
    start_port = frontend_ports.tcp_candidates()[0]
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", start_port))
    blocker.listen(1)
    env = os.environ.copy()
    env["CONTROL_TCP_PORT"] = str(start_port)  # 子进程与沙箱同起点
    proc = subprocess.Popen(
        [sys.executable, str(BACKEND_DIR / "server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        import httpx
        sock_path = ipc_unix_socket_path()
        ok_port = None
        for _ in range(20):
            if sock_path.exists():
                try:
                    with httpx.Client(
                        transport=httpx.HTTPTransport(uds=str(sock_path)), timeout=2,
                    ) as c:
                        r = c.get("http://localhost/api/console-url")
                        if r.status_code == 200:
                            ok_port = r.json().get("tcp_port")
                            break
                except Exception:
                    pass
            time.sleep(0.5)
        assert_true(isinstance(ok_port, int), "IPC 应答 /api/console-url")
        candidates = frontend_ports.tcp_candidates()
        assert_true(
            ok_port in candidates and ok_port != start_port,
            f"应顺延到 {start_port} 之外的候选 {candidates}，实际注册 {ok_port}",
        )
        # 顺延后的 TCP 真的在听
        import services.frontend_port as _fp
        assert_true(_fp._port_alive(ok_port), f"顺延端口 {ok_port} 应有监听")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        blocker.close()


@test("E2E: /embed 空输入 → 400")
def test_e2e_embed_empty():
    cp = get_shared_server()
    import httpx
    r = cp.client.post("http://localhost/embed", json={}, timeout=10)
    assert_eq(r.status_code, 400, "空输入应 400")


@test("E2E: /embed 批量 list 输入")
def test_e2e_embed_batch():
    cp = get_shared_server()
    import httpx
    for _ in range(30):
        r = cp.client.get("http://localhost/health", timeout=3)
        if r.status_code == 200: break
        time.sleep(1)
    r = cp.client.post("http://localhost/embed",
                   json={"inputs": ["hello", "world", "test"]}, timeout=30)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_eq(len(data), 3, "应返回 3 个向量")
    assert_eq(len(data[0]), 1024)


@test("E2E: /embed 字符串单输入")
def test_e2e_embed_single():
    cp = get_shared_server()
    import httpx
    for _ in range(30):
        r = cp.client.get("http://localhost/health", timeout=3)
        if r.status_code == 200: break
        time.sleep(1)
    r = cp.client.post("http://localhost/embed",
                   json={"inputs": "single string"}, timeout=30)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_eq(len(data), 1)


@test("E2E: /rerank 接口")
def test_e2e_rerank():
    cp = get_shared_server()
    import httpx
    for _ in range(60):
        r = cp.client.get("http://localhost/health", timeout=3)
        if r.status_code == 200: break
        time.sleep(1)
    r = cp.client.post("http://localhost/rerank",
                   json={"query": "hello", "texts": ["world", "test"]}, timeout=60)
    assert_eq(r.status_code, 200)
    data = r.json()
    assert_eq(len(data), 2)


@test("E2E: /api/config/{key} 不存在 → 404")
def test_e2e_config_404():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/config/NOT_EXIST_12345", timeout=5)
    assert_eq(r.status_code, 404)


@test("E2E: DELETE /api/config/{key}")
def test_e2e_config_delete():
    cp = get_shared_server()
    import httpx
    cp.client.put("http://localhost/api/config/E2E_DEL",
              json={"value": "test"}, timeout=5)
    r = cp.client.delete("http://localhost/api/config/E2E_DEL", timeout=5)
    assert_eq(r.status_code, 200)
    r = cp.client.get("http://localhost/api/config/E2E_DEL", timeout=5)
    assert_eq(r.status_code, 404, "删后应 404")


@test("E2E: /api/deps/{agent} 不存在 agent → 工具空 + summary 就绪")
def test_e2e_deps_unknown():
    cp = get_shared_server()
    import httpx
    r = cp.client.get("http://localhost/api/deps/non-existent", timeout=5)
    assert_eq(r.status_code, 200)
    d = r.json()
    # 新契约：响应是聚合对象（summary/python/tools/compiler/shared_infra）
    # 未知 agent 无归属工具 → tools 空；all 级 Python 包仍命中；
    # 共享底座非归属 → 不参与判定 → summary.ready 反映 all 级包状态
    assert_eq(len(d["tools"]), 0, "未知 agent 的外部工具应为空")
    assert "summary" in d and "console_url" in d["summary"], "summary 应含 console_url"
    assert isinstance(d["summary"]["required_missing"], list), "summary 应含 required_missing"


@test("E2E: /api/scan 缓存命中（第二次更快）")
def test_e2e_scan_cache():
    cp = get_shared_server()
    import httpx
    t1 = time.time()
    cp.client.get("http://localhost/api/scan?force_refresh=true", timeout=30)
    dur1 = time.time() - t1
    t2 = time.time()
    cp.client.get("http://localhost/api/scan", timeout=30)
    dur2 = time.time() - t2
    assert_true(dur2 < dur1, f"缓存应更快：first={dur1:.2f}s cached={dur2:.2f}s")


@test("config.is_dev_mode: 环境变量优先 + 默认 False")
def test_dev_mode_default():
    # is_dev_mode 优先读环境变量 CONTROL_FRONTEND_DEV（高于 .ai_env）——
    # 测试通过环境变量注入，不落地修改真实 .ai_env（防 kill -9 时无法还原）。
    from config import is_dev_mode
    import os as _os

    saved = _os.environ.get("CONTROL_FRONTEND_DEV")
    try:
        _os.environ["CONTROL_FRONTEND_DEV"] = "0"
        assert_false(is_dev_mode(), "env=0 应 False")
        _os.environ["CONTROL_FRONTEND_DEV"] = "1"
        assert_true(is_dev_mode(), "env=1 应 True")
        _os.environ["CONTROL_FRONTEND_DEV"] = "true"
        assert_true(is_dev_mode(), "env=true 应 True")
    finally:
        if saved is None:
            _os.environ.pop("CONTROL_FRONTEND_DEV", None)
        else:
            _os.environ["CONTROL_FRONTEND_DEV"] = saved


# ============ 运行所有测试 ============

def main():
    print("=" * 60)
    print("opencode-control 测试套件")
    print(f"BACKEND_DIR: {BACKEND_DIR}")
    print(f"TEST_DATA_DIR: {TEST_DATA_DIR}")
    print(f"OPENCODE_ROOT: {OPENCODE_ROOT}")
    print("=" * 60)
    print()

    # 收集所有 @test 函数
    tests = [
        (name, fn) for name, fn in globals().items()
        if callable(fn) and getattr(fn, "_is_test", False)
    ]
    print(f"找到 {len(tests)} 个测试\n")

    # 逐个运行
    for name, fn in tests:
        fn()

    # 统一收尾共享控制台（无论中途失败与否）
    stop_shared_server()

    # 汇总
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"通过 {passed} / 失败 {failed} / 总计 {len(_results)}")
    if failed:
        print("\n失败用例：")
        for name, ok, msg in _results:
            if not ok:
                print(f"  ✗ {name}: {msg}")
    print("=" * 60)
    return 0 if failed == 0 else 1


@test("config_store.ensure_template: 无则创建/有则保留（幂等）")
def test_config_store_ensure_template():
    import tempfile
    from services import config_store

    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / ".ai_env"
        orig = config_store._ai_env_path
        config_store._ai_env_path = lambda: fake
        try:
            assert_true(config_store.ensure_template(), "首次应创建并返回 True")
            assert_true(fake.exists(), "模板文件应存在")
            content = fake.read_text(encoding="utf-8")
            assert "IDA_PRO_HOME=" in content and "DEEPSEEK_API_KEY=" in content
            fake.write_text("USER_CUSTOM=value\n", encoding="utf-8")
            assert_false(config_store.ensure_template(), "已存在应返回 False")
            assert fake.read_text(encoding="utf-8") == "USER_CUSTOM=value\n", "用户内容不得被覆盖"
        finally:
            config_store._ai_env_path = orig


@test("restart: 调度幂等 + 路由契约（不真 exec）")
def test_restart_schedule_and_route():
    from services import restart as restart_mod
    from fastapi.testclient import TestClient
    from server import create_app

    r = restart_mod.ConsoleRestarter()
    calls = []
    r.perform = lambda: calls.append(1)   # 拦截真实 exec
    assert_true(r.schedule(), "首次调度应返回 True")
    assert_false(r.schedule(), "重复调度应返回 False（幂等）")

    app = create_app()
    orig = restart_mod.console_restarter
    restart_mod.console_restarter = r
    try:
        with TestClient(app) as c:
            resp = c.post("/api/system/restart")
            assert resp.status_code == 200
            data = resp.json()
            assert_true(data["success"], "路由应返回 success")
            assert_true("message" in data, "路由应带提示消息")
    finally:
        restart_mod.console_restarter = orig
    # schedule 已被 Timer 挂起 → 立即执行 perform 清掉（Timer 0.05s 后也会调，双调用无害）
    r.perform()
    assert_true(len(calls) >= 1, "perform 应被调用")


@test("health: boot_token 存在且同进程内稳定")
def test_health_boot_token():
    from routes.health import BOOT_TOKEN
    assert_true(len(BOOT_TOKEN) == 8, "boot_token 应为 8 位 hex")


@test("knowledge_store: 队列写路径落库 + 非法条目跳过 + 同步方法（fake embedder）")
def test_knowledge_store_paths():
    import numpy as np
    from services.knowledge_store import MemoryEntry, KnowledgeStoreService

    class FakeEmbedder:
        def encode(self, inputs, **kw):
            single = isinstance(inputs, str)
            seq = [inputs] if single else inputs
            out = np.zeros((len(seq), 1024), dtype=np.float32)
            return out[0] if single else out

    db_path = TEST_DATA_DIR / "ks_unit" / "knowledge.db"
    if db_path.exists():
        db_path.unlink()
    svc = KnowledgeStoreService(db_path=db_path, embedder_factory=FakeEmbedder)
    svc.start()
    assert_true(svc.submit(MemoryEntry(question="bash execution", answer="Tool result...", type="bash", flow_id="flow-1")), "合法条目应入队")
    assert_true(not svc.submit(MemoryEntry(question="", answer="x", type="bash")), "空 question 应跳过")
    assert_true(not svc.submit(MemoryEntry(question="q", answer="a", type="")), "空 type 应跳过")
    svc.stop(timeout=10)

    import sqlite3
    import sqlite_vec
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    rows = conn.execute("SELECT question, type, flow_id FROM answers").fetchall()
    assert_true(rows == [("[bash] bash execution", "memory", "flow-1")], f"落库不符: {rows}")
    assert_true(conn.execute("SELECT count(*) FROM answer_vectors").fetchone()[0] == 1, "向量应 1 行")


@test("event_store: entry/delete 写路径 + add_episode 参数完整（fake graphiti）")
def test_event_store_write_paths():
    from unittest.mock import AsyncMock, patch
    from services.event_store import EventEntry, DeleteGroup, EventStoreService

    calls = []

    class FakeGraphiti:
        driver = object()
        async def build_indices_and_constraints(self):
            calls.append("build")
        async def add_episode(self, **kw):
            calls.append(("add", kw))
        async def close(self):
            calls.append("close")

    svc = EventStoreService(graphiti_factory=lambda: (FakeGraphiti(), None))
    svc.start()
    assert_true(svc.submit(EventEntry(name="bash execution", body="b", source="s", group_id="g1", timestamp=1755432000000.0)), "事件应入队")
    assert_true(svc.submit(DeleteGroup(group_id="g1")), "delete 应入队")
    assert_true(not svc.submit(DeleteGroup(group_id="")), "空 group_id 应跳过")
    with patch("graphiti_core.nodes.EntityNode.delete_by_group_id", new=AsyncMock()) as m1, \
         patch("graphiti_core.nodes.EpisodicNode.delete_by_group_id", new=AsyncMock()) as m2:
        svc.stop(timeout=15)
        assert_true(m1.await_count == 1 and m2.await_count == 1, f"delete 调用数 {m1.await_count}/{m2.await_count}")

    adds = [c for c in calls if isinstance(c, tuple)]
    assert_true(adds and adds[0][0] == "add", f"add_episode 未调用: {calls}")
    kw = adds[0][1]
    assert_true(kw["name"] == "bash execution" and kw["group_id"] == "g1", "name/group_id 不符")
    assert_true(kw["reference_time"].timestamp() == 1755432000.0, "timestamp ms→s 应无损")
    assert_true("Tool" in kw["entity_types"], "entity_types 缺自定义类型")


@test("knowledge/events 路由: 写端点 202 + 搜索端点结构（fake 注入）")
def test_knowledge_events_routes():
    import hashlib
    import numpy as np
    from fastapi.testclient import TestClient
    from services import knowledge_store as ks, event_store as es

    class FakeEmbedder:
        def encode(self, inputs, **kw):
            single = isinstance(inputs, str)
            seq = [inputs] if single else inputs
            def vec(t):
                h = hashlib.sha256(t.encode()).digest()
                out = np.frombuffer((h * 32)[:1024], dtype=np.uint8).astype(np.float32)
                return out / np.linalg.norm(out)
            out = np.stack([vec(t) for t in seq])
            return out[0] if single else out

    class FakeGraphiti:
        driver = object()
        async def build_indices_and_constraints(self):
            pass
        async def add_episode(self, **kw):
            pass
        async def close(self):
            pass

    db_path = TEST_DATA_DIR / "ingest_route" / "knowledge.db"
    if db_path.exists():
        db_path.unlink()
    old_ks, old_es = ks.service_instance(), es.service_instance()
    ks.set_service(ks.KnowledgeStoreService(db_path=db_path, embedder_factory=FakeEmbedder))
    es.set_service(es.EventStoreService(graphiti_factory=lambda: (FakeGraphiti(), None)))
    try:
        from server import create_app
        with TestClient(create_app()) as client:
            r1 = client.post("/api/memory/entry", json={"question": "q", "answer": "a", "type": "bash", "flow_id": "f1"})
            r2 = client.post("/api/events/entry", json={"name": "n", "body": "b", "source": "s", "group_id": "g", "timestamp": 1755432000000})
            r3 = client.post("/api/events/delete", json={"group_id": "g"})
            r4 = client.post("/api/memory/entry", json={"question": "", "answer": "a", "type": "bash"})
            assert_true((r1.status_code, r2.status_code, r3.status_code) == (202, 202, 202), f"状态码 {(r1.status_code, r2.status_code, r3.status_code)}")
            assert_true(r1.json() == {"queued": True}, f"合法应 queued:true: {r1.json()}")
            assert_true(r4.json() == {"queued": False}, f"非法应 queued:false: {r4.json()}")
            r5 = client.post("/api/knowledge/search", json={"questions": ["q"]})
            assert_true(r5.status_code == 200 and r5.json()["count"] == 0, f"knowledge/search: {r5.json()}")
            r6 = client.post("/api/events/time-search", json={"query": "q", "group_id": "g"})
            assert_true(r6.status_code == 200 and r6.json()["edges"] == [], f"time-search: {r6.json()}")
    finally:
        ks.set_service(old_ks)
        es.set_service(old_es)


@test("knowledge_store 同步方法: store 脱敏 + search 命中 + memory flow 隔离（fake embedder）")
def test_knowledge_store_sync_methods():
    import hashlib
    import numpy as np
    from services.knowledge_store import MemoryEntry, KnowledgeStoreService

    def vec(text):
        h = hashlib.sha256(text.encode()).digest()
        out = np.frombuffer((h * 32)[:1024], dtype=np.uint8).astype(np.float32)
        return out / np.linalg.norm(out)

    class FakeEmbedder:
        def encode(self, inputs, **kw):
            single = isinstance(inputs, str)
            seq = [inputs] if single else inputs
            out = np.stack([vec(t) for t in seq])
            return out[0] if single else out

    db_path = TEST_DATA_DIR / "ks_sync" / "knowledge.db"
    if db_path.exists():
        db_path.unlink()
    svc = KnowledgeStoreService(db_path=db_path, embedder_factory=FakeEmbedder)

    r = svc.store_knowledge("如何扫描 192.168.1.1 端口", "nmap -sS 10.0.0.1")
    assert_true(r["stored"] is True, f"store 失败: {r}")
    r = svc.search_knowledge(["如何扫描端口"])
    assert_true(r["count"] == 1 and "<IP>" in r["results"][0]["answer"], f"脱敏失效: {r}")

    svc.start()
    svc.submit(MemoryEntry(question="bash execution", answer="out", type="bash", flow_id="flow-A"))
    svc.stop(timeout=10)
    r = svc.search_memory(["执行过什么"], flow_id="flow-A")
    assert_true(r["count"] == 1 and r["results"][0]["question"].startswith("[bash]"), f"memory 检索: {r}")
    r = svc.search_memory(["执行过什么"], flow_id="flow-B")
    assert_true(r["count"] == 0, "flow 隔离失效")
    assert_true(svc.search_knowledge([])["count"] == 0, "空 questions 应 count=0")
    assert_true(svc.store_knowledge("", "")["stored"] is False, "空 question/content 应 stored=false")


@test("event_store 搜索: time filter + min_mentions 过滤 + 异常重置（fake graphiti）")
def test_event_store_search_paths():
    import asyncio
    from types import SimpleNamespace as NS
    from datetime import datetime
    from services.event_store import EventStoreService

    def mk():
        n1 = NS(name="nmap", uuid="n1", labels=["Tool"], summary="s",
                created_at=datetime(2026, 8, 17), attributes={"mention_count": 3})
        n2 = NS(name="CVE-1", uuid="n2", labels=["Vuln"], summary=None, created_at=None, attributes={})
        return NS(edges=[], nodes=[n1, n2], episodes=[],
                  edge_reranker_scores=[], node_reranker_scores=[0.8, 0.7], episode_reranker_scores=[])

    searched = {}

    class FakeGraphiti:
        driver = object()
        async def build_indices_and_constraints(self): pass
        async def close(self): pass
        async def search_(self, **kw):
            searched.update(kw)
            return mk()

    svc = EventStoreService(graphiti_factory=lambda: (FakeGraphiti(), None))

    async def run():
        p = await svc.search_time("查工具", "g1", time_start="2026-01-01T00:00:00Z")
        assert_true(p["nodes"][0]["name"] == "nmap", "time_search 节点")
        assert_true(searched.get("search_filter") is not None, "time filter 未构建")
        p = await svc.search_entities("q", "g1", node_labels=["Tool"], min_mentions=2)
        assert_true([n["name"] for n in p["nodes"]] == ["nmap"], "min_mentions 过滤")
        assert_true(p["node_scores"] == [0.8], "过滤后 scores 对齐")

    asyncio.run(run())
    svc.stop(timeout=10)

if __name__ == "__main__":
    sys.exit(main())

