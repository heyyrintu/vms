param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [switch]$ConfirmRestore
)
$resolved = [System.IO.Path]::GetFullPath($BackupFile)
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "Backup file does not exist: $resolved" }
if (-not $ConfirmRestore) { throw "Restore replaces database contents. Re-run with -ConfirmRestore after verifying: $resolved" }
Get-Content -LiteralPath $resolved -Raw | docker compose exec -T postgres psql --username=vms --dbname=vms --single-transaction
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed" }
Write-Output "Restore completed from: $resolved"
