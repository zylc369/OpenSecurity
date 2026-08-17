# OpenSecurity 一键安装 (Windows / PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File .opencode\install.ps1
# 逻辑全在 detect_py_deps.py install（跨平台），此脚本只负责找到 Python 并启动它。

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
exit $LASTEXITCODE
