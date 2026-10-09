# Day 30: limited Windows Firewall rule for the gateway port.
#
#   # elevated PowerShell (Run as Administrator)
#   powershell -ExecutionPolicy Bypass -File allow-firewall.ps1 -RemoteAddress 192.168.1.0/24
#   powershell -ExecutionPolicy Bypass -File allow-firewall.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File allow-firewall.ps1 -Remove
#
# The rule allows only the given LAN/VPN subnet to reach the gateway port; it does
# not open the port to the internet. Port forwarding on the router must stay off -
# a private VPN is the way to reach the service from outside the home network.
param(
    [int]$Port = $(if ($env:SERVICE_PORT) { [int]$env:SERVICE_PORT } else { 8091 }),
    [string]$RemoteAddress = "LocalSubnet",
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$RuleName = "day30 private llm gateway $Port"

function Assert-Admin {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "This script needs an elevated PowerShell (firewall rules cannot even be read without it)." -ForegroundColor Red
        Write-Host "Open 'PowerShell (Administrator)' and run this script there." -ForegroundColor Red
        exit 1
    }
}

Assert-Admin

if ($Status) {
    $rules = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if (-not $rules) { Write-Host "no rule named '$RuleName'"; exit 0 }
    $rules | ForEach-Object {
        $address = ($_ | Get-NetFirewallAddressFilter).RemoteAddress
        Write-Host "$($_.DisplayName): Enabled=$($_.Enabled) Action=$($_.Action) RemoteAddress=$address"
    }
    exit 0
}

if ($Remove) {
    $rules = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if ($rules) { $rules | Remove-NetFirewallRule; Write-Host "removed rule '$RuleName'" }
    else { Write-Host "no rule named '$RuleName'" }
    exit 0
}

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) { $existing | Remove-NetFirewallRule }

New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress $RemoteAddress -Profile Private, Domain | Out-Null
Write-Host "added rule '$RuleName': TCP $Port inbound from $RemoteAddress (Private, Domain profiles)"
Write-Host "verify with:  Get-NetFirewallRule -DisplayName '$RuleName' | Get-NetFirewallAddressFilter"
