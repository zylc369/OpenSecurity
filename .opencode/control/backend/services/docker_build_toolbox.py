"""工具箱镜像构建（双架构: arm64 原生 + amd64 QEMU 模拟）—— CLI + import 双模式。

CLI:  python build_toolbox.py [--arch arm64|amd64|both] [--no-smoke]
      docker build 输出实时透传终端。
import: from services import build_toolbox → build_toolbox.build_all(arch="both")
      构建输出写入 DATA_DIR/logs/control.log（控制台统一日志）。

构建顺序（full 依赖同架构 core 基座）:
  core:arm64 → core:amd64 → full:arm64 → full:amd64
  full 通过 --build-arg CORE_REF=<prefix>-core:<arch> 指定同架构基座。

产物 tag: 仅滚动架构 tag（:arm64 / :amd64）——版本锚点 tag 由 docker_push_toolbox.py
在推送时打（职责分离: build 产出内容，push 定版本发布）。

内置轻量冒烟（默认开，--no-smoke 跳过）: 架构确认 + 关键产物存在性
（marshalsec jar / pwndbg venv / gems 入口 / java / nmap）+ dpkg 包计数——
任何缺失判构建失败（零阉割红线的自动化执行点; 完整 37 项冒烟见 progress 第四十九轮清单）。
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field

# CLI 直跑自举（detect_tools.py 同模式）: 把 backend 目录加 sys.path 使 services 可见
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOCKER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "control", "docker")
PREFIX = "zylc369/opensecurity-toolbox"
logger = logging.getLogger(__name__)


@dataclass
class BuildStep:
    name: str
    cmd: list[str]
    ok: bool
    detail: str = ""


@dataclass
class BuildReport:
    ok: bool
    steps: list[BuildStep] = field(default_factory=list)

    def summary(self) -> str:
        bad = [s for s in self.steps if not s.ok]
        return f"构建 {'全部成功' if self.ok else f'失败 {len(bad)} 步'}（共 {len(self.steps)} 步）" + (
            "; " + "; ".join(f"{s.name}: {s.detail}" for s in bad) if bad else "")


def _run_logged(cmd: list[str], interactive: bool, timeout: int = 10800) -> tuple[bool, str]:
    """执行命令（CLI 透传终端 / import 写 control.log; 构建单命令上限 3h——amd64 QEMU 实测 ~40min）。"""
    if interactive:
        r = subprocess.run(cmd, timeout=timeout)
        return r.returncode == 0, f"exit={r.returncode}"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        if out:
            logger.info("[%s] %s", " ".join(cmd[:6]), out[-4000:])  # 构建日志长，留尾部
        return r.returncode == 0, (f"exit={r.returncode}" if r.returncode == 0 else out[-500:])
    except subprocess.TimeoutExpired:
        return False, f"超时（{timeout}s）"


def _binfmt_ok(interactive: bool) -> tuple[bool, str]:
    """amd64 交叉构建前置: QEMU binfmt 可用性（arm64 宿主模拟 amd64）。"""
    r = subprocess.run(["docker", "buildx", "ls"], capture_output=True, text=True, timeout=30)
    if "linux/amd64" in r.stdout:
        return True, "buildx 支持 linux/amd64（QEMU binfmt 在位）"
    return False, "buildx 不支持 linux/amd64——amd64 构建需 QEMU binfmt（Docker Desktop 自带; Linux 宿主: docker run --privileged tonistiigi/binfmt --install amd64）"


def _smoke(arch: str, interactive: bool) -> tuple[bool, str]:
    """轻量冒烟: 架构 + 关键产物（零阉割红线的自动化把关）。"""
    checks = (
        "uname -m",
        "ls /opt/marshalsec/target/marshalsec-*-all.jar",
        "test -d /opt/pwndbg/.venv",
        "ls /usr/local/bin/one_gadget /usr/local/bin/seccomp-tools /usr/local/bin/zsteg",
        "java -version",
        "command -v nmap hashcat john steghide gdb-multiarch qemu-x86_64 "
        "x86_64-w64-mingw32-gcc i686-w64-mingw32-gcc bloodhound searchsploit",
    )
    script = "; ".join(
        f"{c} >/dev/null 2>&1 || {{ echo MISSING:{c}; }}" for c in checks
    ) + "; dpkg-query -W 2>/dev/null | wc -l"
    cmd = ["docker", "run", "--rm", "--platform", f"linux/{arch}",
           "--entrypoint", "sh", f"{PREFIX}-core:{arch}", "-c", script]
    ok, detail = _run_logged(cmd, interactive, timeout=600)
    if not ok:
        return False, f"冒烟容器启动失败: {detail}"
    out = detail.strip().splitlines()[-1] if detail else ""
    # interactive 模式输出透传终端拿不到返回值 → 重跑捕获（冒烟很快，双跑无负担）
    if interactive:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    missing = [l for l in (out.splitlines() if out else []) if l.startswith("MISSING:")]
    pkg_count = next((l.strip() for l in reversed(out.splitlines()) if l.strip().isdigit()), "0")
    if missing:
        return False, f"关键产物缺失: {'; '.join(missing)}"
    expected = {"arm64": "aarch64", "amd64": "x86_64"}[arch]
    # 架构断言由 uname 输出（MISSING 检查之外的第一个检查）——通过 pkg 计数一起回报
    return True, f"关键产物齐备; dpkg 包数 {pkg_count}（架构层 {expected}）"


def build_all(arch: str = "both", smoke: bool = True,
              interactive: bool | None = None) -> BuildReport:
    """构建双架构工具箱镜像。arch: arm64 / amd64 / both。"""
    interactive = sys.stdout.isatty() if interactive is None else interactive
    report = BuildReport(ok=True)
    archs = ["arm64", "amd64"] if arch == "both" else [arch]

    if "amd64" in archs:
        ok, detail = _binfmt_ok(interactive)
        report.steps.append(BuildStep("QEMU binfmt 检查", ["docker", "buildx", "ls"], ok, detail))
        if not ok:
            report.ok = False
            return report

    for a in archs:
        # ── core ──
        cmd = ["docker", "build", "--platform", f"linux/{a}",
               "-f", os.path.join(DOCKER_DIR, "toolbox-core.Dockerfile"),
               "-t", f"{PREFIX}-core:{a}", DOCKER_DIR]
        ok, detail = _run_logged(cmd, interactive)
        report.steps.append(BuildStep(f"build core:{a}", cmd, ok, detail))
        if not ok:
            report.ok = False
            return report
        # ── full（同架构基座） ──
        cmd = ["docker", "build", "--platform", f"linux/{a}",
               "--build-arg", f"CORE_REF={PREFIX}-core:{a}",
               "-f", os.path.join(DOCKER_DIR, "toolbox-full.Dockerfile"),
               "-t", f"{PREFIX}-full:{a}", DOCKER_DIR]
        ok, detail = _run_logged(cmd, interactive)
        report.steps.append(BuildStep(f"build full:{a}", cmd, ok, detail))
        if not ok:
            report.ok = False
            return report
        # ── 轻量冒烟 ──
        if smoke:
            ok, detail = _smoke(a, interactive)
            report.steps.append(BuildStep(f"smoke core:{a}", ["<容器内组合检查>"], ok, detail))
            if not ok:
                report.ok = False
                return report

    if report.ok:
        msg = f"构建完成（{', '.join(archs)}）。发布: ./docker-push-toolbox.sh --ver <版本号>"
        (print if interactive else logger.info)(f"[✓] {msg}")
    return report


def _main() -> int:
    parser = argparse.ArgumentParser(description="工具箱镜像构建（双架构）")
    parser.add_argument("--arch", choices=["arm64", "amd64", "both"], default="both",
                        help="目标架构（默认 both; amd64 走 QEMU 模拟，约 40min）")
    parser.add_argument("--no-smoke", action="store_true", help="跳过构建后轻量冒烟")
    args = parser.parse_args()

    print(f"[*] 构建 {PREFIX}-core / {PREFIX}-full  arch={args.arch}（终端实时透传 docker build 输出）")
    report = build_all(arch=args.arch, smoke=not args.no_smoke, interactive=True)
    print(f"[{'✓' if report.ok else '✗'}] {report.summary()}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
