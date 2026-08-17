"""OCR 服务（glm-ocr 加载/推理/释放，OcrService 类）。

架构：mcp-servers/ocr（FastMCP stdio 薄壳，不驻模型）
  └─ HTTP → routes/ocr.py → 本模块
              ├─ macOS(Apple Silicon): spawn MLX 子进程
              │    ~/bw-security-analysis/mlx-env/bin/python -m mlx_vlm.server
              │    OpenAI 兼容 /v1/chat/completions（图在前的消息格式）
              └─ Windows/Linux: Ollama HTTP（127.0.0.1:11434，keep_alive 空闲卸载）

生命周期（引用计数 + 30s 空闲释放，热启动复用）：
  acquire(client_id) → 引用+1（无实例则启动；starting 并发请求等同一事件）
  extract(...)       → 推理（刷新 last_active）
  close(client_id)   → 引用-1
  reaper 协程每 5s：clients 空 AND 距最后活动 > 30s AND 非 idle → 释放
  MCP 被 SIGKILL 忘 close 的兜底：psutil 检测 client pid 死亡 → 清引用

并发安全：状态变更全走单把 asyncio.Lock（idle→starting→ready→stopping
串行化）；推理不持锁（HTTP 转发）。

孤儿复用：控制台被 kill 后 MLX 子进程存活（start_new_session 独立进程组）。
pid 文件 + 健康探测 → 存活孤儿直接复用（省一次模型加载），死孤儿清理。
"""
from __future__ import annotations

import asyncio
import os
import platform
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import psutil

from config import DATA_DIR

MLX_ENV_PYTHON = Path(DATA_DIR) / "mlx-env" / "bin" / "python"

IDLE_RELEASE_SEC = 30      # 引用归零后的热启动复用窗口
REAPER_INTERVAL_SEC = 5    # 后台清理协程周期
STARTUP_TIMEOUT_SEC = 90   # MLX 子进程就绪超时（含模型加载）
EXTRACT_TIMEOUT_SEC = 180  # 单次识图超时

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_MODEL = "glm-ocr"

STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_READY = "ready"
STATE_STOPPING = "stopping"


@dataclass
class OcrStatus:
    """OCR 服务状态快照（GET /api/ocr/status 与模型页）。"""
    backend: str                  # mlx / ollama
    state: str                    # idle / starting / ready / stopping
    clients: int
    idle_release_sec: int
    last_activity_at: float | None
    error: str | None
    mlx_env_ready: bool
    model_cached: bool


