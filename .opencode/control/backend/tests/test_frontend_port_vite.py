"""frontend_port vite 收割/级联重启测试（mock lsof/kill/端口探测——不起真进程）。"""
from __future__ import annotations

import signal
import subprocess
from dataclasses import dataclass, field
from typing import cast

import pytest

import services.frontend_port as fp
from services.frontend_port import FrontendPortRegistry


@dataclass
class _KillLog:
    """os.kill 调用记录（pid, signal）。"""
    calls: "list[tuple[int, int]]" = field(default_factory=list)


class _FakeCompleted:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.returncode = 0


def _make_registry() -> FrontendPortRegistry:
    """绕过单例构造独立实例（测试隔离）。"""
    reg = FrontendPortRegistry.__new__(FrontendPortRegistry)
    reg._init_once()  # type: ignore[attr-defined] —— 测试构造路径
    return reg


@dataclass
class _FakeProc:
    """本代 vite 进程替身（poll None = 活着）。"""
    pid: int = 42

    def poll(self) -> None:
        return None


def test_vite_listener_pids_parses_and_filters(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """lsof 输出解析: 多 PID 提取、非数字行忽略; lsof 缺失返回空不抛。"""

    def _fake_run(*a: object, **k: object) -> _FakeCompleted:
        return _FakeCompleted("111\n222\nnot-a-pid\n333\n")

    monkeypatch.setattr(fp.subprocess, "run", _fake_run)
    assert FrontendPortRegistry._vite_listener_pids() == [111, 222, 333]

    def _boom(*a: object, **k: object) -> None:
        raise OSError("no lsof")

    monkeypatch.setattr(fp.subprocess, "run", _boom)
    assert FrontendPortRegistry._vite_listener_pids() == []


def test_reap_skips_own_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """本代 PID 跳过——只杀非本代。"""
    reg = _make_registry()
    reg._vite_proc = cast("subprocess.Popen[bytes]", _FakeProc(pid=42))  # type: ignore[arg-type]
    klog = _KillLog()

    def _fake_kill(pid: int, sig: int) -> None:
        klog.calls.append((pid, sig))

    def _fake_run(*a: object, **k: object) -> _FakeCompleted:
        return _FakeCompleted("42\n100\n")  # 42=本代, 100=孤儿

    def _ports_dead(port: int) -> bool:
        return False

    monkeypatch.setattr(fp.os, "kill", _fake_kill)
    monkeypatch.setattr(fp.subprocess, "run", _fake_run)
    monkeypatch.setattr(FrontendPortRegistry, "_port_alive",
                        staticmethod(_ports_dead))
    reg._reap_stale_vite()
    assert klog.calls == [(100, signal.SIGTERM)]


def test_reap_escalates_to_sigkill_on_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """端口迟迟不释放 → 超时升级 SIGKILL。"""
    reg = _make_registry()
    klog = _KillLog()

    def _fake_kill(pid: int, sig: int) -> None:
        klog.calls.append((pid, sig))

    def _fake_run(*a: object, **k: object) -> _FakeCompleted:
        return _FakeCompleted("100\n")

    def _ports_alive(port: int) -> bool:
        return True  # 模拟挂死进程——触发超时路径

    import time as _time

    def _no_sleep(sec: float) -> None:
        return None

    monkeypatch.setattr(fp.os, "kill", _fake_kill)
    monkeypatch.setattr(fp.subprocess, "run", _fake_run)
    monkeypatch.setattr(FrontendPortRegistry, "_port_alive",
                        staticmethod(_ports_alive))
    monkeypatch.setattr(FrontendPortRegistry, "VITE_REAP_TIMEOUT_SEC", 0.4)
    monkeypatch.setattr(_time, "sleep", _no_sleep)
    reg._reap_stale_vite()
    assert (100, signal.SIGTERM) in klog.calls
    assert (100, signal.SIGKILL) in klog.calls


def test_ensure_skips_reap_when_deps_missing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """依赖未装（vite_bin 不存在）→ 直接 False，不动现有实例（先检查后收割）。"""
    reg = _make_registry()
    reap_called = {"n": 0}

    def _fake_reap() -> None:
        reap_called["n"] += 1

    class _Cfg:
        opencode_root = str(tmp_path)  # frontend/node_modules/.bin/vite 不存在

    def _fake_get_instance(cls: type[fp.ConfigManager]) -> _Cfg:
        return _Cfg()

    monkeypatch.setattr(reg, "_reap_stale_vite", _fake_reap)
    monkeypatch.setattr(fp.ConfigManager, "get_instance",
                        classmethod(_fake_get_instance))
    assert reg.ensure_vite_dev() is False
    assert reap_called["n"] == 0  # 未收割——先检查后收割的顺序保证


def test_ensure_reuses_own_alive(
        monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """本代健在且 5173 活 → True 且不收割不重拉（配置与依赖自包含——不依赖
    真实 ConfigManager 单例状态，防全量跑时被其他测试污染）。"""
    reg = _make_registry()
    reg._vite_proc = cast("subprocess.Popen[bytes]", _FakeProc(pid=7))  # type: ignore[arg-type]
    # 自包含环境: 假 opencode_root + 假 vite_bin（is_file 通过）
    from pathlib import Path
    fb = Path(str(tmp_path)) / "control" / "frontend" / "node_modules" / ".bin" / "vite"
    fb.parent.mkdir(parents=True)
    fb.write_text("")

    class _Cfg:
        opencode_root = str(tmp_path)

    def _fake_get_instance(cls: type[fp.ConfigManager]) -> _Cfg:
        return _Cfg()

    reap_called = {"n": 0}
    popen_called = {"n": 0}

    def _fake_reap() -> None:
        reap_called["n"] += 1

    def _fake_popen(*a: object, **k: object) -> None:
        popen_called["n"] += 1

    def _vite_alive() -> bool:
        return True

    monkeypatch.setattr(fp.ConfigManager, "get_instance",
                        classmethod(_fake_get_instance))
    monkeypatch.setattr(reg, "_reap_stale_vite", _fake_reap)
    monkeypatch.setattr(fp.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(reg, "vite_running", _vite_alive)
    assert reg.ensure_vite_dev() is True
    assert reap_called["n"] == 0 and popen_called["n"] == 0
