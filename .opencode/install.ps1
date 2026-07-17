# OpenSecurity 一键安装脚本 (Windows / PowerShell)
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File .opencode\install.ps1
#
# 功能:
#   1. 检测/安装 conda (Miniforge)
#   2. 创建 conda 虚拟环境
#   3. 安装全部 Python 依赖包（所有 agent 共用）
#   4. 安装 Playwright Chromium 浏览器
#   5. 检测 Docker + 启动 Neo4j 容器
#   6. 运行 detect_env.py 验证

$ErrorActionPreference = "Stop"

# ============================================================
# 配置
# ============================================================
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$DATA_DIR = Join-Path $env:USERPROFILE "bw-security-analysis"
$VENV_DIR = Join-Path $DATA_DIR ".venv"

# ============================================================
# 辅助函数
# ============================================================
function Write-Info  { param([string]$Msg) Write-Host "[OK]  $Msg" -ForegroundColor Green }
function Write-Warn2 { param([string]$Msg) Write-Host "[!]   $Msg" -ForegroundColor Yellow }
function Write-Fail  { param([string]$Msg) Write-Host "[X]   $Msg" -ForegroundColor Red }
function Write-Step  { param([int]$Num, [string]$Title) Write-Host "`n=== Step $Num/4: $Title ===" -ForegroundColor Cyan }

Write-Host ""
Write-Host "============================================================"
Write-Host "  OpenSecurity 一键安装 (Windows)"
Write-Host "============================================================"

# ============================================================
# Step 1: 检测 conda
# ============================================================
Write-Step 1 "检测 conda (Miniforge)"

$Conda = $null

# 1. PATH 里的 conda
try {
    $cmd = Get-Command conda -ErrorAction Stop
    $Conda = $cmd.Source
} catch {
    # 2. 常见安装路径
    $candidates = @(
        Join-Path $env:USERPROFILE "miniforge3\Scripts\conda.exe"
        Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            $Conda = $path
            break
        }
    }
}

if (-not $Conda) {
    Write-Fail "conda 未安装"
    Write-Host ""
    Write-Host "请先安装 Miniforge："
    Write-Host "  从 https://github.com/conda-forge/miniforge#download 下载 Windows 安装包"
    Write-Host "  或运行："
    Write-Host "    winget install CondaForge.Miniforge3"
    Write-Host ""
    Write-Host "安装后重新打开 PowerShell，再次运行此脚本。"
    exit 1
}
Write-Info "conda: $Conda"

# ============================================================
# Step 2: 创建 conda 虚拟环境
# ============================================================
Write-Step 2 "创建 conda 虚拟环境"

$PythonPath = Join-Path $VENV_DIR "python.exe"
if (Test-Path $PythonPath) {
    Write-Info "虚拟环境已存在: $VENV_DIR"
} else {
    Write-Host "  创建中（python=3.13）..."
    & $Conda create -p $VENV_DIR python=3.13 -y
    Write-Info "虚拟环境已创建: $VENV_DIR"
}
$Python = $PythonPath

# ============================================================
# Step 3: 安装全部依赖（Python 包 + Playwright + 外部工具提示 + events MCP）
# ============================================================
Write-Step 3 "安装全部依赖（可能需要 5-15 分钟）"

Write-Host "  调用 detect_env.py install..."
$DetectScript = Join-Path $SCRIPT_DIR "binary-analysis\scripts\detect_env.py"
& $Python $DetectScript install

# ============================================================
# Step 4: 验证安装结果
# ============================================================
Write-Step 4 "验证安装结果"

Write-Host "  运行 detect_env.py check-preinstall all..."
Write-Host ""

& $Python $DetectScript check-preinstall all
$DetectExit = $LASTEXITCODE

Write-Host ""
Write-Host "============================================================"
if ($DetectExit -eq 0) {
    Write-Info "全部检测通过！可以开始使用了。"
} else {
    Write-Warn2 "部分依赖未就绪（见上方输出）。"
    Write-Host ""
    Write-Host "  常见需要手动配置的项："
    Write-Host "    - ZHIPU_API_KEY: 在 .opencode\.ai_env 中设置（用于事件检索）"
    Write-Host "    - 外部工具: 按上方提示安装"
}
Write-Host "============================================================"
Write-Host ""
