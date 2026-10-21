$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProject
if (-not (Test-Path -LiteralPath 'tools\chrome\chrome-win64\chrome.exe')) {
    & '.\.venv\Scripts\python.exe' 'scripts\fetch_chrome.py'
    if ($LASTEXITCODE -ne 0) { throw '备用浏览器下载失败' }
}
& (Join-Path $PSScriptRoot 'build.ps1')
if ($LASTEXITCODE -ne 0) { throw 'EXE 构建失败' }
& '.\.venv\Scripts\python.exe' 'scripts\package_release.py'
if ($LASTEXITCODE -ne 0) { throw '便携包或摘要生成失败' }
