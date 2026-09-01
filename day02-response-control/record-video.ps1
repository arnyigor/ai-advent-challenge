<#
Records the Day 2 (Response Control) demo video without puppeteer/playwright:
ffmpeg (gdigrab, window-title capture, no manual coordinate guessing)
plus automatic Enter key delivery into the real python process's stdin.

Requirements: ffmpeg in PATH (or FFMPEG_PATH), GEMINI_API_KEY set in the environment.

Usage:
    powershell -ExecutionPolicy Bypass -File record-video.ps1
    powershell -ExecutionPolicy Bypass -File record-video.ps1 -Out video\my-demo.mp4
#>
param(
    [string]$Out = "$PSScriptRoot\video\day2-demo.mp4",
    [string]$Title = "Day2ResponseControlDemo",
    [int]$Fps = 30
)

$ErrorActionPreference = "Stop"

if (-not $env:GEMINI_API_KEY) {
    throw "GEMINI_API_KEY is not set - set it before recording (see tools/API_KEYS.md)"
}

$ffmpeg = $env:FFMPEG_PATH
if (-not $ffmpeg) { $ffmpeg = "ffmpeg" }

$videoDir = Split-Path -Parent $Out
New-Item -ItemType Directory -Force -Path $videoDir | Out-Null

Write-Host "-> Starting day2_response_control.py in a separate window ($Title)..." -ForegroundColor Cyan

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "cmd.exe"
$psi.Arguments = "/c title $Title && python -u `"$PSScriptRoot\day2_response_control.py`""
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.CreateNoWindow = $false
$psi.WorkingDirectory = $PSScriptRoot
$proc = [System.Diagnostics.Process]::Start($psi)

# wait until the process gets a real window (MainWindowHandle)
$hwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) { $hwnd = $p.MainWindowHandle; break }
}
if ($hwnd -eq [IntPtr]::Zero) {
    $proc.Kill()
    throw "Terminal window titled '$Title' did not appear within 10 seconds"
}

Start-Sleep -Milliseconds 500

Write-Host "-> Starting ffmpeg (gdigrab, capturing only window '$Title')..." -ForegroundColor Cyan

$ffArgsList = @(
    "-y", "-f", "gdigrab", "-framerate", "$Fps",
    "-i", "title=$Title",
    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
    "`"$Out`""
)
$ffPsi = New-Object System.Diagnostics.ProcessStartInfo
$ffPsi.FileName = $ffmpeg
$ffPsi.Arguments = ($ffArgsList -join ' ')
$ffPsi.UseShellExecute = $false
$ffPsi.RedirectStandardInput = $true
$ffPsi.RedirectStandardError = $true
$ffPsi.CreateNoWindow = $true
$ffProc = [System.Diagnostics.Process]::Start($ffPsi)

Start-Sleep -Seconds 1

Write-Host "-> Scenario: Enter #1 (after intro screen)..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
$proc.StandardInput.WriteLine("")

Write-Host "-> Scenario: Enter #2 (after diff-controls screen, runs the comparison)..." -ForegroundColor Cyan
Start-Sleep -Seconds 4
$proc.StandardInput.WriteLine("")

Write-Host "-> Waiting for the script to finish (real Gemini API calls)..." -ForegroundColor Cyan
$finished = $proc.WaitForExit(120000)
if (-not $finished) {
    Write-Host "!! Script did not finish within 120s, stopping the recording as-is" -ForegroundColor Yellow
}

Start-Sleep -Seconds 2

Write-Host "-> Stopping ffmpeg..." -ForegroundColor Cyan
try {
    $ffProc.StandardInput.Write("q")
    $ffProc.StandardInput.Flush()
} catch {}
$ffProc.WaitForExit(15000) | Out-Null
if (-not $ffProc.HasExited) { $ffProc.Kill() }

if (Test-Path $Out) {
    $size = (Get-Item $Out).Length / 1MB
    Write-Host ("`nDone: {0} ({1:N1} MB)" -f $Out, $size) -ForegroundColor Green
} else {
    throw "Video file was not created: $Out"
}
