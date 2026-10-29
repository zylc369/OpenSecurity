#!/bin/zsh
# 本机 Kokoro 退役清理（模型缓存 + venv 包卸载）
set -euo pipefail
CACHE_DIR="$HOME/.cache/opensecurity/tts"
if [[ -d "$CACHE_DIR" ]]; then rm -rf "$CACHE_DIR" && echo "[clean] 已删: $CACHE_DIR"; else echo "[clean] 无缓存目录"; fi
VENV_PY="$HOME/bw-security-analysis/.venv/bin/python"
if [[ -x "$VENV_PY" ]] && "$VENV_PY" -c "import kokoro_onnx" 2>/dev/null; then
  uv pip uninstall --python "$VENV_PY" kokoro-onnx && echo "[clean] 主 venv 已卸 kokoro-onnx"
else
  echo "[clean] 主 venv 无 kokoro-onnx"
fi
echo "[clean] 完成"
