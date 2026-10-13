#!/bin/zsh
# TTS torch 引擎环境（CosyVoice 官方栈——独立 venv .venv-cosy-tts + repo vendor）
# 产出 cv3_full_female 同源品质（上品验收）。依赖踩坑已固化（勿改 pin 除非重验）。
# 用法: ./install_tts_torch.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # backend/
VENV_DIR="$HERE/.venv-cosy-tts"
REPO_DIR="$HERE/third_party/CosyVoice"
MIRROR="${TTS_PIP_MIRROR:-https://mirrors.aliyun.com/pypi/simple/}"
echo "[tts-torch] venv: ${VENV_DIR} | repo: ${REPO_DIR}"

# uv 探测（服务环境 PATH 兜底）
UV_BIN="$(command -v uv 2>/dev/null || true)"
if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; fi
if [[ -z "$UV_BIN" && -x /opt/homebrew/bin/uv ]]; then UV_BIN=/opt/homebrew/bin/uv; fi

# 1. CosyVoice repo（浅克隆 + Matcha submodule; 已在则跳过）
if [[ ! -d "$REPO_DIR/cosyvoice" ]]; then
  mkdir -p "$HERE/third_party"
  git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git "$REPO_DIR"
  git -C "$REPO_DIR" submodule update --init --depth 1 third_party/Matcha-TTS
fi

# 2. venv + 依赖（踩坑固化: scipy 1.17.1 修 macOS dyld; numpy<2;
#    setuptools<81 保 pkg_resources; whisper 走 no-build-isolation;
#    grpc/tensorrt/gradio 等 webui/训练件剔除——推理不需要）
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if [[ -n "$UV_BIN" ]]; then "$UV_BIN" venv "$VENV_DIR" --python 3.12
  else python3 -m venv "$VENV_DIR"; fi
fi
PY="${VENV_DIR}/bin/python"
pip_install() {
  if [[ -n "$UV_BIN" ]]; then "$UV_BIN" pip install --python "$PY" --index-url "$MIRROR" "$@"
  else "$PY" -m pip install --quiet --index-url "$MIRROR" "$@"; fi
}
pip_install "torch==2.3.1" "torchaudio==2.3.1" "scipy==1.17.1" "numpy<2" "setuptools<81"
pip_install conformer==0.3.2 diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 \
  inflect==7.3.1 librosa==0.10.2 lightning==2.2.4 modelscope networkx omegaconf==2.3.0 \
  onnx==1.16.0 onnxruntime==1.18.1 protobuf==4.25 rich soundfile==0.12.1 \
  transformers==4.51.3 x-transformers==2.11.24 wetext gdown wget matplotlib pyarrow==16.1.0
pip_install --no-build-isolation openai-whisper==20231117
"$PY" -c "import sys; sys.path.insert(0, '$REPO_DIR'); sys.path.insert(0, '$REPO_DIR/third_party/Matcha-TTS'); from cosyvoice.cli.cosyvoice import AutoModel; print('[tts-torch] import 链 OK')"
echo "[tts-torch] 完成"
