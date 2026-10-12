#!/bin/zsh
# TTS 推理环境安装（独立 venv .venv-tts——与主 venv 完全隔离）
# 用法: ./install_tts_deps.sh [venv-dir]（默认 backend/.venv-tts）
# 幂等: 已存在的 venv 只补装缺失包; 重建加 --recreate
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # backend/
VENV_DIR="${1:-$HERE/.venv-tts}"
MIRROR="${TTS_PIP_MIRROR:-https://mirrors.aliyun.com/pypi/simple/}"
echo "[tts-deps] venv: ${VENV_DIR} | PATH=${PATH}"

# uv 探测（launchd/服务环境的 PATH 常缺失用户级 bin——多路径兜底）
UV_BIN="$(command -v uv 2>/dev/null || true)"
if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; fi
if [[ -z "$UV_BIN" && -x /opt/homebrew/bin/uv ]]; then UV_BIN=/opt/homebrew/bin/uv; fi
echo "[tts-deps] uv: ${UV_BIN:-无（pip fallback）}"
if [[ "${2:-}" == "--recreate" ]]; then rm -rf "$VENV_DIR"; fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if [[ -n "$UV_BIN" ]]; then "$UV_BIN" venv "$VENV_DIR" --python 3.12
  else python3 -m venv "$VENV_DIR"; fi
fi
PY="${VENV_DIR}/bin/python"

pip_install() {  # uv 优先; 无 uv → venv pip（阿里镜像）——依赖声明同 requirements-tts.txt
  if [[ -n "$UV_BIN" ]]; then "$UV_BIN" pip install --python "$PY" --index-url "$MIRROR" "$@"
  else "$PY" -m pip install --quiet --index-url "$MIRROR" "$@"; fi
}

# no-deps 组（声明依赖有死坑——见 requirements-tts.txt 注释）
pip_install --no-deps "mlx-audio==0.2.10" "mlx-audio-plus==0.1.8" "mlx-lm==0.31.3"

# 常规依赖
pip_install "mlx==0.32.3" torch "numpy<2" "scipy==1.17.1" soundfile sounddevice \
  einops librosa tiktoken huggingface_hub transformers

# 验证 import 链（webrtcvad 缺失不影响）
"$PY" -c "from mlx_audio.tts.models.cosyvoice3 import cosyvoice3; from mlx_audio.tts.generate import load_audio; print('[tts-deps] import 链 OK')"
echo "[tts-deps] 完成: ${VENV_DIR}"
