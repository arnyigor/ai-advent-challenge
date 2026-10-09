# Day 30: autostart for the model and the gateway (Windows Task Scheduler).
#
#   # normal PowerShell is enough for tasks of the current user
#   powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Install -BindHost 192.168.1.212
#   powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove
#
# Two tasks are created:
#   day30-model    - run-model.bat, loopback model on 127.0.0.1:8081 (CPU, ctx 4096, 1 slot)
#   day30-gateway  - run-service.ps1 -BindHost <BindHost>, HTTP gateway on port 8091 (8090 belongs to Strata)
#
# Both start at logon of the current user (no stored password), the gateway with a
# delay so the model can load first, and both restart up to 3 times after a failure.
# If the machine's LAN address changes, re-run -Install with the new -BindHost.
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = $(if ($env:SERVICE_PORT) { [int]$env:SERVICE_PORT } else { 8091 }),
    [int]$GatewayDelaySeconds = 30,
    [switch]$Install,
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$DayDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelTask = "day30-model"
$GatewayTask = "day30-gateway"
$User = "$env:USERDOMAIN\$env:USERNAME"

function Show-Tasks {
    foreach ($name in @($ModelTask, $GatewayTask)) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host "$name : not installed"; continue }
        $info = Get-ScheduledTaskInfo -TaskName $name
        Write-Host "$name : State=$($task.State) LastRun=$($info.LastRunTime) LastResult=$($info.LastTaskResult)"
        Write-Host "         $((($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' '))"
    }
}

function Remove-Tasks {
    foreach ($name in @($ModelTask, $GatewayTask)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "removed $name"
        } else { Write-Host "$name was not installed" }
    }
}

if ($Status -or (-not $Install -and -not $Remove)) {
    Show-Tasks
    if (-not $Install -and -not $Remove) {
        Write-Host "`nUse -Install to create the tasks or -Remove to delete them."
    }
    exit 0
}

if ($Remove) { Remove-Tasks; exit 0 }

Remove-Tasks

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew

# Full path: the task scheduler's own PATH does not include WindowsPowerShell\v1.0,
# and a bare "powershell.exe" fails there with 0x80070002.
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $PowerShellExe)) { $PowerShellExe = (Get-Command powershell.exe).Source }

$modelAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"`"$DayDir\run-model.bat`" >> `"$DayDir\evidence\model-autostart.log`" 2>&1`"" `
    -WorkingDirectory $DayDir
# The script writes its own transcript (run-service.ps1 -LogPath): redirecting a
# native command's stderr from a task can swallow output and abort on Stop.
$gatewayAction = New-ScheduledTaskAction -Execute $PowerShellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$DayDir\run-service.ps1`" -BindHost $BindHost -Port $Port -LogPath `"$DayDir\evidence\gateway.log`"" `
    -WorkingDirectory $DayDir

$logon = New-ScheduledTaskTrigger -AtLogOn -User $User
$gatewayTrigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$gatewayTrigger.Delay = "PT${GatewayDelaySeconds}S"

Register-ScheduledTask -TaskName $ModelTask -Action $modelAction -Trigger $logon `
    -Settings $settings -Description "Day 30: Qwen3-1.7B Q4_K_M on CPU, loopback 127.0.0.1:8081" | Out-Null
Register-ScheduledTask -TaskName $GatewayTask -Action $gatewayAction -Trigger $gatewayTrigger `
    -Settings $settings -Description "Day 30: private LLM HTTP gateway, bind ${BindHost}:$Port" | Out-Null

Write-Host "installed: $ModelTask (at logon) and $GatewayTask (at logon +${GatewayDelaySeconds}s, bind ${BindHost}:$Port)"
Write-Host "logs: evidence\model-autostart.log and evidence\gateway.log"
Write-Host "logon is used so no password is stored; after a reboot check:"
Write-Host "  Get-ScheduledTask -TaskName $GatewayTask | Select-Object TaskName,State"
Write-Host "  curl.exe http://${BindHost}:$Port/health"
Write-Host "Note: if this machine's LAN address changes, re-run -Install with the new -BindHost."
