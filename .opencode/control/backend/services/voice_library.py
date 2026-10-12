"""音色库（TTS zero-shot 参考音频管理——内置 git 资产 + 用户运行时双源）。

双源设计:
  • 内置音色: backend/assets/voices/（随 git 走——节点 update-restart 自动同步），
    清单 voices.json 只读。
  • 用户音色: $OPENSECURITY_HOME/voices/（上传落盘，不污染 git 目录），
    清单 user_voices.json 可写。

不提供删除（引用悬空防护——调用方配置引用音色 id，误删将导致合成报错）。
新增来源: 控制台上传（POST /api/tts/voices）或直接投放文件+清单。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_DIR = _BACKEND_ROOT / "assets" / "voices"
BUILTIN_MANIFEST = BUILTIN_DIR / "voices.json"

VOICE_ID_MAX = 64
WAV_MAX_BYTES = 8 * 1024 * 1024  # 8MB 上限（30s 24kHz PCM16 ≈ 1.5MB——余量充分）
REF_TEXT_MAX = 600


class VoiceError(ValueError):
    """音色库操作失败（校验/IO 统一面——路由层转 4xx）。"""


@dataclass(frozen=True)
class VoiceAsset:
    """音色资产（wav + 逐字稿成对——zero-shot 克隆的两要素）。"""
    id: str
    name: str
    gender: str            # "female" | "male"
    description: str
    wav: str               # 相对各自源目录的文件名
    ref_text: str          # 参考音频逐字稿（不一致会显著劣化克隆质量）
    default_speed: float = 1.0
    source: str = "builtin"  # builtin | user（前端区分展示/上传者不可改内置）

    def resolved_wav(self, library: "VoiceLibrary") -> Path:
        base = library.user_dir if self.source == "user" else BUILTIN_DIR
        return base / self.wav


class VoiceLibrary:
    """音色库（双源清单加载/查询/上传入库，全局单例，线程安全）。"""

    _instance: "VoiceLibrary | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "VoiceLibrary":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "VoiceLibrary":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def _init_once(self) -> None:
        import os
        home = Path(os.environ.get("OPENSECURITY_HOME",
                                   str(Path.home() / "bw-security-analysis")))
        self.user_dir = home / "voices"
        self.user_manifest = self.user_dir / "user_voices.json"
        self._lock = threading.Lock()

    # ── 查询 ─────────────────────────────────────────

    def list_voices(self) -> list[VoiceAsset]:
        """全部音色（内置在前，用户在后——前端默认排序即展示序）。"""
        return self._load_builtin() + self._load_user()

    def get(self, voice_id: str) -> VoiceAsset | None:
        for v in self.list_voices():
            if v.id == voice_id:
                return v
        return None

    def default_voice(self) -> VoiceAsset:
        """默认音色（清单第一条;空清单=配置错误——启动资产已内置不会发生）。"""
        voices = self.list_voices()
        if not voices:
            raise VoiceError("音色库为空（内置资产缺失——检查 assets/voices/）")
        return voices[0]

    # ── 上传入库 ─────────────────────────────────────

    def add_user_voice(self, wav_bytes: bytes, name: str, gender: str,
                       description: str, ref_text: str) -> VoiceAsset:
        """用户音色入库: 校验 → 重采样 24kHz 单声道 → 落盘 + 清单追加。

        wav_bytes: 原始音频字节（wav/flac 可读格式; 服务端统一转 24kHz PCM16 wav）。
        """
        name = name.strip()
        ref_text = ref_text.strip()
        gender = gender.strip().lower()
        if not name or len(name) > 40:
            raise VoiceError("音色名必填且 ≤40 字符")
        if gender not in ("female", "male"):
            raise VoiceError("gender 必须为 female/male")
        if not ref_text or len(ref_text) > REF_TEXT_MAX:
            raise VoiceError(f"逐字稿必填且 ≤{REF_TEXT_MAX} 字符")
        if not wav_bytes or len(wav_bytes) > WAV_MAX_BYTES:
            raise VoiceError(f"音频文件为空或超过 {WAV_MAX_BYTES // 1024 // 1024}MB 上限")
        voice_id = self._make_id(name)
        with self._lock:
            if self.get(voice_id) is not None:
                raise VoiceError(f"音色 id 冲突: {voice_id}（同名已存在）")
            converted = self._convert_audio(wav_bytes)
            duration = self._wav_duration(converted)
            if not 2.0 <= duration <= 30.0:
                raise VoiceError(f"音频时长 {duration:.1f}s 超出 2-30s 有效区间"
                                 "（过短克隆失真/过长拖慢每次合成）")
            self.user_dir.mkdir(parents=True, exist_ok=True)
            (self.user_dir / f"{voice_id}.wav").write_bytes(converted)
            asset = VoiceAsset(
                id=voice_id, name=name, gender=gender,
                description=description.strip()[:200] or f"用户上传（{duration:.0f}s）",
                wav=f"{voice_id}.wav", ref_text=ref_text,
                default_speed=1.0, source="user",
            )
            manifest = self._load_user()
            manifest.append(asset)
            self._save_user_manifest(manifest)
            logger.info("[voices] 用户音色入库: %s (%s, %.1fs)", voice_id, gender, duration)
            return asset

    # ── 内部 ─────────────────────────────────────────

    def _make_id(self, name: str) -> str:
        """音色 id: 中文名转拼音不可靠——统一用 name 的可读 slug + 冲突时序号。
        slug 规则: 中文保留（id 允许 unicode）; 去空白/路径分隔符。"""
        slug = re.sub(r"[\s/\\:*\?\"<>|]+", "_", name)[:VOICE_ID_MAX]
        return slug or "voice"

    def _convert_audio(self, wav_bytes: bytes) -> bytes:
        """音频 → 24kHz 单声道 PCM16 wav（推理端采样率定型）。

        soundfile 解码（wav/flac/ogg 等）+ numpy 线性插值重采样——均为轻依赖;
        读取失败（损坏/非音频）统一 VoiceError。
        """
        import io
        try:
            import numpy as np
            import soundfile as sf
            data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportUnknownArgumentType] —— soundfile 无存根
            if data.ndim > 1:  # 立体声 → 单声道
                data = data.mean(axis=1)  # pyright: ignore[reportUnknownMemberType] —— soundfile 无存根
            if sr != 24000:  # 线性插值重采样（音色参考场景足够）
                n_out = int(len(data) * 24000 / sr)
                idx = np.linspace(0.0, float(len(data) - 1), n_out)
                data = np.interp(idx, np.arange(len(data)), data).astype(np.float32)
            if data.size == 0:
                raise VoiceError("音频内容为空（解码后无样本）")
            buf = io.BytesIO()
            sf.write(buf, data, 24000, subtype="PCM_16", format="WAV")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] —— soundfile 无存根
            return buf.getvalue()
        except VoiceError:
            raise
        except Exception as e:  # noqa: BLE001 —— 解码失败统一面
            raise VoiceError(f"音频解码失败（支持 wav/flac/ogg 等格式）: {e}") from e

    @staticmethod
    def _wav_duration(wav_bytes: bytes) -> float:
        import io
        import soundfile as sf
        info = sf.info(io.BytesIO(wav_bytes))  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportUnknownArgumentType] —— soundfile 无存根
        dur = float(info.duration)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] —— soundfile 无存根
        return dur

    def _load_builtin(self) -> list[VoiceAsset]:
        return self._load_manifest(BUILTIN_MANIFEST, "builtin")

    def _load_user(self) -> list[VoiceAsset]:
        if not self.user_manifest.is_file():
            return []
        return self._load_manifest(self.user_manifest, "user")

    @staticmethod
    def _load_manifest(path: Path, source: str) -> list[VoiceAsset]:
        from typing import cast

        if not path.is_file():
            return []
        try:
            raw = cast("list[object]",
                       json.loads(path.read_text(encoding="utf-8")))
            out: list[VoiceAsset] = []
            for item in raw:
                entry = cast("dict[str, object]", item)
                vid, name, wav = entry.get("id"), entry.get("name"), entry.get("wav")
                # 必键三件缺失/非 str → 条目损坏跳过（不清空整库——部分可用好过全无）
                if not (isinstance(vid, str) and vid
                        and isinstance(name, str) and name
                        and isinstance(wav, str) and wav):
                    logger.warning("[voices] 清单条目缺关键字段，跳过: %s", path)
                    continue
                gender = entry.get("gender", "female")
                description = entry.get("description", "")
                ref_text = entry.get("ref_text", "")
                speed = entry.get("default_speed", 1.0)
                out.append(VoiceAsset(
                    id=vid, name=name,
                    gender=gender if isinstance(gender, str) else "female",
                    description=description if isinstance(description, str) else "",
                    wav=wav, ref_text=ref_text if isinstance(ref_text, str) else "",
                    default_speed=float(speed) if isinstance(speed, (int, float)) else 1.0,
                    source=source,
                ))
            return out
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("[voices] 清单损坏 %s: %s", path, e)
            return []

    def _save_user_manifest(self, voices: list[VoiceAsset]) -> None:
        from dataclasses import asdict as _asdict
        from typing import Any, cast as _cast
        rows = [_cast("dict[str, Any]", _asdict(a)) for a in voices]  # pyright: ignore[reportAny] —— asdict 存根 Any
        data = [{k: v for k, v in row.items()  # pyright: ignore[reportAny] —— JSON 序列化边界（Any 值域由 VoiceAsset 字段类型约束）
                 if k != "source"} for row in rows]
        self.user_manifest.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
