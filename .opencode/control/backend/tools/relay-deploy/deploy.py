"""relayd VPS 部署器（薄壳 deploy-relayd.sh 仅定位，部署逻辑全在此）。

用法（项目根目录）:
  ./deploy-relayd.sh <VPS_IP> [SSH_USER=root]
  python3 tools/relay-deploy/deploy.py <VPS_IP> [SSH_USER=root] [--dry-run]

6 步:
  1. 同步代码（services/remote_crypto.py + remote_signal.py + remote_relayd/*.py → /opt/remote-relayd）
  2. 远端 Python >= 3.9 检测（python3.12→3.9→python3 依次探测）
  3. venv + 依赖（cryptography/msgpack）
  4. PSK: /etc/remote-relayd/relay.env 已有则沿用; 否则远端 genkey 生成并打印（三端共用）
  5. systemd 服务（scp 单元文件 + enable --now）
  6. 防火墙（firewalld/ufw 放行 41000 TCP+UDP; 均无则提示云安全组手动放行）

--dry-run: 打印每步将执行的 ssh/scp 命令，不执行（预检工具）。
前置: ssh 免密可登录目标（默认 root）; VPS 可访问 PyPI。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEST = "/opt/remote-relayd"
ENVFILE = "/etc/remote-relayd/relay.env"
SERVICE_FILE = "remote-relayd.service"
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # tools/relay-deploy → backend
REMOTE_PY_DETECT = """
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  command -v $c >/dev/null 2>&1 && $c -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null && { echo $c; exit 0; }
done; exit 1"""
FIREWALL_SCRIPT = """
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --add-port=41000/tcp --add-port=41000/udp --permanent && firewall-cmd --reload
elif command -v ufw >/dev/null 2>&1; then
  ufw allow 41000/tcp && ufw allow 41000/udp
else
  echo "    （无 firewalld/ufw——确认云安全组放行 41000 TCP+UDP）"
