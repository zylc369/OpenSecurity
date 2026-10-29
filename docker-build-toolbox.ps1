# OpenSecurity 工具箱镜像构建 (Windows / PowerShell 入口)
# 用法: powershell -ExecutionPolicy Bypass -File build-toolbox.ps1 [-Arch both] [-NoSmoke]
# 逻辑全在 control/backend/services/docker_build_toolbox.py（CLI 实时透传 docker build 输出）。

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

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

# -Arch/-NoSmoke → --arch/--no-smoke 转换（其余参数原样）
$Args = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq "-Arch") { $i++; $Args += @("--arch", $args[$i]) }
    elseif ($args[$i] -eq "-NoSmoke") { $Args += "--no-smoke" }
    else { $Args += $args[$i] }
}

& $Python (Join-Path $ScriptDir ".opencode\control\backend\services\docker_build_toolbox.py") @Args
exit $LASTEXITCODE
