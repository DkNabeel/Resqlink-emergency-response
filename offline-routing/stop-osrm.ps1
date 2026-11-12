$ErrorActionPreference = "Stop"

$existing = & docker ps -a --filter "name=^/resqlink-osrm$" --format "{{.Names}}"
if ($existing -eq "resqlink-osrm") {
    & docker stop resqlink-osrm
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stop the local OSRM container."
    }
    Write-Host "Local OSRM stopped. Its prepared road graph remains in offline-routing/data."
} else {
    Write-Host "The local OSRM container is not running."
}
