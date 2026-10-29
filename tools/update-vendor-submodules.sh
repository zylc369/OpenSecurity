#!/usr/bin/env bash
# tools/update-vendor-submodules.sh
# 拉取所有 vendor 子模块（含任意层级嵌套子模块）的最新代码，然后提交并推送到远程。
#
# 更新策略（两段式，保证工作区干净、状态可复现）：
#   1. 顶层子模块   → git submodule update --remote --merge
#      把每个顶层子模块推进到 .gitmodules 中配置的 branch 最新提交。
#   2. 嵌套子模块   → git submodule foreach 'git submodule update --init --recursive'
#      把每个顶层子模块内部的嵌套子模块同步到「该子模块当前 HEAD 记录的指针」，
#      避免「顶层指针更新了、嵌套子模块还停在旧指针」导致的 dirty 状态。
#
# 提交语义：主仓库只记录顶层子模块指针；嵌套子模块跟随各自父提交记录。
# 提交后自动推送到远程（git push），无需额外参数。
#
# 用法：
#   ./tools/update-vendor-submodules.sh            拉取、提交并推送
#   ./tools/update-vendor-submodules.sh --no-commit  仅拉取，不提交也不推送
#   ./tools/update-vendor-submodules.sh -h         查看帮助
#
# 退出码：0 成功；1 参数错误 / 环境异常 / 子模块有未提交改动。

set -euo pipefail

# ------------------------------------------------------------------ 日志
# 自带轻量日志，不 source shell/library/log.sh，保证本基础设施脚本独立可运行。
log_info()  { printf '[+] %s\n' "$*"; }
log_warn()  { printf '[!] %s\n' "$*" >&2; }
log_error() { printf '[x] %s\n' "$*" >&2; }

# ------------------------------------------------------------------ 参数
DO_COMMIT=1

usage() {
    cat <<'EOF'
tools/update-vendor-submodules.sh — 拉取所有 vendor 子模块（含嵌套）最新代码并提交、推送

用法:
  tools/update-vendor-submodules.sh               拉取、提交并推送到远程
  tools/update-vendor-submodules.sh --no-commit   仅拉取，不提交也不推送（改动留在工作区）
  tools/update-vendor-submodules.sh -h|--help     显示本帮助

说明:
  顶层子模块推进到各自分支最新（update --remote --merge），
  嵌套子模块同步到父提交记录的指针（update --init --recursive）。
  若顶层子模块工作区有未提交改动，将中止执行。
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-commit) DO_COMMIT=0 ;;
        -h|--help)   usage; exit 0 ;;
        *) log_error "未知参数: $1"; usage >&2; exit 1 ;;
    esac
    shift
done

# ------------------------------------------------------------------ 环境
REPO_ROOT="${REPO_ROOT:-"$(git rev-parse --show-toplevel 2>/dev/null || true)"}"
if [[ -z "${REPO_ROOT:-}" ]]; then
    log_error "当前不在 git 仓库中"
    exit 1
fi
cd "$REPO_ROOT"

if [[ ! -f .gitmodules ]]; then
    log_warn "仓库无 .gitmodules，不存在子模块，无需操作"
    exit 0
fi

# 收集所有顶层子模块路径（从 .gitmodules 读取，确保与配置一致）
SM_PATHS=()
while IFS= read -r p; do
    [[ -n "$p" ]] && SM_PATHS+=("$p")
done < <(git config -f .gitmodules --get-regexp '\.path$' | awk '{print $2}')

if [[ ${#SM_PATHS[@]} -eq 0 ]]; then
    log_warn ".gitmodules 未配置任何子模块路径"
    exit 0
fi

log_info "仓库根目录: $REPO_ROOT"
log_info "顶层子模块 (${#SM_PATHS[@]}): ${SM_PATHS[*]}"

# ------------------------------------------------------------------ 前置检查
# 顶层子模块工作区必须干净，否则 update --remote --merge 可能产生冲突。
log_info "检查顶层子模块工作区是否干净..."
dirty=0
for p in "${SM_PATHS[@]}"; do
    if ! git -C "$p" diff --quiet --exit-code 2>/dev/null \
       || ! git -C "$p" diff --cached --quiet --exit-code 2>/dev/null; then
        log_error "子模块 '$p' 存在未提交改动，请先处理（git -C '$p' status）后再运行本脚本"
        dirty=1
    fi
done
[[ $dirty -eq 0 ]] || exit 1

# ------------------------------------------------------------------ 第一段：顶层子模块追分支最新
log_info "拉取顶层子模块到各自分支最新 (--remote --merge)..."
git submodule update --remote --merge

# ------------------------------------------------------------------ 第二段：同步嵌套子模块到父提交记录
log_info "同步各顶层子模块内部的嵌套子模块 (update --init --recursive)..."
# 顶层 foreach（不递归），在每个顶层子模块内部递归初始化并同步嵌套子模块。
git submodule foreach \
    'git submodule update --init --recursive' \
    || { log_error "嵌套子模块同步失败，请检查上方输出"; exit 1; }

# ------------------------------------------------------------------ 计算变化
CHANGED=()
for p in "${SM_PATHS[@]}"; do
    # git diff --quiet 返回非 0 表示该路径有未暂存变化（即指针被更新）
    if ! git diff --quiet -- "$p"; then
        CHANGED+=("$p")
    fi
done

if [[ ${#CHANGED[@]} -eq 0 ]]; then
    log_info "所有子模块均已是最新，无需提交"
    exit 0
fi

log_info "本次更新的顶层子模块 (${#CHANGED[@]}): ${CHANGED[*]}"

# ------------------------------------------------------------------ 提交
if [[ $DO_COMMIT -eq 0 ]]; then
    log_warn "--no-commit：已拉取最新代码，跳过提交（改动保留在工作区）"
    exit 0
fi

git add -- "${SM_PATHS[@]}"

# 生成提交信息：列出每个被更新子模块的新版本摘要
msg_file="$(mktemp)"
trap 'rm -f "$msg_file"' EXIT
{
    echo "vendor: bump submodules to latest"
    echo ""
    for p in "${CHANGED[@]}"; do
        name=$(basename "$p")
        short=$(git -C "$p" rev-parse --short HEAD)
        subject=$(git -C "$p" log -1 --format='%s')
        echo "- $name: $short ($subject)"
    done
    echo ""
    echo "Updated by tools/update-vendor-submodules.sh"
} > "$msg_file"

git commit -F "$msg_file"

# ------------------------------------------------------------------ 推送远程
log_info "推送到远程 (git push)..."
git push

# ------------------------------------------------------------------ 收尾校验
# 确保提交后工作区干净（顶层子模块无残留 dirty）
residual=()
while IFS= read -r p; do
    [[ -n "$p" ]] && residual+=("$p")
done < <(git status --porcelain | awk '/^ M / {print $2}')

if [[ ${#residual[@]} -gt 0 ]]; then
    log_warn "以下路径提交后仍有未暂存变化（可能含嵌套子模块本地改动）: ${residual[*]}"
fi

log_info "完成。提交已生成并推送到远程。"
