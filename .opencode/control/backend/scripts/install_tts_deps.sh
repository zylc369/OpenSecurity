#!/bin/zsh
# TTS 推理环境安装（独立 venv .venv-tts——与主 venv 完全隔离）
# 用法: ./install_tts_deps.sh [venv-dir]（默认 backend/.venv-tts）
# 幂等: 已存在的 venv 只补装缺失包; 重建加 --recreate
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # backend/
VENV_DIR="${1:-$HERE/.venv-tts}"
MIRROR="${TTS_PIP_MIRROR:-https://mirrors.aliyun.com/pypi/simple/}"

echo "[tts-deps] venv: ${VENV_DIR}"
if [[ "${2:-}" == "--recreate" ]]; then rm -rf "$VENV_DIR"; fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  uv venv "$VENV_DIR" --python 3.12
fi
PY="${VENV_DIR}/bin/python"

# no-deps 组（声明依赖有死坑——见 requirements-tts.txt 注释）
uv pip install --python "$PY" --index-url "$MIRROR" --no-deps \
  "mlx-audio==0.2.10" "mlx-audio-plus==0.1.8" "mlx-lm==0.31.3"

# 常规依赖
uv pip install --python "$PY" --index-url "$MIRROR" \
  "mlx==0.32.3" torch "numpy<2" "scipy==1.17.1" soundfile sounddevice \
  einops librosa tiktoken huggingface_hub transformers

# 验证 import 链（webrtcvad 缺失不影响）
"$PY" -c "from mlx_audio.tts.models.cosyvoice3 import cosyvoice3; from mlx_audio.tts.generate import load_audio; print('[tts-deps] import 链 OK')"
echo "[tts-deps] 完成: ${VENV_DIR}"
