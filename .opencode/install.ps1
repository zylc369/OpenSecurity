# OpenSecurity 一键安装 (Windows / PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File .opencode\install.ps1
# 逻辑在 detect_py_deps.py install（python 依赖）+ detect_tools.py install（外部工具）。
# 两层都是必需层: python 依赖失败立即中断; 工具层单项失败不中断其余安装，
# 但只要有失败，以非零退出码结束（重装命令见输出末尾汇总）。

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 找 python
$Python = $null
foreach ($cmd in @("python", "python3")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $Python = $found.Source
        break
    }
}

if (-not $Python) {
    Write-Host "错误：未找到 Python。请安装 Miniforge 或 Python 3.10+。" -ForegroundColor Red
    exit 1
}

# 本脚本不接收参数（安装内容固定：全部必需依赖）
if ($args.Count -gt 0) {
    Write-Host "错误：install.ps1 不接收参数。" -ForegroundColor Red
    exit 1
}

$Script = Join-Path $ScriptDir "control\backend\services\detect_py_deps.py"
& $Python $Script install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[*] === 安装外部工具（单项失败不中断，失败汇总在末尾） ===" -ForegroundColor Cyan
$Script = Join-Path $ScriptDir "control\backend\services\detect_tools.py"
& $Python $Script install
exit $LASTEXITCODE
