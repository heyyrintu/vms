param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$resolved = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $resolved | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $resolved "vms-$stamp.sql"
docker compose exec -T postgres pg_dump --format=plain --clean --if-exists --no-owner --username=vms vms | Set-Content -LiteralPath $target -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }
Write-Output "Backup created: $target"
