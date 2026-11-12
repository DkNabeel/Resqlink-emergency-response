param(
    [Parameter(Mandatory = $true)]
    [string]$PbfPath,

    [ValidatePattern("^[A-Za-z0-9_-]+$")]
    [string]$MapName = "resqlink-area"
)

$ErrorActionPreference = "Stop"

$image = "ghcr.io/project-osrm/osrm-backend:latest"
$dataDir = Join-Path $PSScriptRoot "data"
$sourcePbf = (Resolve-Path $PbfPath).Path
$targetPbf = Join-Path $dataDir "$MapName.osm.pbf"
$volumeMount = "$($dataDir):/data"

function Invoke-DockerStep {
    param([string[]]$Arguments, [string]$StepName)

    Write-Host ""
    Write-Host "== $StepName ==" -ForegroundColor Cyan
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed (Docker exit code $LASTEXITCODE)."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Install it, start Docker Desktop, and rerun this script."
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

if ($sourcePbf -ne $targetPbf) {
    Write-Host "Copying regional OSM extract into offline-routing/data..."
    Copy-Item -LiteralPath $sourcePbf -Destination $targetPbf -Force
}

if (-not (Test-Path $targetPbf)) {
    throw "OSM PBF file not found: $targetPbf"
}

Invoke-DockerStep -Arguments @("pull", $image) -StepName "Download OSRM engine image"

Invoke-DockerStep -Arguments @(
    "run", "--rm", "-t",
    "-v", $volumeMount,
    $image,
    "osrm-extract", "-p", "/opt/car.lua", "/data/$MapName.osm.pbf"
) -StepName "Build driving road graph"

Invoke-DockerStep -Arguments @(
    "run", "--rm", "-t",
    "-v", $volumeMount,
    $image,
    "osrm-partition", "/data/$MapName.osrm"
) -StepName "Partition road graph"

Invoke-DockerStep -Arguments @(
    "run", "--rm", "-t",
    "-v", $volumeMount,
    $image,
    "osrm-customize", "/data/$MapName.osrm"
) -StepName "Prepare offline routing weights"

$existing = & docker ps -a --filter "name=^/resqlink-osrm$" --format "{{.Names}}"
if ($existing -eq "resqlink-osrm") {
    Invoke-DockerStep -Arguments @("rm", "-f", "resqlink-osrm") -StepName "Replace previous local router"
}

Invoke-DockerStep -Arguments @(
    "run", "-d",
    "--name", "resqlink-osrm",
    "--restart", "unless-stopped",
    "-p", "5000:5000",
    "-v", $volumeMount,
    $image,
    "osrm-routed", "--algorithm", "mld", "/data/$MapName.osrm"
) -StepName "Start local offline routing server"

Write-Host ""
Write-Host "Local OSRM is starting at http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Check it with: docker logs --tail 30 resqlink-osrm"
Write-Host "Set these two values in backend/.env:"
Write-Host "OFFLINE_ROUTING_URL=http://127.0.0.1:5000"
Write-Host "ROUTING_PREFER_LOCAL=true"
Write-Host ""
Write-Host "Keep this laptop and the ResQLink backend running when testing offline routes."
