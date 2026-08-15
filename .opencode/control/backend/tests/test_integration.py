"""集成测试：多 opencode / exit handler / SIGKILL / 崩溃恢复。

这 4 个场景都涉及多进程编排（spawn bun + spawn 控制台 + kill 等），
不适合在单元测试中跑，独立成文件。

运行：
  cd .opencode/control/backend
  OPENCODE_ROOT=<path> DATA_DIR=<path> python tests/test_integration.py

注意：场景 3 默认等 65 秒（USERS_CLEANUP_INTERVAL_SEC + buffer）。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

WORKSPACE_ROOT = BACKEND_DIR.parent.parent.parent  # OpenSecurity/
# 集成测试用沙箱 DATA_DIR（/tmp）——不碰真实 ~/bw-security-analysis 的
# 端口/users/lock 文件（曾因直接 cleanup 真实 DATA_DIR 把生产控制台搞死）。
# venv 仍用真实位置：constants.ts 的 VENV_DIR 支持 OPENSECURITY_VENV_DIR 覆盖，
# bun（control-manager → venv.ts）经此变量找到真实 venv Python。
TEST_DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/control_integration_test"))
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
REAL_VENV_DIR = Path.home() / "bw-security-analysis" / ".venv"
OPENCODE_ROOT = Path(os.environ.get("OPENCODE_ROOT", WORKSPACE_ROOT / ".opencode"))

os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["OPENCODE_ROOT"] = str(OPENCODE_ROOT)
os.environ["OPENSECURITY_VENV_DIR"] = str(REAL_VENV_DIR)


# ─── 测试框架（与 test_control.py 一致）─────────────────
_results: list[tuple[str, bool, str]] = []


def test(name: str):
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


# ─── 工具：清理 + 进程管理 ────────────────────────────────


def cleanup_state():
    """清理所有残留状态文件 + 杀残留控制台。"""
    # 杀残留控制台
    port_file = TEST_DATA_DIR / ".opencode-control.port"
    if port_file.exists():
        try:
            lines = port_file.read_text().strip().split("\n")
            if len(lines) >= 2:
                pid = int(lines[1])
                try: os.kill(pid, signal.SIGTERM)
                except: pass
                time.sleep(0.5)
                try: os.kill(pid, signal.SIGKILL)
                except: pass
        except: pass
    # 删状态文件
    for fname in [".opencode-control.port", ".opencode-control.users", ".opencode-control.lock"]:
        f = TEST_DATA_DIR / fname
        if f.exists():
            try: f.unlink()
            except: pass


def wait_control_started(proc: subprocess.Popen, timeout: int = 30) -> dict | None:
    """等子进程输出 CONTROL_STARTED 行，返回 {port, pid}。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return None  # 进程已退出
        line = proc.stdout.readline()
        if line and "CONTROL_STARTED" in line:
            # 解析 JSON
            json_part = line.split("CONTROL_STARTED:", 1)[1].strip()
            return json.loads(json_part)
    return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def bun_env() -> dict:
    """bun 子进程环境变量。"""
    env = os.environ.copy()
    env["DATA_DIR"] = str(TEST_DATA_DIR)
    env["OPENCODE_ROOT"] = str(OPENCODE_ROOT)
    return env


# ─── bun 脚本片段（最小化）────────────────────────────────

# 启动控制台 + 保持运行（模拟 opencode 主进程）
# 场景 3 需要短清洗间隔，通过 process.env 传给控制台 spawn
BUN_START_KEEP = """
import { startControl } from './.opencode/plugins/lib/control-manager.ts';
process.env.USERS_CLEANUP_INTERVAL_SEC = process.env.USERS_CLEANUP_INTERVAL_SEC || '2';
const r = await startControl();
if (r) console.log('CONTROL_STARTED:', JSON.stringify(r));
else console.log('CONTROL_FAILED');
setInterval(() => {}, 1000);
"""

