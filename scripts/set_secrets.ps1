<#
Run once by you, locally. Reads the repo-root .env, takes ONLY
SPOTIFY_CLIENT_ID and SPOTIFY_REFRESH_TOKEN, and stores them as GitHub Actions
secrets on Vishnu-DRX/SpotiSort via the gh CLI. Values are piped through stdin
and are never passed as arguments, printed, or logged. SPOTIFY_CLIENT_SECRET is
not needed (PKCE) and is never read or set. Requires: gh installed and `gh auth login`.
#>
$ErrorActionPreference = 'Stop'
$Repo = 'Vishnu-DRX/SpotiSort'
$Names = @('SPOTIFY_CLIENT_ID', 'SPOTIFY_REFRESH_TOKEN')
$EnvPath = Join-Path $PSScriptRoot '..\.env'

if (-not (Test-Path $EnvPath)) { Write-Error "Missing .env at repo root."; exit 1 }

$found = @{}
foreach ($line in Get-Content -LiteralPath $EnvPath) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $k = $t.Substring(0, $i).Trim()
    if ($k -notin $Names) { continue }
    $v = $t.Substring($i + 1).Trim()
    if ($v.Length -ge 2 -and (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'")))) {
        $v = $v.Substring(1, $v.Length - 2)
    }
    $found[$k] = $v
}

foreach ($n in $Names) {
    if (-not $found.ContainsKey($n) -or [string]::IsNullOrEmpty($found[$n])) {
        Write-Error "Missing or empty key in .env: $n"
        exit 1
    }
}

$answer = Read-Host "Set secrets $($Names -join ', ') on $Repo? (y/N)"
if ($answer -notmatch '^(y|yes)$') { Write-Host "Aborted."; exit 0 }

foreach ($n in $Names) {
    $found[$n] | gh secret set $n --repo $Repo
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to set secret: $n"; exit 1 }
    Write-Host "Set secret: $n"
}
Write-Host "Done. $($Names.Count) secrets stored on $Repo."
