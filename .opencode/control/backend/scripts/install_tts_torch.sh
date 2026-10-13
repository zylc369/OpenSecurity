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
# 全程 stdlib venv + pip（uv 的 index 解析对老版本 torch 不可靠——PyPI 已
# 下架 <2.9，uv 的版本协商会漏掉 --index-url 指定的自定义源）
# 版本校验: torch wheel 是 cp312——venv 必须 3.12（旧 venv 可能是 uv 建的 3.13）
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  VV="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo none)"
  if [[ "$VV" != "3.12" ]]; then
    echo "[tts-torch] venv 版本 $VV ≠ 3.12 → 重建"
    rm -rf "$VENV_DIR"
  fi
fi
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  # 3.12 定位: 系统优先 → uv 管理的（uv python find）→ 无则报错
  P312="$(command -v python3.12 || true)"
  if [[ -z "$P312" && -n "$UV_BIN" ]]; then
    P312="$("$UV_BIN" python find 3.12 2>/dev/null || true)"
  fi
  if [[ -z "$P312" ]]; then
    echo "[tts-torch][ERROR] 无 Python 3.12（torch wheel 为 cp312）——安装 python3.12 后重试"; exit 1
  fi
  "$P312" -m venv "$VENV_DIR"
fi
PY="${VENV_DIR}/bin/python"
"$PY" -m pip install --quiet --upgrade pip --index-url "$MIRROR"
pip_install() {
  "$PY" -m pip install --quiet --index-url "$MIRROR" "$@"
}
# torch/torchaudio wheel 直 URL 安装（PyPI 下架 <2.9、镜像缺 mac arm、
# pip/uv 的 index 协商在部分网络下漏源——直 URL 零协商零歧义）
"$PY" -m pip install --quiet \
  "https://download.pytorch.org/whl/cpu/torch-2.3.1-cp312-none-macosx_11_0_arm64.whl" \
  "https://download.pytorch.org/whl/cpu/torchaudio-2.3.1-cp312-cp312-macosx_11_0_arm64.whl"
pip_install "scipy==1.17.1" "numpy<2" "setuptools<81"
pip_install conformer==0.3.2 diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 \
  inflect==7.3.1 librosa==0.10.2 lightning==2.2.4 modelscope networkx omegaconf==2.3.0 \
  onnx==1.16.0 onnxruntime==1.18.1 protobuf==4.25 rich soundfile==0.12.1 \
  transformers==4.51.3 x-transformers==2.11.24 wetext gdown wget matplotlib pyarrow==16.1.0 \
  pyworld==0.3.4
pip_install --no-build-isolation openai-whisper==20231117
"$PY" -c "import sys; sys.path.insert(0, '$REPO_DIR'); sys.path.insert(0, '$REPO_DIR/third_party/Matcha-TTS'); from cosyvoice.cli.cosyvoice import AutoModel; print('[tts-torch] import 链 OK')"
echo "[tts-torch] 完成"
