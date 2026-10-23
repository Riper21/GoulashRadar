# Supplier Radar - local demo launcher.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1           (warm 2 demo queries)
#   powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1 -Full     (warm all 5)
#   ... -Port 8001                                                            (custom port)
# NOTE: ASCII-only on purpose (PS 5.1 parses .ps1 in the system codepage).
# Cyrillic demo queries are built from [char] codes below.
param(
    [int]$Port = 8000,
    [switch]$Full,
    [switch]$NoWarm
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Say($msg) { Write-Host "[demo] $msg" -ForegroundColor Cyan }
function Ru([int[]]$codes) { -join ($codes | ForEach-Object { [char]$_ }) }

# muka/Moskva, kofe/Moskva + full set
$q1c = Ru (1084, 1091, 1082, 1072);                  $q1t = Ru (1052, 1086, 1089, 1082, 1074, 1072)
$q2c = Ru (1082, 1086, 1092, 1077);                  $q2t = $q1t
$q3c = Ru (1091, 1087, 1072, 1082, 1086, 1074, 1082, 1072, 32, 1076, 1083, 1103, 32, 1082, 1086, 1092, 1077)
$q3t = Ru (1057, 1072, 1085, 1082, 1090, 45, 1055, 1077, 1090, 1077, 1088, 1073, 1091, 1088, 1075)
$q4c = Ru (1089, 1099, 1088, 1099);                  $q4t = Ru (1050, 1072, 1079, 1072, 1085, 1100)
$q5c = Ru (1089, 1087, 1077, 1094, 1080, 1080, 32, 1080, 32, 1087, 1088, 1080, 1087, 1088, 1072, 1074, 1099)
$q5t = Ru (1045, 1082, 1072, 1090, 1077, 1088, 1080, 1085, 1073, 1091, 1088, 1075)

# 1) deps (fast no-op if installed)
Say "installing dependencies (if needed)..."
py -X utf8 -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 2) start server in its own console window
$server = Start-Process py -ArgumentList "-X", "utf8", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" -WorkingDirectory $root -PassThru
Say "server started (PID $($server.Id)) - http://127.0.0.1:$Port"

# 3) wait for /api/health
$health = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        break
    } catch { }
}
if (-not $health) { throw "server did not become healthy in 30 s" }
Say "health OK: $($health.status), version $($health.version)"

# 4) warm demo queries (fills SERP/page cache -> instant repeat demo)
if (-not $NoWarm) {
    $queries = @(
        @{ category = $q1c; city = $q1t },
        @{ category = $q2c; city = $q2t }
    )
    if ($Full) {
        $queries += @(
            @{ category = $q3c; city = $q3t },
            @{ category = $q4c; city = $q4t },
            @{ category = $q5c; city = $q5t }
        )
    }
    foreach ($q in $queries) {
        Say ("warming: {0} / {1} ..." -f $q.category, $q.city)
        $json = @{ category = $q.category; city = $q.city } | ConvertTo-Json -Compress
        $body = [System.Text.Encoding]::UTF8.GetBytes($json)
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/search" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30
        for ($i = 0; $i -lt 24; $i++) {
            Start-Sleep -Seconds 5
            try { $job = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/jobs/$($r.job_id)" -TimeoutSec 10 } catch { continue }
            if ($job.status -in @("done", "error")) { break }
        }
        $found = "?"
        try {
            $sup = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/jobs/$($r.job_id)/suppliers" -TimeoutSec 10
            $found = $sup.suppliers.Count
        } catch { }
        Say ("  -> {0} [{1}] cards: {2}" -f $job.status, $r.job_id, $found)
    }
    Say "cache warmed: repeat searches answer in ~2 s"
}

Say ""
Say "================================================" -ForegroundColor Green
Say " DEMO READY:  http://127.0.0.1:$Port"
Say " Chrome widget: options -> API URL http://127.0.0.1:$Port"
Say " stop: close the python/server console window"
Say "================================================" -ForegroundColor Green