# 启动控制台 + 立即退出（触发 exit handler）
BUN_START_EXIT = """
import { startControl } from './.opencode/plugins/lib/control-manager.ts';
const r = await startControl();
if (r) console.log('CONTROL_STARTED:', JSON.stringify(r));
else console.log('CONTROL_FAILED');
await new Promise(r => setTimeout(r, 1500));  // 等 addSelfToUsers + registerExitHandler 完成
process.exit(0);
"""

# 用 getControlPort 拿端口（如果控制台死了会重启）
BUN_GET_PORT = """
import { getControlPort } from './.opencode/plugins/lib/control-manager.ts';
import { readControlPortFile } from './.opencode/plugins/lib/control-manager.ts';
const port = await getControlPort();
const info = readControlPortFile();
console.log('CONTROL_PORT:', port);
console.log('CONTROL_INFO:', JSON.stringify(info));
process.exit(0);
"""


# ============ 场景 1：多 opencode 共享控制台 ============

@test("场景1: 多 opencode 共享控制台（第二个复用）")
def test_multi_opencode_sharing():
    cleanup_state()
    try:
        # 启动第一个 bun（模拟 opencode 1）
        proc1 = subprocess.Popen(
            ["bun", "-e", BUN_START_KEEP],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        info1 = wait_control_started(proc1, timeout=30)
        if info1 is None:
            raise AssertionError("第一个 bun 启动控制台失败")
        print(f"    [setup] opencode1: port={info1['port']} pid={info1['pid']}")

        # 启动第二个 bun（应该复用，不 spawn 新控制台）
        proc2 = subprocess.Popen(
            ["bun", "-e", BUN_START_KEEP],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        info2 = wait_control_started(proc2, timeout=30)
        if info2 is None:
            raise AssertionError("第二个 bun 启动控制台失败")
        print(f"    [setup] opencode2: port={info2['port']} pid={info2['pid']}")

        # 验证：两次的 port 和 pid 应该相同（复用同一个控制台）
        assert_eq(info1["port"], info2["port"], "两次 port 应相同（复用）")
        assert_eq(info1["pid"], info2["pid"], "两次控制台 pid 应相同（复用）")

        # 验证 users 文件有 2 条记录（两个 bun PID）
        users_file = TEST_DATA_DIR / ".opencode-control.users"
        users_content = users_file.read_text()
        pid_count = users_content.count("pid=")
        assert_true(pid_count >= 2, f"users 应有 ≥2 条记录，实际 {pid_count}")
    finally:
        # 清理：强制 kill 两个 bun（SIGTERM 可能不响应）
        for name in ['proc1', 'proc2']:
            p = locals().get(name)
            if p is not None:
                try: p.kill()
                except: pass
                try: p.wait(timeout=3)
                except: pass
        cleanup_state()


# ============ 场景 2：exit handler 减引用 + kill 控制台 ============

@test("场景2: opencode 退出 → exit handler 减引用 → 控制台自杀")
def test_exit_handler():
    cleanup_state()
    proc = None
    try:
        # 启动 bun（startControl + 立即 process.exit）
        proc = subprocess.Popen(
            ["bun", "-e", BUN_START_EXIT],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        info = wait_control_started(proc, timeout=30)
        if info is None:
            raise AssertionError("bun 启动控制台失败")
        control_pid = info["pid"]
        print(f"    [setup] 控制台 pid={control_pid}")

        # 等 bun 退出（exit handler 触发）
        proc.wait(timeout=15)
        print(f"    [setup] bun 已退出（exit handler 触发）")

        # 给 exit handler 一点时间完成 SIGTERM
        time.sleep(2)

        # 验证：控制台应该被 kill（users 空 → exit handler kill）
        assert_false(is_pid_alive(control_pid), f"控制台 pid={control_pid} 应被 kill")

        # 验证：端口文件应该被删
        port_file = TEST_DATA_DIR / ".opencode-control.port"
        assert_false(port_file.exists(), "端口文件应被删")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except: proc.kill()
        cleanup_state()


# ============ 场景 3：SIGKILL 后周期清洗自杀 ============

@test("场景3: opencode SIGKILL 后控制台周期清洗自杀")
def test_sigkill_cleanup():
    """直接用 Python 启动控制台（不通过 bun），写假 users，等周期清洗。

    bun spawn 控制台时 stdio=ignore + env 传递可能有边缘问题，
    这里直接用 Python 启动，跟手动验证一致。
    """
    from services.ref_counter import write_users, UserEntry
    from services.process_lock import get_process_start_time

    cleanup_state()
    proc = None
    try:
        # 直接用 Python 启动控制台（跟手动测试一致）
        env = os.environ.copy()
        env["USERS_CLEANUP_INTERVAL_SEC"] = "2"  # 短间隔加速
        proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )

        # 等端口文件出现
        from services.port_manager import PORT_FILE
        for _ in range(20):
            if PORT_FILE.exists(): break
            time.sleep(0.5)
        if not PORT_FILE.exists():
            raise AssertionError("控制台启动失败")
        control_pid = proc.pid
        print(f"    [setup] 控制台 pid={control_pid}")

        # 写假 users（一个不存在的 PID）
        fake_pid = 99999
        write_users([UserEntry(pid=fake_pid, start_time=1000)])
        print(f"    [setup] 写假 users: pid={fake_pid}")

        # 等周期清洗（USERS_CLEANUP_INTERVAL_SEC=2，最多 10s）
        print(f"    [wait] 等周期清洗（最多 10s）...")
        control_dead = False
        for i in range(10):
            time.sleep(1)
            if proc.poll() is not None:
                control_dead = True
                print(f"    [wait] 第 {i+1}s 控制台退出（自杀）")
                break
        assert_true(control_dead, "控制台应在 10s 内自杀（users 清洗后空）")

        # 读日志确认自杀消息
        if proc.stdout:
            output = proc.stdout.read()
            assert_true("自杀" in output or "users 空" in output,
                        f"日志应含'自杀'或'users 空'，实际: {output[-200:]}")
    finally:
        if proc and proc.poll() is None:
            try: proc.kill()
            except: pass
        cleanup_state()


# ============ 场景 4：控制台崩溃 → Plugin 重启 ============

@test("场景4: 控制台崩溃 → Plugin 检测 + 重启")
def test_control_crash_recovery():
    cleanup_state()
    proc1 = None
    proc2 = None
    try:
        # 启动 bun（startControl + 保持）
        proc1 = subprocess.Popen(
            ["bun", "-e", BUN_START_KEEP],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        info1 = wait_control_started(proc1, timeout=30)
        if info1 is None:
            raise AssertionError("启动失败")
        old_control_pid = info1["pid"]
        print(f"    [setup] 控制台 pid={old_control_pid}")

        # kill 控制台（模拟崩溃）
        os.kill(old_control_pid, signal.SIGKILL)
        # 不能用 os.waitpid（非子进程），轮询等控制台死
        for _ in range(20):
            if not is_pid_alive(old_control_pid): break
            time.sleep(0.2)
        print(f"    [setup] 控制台被 SIGKILL（崩溃）")
        time.sleep(1)

        # 端口文件可能还在（残留），但 PID 死了
        # bun1 的 getControlPort 应该检测到端口文件失效，重新 spawn
        # 但 bun1 的 control-manager 已经初始化过，缓存了 controlProc
        # 实际场景：用户重新发消息 → chat.message → getControlPort
        # 这里直接用新 bun 进程调 getControlPort 模拟

        proc2 = subprocess.Popen(
            ["bun", "-e", BUN_GET_PORT],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        # 等 bun2 输出
        deadline = time.time() + 30
        port_line = None
        info_line = None
        while time.time() < deadline:
            if proc2.poll() is not None: break
            line = proc2.stdout.readline()
            if not line: continue
            line = line.strip()
            if line.startswith("CONTROL_PORT:"):
                port_line = line.split(":", 1)[1].strip()
            elif line.startswith("CONTROL_INFO:"):
                info_line = line.split(":", 1)[1].strip()
                break

        if info_line is None:
            raise AssertionError("bun2 未返回 CONTROL_INFO")

        new_info = json.loads(info_line)
        new_control_pid = new_info["pid"]
        print(f"    [verify] 新控制台 pid={new_control_pid}")

        # 验证：新控制台 PID 不等于旧的（崩溃后重启）
        assert_true(new_control_pid != old_control_pid,
                    f"新控制台 pid={new_control_pid} 应不等于崩溃的 pid={old_control_pid}")

        # 验证：新控制台健康
        assert_true(is_pid_alive(new_control_pid), "新控制台应健康运行")
    finally:
        for p in [proc1, proc2]:
            if p and p.poll() is None:
                try: p.kill()
                except: pass
                try: p.wait(timeout=3)
                except: pass
        cleanup_state()


# ============ 场景 5：端口文件误删 → 孤儿接管 ============

@test("场景5: 端口文件误删 → 新实例探测孤儿 → 重建文件并退出（无双实例）")
def test_port_file_deleted_orphan_takeover():
    cleanup_state()
    proc_a = None
    proc_b = None
    try:
        # 起 A（等端口文件出现即可，不等模型加载）
        proc_a = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env={**os.environ,
                 "DATA_DIR": str(TEST_DATA_DIR),
                 "OPENCODE_ROOT": str(OPENCODE_ROOT),
                 "OPENSECURITY_VENV_DIR": str(REAL_VENV_DIR)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port_file = TEST_DATA_DIR / ".opencode-control.port"
        deadline = time.time() + 15
        while time.time() < deadline:
            if port_file.exists():
                break
            time.sleep(0.3)
        assert_true(port_file.exists(), "A 的端口文件 15s 内未出现")
        a_info = port_file.read_text().strip().split("\n")
        a_port, a_pid = int(a_info[0]), int(a_info[1])
        print(f"    [setup] 控制台 A pid={a_pid} port={a_port}（模型加载中即开始测）")

        # 误删端口文件
        port_file.unlink()
        print("    [setup] 端口文件已误删，A 仍存活")

        # 起 B：应探测到孤儿 A → 重建文件指向 A → 自己退出（码 2）
        proc_b = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env={**os.environ,
                 "DATA_DIR": str(TEST_DATA_DIR),
                 "OPENCODE_ROOT": str(OPENCODE_ROOT),
                 "OPENSECURITY_VENV_DIR": str(REAL_VENV_DIR)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        b_exit = proc_b.wait(timeout=30)
        assert_eq(b_exit, 2, "B 应以复用码 2 退出")
        print(f"    [verify] B 退出码 = {b_exit}（探测孤儿后复用退出）")

        # 端口文件应已重建且指向 A
        b_info = port_file.read_text().strip().split("\n")
        assert_eq(int(b_info[0]), a_port, "重建文件端口应指向 A")
        assert_eq(int(b_info[1]), a_pid, "重建文件 PID 应指向 A")

        # A 仍存活（无双实例、无模型二次加载）
        assert_true(is_pid_alive(a_pid), "A 应仍存活")
    finally:
        # SIGTERM 收尾（新信号处理会自删端口文件）
        for p in [proc_b, proc_a]:
            if p and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:
                    try: p.kill()
                    except Exception: pass
        cleanup_state()


# ============ 运行所有测试 ============

def main():
    print("=" * 60)
    print("opencode-control 集成测试")
    print(f"WORKSPACE_ROOT: {WORKSPACE_ROOT}")
    print(f"TEST_DATA_DIR: {TEST_DATA_DIR}")
    print(f"OPENCODE_ROOT: {OPENCODE_ROOT}")
    print("=" * 60)
    print()

    tests = [
        (name, fn) for name, fn in globals().items()
        if callable(fn) and getattr(fn, "_is_test", False)
    ]
    print(f"找到 {len(tests)} 个集成测试\n")

    for name, fn in tests:
        fn()

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


if __name__ == "__main__":
    sys.exit(main())
