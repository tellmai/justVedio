$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskProject
& '.\.venv\Scripts\python.exe' 'scripts\make_icon.py'
if ($LASTEXITCODE -ne 0) { throw '程序图标生成失败' }
$taskVersion = & '.\.venv\Scripts\python.exe' -c 'from justvedio.version import VERSION; print(VERSION)'
if ($LASTEXITCODE -ne 0) { throw '版本读取失败' }
$taskDistRoot = Join-Path 'dist' ('v' + $taskVersion)
$taskAppDir = Join-Path $taskDistRoot 'justVedio'
$taskSavedResults = $null
$taskExistingResults = Join-Path $taskAppDir 'results'
if (Test-Path -LiteralPath $taskExistingResults) {
    $taskSavedResults = Join-Path $taskProject ('build\results-backup-' + $taskVersion + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
    Copy-Item -LiteralPath $taskExistingResults -Destination $taskSavedResults -Recurse
    Write-Output ('已有运行结果已备份到 ' + $taskSavedResults)
}
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --distpath $taskDistRoot 'justVedio.spec'
if ($LASTEXITCODE -ne 0) { throw 'EXE 打包失败' }
if ($taskSavedResults) {
    Copy-Item -LiteralPath $taskSavedResults -Destination $taskExistingResults -Recurse
}
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $taskAppDir 'README.md') -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $taskAppDir 'THIRD_PARTY_NOTICES.md') -Force
Copy-Item -LiteralPath '使用说明.txt' -Destination (Join-Path $taskAppDir '使用说明.txt') -Force
Copy-Item -LiteralPath '验证记录.md' -Destination (Join-Path $taskAppDir '验证记录.md') -Force
Write-Output ('已生成 ' + (Join-Path $taskAppDir 'justVedio.exe') + '，请保留同目录 _internal 文件夹。')
