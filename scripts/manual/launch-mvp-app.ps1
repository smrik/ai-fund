<#
.SYNOPSIS
Launch the Alpha Pod MVP React app and FastAPI backend locally.

.DESCRIPTION
Run this from host Windows PowerShell after activating the ai-fund conda env.
The script starts FastAPI and Vite, stores process metadata and logs under
ignored .pwtmp/, waits for both ports, and prints the URLs to open.

.EXAMPLE
pwsh -File .\scripts\manual\launch-mvp-app.ps1

.EXAMPLE
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Open

.EXAMPLE
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Status

.EXAMPLE
pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Stop
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173,
[string]$PythonCommand = "python",
    [string]$NpmCommand = "npm",
    [switch]$Open,
    [switch]$Detach,
    [switch]$Reload,
    [switch]$Preview,
    [switch]$Status,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Test-PortOpen {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(500, $false)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-PortOpen {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$Attempts = 60,
        [int]$DelaySeconds = 1
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (Test-PortOpen -Address $Address -Port $Port) {
            return
        }
        Start-Sleep -Seconds $DelaySeconds
    }

    throw "Timed out waiting for $Address`:$Port"
}

function Test-HttpReady {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-ListeningPidsOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)$"
    $localizedPattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+ABH.REN\s+(\d+)$"
    $pids = @()
    foreach ($line in (& netstat -ano)) {
        if ($line -match $pattern -or $line -match $localizedPattern) {
            $pids += [int]$Matches[1]
        }
    }
    return $pids | Sort-Object -Unique
}

function Stop-MvpProcess {
    param([int[]]$ProcessIds)

    foreach ($processId in ($ProcessIds | Sort-Object -Unique)) {
        if ($processId -le 0) {
            continue
        }

        $taskkillOutput = & taskkill.exe /PID $processId /T /F 2>&1
        $taskkillExitCode = $LASTEXITCODE
        Start-Sleep -Milliseconds 200
        if ($taskkillExitCode -eq 0) {
            Write-Host "Stopped PID $processId and child processes"
            continue
        }

        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped PID $processId"
        } catch {
            $message = ($taskkillOutput | Out-String).Trim()
            if (-not $message) {
                $message = $_.Exception.Message
            }
            Write-Warning "Could not stop PID $processId. $message"
        }
    }
}

