#!/bin/zsh
# TTS 依赖安装（主 venv——vendor/tts-funaudio 引擎所需; 模型另见资产下载）
# 实测栈: torch 2.14 + transformers 5.17 + numpy 2.5（Python 3.13 主 venv）
# 用法: ./install_tts_torch.sh [venv-python]（默认 $OPENSECURITY_HOME/.venv/bin/python）
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"           # backend/
ROOT="$(cd "$HERE/../.." && pwd)"                  # 仓库根（vendor 所在）
VENV_PY="${1:-$HOME/bw-security-analysis/.venv/bin/python}"
MIRROR="${TTS_PIP_MIRROR:-https://mirrors.aliyun.com/pypi/simple/}"
echo "[tts-deps] venv python: ${VENV_PY} | vendor: ${ROOT}/vendor/tts-funaudio"

[[ -x "$VENV_PY" ]] || { echo "[tts-deps][ERROR] venv python 不存在: $VENV_PY"; exit 1; }

"$VENV_PY" -m pip install --quiet --index-url "$MIRROR" \
  HyperPyYAML onnxruntime wetext modelscope conformer diffusers \
  "hydra-core" inflect lightning omegaconf "x-transformers" \
  torchaudio torchcodec gdown wget matplotlib pyworld \
  "setuptools<81"   # pkg_resources（pyworld/processor 运行时 import; ≥81 已移除

# 主 venv 缺 torch 时兜底（一般已就绪）
"$VENV_PY" -c "import torch" 2>/dev/null || \
  "$VENV_PY" -m pip install --quiet --index-url "$MIRROR" torch

# vendor 引擎就位（submodule 或直接克隆 fork——两形态都可）
if [[ ! -d "$ROOT/vendor/tts-funaudio/cosyvoice" ]]; then
  git clone -q --depth 1 --recurse-submodules \
    https://github.com/zylc369/tts-funaudio-cozyvoice3.git "$ROOT/vendor/tts-funaudio" \
    || git -C "$ROOT" submodule update --init --depth 1 vendor/tts-funaudio
fi

# 验证 import 链（模型无关——秒级）
cd "$ROOT/vendor/tts-funaudio"
"$VENV_PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice3
print('[tts-deps] import 链 OK')"
echo "[tts-deps] 完成"
