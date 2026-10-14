"""远程节点引导器（Mac Mini 等远程角色的一等公民入口）。

薄壳 start-remote-node.sh 仅定位+exec 本模块; 全部引导逻辑在此:
  1. venv 自举   — 不在 RuntimePaths.VENV_DIR 的 venv 内 → stdlib venv 创建
                   （显式选择，与 detect_py_deps --venv-backend stdlib 同语义）+ exec 重启自身
  2. 依赖幂等    — fastapi 哨兵探测; 缺则 detect_py_deps install（tags=console_runtime）
  3. 配置初始化  — RELAY 四键（RELAY_HOST/RELAY_PORT/RELAY_PSK/REMOTE_NODE_ID）缺失时
                   参数注入或终端交互补齐; 落盘远程模式键组:
                   P2P_GATEWAY_ENABLE=1（gateway 必开）+ CONTROL_RESIDENT=1（心跳不自杀）
  4. 模型 ensure — --model-tags 圈选（默认安全三件套; 含 tts 则加 CosyVoice3）;
                   --model-tags 圈选安装范围（默认安全组）、--skip-models 全跳（已缓存项秒过）
  5. 启动控制台  — exec python server.py（信号/模型预载/uvicorn 全复用其 main）

--check 模式: 打印引导计划（将写的配置/将装的模型/启动命令）后退出——预检工具。
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import dataclass, field

from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:  # 静态分析用（运行时不导入——见下方延迟导入说明）
    from services.config_manager import ConfigManager
    from services.model_assets import ModelAssetRegistry

# 允许 `python services/remote_node.py` 直跑（backend 目录为包根）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .ai_env 位置锚定仓库根下的 .opencode/（与主环境一致: 插件注入的 OPENCODE_ROOT
# 即 .opencode 目录; 无 env 的手动启动（远程节点薄壳）由 runtime_paths 兜底回退
# 到同一路径——两端统一, 无需此处干预）

from services.detect_py_deps import (  # noqa: E402
    VENV_DIR,
    _get_venv_python,
    _log,
)
from services.endpoint_probe import EndpointProber, ProbeSpec  # noqa: E402
from services.runtime_paths import RuntimePaths  # noqa: E402

# ConfigManager / model_assets / _run_install 为重依赖（psutil 等三方包）——
# 延迟到方法内 import: 保证系统 Python（无三方包）也能执行 venv 自举（鸡生蛋约束）
def _cm() -> "type[ConfigManager]":
    from services.config_manager import ConfigManager
    return ConfigManager


def _registry() -> "ModelAssetRegistry":
    from services.model_assets import ModelAssetRegistry
    return ModelAssetRegistry.get_instance()

BOOTSTRAP_ENV = "_REMOTE_NODE_BOOTSTRAPPED"
MODEL_WAIT_TIMEOUT_SEC = 3600  # 全部模型下载等待上限（官方直连慢网络实测 30min 不够）


@dataclass(frozen=True)
class RemoteNodeArgs:
    """CLI 参数定型（argparse 解析边界，解析后立即定型）。"""

    relay_host: str = ""
    relay_port: str = ""
    relay_psk: str = ""
    node_id: str = ""
    skip_models: bool = False
    model_tags: tuple[str, ...] = ()  # 圈选安装范围（空=默认安全组; 如 ("security","tts")）
    assume_yes: bool = False
    check_only: bool = False


@dataclass(frozen=True)
class RelayConfig:
    """RELAY 四键（gateway 注册到 relayd 所需的完整配置）。"""

    host: str = ""
    port: str = ""
    psk: str = ""
    node_id: str = ""

    def complete(self) -> bool:
        return all((self.host, self.port, self.psk, self.node_id))

    def to_env_updates(self) -> dict[str, str]:
        """落盘键组: 四键 + 远程模式语义键（gateway 必开 + 心跳常驻不自杀）。"""
        k = _cm().Keys
        return {
            k.RELAY_HOST: self.host,
            k.RELAY_PORT: self.port,
            k.RELAY_PSK: self.psk,
            k.REMOTE_NODE_ID: self.node_id,
            k.P2P_GATEWAY_ENABLE: "1",
            k.CONTROL_RESIDENT: "1",
        }


@dataclass
class BootstrapPlan:
    """引导计划（--check 的展示单元 + 各步骤的执行依据）。"""

    venv_python: str = ""
    deps_install_needed: bool = False
    relay: RelayConfig = field(default_factory=RelayConfig)
    config_updates: dict[str, str] = field(default_factory=dict)
    model_ids: list[str] = field(default_factory=list)
    launch_cmd: list[str] = field(default_factory=list)


class RemoteNodeBootstrapper:
    """远程节点引导器（五步链: venv → 依赖 → 配置 → 模型 → 启动）。"""

    def __init__(self, args: RemoteNodeArgs) -> None:
        self._args = args

    # ---- 步骤 1: venv 自举 -------------------------------------------------
    def ensure_venv(self) -> str:
        """确保在 RuntimePaths 目标 venv 内运行; 不在则建 venv 并 exec 重启自身。

        Returns: venv python 路径（_get_venv_python 拼接值，两种分支一致）。
        """
        venv_python = _get_venv_python()
        # venv 身份判定: sys.prefix 是解释器自认的 venv 根——不受路径拼接差异影响
        # （macOS /var→/private/var symlink 会让 abspath 字符串比较误判）;
        # realpath 只消除 symlink 前缀差异，比较对象是 sys.prefix 而非解释器 symlink
        if os.path.realpath(sys.prefix) == os.path.realpath(VENV_DIR):
            return venv_python
        if os.environ.get(BOOTSTRAP_ENV) == "1":
            _log("[ERROR] venv 重启已执行过但仍不在 venv 内，终止（防循环）")
            sys.exit(1)
        _log(f"[*] 当前不在目标 venv: {sys.executable}")
        if not os.path.isfile(venv_python):
            _log(f"[*] python -m venv {VENV_DIR} ...（stdlib 显式选择）")
            result = subprocess.run([sys.executable, "-m", "venv", VENV_DIR])
            if result.returncode != 0:
                _log(f"[ERROR] venv 创建失败（退出码 {result.returncode}）")
                sys.exit(1)
        _log(f"[*] 重启到 venv Python: {venv_python}")
        os.environ[BOOTSTRAP_ENV] = "1"
        if os.name == "nt":
            result = subprocess.run([venv_python, os.path.abspath(__file__)] + sys.argv[1:])
            sys.exit(result.returncode)
        os.execv(venv_python, [venv_python, os.path.abspath(__file__)] + sys.argv[1:])

    # ---- 步骤 2: 依赖幂等 ---------------------------------------------------
    def ensure_deps(self) -> bool:
        """fastapi 哨兵探测; 缺则 console_runtime 集安装。Returns: 是否执行了安装。"""
        probe = subprocess.run([sys.executable, "-c", "import fastapi"],
                               capture_output=True)
        # TTS 依赖（plus 引擎, 主 venv uv --no-deps 直装）按 tags 圈选联动
        tts_installed = False
        if "tts" in self._args.model_tags:
            if not self._tts_env_ready():
                _log("[*] --model-tags tts: plus 依赖缺失——uv 直装主 venv")
                try:
                    r = subprocess.run(  # noqa: S603 —— venv 自身 pip
                        [sys.executable, "-m", "pip", "install", "--no-deps",
                         "mlx-audio==0.2.10", "mlx-audio-plus==0.1.8", "mlx-lm",
                         "-i", "https://mirrors.aliyun.com/pypi/simple/"],
                        timeout=1200, capture_output=True, text=True)
                    tts_installed = r.returncode == 0
                    if r.returncode != 0:
                        _log(f"[WARN] plus 依赖安装失败: {r.stderr[-200:]}")
                except FileNotFoundError as e:
                    _log(f"[WARN] 自愈安装异常(解释器缺失): {e}")
        if probe.returncode == 0:
            _log("[+] 依赖齐备（fastapi 可导入），跳过安装")
            return tts_installed
        _log("[*] 依赖缺失——安装 console_runtime 集（stdlib venv）")
        from services.detect_py_deps import DepTag, _run_install
        _run_install(dry_run=False, tags=[DepTag.CONSOLE_RUNTIME], venv_backend="stdlib")
        return True

    # ---- 步骤 3: 配置初始化 -------------------------------------------------
    def _collect_relay(self, cm: "ConfigManager") -> RelayConfig:
        """收集 RELAY 四键（CLI 参数优先，回退 .ai_env 现值）——ensure_config/build_plan 共用。"""
        k = cm.Keys
        return RelayConfig(
            host=self._args.relay_host or (cm.get(k.RELAY_HOST) or "").strip(),
            port=self._args.relay_port or (cm.get(k.RELAY_PORT) or "").strip(),
            psk=self._args.relay_psk or (cm.get(k.RELAY_PSK) or "").strip(),
            node_id=self._args.node_id or (cm.get(k.REMOTE_NODE_ID) or "").strip(),
        )

    def ensure_config(self) -> tuple[RelayConfig, dict[str, str]]:
        """读 .ai_env 四键; 缺则参数/交互补齐; 返回（最终配置, 待落盘键组）。

        已完整且远程模式键已就位 → updates 为空（幂等零写入）。
        """
        cm = _cm().get_instance()
        relay = self._collect_relay(cm)
        if not relay.complete() and sys.stdin.isatty():
            relay = self._prompt_missing(relay)
        if not relay.complete():
            _log("[ERROR] RELAY 四键不完整（host/port/psk/node_id）——"
                 "用 --relay-host/--relay-port/--relay-psk/--node-id 注入或交互输入")
            sys.exit(1)
        wanted = relay.to_env_updates()
        updates = {key: val for key, val in wanted.items()
                   if (cm.get(key) or "").strip() != val}
        # 控制台令牌: 远程节点语义必配——非空才会绑 0.0.0.0（LAN 可视化访问）
        # + 节点模式预载; 为空则自动生成（用户从启动日志取值, 填 MacBook 远程 TAB 令牌）
        api_key_now = (cm.get(cm.Keys.CONTROL_API_KEY) or "").strip()
        if not api_key_now:
            import secrets
            api_key = secrets.token_urlsafe(32)
            updates[cm.Keys.CONTROL_API_KEY] = api_key
            _log("[+] 已生成控制台令牌 CONTROL_API_KEY = " + api_key)
            _log("    用途: ①LAN 浏览器可视化访问的前提 ②MacBook 远程 TAB(HTTP直连模式)"
                 "的 Bearer 令牌——填入「远程控制台令牌」")
        if updates:
            cm.set(updates)
            _log(f"[+] 配置已落盘: {sorted(updates)}")
        else:
            _log("[+] 远程模式配置已就位，零写入")
        return relay, updates

    def _prompt_missing(self, relay: RelayConfig) -> RelayConfig:
        """终端交互补齐缺失键（显示已有值，回车保留）。"""
        _log("[*] RELAY 配置不完整——交互补齐（回车保留已有值）")
        prompts = (("relayd 主机（VPS 公网 IP）", "host"),
                   ("relayd 端口（默认 41000）", "port"),
                   ("RELAY_PSK（base64 32B，relayd genkey 生成，两端一致）", "psk"),
                   ("节点 ID（如 macmini）", "node_id"))
        values = {"host": relay.host, "port": relay.port or "41000",
                  "psk": relay.psk, "node_id": relay.node_id}
        for label, attr in prompts:
            cur = values[attr]
            hint = f"（当前: {cur}）" if cur else ""
            answer = input(f"  {label}{hint}: ").strip()
            if answer:
                values[attr] = answer
        return RelayConfig(**values)

    # ---- 步骤 4: 模型 ensure ------------------------------------------------
    HF_OFFICIAL = "https://huggingface.co"
    HF_MIRROR = "https://hf-mirror.com"
    # 测速路径: bge-m3 权重（2.3GB——4s 内读不完; 官方与镜像同 repo 路径,
    # 302 到各自 CDN, 测的是真实下载链路吞吐。小文件会一次 read 读完导致
    # 循环 break、total/时长 被低估为 ~0）
    HF_PROBE_PATH = "BAAI/bge-m3/resolve/main/pytorch_model.bin"

    def ensure_hf_endpoint(self) -> None:
        """.ai_env 未配置 HF_ENDPOINT 时双端测速取优——镜像显著快（>2x）才切并固化。

        已显式配置则完全尊重用户选择（含强制官方的场景），零干预。
        官方胜出不写配置（保持空=官方默认, 网络环境变化后下次引导可重探）;
        镜像胜出写入固化（探测结论"官方不可达/显著慢"短期不会变）。
        """
        cm = _cm().get_instance()
        if (cm.get(cm.Keys.HF_ENDPOINT) or "").strip():
            return  # 显式配置优先
        spec = ProbeSpec(path=self.HF_PROBE_PATH)
        _log(f"[*] HF 端点测速（各 {spec.duration_sec:.0f}s）...")
        official, mirror = EndpointProber.probe_all(
            [self.HF_OFFICIAL, self.HF_MIRROR], spec)
        _log(f"    官方 {official.mbps} MB/s | 镜像 {mirror.mbps} MB/s")
        if EndpointProber.significantly_faster(mirror, official):
            _log("[!] 镜像显著更快——写入 .ai_env:")
            _log(f"    HF_ENDPOINT={self.HF_MIRROR}")
            cm.set_one(cm.Keys.HF_ENDPOINT, self.HF_MIRROR)
        else:
            _log("[+] 使用官方端点直连")

    def _selected_model_ids(self) -> list[str]:
        """tags 圈选（tts tag 当前对应 cosyvoice3-8bit 单资产, plus 引擎）。"""
        return [m.id for m in _registry().filter_by_tags(list(self._args.model_tags))]

    def _tts_env_ready(self) -> bool:
        """plus 引擎健康探测（--check 计划与 ensure_deps 共用）。"""
        r = subprocess.run([sys.executable, "-c",
                            "import mlx_audio, mlx_audio_plus"],
                           capture_output=True, timeout=60)  # noqa: S603
        return r.returncode == 0

    def ensure_models(self) -> list[str]:
        """确保模型缓存就位（已缓存秒过）。Returns: 本次实际等待的模型 id 列表。"""
        if self._args.skip_models:
            _log("[*] --skip-models: 跳过模型检查")
            return []
        self.ensure_hf_endpoint()
        ids = self._selected_model_ids()
        pending = self._start_pending(reg := _registry(), ids)
        if not pending:
            _log("[+] 模型缓存全部就位，零下载")
            return []
        self._wait_models(reg, pending)
        return pending

    def _start_pending(self, reg: ModelAssetRegistry,
                       ids: list[str]) -> list[str]:
        """对未缓存模型启动后台下载，返回待等待列表。"""
        snapshot = {m.id: m for m in reg.get_model_assets()}
        pending: list[str] = []
        for mid in ids:
            if mid not in snapshot:
                _log(f"[ERROR] 模型 {mid} 未注册（id 拼写或注册表缺项）")
                sys.exit(1)
            if snapshot[mid].cached:
                _log(f"[+] {mid} 已缓存")
                continue
            _log(f"[*] {mid} 未缓存——启动下载 ...")
            if not reg.start_download(mid):
                _log(f"[ERROR] {mid} 下载启动失败")
                sys.exit(1)
            pending.append(mid)
        return pending

    def _wait_models(self, reg: ModelAssetRegistry, pending: list[str]) -> None:
        """轮询快照直到全部 cached、任一下载 error（立即失败）或超时。"""
        deadline = time.monotonic() + MODEL_WAIT_TIMEOUT_SEC
        while True:
            time.sleep(5)
            snapshot = {m.id: m for m in reg.get_model_assets()}
            failed = {mid: snapshot[mid].download.error
                      for mid in pending if snapshot[mid].download.status == "error"}
            if failed:
                for mid, err in failed.items():
                    _log(f"[ERROR] {mid} 下载失败: {err}")
                sys.exit(1)
            # 完成判定用下载状态（worker returncode=0 才 done）而非 cached
            # （目录存在性——snapshot_download 启动即建目录, 会假完成）
            waiting = [mid for mid in pending
                       if snapshot[mid].download.status != "done"]
            done = [mid for mid in pending
                    if snapshot[mid].download.status == "done"]
            for mid in done:
                _log(f"[+] {mid} 下载完成")
            pending = waiting
            if not pending:
                return
            if time.monotonic() > deadline:
                _log(f"[ERROR] 模型下载超时（>{MODEL_WAIT_TIMEOUT_SEC}s）: {pending}")
                _log("[!] 后台下载子进程仍在继续（数据保留，断点续传）——"
                     "慢速网络可配置 .ai_env: HF_ENDPOINT=https://hf-mirror.com 后重跑")
                sys.exit(1)
            parts = [f"{mid} {snapshot[mid].download.progress * 100:.0f}%" for mid in pending]
            _log(f"[*] 等待下载: {', '.join(parts)}")

    # ---- 步骤 5: 启动控制台 -------------------------------------------------
    def launch(self) -> int:
        """spawn 独立会话的控制台进程, 等就绪后返回（SSH 断开不影响控制台）。

        - start_new_session=True: 新会话+新进程组——SIGHUP 免疫（脚本退出/SSH
          断开不连带）; stdio 重定向 LOGS_DIR/remote-node.log（-u 无缓冲可实时 tail）
        - 就绪信号: IPC socket 文件出现（server 侧 "bind 成功，本实例成为监听者"
          的权威标志; 早于模型加载, 不会久等）
        - Returns: 控制台 pid（调用方随后退出, 控制台继续跑）
        """
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(RuntimePaths.LOGS_DIR, "remote-node.log")
        os.makedirs(RuntimePaths.LOGS_DIR, exist_ok=True)
        ipc_path = _cm().get_instance().ipc_addr()
        _log("[*] 启动控制台（独立会话）...")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== remote-node start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            proc = subprocess.Popen(
                [sys.executable, "-u", "server.py"], cwd=backend_dir,
                stdin=subprocess.DEVNULL,  # stdin 免疫终端关闭（坏 fd 0 会在
                                           # execv 重启时 Fatal: init_sys_streams）
                stdout=fh, stderr=fh, start_new_session=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if os.path.exists(ipc_path):
                _log(f"[+] 控制台已就绪: pid={proc.pid}（独立会话, SSH 断开不影响）")
                _log(f"    日志: tail -f {log_path}")
                _log(f"    停止: kill {proc.pid}")
                return proc.pid
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        _log(f"[ERROR] 控制台启动失败（{proc.pid} 已退出或 90s 未就绪）——日志尾部:")
        try:
            with open(log_path, encoding="utf-8", errors="ignore") as fh:
                tail = fh.read().splitlines()[-25:]
            for line in tail:
                _log(f"    {line}")
        except OSError:
            pass
        sys.exit(1)

    # ---- 计划与入口 ---------------------------------------------------------
    def build_plan(self) -> BootstrapPlan:
        """构建引导计划（--check 展示用; 不落盘不下载不启动）。"""
        venv_python = _get_venv_python()
        # 依赖探测用目标 venv python（存在时）——与 ensure_deps 真实执行视角一致;
        # venv 未建时用当前解释器（此时真实运行也必然先走安装）
        probe_py = venv_python if os.path.isfile(venv_python) else sys.executable
        probe = subprocess.run([probe_py, "-c", "import fastapi"],
                               capture_output=True)
        cm = _cm().get_instance()
        relay = self._collect_relay(cm)
        ids = [] if self._args.skip_models else self._selected_model_ids()
        return BootstrapPlan(
            venv_python=venv_python,
            deps_install_needed=probe.returncode != 0,
            relay=relay,
            # 与 ensure_config 的 diff 语义一致（现值已等于目标值的键不列——真实运行零写入）
            config_updates=({key: val for key, val in relay.to_env_updates().items()
                             if (cm.get(key) or "").strip() != val}
                            if relay.complete() else {}),
            model_ids=ids,
            launch_cmd=[venv_python, "server.py"],
        )

    def run(self) -> None:
        """完整引导链（--check 只打印计划）。"""
        if self._args.check_only:
            self._print_plan(self.build_plan())
            return
        self.ensure_venv()          # 可能 exec 重启——后续步骤在新进程中继续
        self.ensure_deps()
        self.ensure_config()
        self.ensure_models()
        self.launch()               # spawn 独立会话 + 等就绪; 返回后脚本正常结束

    def _print_plan(self, plan: BootstrapPlan) -> None:
        _log("[*] === 远程节点引导计划（--check，不执行）===")
        _log(f"    venv Python:   {plan.venv_python}")
        _log(f"    依赖安装:      {'需要（console_runtime 集）' if plan.deps_install_needed else '不需要（已齐备）'}")
        _log(f"    RELAY 配置:    {'完整' if plan.relay.complete() else '不完整（将交互/参数补齐）'}"
             f"{f' → {plan.relay.host}:{plan.relay.port}（node={plan.relay.node_id}）' if plan.relay.complete() else ''}")
        _log(f"    将落盘键组:    {sorted(plan.config_updates) if plan.config_updates else '无（已就位）'}")
        _log(f"    模型 ensure:   {plan.model_ids if plan.model_ids else '跳过'}")
        _log(f"    启动命令:      {' '.join(plan.launch_cmd)}")


def _parse_args(argv: list[str]) -> RemoteNodeArgs:
    parser = argparse.ArgumentParser(
        prog="remote_node.py",
        description="远程节点引导器（依赖/配置/模型/启动 一站式）")
    parser.add_argument("--relay-host", default="", help="relayd 主机（VPS 公网 IP）")
    parser.add_argument("--relay-port", default="", help="relayd 端口（默认 41000）")
    parser.add_argument("--relay-psk", default="", help="RELAY_PSK（base64 32B，与 relayd 一致）")
    parser.add_argument("--node-id", default="", help="节点 ID（如 macmini）")
    parser.add_argument("--skip-models", action="store_true", help="跳过模型检查/下载")
    parser.add_argument("--model-tags", default="",
                        help="模型圈选标签（逗号分隔: security,tts; 空=默认安全组）")
    parser.add_argument("-y", "--assume-yes", action="store_true", help="免交互（当前用于语义显式化）")
    parser.add_argument("--check", action="store_true",
                        help="只打印引导计划，不执行（预检工具）")
    ns = parser.parse_args(argv)
    from typing import cast
    model_tags_raw = cast("str", ns.model_tags)
    return RemoteNodeArgs(
        relay_host=cast("str", ns.relay_host), relay_port=cast("str", ns.relay_port),
        relay_psk=cast("str", ns.relay_psk), node_id=cast("str", ns.node_id),
        skip_models=cast("bool", ns.skip_models),
        model_tags=tuple(t.strip() for t in model_tags_raw.split(",") if t.strip()),
        assume_yes=cast("bool", ns.assume_yes), check_only=cast("bool", ns.check),
    )


def main() -> int:
    bootstrapper = RemoteNodeBootstrapper(_parse_args(sys.argv[1:]))
    bootstrapper.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
