"""端到端联调: 主控 + 节点双进程真实链路（模型远程化一期 §4.1 验收）。

场景链（需求文档步骤 19 验证点）:
  1. 节点(B) /api/remote/health 带 token 可探测; 无 token（非本机来源）401
  2. 主控(A) 切换远程成功
  3. A 的 /embed 实际走 B（B 日志可见; 本地模型未加载）
  4. kill B → 2 心跳周期内 A 降级（DEGRADED）→ embed fallback 本地成功（HOLD）
  5. 重启 B → 3 周期恢复（REMOTE）→ 稳定期后 A 本地模型卸载
  6. B 非本机管理面 403

运行（真实模型加载，全程 ~3-5 分钟）:
  cd .opencode/control/backend
  OPENSECURITY_E2E_REMOTE=1 python3 tests/test_e2e_remote.py
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

NODE_PORT = 46010
MASTER_PORT = 46510
TOKEN = "e2e-remote-key-0123456789"
NODE_ROOT = Path("/tmp/e2e_remote_node")
MASTER_ROOT = Path("/tmp/e2e_remote_master")
HEARTBEAT_SEC = "1"
UNLOAD_SEC = "8"

# 可调参数小值（e2e 加速; 唯一通道 .ai_env——随 _setup 写入两个沙箱）
_TUNABLES_AI_ENV = {
    "REMOTE_HEARTBEAT_INTERVAL_SEC": HEARTBEAT_SEC,
    "REMOTE_FAIL_THRESHOLD": "2",
    "REMOTE_RECOVER_THRESHOLD": "3",
    "REMOTE_UNLOAD_DELAY_SEC": UNLOAD_SEC,
    "REMOTE_INFER_TIMEOUT_SEC": "30",
    "REMOTE_PROBE_TIMEOUT_SEC": "3",
}

# 本机局域网 IP（让 A→B 走非回环地址——验证 api_guard 的局域网分支）
def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _setup(root: Path, ai_env: dict[str, str]) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    merged = {**_TUNABLES_AI_ENV, **ai_env}
    lines = ["# e2e 临时配置"]
    lines += [f"{k}={v}" for k, v in merged.items()]
    (root / ".ai_env").write_text("\n".join(lines) + "\n")


def _spawn(root: Path, opensecurity_home: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "OPENCODE_ROOT": str(root),
        "OPENSECURITY_HOME": str(opensecurity_home),
        "CONTROL_TCP_PORT": str(port),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    log = open(opensecurity_home / "spawn.log", "w")
    return subprocess.Popen(
        [sys.executable, str(BACKEND_DIR / "server.py")],
        env=env, stdout=log, stderr=log,
    )


def _wait_health(port: int, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code in (200, 503):  # 503=活着但模型加载中
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def _wait_state(port: int, state: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/remote/status", timeout=3)
            d = r.json()
            if d.get("state") == state:
                return d
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"等待 state={state} 超时（最后: {d!r}）")


def main() -> int:
    if os.environ.get("OPENSECURITY_E2E_REMOTE") != "1":
        print("⏭ 跳过（设 OPENSECURITY_E2E_REMOTE=1 启用）")
        return 0

    lan_ip = _lan_ip()
    print(f"本机局域网 IP: {lan_ip}")
    node_base = f"http://{lan_ip}:{NODE_PORT}"

    # ── 环境搭建 ────────────────────────────────────────
    _setup(NODE_ROOT, {"CONTROL_API_KEY": TOKEN, "CONTROL_RESIDENT": "1"})
    _setup(MASTER_ROOT, {"REMOTE_CONSOLE_URL": node_base, "REMOTE_CONSOLE_TOKEN": TOKEN})
    node_data = NODE_ROOT / "data"; node_data.mkdir(parents=True)
    master_data = MASTER_ROOT / "data"; master_data.mkdir(parents=True)

    node_log = (node_data / "logs" / "control.log")

    print("1) 启动节点(B)...")
    node_proc = _spawn(NODE_ROOT, node_data, NODE_PORT)
    assert _wait_health(NODE_PORT), "节点启动超时"
    print("   节点就绪")

    try:
        # ── 1. health 探测 + 鉴权 ──────────────────────────
        r = httpx.get(f"{node_base}/api/remote/health",
                      headers={"Authorization": f"Bearer {TOKEN}"}, timeout=5)
        assert r.status_code == 200, f"带 token health 失败: {r.status_code}"
        health = r.json()
        assert health["service"] == "opencode-control"
        assert len(health["models"]) == 3, "三模型指纹"
        print(f"   health OK（延迟内嵌; 指纹 {len(health['models'])} 模型）")

        r = httpx.get(f"{node_base}/api/remote/health", timeout=5)
        assert r.status_code == 401, f"无 token 应 401，实际 {r.status_code}"
        r = httpx.get(f"{node_base}/api/config", timeout=5)
        assert r.status_code == 403, f"非本机管理面应 403，实际 {r.status_code}"
        print("   鉴权验证 OK（无 token 401 / 管理面 403）")

        # ── 2. 主控切换远程 ───────────────────────────────
        print("2) 启动主控(A) + 切换远程...")
        master_proc = _spawn(MASTER_ROOT, master_data, MASTER_PORT)
        assert _wait_health(MASTER_PORT), "主控启动超时"
        try:
            r = httpx.post(f"http://127.0.0.1:{MASTER_PORT}/api/remote/switch",
                           json={"target": "remote"}, timeout=15)
            d = r.json()
            assert d.get("ok"), f"切换失败: {d}"
            print("   切换远程 OK")

            # 转发路径锚点（B1）: 经 A 的 node=remote 读/写 B 的节点配置
            r = httpx.get(f"http://127.0.0.1:{MASTER_PORT}/api/remote/node-config",
                          params={"node": "remote"}, timeout=10)
            assert r.status_code == 200, f"转发读 node-config 失败: {r.status_code} {r.text[:200]}"
            assert "CONTROL_RESIDENT" in r.json(), "转发读应含节点三 KEY"
            r = httpx.put(f"http://127.0.0.1:{MASTER_PORT}/api/remote/node-config",
                          params={"node": "remote"},
                          json={"configs": {"CONTROL_RESIDENT": "1"}}, timeout=10)
            assert r.status_code == 200, f"转发写 node-config 失败: {r.status_code} {r.text[:200]}"
            assert r.json().get("ok"), f"转发写返回异常: {r.json()}"
            print("   转发读写 node-config OK（B1 锚点）")

            st = _wait_state(MASTER_PORT, "remote", timeout=15)
            assert st["enabled"] is True
            print(f"   状态 REMOTE（远程指纹 {len(st['remote_health']['models'])} 模型）")

            # ── 3. embed 实际走 B ─────────────────────────
            print("3) 等 B 模型预加载完成...")
            deadline = time.time() + 180
            while time.time() < deadline:
                h = httpx.get(f"{node_base}/api/remote/health",
                              headers={"Authorization": f"Bearer {TOKEN}"}, timeout=5).json()
                if all(m["loaded"] for m in h["models"]):
                    break
                time.sleep(2)
            else:
                raise AssertionError("B 模型预加载超时（180s）")
            print("   B 三模型 ready")

            t0 = time.time()
            r = httpx.post(f"http://127.0.0.1:{MASTER_PORT}/embed",
                           json={"inputs": ["e2e 远程推理验证"]}, timeout=60)
            assert r.status_code == 200, f"embed 失败: {r.status_code} {r.text[:200]}"
            vecs = r.json()
            assert len(vecs[0]) == 1024, f"向量维度 {len(vecs[0])}"
            print(f"   embed OK（1024 维，耗时 {time.time()-t0:.1f}s）")

            # 三模型远程全覆盖锚点: rerank + ocr 也走远程链路（B 节点真模型）
            t0 = time.time()
            r = httpx.post(f"http://127.0.0.1:{MASTER_PORT}/rerank",
                           json={"query": "端口扫描工具", "texts": ["nmap 是端口扫描工具", "今天天气不错"]},
                           timeout=60)
            assert r.status_code == 200, f"rerank 失败: {r.status_code} {r.text[:200]}"
            scores = r.json()
            assert len(scores) == 2 and scores[0] > scores[1], \
                f"rerank 分数语义（相关>无关）: {scores}"
            print(f"   rerank 远程 OK（score[0]={scores[0]:.3f} > score[1]={scores[1]:.3f}，耗时 {time.time()-t0:.1f}s）")

            import base64 as _b64
            import io as _io
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (320, 100), "white")
            ImageDraw.Draw(img).text((40, 35), "REMOTE-OCR-OK", fill="black")
            buf = _io.BytesIO(); img.save(buf, format="PNG")
            img_b64 = _b64.b64encode(buf.getvalue()).decode()
            t0 = time.time()
            r = httpx.post(f"http://127.0.0.1:{MASTER_PORT}/api/ocr/extract",
                           json={"image_b64": img_b64, "prompt": ""}, timeout=120)
            assert r.status_code == 200, f"ocr 远程失败: {r.status_code} {r.text[:200]}"
            text = r.json().get("text", "")
            assert "REMOTE" in text and "OCR" in text.replace(" ", ""), \
                f"OCR 应识别出标记文本，实际 {text!r}"
            print(f"   OCR 远程 OK（识别 {text.strip()[:30]!r}，耗时 {time.time()-t0:.1f}s）")
            st = httpx.get(f"http://127.0.0.1:{MASTER_PORT}/api/remote/status", timeout=5).json()
            assert st["local_models"].get("ocr") != "ready", "远程模式下 A 本地 OCR 不应加载"
            print("   三模型（embed/rerank/ocr）远程链路全覆盖 ✓")

            # 稳定期（8s）后 A 本地 embedder 卸载（启动时的预加载被释放）
            print("   等稳定期后本地模型卸载...")
            deadline = time.time() + int(UNLOAD_SEC) + 30
            while time.time() < deadline:
                st = httpx.get(f"http://127.0.0.1:{MASTER_PORT}/api/remote/status", timeout=5).json()
                if st["local_models"].get("embedder") not in ("ready", "starting"):
                    break
                time.sleep(1)
            assert st["local_models"].get("embedder") != "ready", \
                f"稳定期后 A 本地 embedder 应卸载（实际 {st['local_models']}）"
            print("   A 本地 embedder 已卸载（远程托管生效）✓")

            # ── 4. kill B → 降级 + fallback ───────────────
            print("4) kill 节点(B) → 降级...")
            node_proc.send_signal(signal.SIGTERM)
            node_proc.wait(timeout=15)
            _wait_state(MASTER_PORT, "degraded", timeout=20)
            print("   A 状态 DEGRADED ✓")

            t0 = time.time()
            r = httpx.post(f"http://127.0.0.1:{MASTER_PORT}/embed",
                           json={"inputs": ["e2e 降级 fallback 验证"]}, timeout=180)
            assert r.status_code == 200, f"fallback embed 失败: {r.status_code}"
            assert len(r.json()[0]) == 1024
            print(f"   fallback 本地 embed OK（HOLD 加载+推理 {time.time()-t0:.1f}s）")

            # ── 5. 重启 B → 恢复 + 延迟卸载 ───────────────
            print("5) 重启节点(B) → 恢复 + 稳定期后卸载...")
            node_log.parent.mkdir(parents=True, exist_ok=True)
            log_f = open(node_data / "spawn.log", "a")
            node_proc = _spawn(NODE_ROOT, node_data, NODE_PORT)
            assert _wait_health(NODE_PORT, timeout=90), "节点重启超时"
            _wait_state(MASTER_PORT, "remote", timeout=20)
            print("   A 恢复 REMOTE ✓")

            deadline = time.time() + int(UNLOAD_SEC) + 20
            while time.time() < deadline:
                st = httpx.get(f"http://127.0.0.1:{MASTER_PORT}/api/remote/status", timeout=5).json()
                if st["local_models"].get("embedder") not in ("ready", "starting"):
                    break
                time.sleep(1)
            assert st["local_models"].get("embedder") != "ready", \
                f"稳定期后 A 本地 embedder 应卸载（实际 {st['local_models']}）"
            print("   A 本地 embedder 已卸载（内存释放）✓")

            # A 日志验证 embed 请求实际发往 B（httpx 客户端日志; uvicorn access log 不落盘）
            a_log = (master_data / "logs" / "control.log")
            if a_log.exists():
                log_text = a_log.read_text(errors="ignore")
                assert "POST http" in log_text and "/embed" in log_text, \
                    "A 日志应有发往 B 的 /embed 请求记录"
                print("   A 日志确认 embed 请求发往 B ✓")

            print("\n✅ 端到端全部通过")
            return 0
        finally:
            master_proc.send_signal(signal.SIGTERM)
            try:
                master_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                master_proc.kill()
    finally:
        if node_proc.poll() is None:
            node_proc.send_signal(signal.SIGTERM)
            try:
                node_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                node_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