function Wait-PortsClosed {
    param(
        [Parameter(Mandatory = $true)][int[]]$Ports,
        [int]$Attempts = 15,
        [int]$DelayMilliseconds = 250
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $open = @()
        foreach ($port in $Ports) {
            $open += @(Get-ListeningPidsOnPort -Port $port)
        }
        if ($open.Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMilliseconds
    }
    return $false
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stateDir = Join-Path $repoRoot ".pwtmp"
$stateFile = Join-Path $stateDir "mvp-app.json"
$apiUrl = "http://$HostAddress`:$ApiPort"
$frontendUrl = "http://$HostAddress`:$FrontendPort"
$apiBase = "$apiUrl/api"
$watchlistUrl = "$frontendUrl/watchlist"
$resolvedPythonCommand = $PythonCommand

if ($PythonCommand -eq "python") {
    $pythonCandidates = @()
    if ($env:USERPROFILE) {
        $pythonCandidates += (Join-Path $env:USERPROFILE "miniconda3\envs\ai-fund\python.exe")
        $pythonCandidates += (Join-Path $env:USERPROFILE "anaconda3\envs\ai-fund\python.exe")
    }
    foreach ($candidate in $pythonCandidates) {
        if (Test-Path $candidate) {
            $resolvedPythonCommand = $candidate
            break
        }
    }
}

if ($Preview) {
    $reloadArg = if ($Reload) { " --reload" } else { "" }
    Write-Host "Repository root: $repoRoot"
    Write-Host "Expected env: ai-fund"
    Write-Host "Python command: $resolvedPythonCommand"
    Write-Host "API URL: $apiUrl"
    Write-Host "Frontend URL: $frontendUrl"
    Write-Host "Backend command:"
    Write-Host "  $resolvedPythonCommand -m uvicorn api.main:app --host $HostAddress --port $ApiPort$reloadArg"
    Write-Host "Frontend command:"
    Write-Host "  `$env:VITE_API_BASE = '$apiBase'; $NpmCommand --prefix frontend run dev -- --host $HostAddress --port $FrontendPort --strictPort"
    Write-Host "Default behavior: keep this PowerShell window open as the supervisor; press Ctrl+C to stop."
    Write-Host "Detached behavior: add -Detach, then stop later with -Stop."
    return
}

if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir | Out-Null
}

if ($Status) {
    $apiPids = @(Get-ListeningPidsOnPort -Port $ApiPort)
    $frontendPids = @(Get-ListeningPidsOnPort -Port $FrontendPort)
    Write-Host "API port $ApiPort PIDs: $($apiPids -join ', ')"
    Write-Host "Frontend port $FrontendPort PIDs: $($frontendPids -join ', ')"
    Write-Host "API reachable: $(Test-PortOpen -Address $HostAddress -Port $ApiPort)"
    Write-Host "Frontend reachable: $(Test-PortOpen -Address $HostAddress -Port $FrontendPort)"
    if (Test-Path $stateFile) {
        Write-Host "State file: $stateFile"
        Get-Content $stateFile
    }
    return
}

if ($Stop) {
    $stateProcessIds = @()
    $hasState = $false
    $stateReusedApi = $false
    $stateReusedFrontend = $false
    if (Test-Path $stateFile) {
        try {
            $state = Get-Content $stateFile | ConvertFrom-Json
            $hasState = $true
            $stateReusedApi = [bool]$state.reused_api
            $stateReusedFrontend = [bool]$state.reused_frontend
            $stateProcessIds += [int]$state.api_pid
            $stateProcessIds += [int]$state.frontend_pid
        } catch {
            Write-Warning "Could not parse $stateFile; stopping by port only."
        }
    }

    $portProcessIds = @()
    if (-not $hasState -or -not $stateReusedApi) {
        $portProcessIds += @(Get-ListeningPidsOnPort -Port $ApiPort)
    }
    if (-not $hasState -or -not $stateReusedFrontend) {
        $portProcessIds += @(Get-ListeningPidsOnPort -Port $FrontendPort)
    }
    Stop-MvpProcess -ProcessIds @($stateProcessIds + $portProcessIds)
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    $portsToClose = @()
    if (-not $hasState -or -not $stateReusedApi) {
        $portsToClose += $ApiPort
    }
    if (-not $hasState -or -not $stateReusedFrontend) {
        $portsToClose += $FrontendPort
    }
    if ($portsToClose.Count -eq 0 -or (Wait-PortsClosed -Ports $portsToClose)) {
        Write-Host "MVP app stopped."
    } else {
        $remainingApi = if ($portsToClose -contains $ApiPort) { @(Get-ListeningPidsOnPort -Port $ApiPort) } else { @() }
        $remainingFrontend = if ($portsToClose -contains $FrontendPort) { @(Get-ListeningPidsOnPort -Port $FrontendPort) } else { @() }
        Write-Warning "MVP app stop attempted, but ports are still in use. API $ApiPort PIDs=[$($remainingApi -join ', ')], frontend $FrontendPort PIDs=[$($remainingFrontend -join ', ')]."
    }
    return
}

if ($env:CONDA_DEFAULT_ENV -ne "ai-fund" -and $resolvedPythonCommand -eq "python") {
    Write-Warning "Expected CONDA_DEFAULT_ENV=ai-fund. Activate it first if imports fail: conda activate ai-fund"
} elseif ($resolvedPythonCommand -ne $PythonCommand) {
    Write-Host "Using detected ai-fund Python: $resolvedPythonCommand"
}

Test-CommandAvailable -Name $resolvedPythonCommand
Test-CommandAvailable -Name $NpmCommand

$apiPids = @(Get-ListeningPidsOnPort -Port $ApiPort)
$frontendPids = @(Get-ListeningPidsOnPort -Port $FrontendPort)
$apiProcess = $null
$frontendProcess = $null
$reuseApi = $false
$reuseFrontend = $false

if ($apiPids.Count -gt 0) {
    if (Test-HttpReady -Url "$apiUrl/docs") {
        $reuseApi = $true
        Write-Warning "API port $ApiPort is already in use by PID(s) [$($apiPids -join ', ')], but FastAPI is reachable. Reusing existing API."
    } else {
        throw "API port $ApiPort is already in use by PID(s) [$($apiPids -join ', ')] and did not respond as FastAPI. Run with -Status or -Stop, or pass -ApiPort."
    }
}

if ($frontendPids.Count -gt 0) {
    if (Test-HttpReady -Url $watchlistUrl) {
        $reuseFrontend = $true
        Write-Warning "Frontend port $FrontendPort is already in use by PID(s) [$($frontendPids -join ', ')], but the React app is reachable. Reusing existing frontend."
    } else {
        throw "Frontend port $FrontendPort is already in use by PID(s) [$($frontendPids -join ', ')] and did not respond as the React app. Run with -Status or -Stop, or pass -FrontendPort."
    }
}

$apiOut = Join-Path $stateDir "mvp-api.out.log"
$apiErr = Join-Path $stateDir "mvp-api.err.log"
$frontendOut = Join-Path $stateDir "mvp-frontend.out.log"
$frontendErr = Join-Path $stateDir "mvp-frontend.err.log"

$apiArgs = @(
    "-m", "uvicorn", "api.main:app",
    "--host", $HostAddress,
    "--port", $ApiPort.ToString()
)
if ($Reload) {
    $apiArgs += "--reload"
}
$quotedPython = $resolvedPythonCommand.Replace("'", "''")
$quotedApiOut = $apiOut.Replace("'", "''")
$quotedNpm = $NpmCommand.Replace("'", "''")
$quotedFrontendOut = $frontendOut.Replace("'", "''")
$apiCommand = "Set-Location '$($repoRoot.Replace("'", "''"))'; & '$quotedPython' $($apiArgs -join ' ') *> '$quotedApiOut'"
if (-not $reuseApi) {
    $apiProcess = Start-Process `
        -FilePath "pwsh" `
        -ArgumentList @("-NoProfile", "-NoExit", "-Command", $apiCommand) `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -WindowStyle Hidden
}

$frontendCommand = "Set-Location '$($repoRoot.Replace("'", "''"))'; `$env:VITE_API_BASE = '$apiBase'; & '$quotedNpm' --prefix frontend run dev -- --host $HostAddress --port $FrontendPort --strictPort *> '$quotedFrontendOut'"
if (-not $reuseFrontend) {
    $frontendProcess = Start-Process `
        -FilePath "pwsh" `
        -ArgumentList @("-NoProfile", "-NoExit", "-Command", $frontendCommand) `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -WindowStyle Hidden
}

@{
    started_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    api_pid = if ($apiProcess) { $apiProcess.Id } else { 0 }
    frontend_pid = if ($frontendProcess) { $frontendProcess.Id } else { 0 }
    reused_api = $reuseApi
    reused_frontend = $reuseFrontend
    api_url = $apiUrl
    frontend_url = $frontendUrl
    watchlist_url = $watchlistUrl
    api_log = $apiOut
    api_error_log = $apiErr
    frontend_log = $frontendOut
    frontend_error_log = $frontendErr
} | ConvertTo-Json | Set-Content $stateFile

if ($apiProcess) {
    Write-Host "Started API PID $($apiProcess.Id)"
} else {
    Write-Host "Reusing existing API at $apiUrl"
}
if ($frontendProcess) {
    Write-Host "Started frontend PID $($frontendProcess.Id)"
} else {
    Write-Host "Reusing existing frontend at $frontendUrl"
}
Write-Host "Waiting for API at $apiUrl ..."
Wait-PortOpen -Address $HostAddress -Port $ApiPort
Write-Host "Waiting for frontend at $frontendUrl ..."
Wait-PortOpen -Address $HostAddress -Port $FrontendPort

Write-Host ""
Write-Host "MVP app is ready."
Write-Host "Watchlist: $watchlistUrl"
Write-Host "MSFT PM Queue: $frontendUrl/ticker/MSFT/valuation?view=Recommendations"
Write-Host "API docs: $apiUrl/docs"
Write-Host ""
Write-Host "Logs:"
Write-Host "  API stdout: $apiOut"
Write-Host "  API stderr: $apiErr"
Write-Host "  Frontend stdout: $frontendOut"
Write-Host "  Frontend stderr: $frontendErr"
Write-Host ""
Write-Host "Stop later with:"
Write-Host "  pwsh -File .\scripts\manual\launch-mvp-app.ps1 -Stop"

if ($Open) {
    Start-Process $watchlistUrl
}

if ($Detach) {
    return
}

Write-Host ""
Write-Host "Supervisor is running. Keep this window open while using the app."
Write-Host "Press Ctrl+C to stop the API and frontend."

try {
    while ($true) {
        Start-Sleep -Seconds 2
        $apiAlive = Test-PortOpen -Address $HostAddress -Port $ApiPort
        $frontendAlive = Test-PortOpen -Address $HostAddress -Port $FrontendPort
        if (-not $apiAlive -or -not $frontendAlive) {
            Write-Warning "One of the app ports stopped responding. API=$apiAlive frontend=$frontendAlive"
            break
        }
    }
} finally {
    $stateProcessIds = @()
    if ($apiProcess) {
        $stateProcessIds += $apiProcess.Id
    }
    if ($frontendProcess) {
        $stateProcessIds += $frontendProcess.Id
    }
    $portProcessIds = @()
    if (-not $reuseApi) {
        $portProcessIds += @(Get-ListeningPidsOnPort -Port $ApiPort)
    }
    if (-not $reuseFrontend) {
        $portProcessIds += @(Get-ListeningPidsOnPort -Port $FrontendPort)
    }
    Stop-MvpProcess -ProcessIds @($stateProcessIds + $portProcessIds)
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    $ownedPorts = @()
    if (-not $reuseApi) {
        $ownedPorts += $ApiPort
    }
    if (-not $reuseFrontend) {
        $ownedPorts += $FrontendPort
    }
    if ($ownedPorts.Count -eq 0 -or (Wait-PortsClosed -Ports $ownedPorts)) {
        Write-Host "MVP app stopped."
    } else {
        $remainingApi = if ($ownedPorts -contains $ApiPort) { @(Get-ListeningPidsOnPort -Port $ApiPort) } else { @() }
        $remainingFrontend = if ($ownedPorts -contains $FrontendPort) { @(Get-ListeningPidsOnPort -Port $FrontendPort) } else { @() }
        Write-Warning "MVP app stop attempted, but ports are still in use. API $ApiPort PIDs=[$($remainingApi -join ', ')], frontend $FrontendPort PIDs=[$($remainingFrontend -join ', ')]."
    }
}
