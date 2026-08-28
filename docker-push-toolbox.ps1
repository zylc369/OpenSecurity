# OpenSecurity 工具箱镜像推送 (Windows / PowerShell 入口)
# 用法: powershell -ExecutionPolicy Bypass -File push-toolbox.ps1 -Ver 1.0（版本号必填，1.0 与 v1.0 等价）
# 逻辑全在 control/backend/services/docker_push_toolbox.py（CLI 实时透传 docker 输出）。

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
    Write-Host "错误：未找到 Python。请安装 Python 3.10+。" -ForegroundColor Red
    exit 1
}

# -Ver v1.1 → --ver v1.1 透传（其余参数原样）
$Args = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq "-Ver") { $i++; $Args += @("--ver", $args[$i]) }
    else { $Args += $args[$i] }
}

& $Python (Join-Path $ScriptDir ".opencode\control\backend\services\docker_push_toolbox.py") @Args
exit $LASTEXITCODE
