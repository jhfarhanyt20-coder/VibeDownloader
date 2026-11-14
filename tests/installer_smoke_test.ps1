param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'This installer test is only for a disposable GitHub Actions Windows runner.'
}
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The disposable Windows runner must have administrator permissions.'
}
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$installDir = Join-Path $env:RUNNER_TEMP 'VibeDownloader smoke install'
$report = Join-Path (Get-Location) 'dist\release\SMOKE_TEST_REPORT.json'
$version = python release_tools.py version
if ($LASTEXITCODE -ne 0) { throw 'Could not read the application version.' }

# Keep /D= unquoted and last, including when the install directory has spaces.
$process = Start-Process -FilePath $installer -ArgumentList "/S /NORESTART /D=$installDir" -PassThru -Wait
if ($process.ExitCode -ne 0) { throw "Fresh install failed: $($process.ExitCode)" }
foreach ($relative in @('VibeDownloader.exe', 'yt-dlp.exe', 'uninst.exe', 'extension\manifest.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $installDir $relative))) {
        throw "Installer did not create $relative in the requested directory."
    }
}
$registration = Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\VibeDownloader'
if ($registration.DisplayVersion -ne $version) { throw 'Installed version does not match app_info.py.' }

$savedLocalData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = Join-Path $env:RUNNER_TEMP 'VibeDownloader smoke user data'
    $process = Start-Process -FilePath (Join-Path $installDir 'VibeDownloader.exe') `
        -ArgumentList "--self-test `"$report`"" -PassThru -Wait
    if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) {
        throw "Frozen application self-test failed: $($process.ExitCode)"
    }
    $result = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
    if (-not $result.ok -or -not $result.frozen -or $result.architecture_bits -ne 64) {
        throw 'The installer did not contain a working x64 frozen application.'
    }
    $dataDir = Join-Path $env:LOCALAPPDATA 'VibeDownloader'
    $history = Join-Path $dataDir 'history.json'
    '[{"id":"keep-during-update","status":"paused"}]' | Set-Content -LiteralPath $history -Encoding utf8
    $historyHash = (Get-FileHash -LiteralPath $history -Algorithm SHA256).Hash
    $sentinel = Join-Path $installDir 'user-file-that-must-not-be-deleted.txt'
    'User file: preserve on upgrade and uninstall.' | Set-Content -LiteralPath $sentinel

    # Exercise the same silent in-place command as the app, including PID wait.
    $closingApp = Start-Process -FilePath powershell.exe `
        -ArgumentList '-NoProfile -NonInteractive -Command "[Threading.Thread]::Sleep(2000)"' `
        -WindowStyle Hidden -PassThru
    $process = Start-Process -FilePath $installer `
        -ArgumentList "/S /UPDATE /NORESTART /WAITPID=$($closingApp.Id) /D=$installDir" -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "In-place update failed: $($process.ExitCode)" }
    if ((Get-FileHash -LiteralPath $history -Algorithm SHA256).Hash -ne $historyHash) {
        throw 'The update changed user history.'
    }
    if (-not (Test-Path -LiteralPath $sentinel)) { throw 'The update deleted an unrelated user file.' }
    $process = Start-Process -FilePath (Join-Path $installDir 'uninst.exe') -ArgumentList '/S' -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Uninstall failed: $($process.ExitCode)" }
    if (Test-Path -LiteralPath (Join-Path $installDir 'VibeDownloader.exe')) {
        throw 'Uninstall did not remove the application.'
    }
    if (-not (Test-Path -LiteralPath $history) -or -not (Test-Path -LiteralPath $sentinel)) {
        throw 'Uninstall removed retained user data or an unrelated user file.'
    }
} finally {
    $env:LOCALAPPDATA = $savedLocalData
}
Write-Output 'Installer smoke test passed: install, frozen UI/tools, update, data retention, uninstall.'
