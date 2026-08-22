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
import random
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
# CONTROL_TCP_PORT 随机高位（隔离铁律）：沙箱控制台的浏览器 TCP 通道避开生产 9776。
# IPC（sock/users）由 DATA_DIR 沙箱隔离；此处只需避开 TCP bind 冲突。
os.environ["CONTROL_TCP_PORT"] = str(random.randint(41000, 49000))


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
    """清理所有残留状态文件 + 杀残留控制台（经 IPC /health 拿 PID）。"""
    import httpx
    sock = TEST_DATA_DIR / "opensecurity-control.sock"
    if sock.exists():
        try:
            with httpx.Client(
                transport=httpx.HTTPTransport(uds=str(sock)), timeout=2,
            ) as c:
                r = c.get("http://localhost/health")
                pid = r.json().get("pid")
                if isinstance(pid, int):
                    try: os.kill(pid, signal.SIGTERM)
                    except: pass
                    time.sleep(0.5)
                    try: os.kill(pid, signal.SIGKILL)
                    except: pass
        except: pass
    # 删状态文件
    for fname in ["opensecurity-control.sock", ".opencode-control.users"]:
        f = TEST_DATA_DIR / fname
        if f.exists():
            try: f.unlink()
            except: pass


def wait_control_pid(proc: subprocess.Popen, timeout: int = 30) -> int | None:
    """等子进程输出 CONTROL_PID 行（startControl 成功 + 身份 pid），失败返回 None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return None  # 进程已退出
        line = proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if line.startswith("CONTROL_PID:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
        if line == "CONTROL_FAILED":
            return None
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
# startControl 返回 boolean；实例身份（pid）经 getControlIdentity 取——复用断言用
BUN_START_KEEP = """
import { startControl, getControlIdentity } from './.opencode/plugins/lib/control-manager.ts';
process.env.USERS_CLEANUP_INTERVAL_SEC = process.env.USERS_CLEANUP_INTERVAL_SEC || '2';
const ok = await startControl();
if (ok) { const id = await getControlIdentity(); console.log('CONTROL_PID:', id?.pid ?? 0); }
else console.log('CONTROL_FAILED');
setInterval(() => {}, 1000);
"""

# 启动控制台 + 立即退出（触发 exit handler）
BUN_START_EXIT = """
import { startControl, getControlIdentity } from './.opencode/plugins/lib/control-manager.ts';
const ok = await startControl();
if (ok) { const id = await getControlIdentity(); console.log('CONTROL_PID:', id?.pid ?? 0); }
else console.log('CONTROL_FAILED');
await new Promise(r => setTimeout(r, 1500));  // 等 addSelfToUsers + registerExitHandler 完成
process.exit(0);
"""

# 用 startControl 重新检测/拉起控制台（控制台死了会重启；pid 经身份接口取）
BUN_GET_PORT = """
import { startControl, getControlIdentity } from './.opencode/plugins/lib/control-manager.ts';
const ok = await startControl();
if (ok) { const id = await getControlIdentity(); console.log('CONTROL_PID:', id?.pid ?? 0); }
else console.log('CONTROL_FAILED');
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
        pid1 = wait_control_pid(proc1, timeout=30)
        if pid1 is None:
            raise AssertionError("第一个 bun 启动控制台失败")
        print(f"    [setup] opencode1: 控制台 pid={pid1}")

        # 启动第二个 bun（应该复用，不 spawn 新控制台）
        proc2 = subprocess.Popen(
            ["bun", "-e", BUN_START_KEEP],
            cwd=str(WORKSPACE_ROOT),
            env=bun_env(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        pid2 = wait_control_pid(proc2, timeout=30)
        if pid2 is None:
            raise AssertionError("第二个 bun 启动控制台失败")
        print(f"    [setup] opencode2: 控制台 pid={pid2}")

        # 验证：两次身份 pid 应相同（复用同一个控制台）
        assert_eq(pid1, pid2, "两次控制台 pid 应相同（复用）")

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
        control_pid = wait_control_pid(proc, timeout=30)
        if control_pid is None:
            raise AssertionError("bun 启动控制台失败")
        print(f"    [setup] 控制台 pid={control_pid}")

        # 等 bun 退出（exit handler 触发）
        proc.wait(timeout=15)
        print(f"    [setup] bun 已退出（exit handler 触发）")

        # 给 exit handler 一点时间完成 SIGTERM
        time.sleep(2)

        # 验证：控制台应该被 kill（users 空 → exit handler kill）
        assert_false(is_pid_alive(control_pid), f"控制台 pid={control_pid} 应被 kill")

        # 验证：IPC socket 文件应该被删（控制台信号处理清理）
        sock_file = TEST_DATA_DIR / "opensecurity-control.sock"
        assert_false(sock_file.exists(), "IPC socket 文件应被删")
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

        # 等 IPC socket 出现 + /health 应答
        from config import ipc_unix_socket_path
        import httpx
        sock_path = ipc_unix_socket_path()
        started = False
        for _ in range(20):
            if sock_path.exists():
                try:
                    with httpx.Client(
                        transport=httpx.HTTPTransport(uds=str(sock_path)), timeout=2,
                    ) as probe:
                        probe.get("http://localhost/health")
                        started = True
                        break
                except OSError:
                    pass
            time.sleep(0.5)
        if not started:
            raise AssertionError("控制台启动失败（IPC 未就绪）")
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
        old_control_pid = wait_control_pid(proc1, timeout=30)
        if old_control_pid is None:
            raise AssertionError("启动失败")
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
        # 等 bun2 输出（startControl 重启后的新实例 pid）
        new_control_pid = wait_control_pid(proc2, timeout=30)
        if new_control_pid is None:
            raise AssertionError("bun2 未返回 CONTROL_PID")

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


# ============ 场景 5：IPC sock 死残留 → 新实例自愈 ============

@test("场景5: sock 死残留（SIGKILL 残留文件）→ 新实例清理重建（无双实例）")
def test_stale_sock_self_healing():
    cleanup_state()
    proc_a = None
    proc_b = None
    try:
        # 起 A（等 IPC 就绪即可，不等模型加载）
        proc_a = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env={**os.environ,
                 "DATA_DIR": str(TEST_DATA_DIR),
                 "OPENCODE_ROOT": str(OPENCODE_ROOT),
                 "OPENSECURITY_VENV_DIR": str(REAL_VENV_DIR)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        sock = TEST_DATA_DIR / "opensecurity-control.sock"
        deadline = time.time() + 15
        while time.time() < deadline:
            if sock.exists():
                break
            time.sleep(0.3)
        assert_true(sock.exists(), "A 的 IPC socket 15s 内未出现")
        print(f"    [setup] 控制台 A pid={proc_a.pid}（IPC 已就绪）")

        # SIGKILL A（模拟崩溃——sock 文件残留，无人监听）
        proc_a.kill()
        proc_a.wait(timeout=5)
        assert_true(sock.exists(), "SIGKILL 后 sock 应残留")
        print("    [setup] A 被 SIGKILL，sock 残留")

        # 起 B：应探测残留（connect 失败）→ unlink → bind 成功 → 正常运行
        proc_b = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "server.py")],
            env={**os.environ,
                 "DATA_DIR": str(TEST_DATA_DIR),
                 "OPENCODE_ROOT": str(OPENCODE_ROOT),
                 "OPENSECURITY_VENV_DIR": str(REAL_VENV_DIR)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # B 应存活（自愈成功，非复用退出）
        time.sleep(3)
        assert_true(proc_b.poll() is None, "B 应自愈残留并正常运行（而非异常退出）")
        print(f"    [verify] B pid={proc_b.pid} 自愈成功")

        # B 的 IPC 应可用（/health 应答）
        import httpx
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(sock)), timeout=3,
        ) as c:
            r = c.get("http://localhost/health")
            assert_true(r.status_code in (200, 503), f"B 的 IPC 应答 /health，实际 {r.status_code}")
    finally:
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
