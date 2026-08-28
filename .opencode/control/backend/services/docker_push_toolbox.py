"""工具箱镜像推送（Docker Hub: zylc369/opensecurity-toolbox-*）—— CLI + import 双模式。

CLI:  python push_toolbox.py [--ver v1.0]
      docker 输出实时透传终端（不捕获，与手敲命令一致的观感）。
import: from services import push_toolbox → push_toolbox.push_all(ver="v1.0")
      docker 输出写入 DATA_DIR/logs/control.log（控制台统一日志，stdio=ignore 下 print 不可见）。

tag 语义:
  :v1.0-arm64 / :v1.0-amd64  版本锚点——发新版后永不再动，用于复现/回退
  :arm64 / :amd64            滚动指针——发新版时重新 tag+push 移动它
  :v1.0 / :latest            双架构 manifest——任何机器按 CPU 自动选层

原理: 层内容寻址（相同内容 = 相同 ID），重复 push 只补 manifest JSON（几十 KB）。
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import time
import subprocess
import sys
from dataclasses import dataclass, field

# CLI 直跑自举（detect_tools.py 同模式）: 把 backend 目录加 sys.path 使 services 可见
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREFIX = "zylc369/opensecurity-toolbox"
logger = logging.getLogger(__name__)


def _normalize_ver(ver: str | None) -> tuple[str | None, str]:
    """版本号归一化: '1.0' → 'v1.0'; 未提供/格式非法 → (None, 错误描述)。"""
    if not ver:
        return None, ("必须指定版本号（如 1.0 / v1.1）—— CLI 加 --ver 1.0; import 调 push_all(ver='1.0')。"
                      "版本号用于打不可变的版本锚点 tag，不允许省略后误推滚动 tag")
    v = ver if ver.startswith("v") else f"v{ver}"
    if not re.match(r"^v\d+\.\d+$", v):
        return None, f"版本号格式非法: {ver}（应为 1.0 / v1.1 形式）"
    return v, ""


# ─── 强类型结果 ────────────────────────────────────────────


@dataclass
class PushStep:
    """单条 docker 命令的执行结果。"""
    name: str                     # 步骤描述（如 "push core:v1.0-arm64"）
    cmd: list[str]
    ok: bool
    detail: str = ""              # 失败原因 / 耗时摘要


@dataclass
class PushReport:
    """整体推送报告。"""
    ok: bool
    steps: list[PushStep] = field(default_factory=list)

    def summary(self) -> str:
        bad = [s for s in self.steps if not s.ok]
        if not bad:
            return f"推送全部成功（共 {len(self.steps)} 步）"
        # 区分: push/manifest 步失败 = 远端没推上（真失败）; verify 步失败 = 已推上但复核未过
        push_bad = [s for s in bad if not s.name.startswith("verify")]
        head = "推送失败" if push_bad else "推送已完成，但远端验证未通过"
        return f"{head}（失败 {len(bad)}/{len(self.steps)} 步）" + (
            "; " + "; ".join(f"{s.name}: {s.detail}" for s in bad))


# ─── 执行内核 ──────────────────────────────────────────────


def _run_logged(cmd: list[str], interactive: bool) -> tuple[bool, str]:
    """执行单条 docker 命令。

    interactive=True  → 子进程 stdio 直连终端（docker push 进度条实时透传）
    interactive=False → stdout/stderr 捕获后 logger.info 写 control.log
    """
    if interactive:
        # 边透传边捕获: 终端实时看输出，尾部文本留作 detail（429 等错误信息可被上层识别）
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        proc.wait()
        tail = "".join(lines)[-500:]
        return proc.returncode == 0, (f"exit={proc.returncode}" if proc.returncode == 0 else tail)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        out = (r.stdout + r.stderr).strip()
        if out:
            logger.info("[%s] %s", " ".join(cmd), out[:4000])
        return r.returncode == 0, (f"exit={r.returncode}" if r.returncode == 0 else out[-500:])
    except subprocess.TimeoutExpired:
        return False, "超时（2h）"


def _logged_login_ok(interactive: bool) -> tuple[bool, str]:
    """登录态检查（三级检测，静默执行不刷屏）。

    新版 Docker（29.x）的 system info 已无 Username 行，且 Docker Desktop 凭据存
    钥匙串（config.json 的 credsStore=desktop）——按可靠性排序:
      1. credential helper: docker-credential-<credsStore> list → index.docker.io 条目
      2. config.json auths 直接凭据（docker.io 条目）
      3. 旧版兼容: system info 的 Username 行
    全部检测不到不硬拦截（防误报挡路）——未登录时 docker push 自会报权威的 unauthorized。
    """
    r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not r.stdout.strip():
        return False, "docker daemon 不可用"
    import json
    try:
        with open(os.path.expanduser("~/.docker/config.json")) as fh:
            cfg = json.load(fh)
        store = cfg.get("credsStore") or ""
        if store:
            h = subprocess.run([f"docker-credential-{store}", "list"],
                               capture_output=True, text=True, timeout=15)
            if h.returncode == 0:
                user = json.loads(h.stdout or "{}").get("https://index.docker.io/v1/")
                if user:
                    return True, f"已登录 Docker Hub（{user}, credential helper）"
        if any("docker.io" in k for k in cfg.get("auths", {})):
            return True, "已登录 Docker Hub（config.json auths）"
    except (OSError, ValueError):
        pass
    r = subprocess.run(["docker", "system", "info"], capture_output=True, text=True, timeout=30)
    for line in (r.stdout + r.stderr).splitlines():
        if "Username:" in line:
            return True, line.strip()
    return True, "登录态未能自动确认——继续推送（若未登录，docker 会明确报 unauthorized）"


def _images_ready() -> str | None:
    """本地 4 个实体 tag 齐备检查; 返回缺失描述（None=齐）。"""
    missing = []
    for repo in (f"{PREFIX}-core", f"{PREFIX}-full"):
        for arch in ("arm64", "amd64"):
            ref = f"{repo}:{arch}"
            r = subprocess.run(["docker", "image", "inspect", ref], capture_output=True, timeout=30)
            if r.returncode != 0:
                missing.append(ref)
    return f"本地缺 {', '.join(missing)} —— 先构建（control/docker/ 下 Dockerfile）" if missing else None


# ─── 推送主流程（控制台 import 入口） ──────────────────────


def push_all(ver: str | None = None, interactive: bool | None = None) -> PushReport:
    """推送工具箱镜像全流程: 版本 tag 打标 → 8 实体 → 4 manifest → 远端验证。

    ver: 必填版本号（'1.0' 自动归一化 'v1.0'）; 省略返回错误报告。
    interactive: None=自动判断（终端 CLI → True 透传; 后端 import → False 写日志文件）
    """
    interactive = sys.stdout.isatty() if interactive is None else interactive
    report = PushReport(ok=True)
    ver, err = _normalize_ver(ver)
    if err:
        report.steps.append(PushStep("版本号校验", [], False, err))
        report.ok = False
        return report

    # ── 前置检查 ──
    ok, detail = _logged_login_ok(interactive)
    report.steps.append(PushStep("检查登录态", ["docker", "system", "info"], ok, detail))
    if not ok:
        report.ok = False
        return report

    missing = _images_ready()
    report.steps.append(PushStep("检查本地镜像", ["docker", "image", "inspect"], missing is None, missing or "4 tag 齐"))
    if missing:
        report.ok = False
        return report

    # ── 版本 tag 打标（幂等） ──
    for repo in (f"{PREFIX}-core", f"{PREFIX}-full"):
        for arch in ("arm64", "amd64"):
            cmd = ["docker", "tag", f"{repo}:{arch}", f"{repo}:{ver}-{arch}"]
            ok, detail = _run_logged(cmd, interactive)
            report.steps.append(PushStep(f"tag {repo}:{ver}-{arch}", cmd, ok, detail))
            if not ok:
                report.ok = False
                return report

    # ── 1. 八个实体 tag（层已存在时秒跳过） ──
    for repo in (f"{PREFIX}-core", f"{PREFIX}-full"):
        for ref in (f"{ver}-arm64", f"{ver}-amd64", "arm64", "amd64"):
            cmd = ["docker", "push", f"{repo}:{ref}"]
            ok, detail = _run_logged(cmd, interactive)
            report.steps.append(PushStep(f"push {repo}:{ref}", cmd, ok, detail))
            if not ok:
                report.ok = False
                return report

    # ── 2+3. 双架构 manifest（版本锁定 + 滚动） ──
    # buildx imagetools 在 registry 层面组 manifest list（一条命令=create+push）。
    # 不用旧式 docker manifest create/push: Docker Desktop 29.x containerd snapshotter
    # 模式下本地镜像是 index 形态，manifest create 拒绝 index 成员（"is a manifest list"）。
    for repo in (f"{PREFIX}-core", f"{PREFIX}-full"):
        for mt in (ver, "latest"):
            cmd = ["docker", "buildx", "imagetools", "create",
                   "-t", f"{repo}:{mt}",
                   f"{repo}:{ver}-arm64", f"{repo}:{ver}-amd64"]
            ok, detail = _run_logged(cmd, interactive)
            report.steps.append(PushStep(f"manifest {repo}:{mt}", cmd, ok, detail))
            if not ok:
                report.ok = False
                return report

    # ── 远端验证（manifest 架构构成） ──
    # 用 buildx imagetools inspect --raw: buildx 命令族走 docker 登录凭证——
    # 旧式 docker manifest inspect 匿名访问 registry API，Docker Hub 限 100 次/6h/IP（多轮跑脚本会打爆报 toomanyrequests）。
    # 重试 ×3: 防限流残余与 Hub 后端传播延迟（刚推的 manifest 秒查可能 404）。
    for repo in (f"{PREFIX}-core", f"{PREFIX}-full"):
        for mt in (ver, "latest"):
            stdout = ""
            for attempt in range(3):
                r = subprocess.run(["docker", "buildx", "imagetools", "inspect", f"{repo}:{mt}", "--raw"],
                                   capture_output=True, text=True, timeout=60)
                stdout = r.stdout
                if '"architecture"' in stdout:
                    break
                (print if interactive else logger.warning)(
                    f"[验证重试 {attempt + 1}/3] {repo}:{mt} 暂不可读（限流/传播延迟），5s 后重试")
                time.sleep(5)
            all_archs = [ln.split('"')[3] for ln in stdout.splitlines()
                         if '"architecture"' in ln and '"' in ln]
            platforms = sorted(a for a in all_archs if a != "unknown")
            attestation = all_archs.count("unknown")
            # 必须含双架构; unknown 条目 = buildx 自动附加的构建溯源证明（attestation），
            # 不属于任何 CPU 架构，拉取时永远不会被选中，零功能影响
            ok = {"arm64", "amd64"} <= set(platforms)
            att_note = f"; 另含 {attestation} 份构建溯源证明（不影响拉取）" if attestation else ""
            detail = f"架构: {'+'.join(platforms) if platforms else 'inspect 失败'}{att_note}"
            (logger.info if not interactive else print)(f"[验证] {repo}:{mt} → {detail}")
            report.steps.append(PushStep(f"verify {repo}:{mt}", ["docker", "manifest", "inspect"], ok, detail))
            if not ok:
                report.ok = False

    return report


# ─── CLI ──────────────────────────────────────────────────


def _main() -> int:
    parser = argparse.ArgumentParser(description="工具箱镜像推送（双架构 manifest）")
    parser.add_argument("--ver", required=True, help="版本号，必填（如 --ver 1.0 或 --ver v1.1，等价）")
    args = parser.parse_args()
    ver, err = _normalize_ver(args.ver)
    if err:
        print(f"[✗] {err}", file=sys.stderr)
        return 2

    print(f"[*] 推送 {PREFIX}-core / {PREFIX}-full  ver={ver}（终端实时透传 docker 输出）")
    report = push_all(ver=ver, interactive=True)
    print(f"[{'✓' if report.ok else '✗'}] {report.summary()}")
    if not report.ok and any("429" in s.detail or "Too Many Requests" in s.detail for s in report.steps):
        print("    ⚠ Docker Hub 限流中（429 Too Many Requests，匿名 100 次/6h/IP）——")
        print("      ① 远端状态可能已完整: 浏览器打开 https://hub.docker.com/v2/repositories/zylc369/opensecurity-toolbox-core/tags 验证（Web API 独立限流）")
        print("      ② 每次重跑都在消耗额度、推迟恢复——停跑，约 6 小时后窗口自然重置")
    if report.ok:
        print(f"    验证拉取: docker pull {PREFIX}-core（任何机器自动按 CPU 选架构）")
        print("    记得去 hub.docker.com 仓库 Settings 改 Public（如需免登录拉取）")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
