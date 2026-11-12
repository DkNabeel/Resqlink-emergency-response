param(
    [string]$PbfPath = "",

    [ValidatePattern("^[A-Za-z0-9_-]+$")]
    [string]$MapName = "resqlink-southern-zone",

    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

# Official Geofabrik extract for the Southern Zone of India.
# This is a regional road dataset, not the entire India extract.
$downloadUrl = "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"
$checksumUrl = "$downloadUrl.md5"

$image = "ghcr.io/project-osrm/osrm-backend:latest"
$dataDir = Join-Path $PSScriptRoot "data"
$targetPbf = Join-Path $dataDir "$MapName.osm.pbf"
$volumeMount = "{0}:/data" -f $dataDir

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

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but not running. Start Docker Desktop and rerun this script."
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

if ([string]::IsNullOrWhiteSpace($PbfPath)) {
    Write-Host "No local PBF was supplied. ResQLink will download the official Southern India road map."
    Write-Host "Source: $downloadUrl"
    Write-Host "The latest published extract is roughly 560 MB; keep enough disk space for the download and prepared routing graph."

    $expectedMd5 = $null
    try {
        $checksumResponse = Invoke-WebRequest -Uri $checksumUrl -UseBasicParsing -TimeoutSec 45
        if ($checksumResponse.Content -match '(?i)\b([a-f0-9]{32})\b') {
            $expectedMd5 = $Matches[1].ToLowerInvariant()
        }
    }
    catch {
        throw "Could not download the official Geofabrik checksum: $($_.Exception.Message)"
    }

    if ([string]::IsNullOrWhiteSpace($expectedMd5)) {
        throw "Geofabrik returned an unrecognized MD5 checksum file. No map was installed."
    }

    $downloadIsValid = $false
    if (Test-Path $targetPbf) {
        $existingHash = (Get-FileHash -LiteralPath $targetPbf -Algorithm MD5).Hash.ToLowerInvariant()
        if ($existingHash -eq $expectedMd5) {
            Write-Host "A current, checksum-verified regional map is already downloaded. Reusing it."
            $downloadIsValid = $true
        }
        else {
            Write-Host "An older or incomplete map file exists. It will be replaced."
            Remove-Item -LiteralPath $targetPbf -Force
        }
    }

    if (-not $downloadIsValid) {
        if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
            throw "curl.exe was not found. Windows 10/11 normally includes it; install curl or supply -PbfPath."
        }

        Write-Host "Downloading regional OSM data. If interrupted, rerun this command; curl will resume the partial file."
        & curl.exe --location --fail --show-error --retry 4 --retry-delay 3 --continue-at - --output $targetPbf $downloadUrl
        if ($LASTEXITCODE -ne 0) {
            throw "The regional map download failed (curl exit code $LASTEXITCODE). Rerun the script to resume."
        }

        $downloadedHash = (Get-FileHash -LiteralPath $targetPbf -Algorithm MD5).Hash.ToLowerInvariant()
        if ($downloadedHash -ne $expectedMd5) {
            Remove-Item -LiteralPath $targetPbf -Force
            throw "The downloaded map failed its MD5 checksum. The incomplete file was removed; rerun the script."
        }
        Write-Host "Regional OSM map downloaded and checksum verified." -ForegroundColor Green
    }
}
else {
    $sourcePbf = (Resolve-Path -LiteralPath $PbfPath).Path
    if ($sourcePbf -ne $targetPbf) {
        Write-Host "Copying supplied OSM extract into offline-routing/data..."
        Copy-Item -LiteralPath $sourcePbf -Destination $targetPbf -Force
    }
}

if (-not (Test-Path $targetPbf)) {
    throw "OSM PBF file not found: $targetPbf"
}

$osrmGraph = Join-Path $dataDir "$MapName.osrm"
if ((Test-Path $osrmGraph) -and -not $Rebuild) {
    Write-Host "A prepared OSRM graph already exists. Reusing it. Use -Rebuild to regenerate it."
}
else {
    Invoke-DockerStep -Arguments @("pull", $image) -StepName "Download OSRM routing engine"

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
}

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
Write-Host "The laptop now calculates routes from its downloaded Southern India road graph."
Write-Host "Keep the laptop, Docker container, FastAPI and phone hotspot/local Wi-Fi running during offline tests."
