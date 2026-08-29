# OpenSecurity 一键安装 (Windows / PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File .opencode\install.ps1
# 逻辑在 detect_py_deps.py install（python 依赖）+ detect_tools.py install（外部工具）。
# Windows 的 Git Bash 前提（opencode shell 配置）由 detect_tools 的 git-bash 配方自动建立：
# 下载最新 PortableGit 便携版（按 CPU 架构）到 ~/bw-security-analysis/bin/git-portable/，
# opencode.json 的 shell 写为其 bash.exe。配置写入后需重启 opencode 会话生效。
# 两层都是必需层: python 依赖失败立即中断; 工具层单项失败不中断其余安装，
# 但只要有失败，以非零退出码结束（重装命令见输出末尾汇总）。

param([switch]$Force)
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

# 参数: -Force（透传给 detect_tools install --force——忽略幂等跳过强制重装）
if ($args.Count -gt 0) {
    Write-Host "错误：install.ps1 仅支持 -Force 参数（收到: $args）。" -ForegroundColor Red
    exit 1
}

$Script = Join-Path $ScriptDir "control\backend\services\detect_py_deps.py"
& $Python $Script install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[*] === 安装外部工具（单项失败不中断，失败汇总在末尾） ===" -ForegroundColor Cyan
$Script = Join-Path $ScriptDir "control\backend\services\detect_tools.py"
$ToolArgs = @("install")
if ($Force) { $ToolArgs += "--force" }
& $Python $Script @ToolArgs
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[*] 提示: opencode shell 已自动配置为 Git Bash（见上方 git-bash 条目）——重启 opencode 会话后生效。" -ForegroundColor Cyan
}
exit $LASTEXITCODE
