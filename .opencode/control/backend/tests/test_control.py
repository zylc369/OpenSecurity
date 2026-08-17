"""opencode-control 后端 + Plugin 集成测试。

按需求文档 §4 验收标准设计测试用例，覆盖：
- 功能验收 F1-F12, F15, F16（F13/F14 前端测试，留待前端完成）
- 边界条件（PID 复用、文件锁 SIGKILL、原子写、端口 fallback、users 清洗）
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
# CONTROL_PORT 随机高位：隔离 bind 候选与孤儿探测范围，避免沙箱 spawn 收编/干扰
# 生产控制台（9776）。test_e2e_port_exhausted 动态读 get_port_candidates，自洽。
os.environ.setdefault("CONTROL_PORT", str(__import__("random").randint(41000, 49000)))


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
            except Exception as e:
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

@test("process_lock.is_process_alive: 自己 PID 存活")
def test_is_process_alive_self():
    from services.process_lock import is_process_alive
    assert_true(is_process_alive(os.getpid()), "自己 PID 应该存活")


@test("process_lock.is_process_alive: 死 PID")
def test_is_process_alive_dead():
    from services.process_lock import is_process_alive
    assert_false(is_process_alive(99999), "99999 应该不存在")


@test("process_lock.is_process_alive: PID 复用防护（startTime=0 视为未提供）")
def test_pid_reuse_protection():
    from services.process_lock import is_process_alive
    # startTime=0 视为未提供，宽容处理（返回 True）
    assert_true(is_process_alive(os.getpid(), 0), "startTime=0 应宽容返回 True")
    # startTime=99999（明显不匹配）应该返回 False
    assert_false(is_process_alive(os.getpid(), 99999), "不匹配的 startTime 应返回 False")


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


@test("process_lock.acquire_startup_lock: 拿到锁")
def test_acquire_lock():
    from services.process_lock import acquire_startup_lock
    with acquire_startup_lock():
        pass  # 拿到锁后正常释放


@test("process_lock.acquire_startup_lock: SIGKILL 后内核释放")
def test_lock_release_on_sigkill():
    """子进程持锁被 SIGKILL，父进程应该能拿到锁。"""
    import portalocker
    lock_file = TEST_DATA_DIR / ".opencode-control.lock"

    pid = os.fork()
    if pid == 0:
        # 子进程：拿锁后睡眠等被 kill
        fd = open(str(lock_file), "w")
        portalocker.lock(fd, portalocker.LOCK_EX)
        time.sleep(10)
        os._exit(0)

    time.sleep(0.5)  # 等子进程拿到锁
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    time.sleep(0.5)

    # 父进程应该能拿到锁
    from services.process_lock import acquire_startup_lock
    with acquire_startup_lock():
        pass  # 成功


# ============ port_manager 测试 ============

@test("port_manager.bind_port_with_fallback: bind 端口成功")
def test_bind_port():
    from services.port_manager import bind_port_with_fallback
    from config import get_port_candidates
    port, sock = bind_port_with_fallback()
    try:
        # 断言落在当前候选列表内（CONTROL_PORT env 可重定向起始端口，不再硬编码 9776 段）
        assert_true(port in get_port_candidates(),
                    f"端口 {port} 应在候选列表 {get_port_candidates()} 内")
    finally:
        sock.close()


@test("port_manager.write_port_file + read_port_file: 写读一致")
def test_port_file_io():
    from services.port_manager import write_port_file, read_port_file
    write_port_file(9912)
    info = read_port_file()
    assert_true(info is not None, "应该读到端口文件")
    assert_eq(info[0], 9912, "端口号应该一致")
    assert_eq(info[1], os.getpid(), "PID 应该一致")
    assert_true(info[2] > 0, "启动时间应该 > 0")


@test("port_manager.is_control_running: 端口文件不存在时返回 False")
def test_is_control_running_no_file():
    from services.port_manager import is_control_running, PORT_FILE
    if PORT_FILE.exists():
        PORT_FILE.unlink()
    assert_false(is_control_running(), "端口文件不存在时应该返回 False")


# ============ ref_counter 测试 ============

@test("ref_counter: 写入 + 读取 users")
def test_users_io():
    from services.ref_counter import read_users, write_users, UserEntry
    entries = [
        UserEntry(pid=11111, start_time=1000),
        UserEntry(pid=22222, start_time=2000),
    ]
    write_users(entries)
    got = read_users()
    assert_eq(len(got), 2, "应该读到 2 条")


@test("ref_counter.cleanup_dead_users: 死 PID 被清理")
def test_cleanup_dead_users():
    from services.ref_counter import (
        read_users, write_users, cleanup_dead_users, UserEntry
    )
    entries = [
        UserEntry(pid=os.getpid(), start_time=0),  # 自己（startTime=0 宽容存活）
        UserEntry(pid=99999, start_time=0),         # 死 PID
    ]
    write_users(entries)
    alive = cleanup_dead_users()
    assert_eq(len(alive), 1, "应该剩 1 条（自己）")
    assert_eq(alive[0].pid, os.getpid(), "应该是自己的 PID")


@test("ref_counter.is_users_empty: 全死时返回 True")
def test_users_empty():
    from services.ref_counter import write_users, is_users_empty, UserEntry
    write_users([UserEntry(pid=99999, start_time=0)])
    assert_true(is_users_empty(), "全死时应该 True")


# ============ config_store 测试 ============

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
        self.port: int | None = None

    def start(self, custom_users_interval: int = 600):
        """启动控制台（不触发自杀）。"""
        env = os.environ.copy()
        # 短化 users 清洗间隔仅用于自杀测试，正常测试设大避免误自杀
        cmd = [
            sys.executable,
            str(BACKEND_DIR / "server.py"),
        ]
        # 注入 USERS_CLEANUP_INTERVAL_SEC（通过修改 config 模块）
        # 简化：直接设环境变量
        self.proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        # 等端口文件出现
        from services.port_manager import PORT_FILE
        for _ in range(20):
            if PORT_FILE.exists():
                content = PORT_FILE.read_text().strip().split("\n")
                if len(content) >= 1 and content[0].isdigit():
                    self.port = int(content[0])
                    # 加一个假的 users 防止自杀
                    from services.ref_counter import write_users, UserEntry
                    write_users([UserEntry(pid=os.getpid(), start_time=0)])
                    return
            time.sleep(0.5)
        raise AssertionError("控制台启动超时（端口文件未出现）")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            self.proc = None
        from services.port_manager import PORT_FILE, delete_port_file
        delete_port_file()
        from services.ref_counter import USERS_FILE
        if USERS_FILE.exists():
            USERS_FILE.unlink()


@test("E2E: 控制台启动 + /health + /embed")
def test_e2e_control_startup():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        # /health
        r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=10)
        assert_true(r.status_code in (200, 503), f"/health 应返回 200/503，实际 {r.status_code}")

        # 等模型加载
        for _ in range(30):
            r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=3)
            if r.status_code == 200:
                break
            time.sleep(1)

        # /embed
        r = httpx.post(
            f"http://127.0.0.1:{cp.port}/embed",
            json={"inputs": "hello world"},
            timeout=30,
        )
        assert_eq(r.status_code, 200, f"/embed 应返回 200，实际 {r.status_code}")
        data = r.json()
        assert_true(len(data) == 1, f"应返回 1 个向量，实际 {len(data)}")
        assert_eq(len(data[0]), 1024, f"向量维度应 1024，实际 {len(data[0])}")
    finally:
        cp.stop()


@test("E2E: 控制台全局唯一（第二个进程 exit 2）")
def test_e2e_singleton():
    cp = ControlProcess()
    try:
        cp.start()
        # 启动第二个控制台
        env = os.environ.copy()
        proc2 = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        # 等第二个进程退出
        proc2.wait(timeout=15)
        assert_eq(proc2.returncode, 2, f"第二个进程应该 exit 2，实际 {proc2.returncode}")
    finally:
        cp.stop()


@test("E2E: GET /api/config 返回配置")
def test_e2e_get_config():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置")
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/config", timeout=5)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_true("DEEPSEEK_API_KEY" in data, "应有 DEEPSEEK_API_KEY")
    finally:
        cp.stop()


@test("E2E: GET /api/config/required-status")
def test_e2e_required_status():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/config/required-status", timeout=5)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_true("DEEPSEEK_API_KEY" in data, "应有 DEEPSEEK_API_KEY 状态")
    finally:
        cp.stop()


@test("E2E: GET /api/scan 全量扫描")
def test_e2e_scan():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        # 等模型加载（scanner 会查 model 状态）
        for _ in range(20):
            r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=3)
            if r.status_code == 200:
                break
            time.sleep(1)

        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/scan", timeout=30)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_true("agents" in data, "应有 agents")
        assert_true("global" in data, "应有 global")
    finally:
        cp.stop()


@test("E2E: GET /api/deps/mobile-analysis")
def test_e2e_deps():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/deps/mobile-analysis", timeout=10)
        assert_eq(r.status_code, 200)
        tools = r.json()
        assert_true(len(tools) > 0, "应有工具列表")
    finally:
        cp.stop()


@test("E2E: GET /api/docker/status")
def test_e2e_docker():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/docker/status", timeout=10)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_true("docker" in data, "应有 docker 字段")
    finally:
        cp.stop()


@test("E2E: GET /api/hardware 硬件信息")
def test_e2e_hardware():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/hardware", timeout=10)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_true("cpu" in data, "应有 cpu")
        assert_true("memory" in data, "应有 memory")
        assert_true("os" in data, "应有 os")
        assert_true("gpu" in data, "应有 gpu")
    finally:
        cp.stop()


@test("E2E: PUT /api/config 写入 + 验证文件")
def test_e2e_config_write():
    if not OPENCODE_ROOT.exists():
        raise AssertionError("OPENCODE_ROOT 未设置")
    ai_env_path = OPENCODE_ROOT / ".ai_env"
    original = ai_env_path.read_text()
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.put(
            f"http://127.0.0.1:{cp.port}/api/config",
            json={"configs": {"E2E_TEST_KEY": "e2e_value"}},
            timeout=5,
        )
        assert_eq(r.status_code, 200)
        # 验证文件实际改变
        content = ai_env_path.read_text()
        assert_true("E2E_TEST_KEY=e2e_value" in content, "文件应包含新 key")
    finally:
        cp.stop()
        # 清理 + 还原
        ai_env_path.write_text(original)


@test("E2E: /api/install 白名单外拒绝")
def test_e2e_install_whitelist():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.post(
            f"http://127.0.0.1:{cp.port}/api/install",
            json={"package": "malicious-package-not-in-whitelist"},
            timeout=5,
        )
        assert_eq(r.status_code, 400, "白名单外应返回 400")
    finally:
        cp.stop()


# ============ 边界条件补充测试 ============

@test("port_manager.is_control_running: 端口文件残留 + PID 死 → False")
def test_is_control_running_dead_pid():
    from services.port_manager import is_control_running, PORT_FILE
    from services.process_lock import atomic_write
    if PORT_FILE.exists(): PORT_FILE.unlink()
    atomic_write(PORT_FILE, "9912\n99999\n0\n")
    try:
        assert_false(is_control_running(), "PID 99999 已死应 False")
    finally:
        if PORT_FILE.exists(): PORT_FILE.unlink()


@test("port_manager.is_control_running: 端口文件格式错误 → False")
def test_is_control_running_bad_format():
    from services.port_manager import is_control_running, PORT_FILE
    from services.process_lock import atomic_write
    if PORT_FILE.exists(): PORT_FILE.unlink()
    atomic_write(PORT_FILE, "not_a_port\nabc\n")
    try:
        assert_false(is_control_running(), "格式错误应 False")
    finally:
        if PORT_FILE.exists(): PORT_FILE.unlink()


@test("process_lock.is_process_alive: PID=0 / -1 非法")
def test_pid_zero_negative():
    from services.process_lock import is_process_alive
    assert_false(is_process_alive(0), "PID=0 非法")
    assert_false(is_process_alive(-1), "PID=-1 非法")


@test("ref_counter: 多条记录解析（含错行 + 注释）")
def test_users_parse_robust():
    from services.ref_counter import _parse_users
    content = "\npid=11111 start_time=1000\n# 注释\npid=22222 start_time=2000\n\nbad_line\npid=bad\npid=33333 start_time=3000\n"
    entries = _parse_users(content)
    assert_eq(len(entries), 3, "应解析 3 条")
    assert_eq(entries[2].pid, 33333)


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


@test("E2E: 端口耗尽 exit code 3（模拟）")
def test_e2e_port_exhausted():
    import socket
    from config import get_port_candidates
    sockets = []
    try:
        for port in get_port_candidates():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                s.listen(1)
                sockets.append(s)
            except OSError:
                pass
        env = os.environ.copy()
        proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=15)
        assert proc.returncode in (3, 2), f"端口耗尽应 exit 3 或 2，实际 {proc.returncode}"
    finally:
        for s in sockets: s.close()


@test("E2E: /embed 空输入 → 400")
def test_e2e_embed_empty():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.post(f"http://127.0.0.1:{cp.port}/embed", json={}, timeout=10)
        assert_eq(r.status_code, 400, "空输入应 400")
    finally:
        cp.stop()


@test("E2E: /embed 批量 list 输入")
def test_e2e_embed_batch():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        for _ in range(30):
            r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=3)
            if r.status_code == 200: break
            time.sleep(1)
        r = httpx.post(f"http://127.0.0.1:{cp.port}/embed",
                       json={"inputs": ["hello", "world", "test"]}, timeout=30)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_eq(len(data), 3, "应返回 3 个向量")
        assert_eq(len(data[0]), 1024)
    finally:
        cp.stop()


@test("E2E: /embed 字符串单输入")
def test_e2e_embed_single():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        for _ in range(30):
            r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=3)
            if r.status_code == 200: break
            time.sleep(1)
        r = httpx.post(f"http://127.0.0.1:{cp.port}/embed",
                       json={"inputs": "single string"}, timeout=30)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_eq(len(data), 1)
    finally:
        cp.stop()


@test("E2E: /rerank 接口")
def test_e2e_rerank():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        for _ in range(60):
            r = httpx.get(f"http://127.0.0.1:{cp.port}/health", timeout=3)
            if r.status_code == 200: break
            time.sleep(1)
        r = httpx.post(f"http://127.0.0.1:{cp.port}/rerank",
                       json={"query": "hello", "texts": ["world", "test"]}, timeout=60)
        assert_eq(r.status_code, 200)
        data = r.json()
        assert_eq(len(data), 2)
    finally:
        cp.stop()


@test("E2E: /api/config/{key} 不存在 → 404")
def test_e2e_config_404():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/config/NOT_EXIST_12345", timeout=5)
        assert_eq(r.status_code, 404)
    finally:
        cp.stop()


@test("E2E: DELETE /api/config/{key}")
def test_e2e_config_delete():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        httpx.put(f"http://127.0.0.1:{cp.port}/api/config/E2E_DEL",
                  json={"value": "test"}, timeout=5)
        r = httpx.delete(f"http://127.0.0.1:{cp.port}/api/config/E2E_DEL", timeout=5)
        assert_eq(r.status_code, 200)
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/config/E2E_DEL", timeout=5)
        assert_eq(r.status_code, 404, "删后应 404")
    finally:
        cp.stop()


@test("E2E: /api/deps/{agent} 不存在 agent → 工具空 + summary 就绪")
def test_e2e_deps_unknown():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        r = httpx.get(f"http://127.0.0.1:{cp.port}/api/deps/non-existent", timeout=5)
        assert_eq(r.status_code, 200)
        d = r.json()
        # 新契约：响应是聚合对象（summary/python/tools/compiler/shared_infra）
        # 未知 agent 无归属工具 → tools 空；all 级 Python 包仍命中；
        # 共享底座非归属 → 不参与判定 → summary.ready 反映 all 级包状态
        assert_eq(len(d["tools"]), 0, "未知 agent 的外部工具应为空")
        assert "summary" in d and "console_url" in d["summary"], "summary 应含 console_url"
        assert isinstance(d["summary"]["required_missing"], list), "summary 应含 required_missing"
    finally:
        cp.stop()


@test("E2E: /api/scan 缓存命中（第二次更快）")
def test_e2e_scan_cache():
    cp = ControlProcess()
    try:
        cp.start()
        import httpx
        t1 = time.time()
        httpx.get(f"http://127.0.0.1:{cp.port}/api/scan?force_refresh=true", timeout=30)
        dur1 = time.time() - t1
        t2 = time.time()
        httpx.get(f"http://127.0.0.1:{cp.port}/api/scan", timeout=30)
        dur2 = time.time() - t2
        assert_true(dur2 < dur1, f"缓存应更快：first={dur1:.2f}s cached={dur2:.2f}s")
    finally:
        cp.stop()


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


if __name__ == "__main__":
    sys.exit(main())