fi"""


@dataclass(frozen=True)
class DeployTarget:
    """部署目标定型。"""

    host: str
    ssh_user: str = "root"
    dest: str = DEST
    envfile: str = ENVFILE

    @property
    def ssh_dest(self) -> str:
        return f"{self.ssh_user}@{self.host}"


@dataclass
class DeployReport:
    """部署结果（步骤完成记录 + PSK 交接）。"""

    steps_done: list[str] = field(default_factory=list)
    psk_generated: str = ""        # 非空 = 本次新生成（需用户记录）
    psk_reused: bool = False       # True = 沿用远端已有 envfile


class RelaydDeployer:
    """relayd 部署编排器（6 步链; 每步失败立即中止）。"""

    def __init__(self, target: DeployTarget, dry_run: bool = False) -> None:
        self._t = target
        self._dry = dry_run
        self._report = DeployReport()

    # ---- 基础封装 -----------------------------------------------------------
    def _ssh(self, step: str, remote_cmd: str,
             capture: bool = False) -> "subprocess.CompletedProcess[str]":
        """执行远端命令; 非零退出即失败中止（dry_run 只打印）。"""
        argv = ["ssh", self._t.ssh_dest, remote_cmd]
        return self._run(step, argv, capture)

    def _scp(self, step: str, sources: list[str], dest: str) -> None:
        """上传文件到远端。"""
        argv = ["scp", *sources, dest]
        self._run(step, argv)

    def _run(self, step: str, argv: list[str],
             capture: bool = False) -> "subprocess.CompletedProcess[str]":
        printable = " ".join(argv)
        if self._dry:
            print(f"[dry] {printable}")
            # dry-run 返回假完成对象（调用方约定: dry 模式不消费输出，除 _ensure_psk 走沿用分支）
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        print(f"==> {step}")
        result = subprocess.run(argv, capture_output=capture, text=True)
        if result.returncode != 0:
            print(f"[ERROR] 步骤失败（退出码 {result.returncode}）: {printable}", file=sys.stderr)
            if capture and result.stderr:
                print(f"       stderr: {result.stderr.strip()[:400]}", file=sys.stderr)
            sys.exit(1)
        return result

    # ---- 6 步 ---------------------------------------------------------------
    def sync_code(self) -> None:
        """步骤 1: 同步 relayd 运行所需代码到远端。"""
        t = self._t
        self._ssh("1/6 同步代码（services/remote_* + 入口）",
                  f"mkdir -p {t.dest}/venv {t.dest}/services/remote_relayd")
        srcs = [str(BACKEND_DIR / "services" / n) for n in ("remote_crypto.py", "remote_signal.py")]
        self._scp("1/6 同步代码（加密/信令模块）", srcs, f"{t.ssh_dest}:{t.dest}/services/")
        relayd_py = sorted(str(p) for p in (BACKEND_DIR / "services" / "remote_relayd").glob("*.py"))
        self._scp("1/6 同步代码（relayd 包）", relayd_py, f"{t.ssh_dest}:{t.dest}/services/remote_relayd/")
        self._ssh("1/6 收尾（包标记 + 清理 pycache）",
                  f"cd {t.dest} && touch services/__init__.py && rm -rf services/remote_relayd/__pycache__")
        self._report.steps_done.append("sync_code")

    def ensure_python(self) -> str:
        """步骤 2: 远端 Python >= 3.9 探测。Returns: 远端 python 命令名。"""
        if self._dry:
            print(f"[dry] ssh {self._t.ssh_dest} '{REMOTE_PY_DETECT.strip()}'")
            return "python3(待探测)"
        result = self._ssh("2/6 检测 Python >= 3.9", REMOTE_PY_DETECT, capture=True)
        py = (result.stdout or "").strip()
        if not py:
            print("!! 未找到 Python>=3.9——请先安装"
                  "（CentOS: dnf install python3.11; Ubuntu: apt install python3.10-venv）",
                  file=sys.stderr)
            sys.exit(1)
        print(f"    Python: {py}")
        self._report.steps_done.append(f"ensure_python({py})")
        return py

    def setup_venv(self, py: str) -> None:
        """步骤 3: 远端 venv + 依赖。"""
        t = self._t
        self._ssh("3/6 venv + 依赖（cryptography/msgpack）",
                  f"{py} -m venv {t.dest}/venv && {t.dest}/venv/bin/pip install -q "
                  f"--upgrade cryptography msgpack")
        self._report.steps_done.append("setup_venv")

    def ensure_psk(self) -> None:
        """步骤 4: PSK——已有沿用; 否则远端 genkey 并打印。"""
        t = self._t
        self._ssh("4/6 准备目录", f"mkdir -p /etc/remote-relayd /var/log/remote-relayd")
        if self._dry:
            print(f"[dry] ssh {t.ssh_dest} 'test -s {t.envfile}（非空则沿用）'")
            print(f"[dry] ssh {t.ssh_dest} 'cd {t.dest} && venv python -m services.remote_relayd genkey'")
            self._report.steps_done.append("ensure_psk(dry)")
            return
        # 注意: test -s 失败（文件缺失/空）不能走 _ssh 的失败中止路径——单独 run
        check = subprocess.run(["ssh", t.ssh_dest, f"test -s {t.envfile}"])
        if check.returncode == 0:
            print(f"    沿用已有 {t.envfile}")
            self._report.psk_reused = True
            self._report.steps_done.append("ensure_psk(reused)")
            return
        psk = self._ssh("4/6 生成 PSK",
                        f"cd {t.dest} && {t.dest}/venv/bin/python -m services.remote_relayd genkey",
                        capture=True).stdout.strip()
        if not psk:
            print("[ERROR] 远端 genkey 无输出", file=sys.stderr)
            sys.exit(1)
        self._ssh("4/6 写入 PSK 配置",
                  f"printf 'REMOTE_RELAY_PSK=%s\\nREMOTE_RELAY_PORT=41000\\n' '{psk}' "
                  f"> {t.envfile} && chmod 600 {t.envfile}")
        self._report.psk_generated = psk
        self._report.steps_done.append("ensure_psk(generated)")

    def install_systemd(self) -> None:
        """步骤 5: systemd 服务（enable --now）。"""
        t = self._t
        unit_src = Path(__file__).resolve().parent / SERVICE_FILE
        self._scp("5/6 上传 systemd 单元", [str(unit_src)], f"{t.ssh_dest}:/etc/systemd/system/")
        self._ssh("5/6 启用服务", "systemctl daemon-reload && systemctl enable --now remote-relayd")
        self._report.steps_done.append("install_systemd")

    def firewall(self) -> None:
        """步骤 6: 防火墙放行 41000 TCP+UDP。"""
        self._ssh("6/6 防火墙（TCP/UDP 41000）", FIREWALL_SCRIPT)
        self._report.steps_done.append("firewall")

    # ---- 入口 ---------------------------------------------------------------
    def run(self) -> DeployReport:
        self.sync_code()
        py = self.ensure_python()
        self.setup_venv(py)
        self.ensure_psk()
        self.install_systemd()
        self.firewall()
        return self._report

    def print_summary(self) -> None:
        t = self._t
        if self._dry:
            print("\n[dry] 以上为将执行的命令（未执行）")
            return
        print("\n✅ 完成。"
              f"状态: ssh {t.ssh_dest} systemctl status remote-relayd")
        print(f"   日志: ssh {t.ssh_dest} tail -f /var/log/remote-relayd/relayd.log")
        if self._report.psk_generated:
            print("\n    ⚠ PSK 已生成（三端共用——复制到 MacBook/MacMini .ai_env 的 RELAY_PSK、"
                  "手机 Legado 配置）:")
            print(f"    {self._report.psk_generated}")
        elif self._report.psk_reused:
            print(f"\n    PSK: 沿用远端 {t.envfile}（查看: ssh {t.ssh_dest} cat {t.envfile}）")


def _parse_args(argv: list[str]) -> tuple[DeployTarget, bool]:
    from typing import cast
    parser = argparse.ArgumentParser(
        prog="deploy.py",
        description="relayd VPS 部署器（薄壳 deploy-relayd.sh 的实际入口）")
    parser.add_argument("host", help="VPS IP 或 hostname")
    parser.add_argument("ssh_user", nargs="?", default="root", help="SSH 用户（默认 root）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将执行的 ssh/scp 命令，不执行")
    ns = parser.parse_args(argv)
    return DeployTarget(host=cast("str", ns.host), ssh_user=cast("str", ns.ssh_user)), \
        cast("bool", ns.dry_run)


def main() -> int:
    target, dry_run = _parse_args(sys.argv[1:])
    deployer = RelaydDeployer(target, dry_run=dry_run)
    report = deployer.run()
    deployer.print_summary()
    if report.psk_generated:
        pass  # 已在 summary 打印（保持 main 简洁）
    return 0


if __name__ == "__main__":
    sys.exit(main())
