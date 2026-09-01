param([Parameter(Mandatory=$true)][string]$Path)

$patterns = @(
    'AIza[0-9A-Za-z_\-]{35}',
    'sk-[A-Za-z0-9]{20,}',
    'Bearer\s+[A-Za-z0-9\-_\.]{20,}',
    '(?i)api_key\s*=\s*["''][^"'']{10,}["'']'
)

$found = $false
Get-ChildItem -Path $Path -Recurse -File -Include *.py,*.js,*.json,*.env,*.ps1,*.md |
    Where-Object { $_.FullName -notmatch '\\\.git\\' } |
    ForEach-Object {
        $lines = Get-Content $_.FullName -Encoding UTF8
        for ($i = 0; $i -lt $lines.Count; $i++) {
            foreach ($p in $patterns) {
                if ($lines[$i] -match $p) {
                    Write-Host "ERROR: possible API key in $($_.FullName):$($i+1)" -ForegroundColor Red
                    $found = $true
                }
            }
        }
    }

if ($found) { Write-Host "`nSubmission aborted." -ForegroundColor Red; exit 1 }
Write-Host "No secrets found." -ForegroundColor Green
exit 0