class OcrService:
    """glm-ocr 推理服务（模块级单例 ocr_service）。

    MLX 分支持有子进程；Ollama 分支无常驻进程（keep_alive 语义托管给 Ollama）。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state: str = STATE_IDLE
        self._ready_event: asyncio.Event | None = None
        self._subprocess: subprocess.Popen | None = None
        self._sub_port: int | None = None
        self._sub_model: str = ""
        self._clients: dict[str, float] = {}       # client_id("pid:start_time") → last_seen
        self._last_activity_at: float = 0.0
        self._error: str = ""
        self._reaper_task: asyncio.Task | None = None
        self._orphan_adopted: bool = False
        self._http = httpx.AsyncClient(timeout=EXTRACT_TIMEOUT_SEC)

    # ─── 公开 API（routes/ocr.py 调用） ───────────────────

    async def acquire(self, pid: int, start_time: float) -> None:
        """引用+1。无实例则启动（starting 并发等待同一事件，单飞不重复 spawn）。"""
        cid = self._client_id(pid, start_time)
        async with self._lock:
            self._ensure_reaper()
            self._clients[cid] = time.time()
            self._last_activity_at = time.time()
            if self._backend() == "ollama":
                return  # Ollama 路径无常驻子进程
            if self._state == STATE_READY:
                return
            if self._state == STATE_STOPPING:
                while self._state == STATE_STOPPING:
                    await asyncio.sleep(0.2)      # 等停止完成再重启
            if self._state == STATE_IDLE:
                self._state = STATE_STARTING
                await self._start_mlx_locked()
                event = self._ready_event
            else:                                  # starting：搭车等同一事件
                event = self._ready_event
        if event is not None:
            await event.wait()
            async with self._lock:
                if self._error:
                    await self._cleanup_failed_start_locked()
                    raise RuntimeError(self._error)
                self._state = STATE_READY

    async def extract(self, image_b64: str, prompt: str) -> str:
        """识图（不持锁，可并发转发）。自动记录活跃时间。"""
        self._last_activity_at = time.time()
        if self._backend() == "ollama":
            if not self._ollama_available():
                raise RuntimeError("Ollama 不可用或未拉取 glm-ocr（控制台模型页可下载）")
            return await self._extract_ollama(image_b64, prompt)
        # MLX：必须 ready（acquire 已保证；防御性再查）
        async with self._lock:
            if self._state != STATE_READY or self._sub_port is None:
                raise RuntimeError("OCR 服务未就绪（需先 acquire）")
            port, model = self._sub_port, self._sub_model
        payload = {
            "model": model,  # 必须传启动加载的完整路径（别名会触发 HF 仓库解析 400）
            "temperature": 0.0,
            "max_tokens": 4096,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text",
                     "text": prompt or "Extract all text from this image. Output text only."},
                ],
            }],
        }
        r = await self._http.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    async def close(self, pid: int, start_time: float) -> None:
        """引用-1。归零后由 reaper 在空闲窗口后释放（热启动复用）。"""
        cid = self._client_id(pid, start_time)
        async with self._lock:
            self._clients.pop(cid, None)

    async def force_release(self) -> None:
        """强制释放（前端模型页停止按钮）。"""
        async with self._lock:
            self._clients.clear()
            if self._backend() == "mlx":
                await self._stop_locked()
            else:
                await self._ollama_unload()

    def status(self) -> OcrStatus:
        """状态快照。"""
        alive = sum(1 for cid in self._clients if self._client_alive(cid))
        return OcrStatus(
            backend=self._backend(),
            state=self._state,
            clients=alive,
            idle_release_sec=IDLE_RELEASE_SEC,
            last_activity_at=self._last_activity_at or None,
            error=self._error or None,
            mlx_env_ready=MLX_ENV_PYTHON.exists(),
            model_cached=(self._find_mlx_model() is not None) if self._backend() == "mlx"
                         else self._ollama_available(),
        )

    # ─── 后台清理 ─────────────────────────────────────────

    def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.get_running_loop().create_task(self._reaper_loop())

    async def _reaper_loop(self) -> None:
        """周期清理：死 client 引用 + 空闲释放。异常绝不自杀。"""
        while True:
            await asyncio.sleep(REAPER_INTERVAL_SEC)
            try:
                async with self._lock:
                    dead = [cid for cid in self._clients if not self._client_alive(cid)]
                    for cid in dead:
                        self._clients.pop(cid, None)
                    if (self._state == STATE_READY
                            and not self._clients
                            and self._last_activity_at > 0
                            and time.time() - self._last_activity_at > IDLE_RELEASE_SEC):
                        if self._backend() == "mlx":
                            await self._stop_locked()
                        else:
                            await self._ollama_unload()
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    # ─── MLX 分支 ─────────────────────────────────────────

    async def _start_mlx_locked(self) -> None:
        """启动 MLX 子进程（调用方必须持锁，state=starting）。先尝试孤儿复用。"""
        if not MLX_ENV_PYTHON.exists():
            self._error = f"MLX 环境缺失: {MLX_ENV_PYTHON}（控制台模型页可安装）"
            raise RuntimeError(self._error)
        model = self._find_mlx_model()
        if not model:
            self._error = "GLM-OCR 模型未缓存（控制台模型页可下载）"
            raise RuntimeError(self._error)

        self._ready_event = asyncio.Event()
        self._error = ""
        pid_file = Path(DATA_DIR) / ".ocr-mlx.pid"

        # 孤儿复用：控制台重启后子进程存活 → 健康探测通过直接接管
        if pid_file.exists():
            if await self._adopt_orphan(pid_file, model):
                return
        # 正常 spawn
        port = self._free_port()
        proc = subprocess.Popen(
            [str(MLX_ENV_PYTHON), "-m", "mlx_vlm.server",
             "--model", model, "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,   # 独立进程组——控制台重启不连带杀（孤儿可复用）
        )
        self._subprocess, self._sub_port, self._sub_model = proc, port, model
        self._orphan_adopted = False
        pid_file.write_text(f"{proc.pid}\n{port}\n")
        asyncio.get_running_loop().create_task(self._wait_mlx_ready(proc, port))

    async def _adopt_orphan(self, pid_file: Path, model: str) -> bool:
        """pid 文件 + 健康探测 → 复用存活孤儿；死孤儿清理。"""
        try:
            raw = pid_file.read_text().strip().splitlines()
            opid, oport = int(raw[0]), int(raw[1])
        except (ValueError, IndexError, OSError):
            return False
        if opid > 0 and await self._probe(oport):
            try:
                alive = psutil.Process(opid).is_running()
            except psutil.Error:
                alive = False
            if alive:
                self._subprocess, self._sub_port = None, oport
                self._sub_model, self._orphan_adopted = model, True
                self._ready_event.set()
                return True
        try:
            os.kill(opid, 9)   # 端口不通/进程死 → 清死孤儿（防端口占位）
        except (ProcessLookupError, OSError):
            pass
        return False

    async def _wait_mlx_ready(self, proc: subprocess.Popen, port: int) -> None:
        """后台等 MLX 子进程就绪（health 200/503）；超时/退出置错并唤醒等待者。"""
        deadline = time.time() + STARTUP_TIMEOUT_SEC
        async with httpx.AsyncClient(timeout=2.0) as hc:
            while time.time() < deadline:
                if proc.poll() is not None:
                    self._error = f"MLX 子进程退出 code={proc.returncode}"
                    break
                if await self._probe(port):
                    break
                await asyncio.sleep(0.5)
            else:
                self._error = "MLX 子进程就绪超时"
        self._ready_event.set()

    @staticmethod
    async def _probe(port: int) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as hc:
                r = await hc.get(f"http://127.0.0.1:{port}/health")
                return r.status_code in (200, 503)
        except httpx.HTTPError:
            return False

    async def _stop_locked(self) -> None:
        """释放 MLX 分支（调用方必须持锁）。kill 子进程 → 内存立即归还。"""
        self._state = STATE_STOPPING
        proc, self._subprocess = self._subprocess, None
        self._sub_port = None
        self._last_activity_at = 0.0
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 15)  # 进程组 SIGTERM
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, OSError):
                pass
        else:
            # 复用的孤儿（无 Popen 句柄）→ 经 pid 文件直接 kill
            pid_file = Path(DATA_DIR) / ".ocr-mlx.pid"
            try:
                os.kill(int(pid_file.read_text().strip().splitlines()[0]), 15)
            except (ValueError, IndexError, OSError):
                pass
            pid_file.unlink(missing_ok=True)
        self._state = STATE_IDLE

    async def _cleanup_failed_start_locked(self) -> None:
        """启动失败的收尾（持锁调用）。"""
        self._state = STATE_IDLE
        proc, self._subprocess = self._subprocess, None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, OSError):
                pass

    @staticmethod
    def _find_mlx_model() -> str | None:
        """HF 缓存定位 GLM-OCR-4bit snapshot 目录。"""
        hub = Path.home() / ".cache" / "huggingface" / "hub"
        for d in hub.glob("models--mlx-community--GLM-OCR-4bit/snapshots/*"):
            if (d / "model.safetensors").exists() or (d / "model.safetensors.index.json").exists():
                return str(d)
        return None

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    # ─── Ollama 分支（win/linux/intel-mac） ───────────────

    def _ollama_available(self) -> bool:
        try:
            r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3.0)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return any(n.split(":")[0] == OLLAMA_MODEL for n in names)
        except (httpx.HTTPError, ValueError):
            return False

    async def _extract_ollama(self, image_b64: str, prompt: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt or "Extract all text from this image. Output text only.",
            "images": [image_b64],
            "stream": False,
            "keep_alive": f"{IDLE_RELEASE_SEC}s",  # Ollama 原生空闲卸载窗口
            "options": {"temperature": 0},
        }
        r = await self._http.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "")

    async def _ollama_unload(self) -> None:
        """Ollama 显式卸载（keep_alive=0；不动 Ollama 进程本身）。"""
        try:
            await self._http.post(f"{OLLAMA_BASE}/api/generate",
                                  json={"model": OLLAMA_MODEL, "keep_alive": 0, "prompt": ""},
                                  timeout=5.0)
        except httpx.HTTPError:
            pass

    # ─── 工具 ─────────────────────────────────────────────

    @staticmethod
    def _backend() -> str:
        """平台分支：mlx / ollama。"""
        if platform.system() == "Darwin" and os.uname().machine == "arm64":
            return "mlx"
        return "ollama"

    @staticmethod
    def _client_id(pid: int, start_time: float) -> str:
        return f"{pid}:{start_time}"

    @staticmethod
    def _client_alive(client_id: str) -> bool:
        """client pid 存活检测（MCP SIGKILL 兜底）。id 格式错视为死。"""
        try:
            pid_s, _, st_s = str(client_id).partition(":")
            pid = int(pid_s)
            st = float(st_s) if st_s else 0.0
            p = psutil.Process(pid)
            return p.is_running() and (st == 0 or abs(p.create_time() - st) < 1.0)
        except (ValueError, psutil.Error):
            return False


# 模块级单例 + 兼容委托（routes/ocr.py、model_assets 消费）
ocr_service = OcrService()

# 模块级 async 入口委托
acquire = ocr_service.acquire
extract = ocr_service.extract
close = ocr_service.close
force_release = ocr_service.force_release


def status() -> OcrStatus:
    return ocr_service.status()
