<#
.SYNOPSIS
Launch Streamlit locally and open Playwright CLI against it.

.DESCRIPTION
Run this from a normal local PowerShell session, not from the restricted Codex shell.
This is the canonical scripted local validation path for Alpha Pod.
Activate the repo env first with `ca ai-fund`.
The script starts or reuses a local Streamlit dashboard, opens Playwright CLI against it,
and leaves the dashboard running so you can continue using `playwright-cli` commands.
Core launch pattern: `playwright-cli open http://127.0.0.1:8502`
Dashboard command pattern: `python -m streamlit run dashboard/app.py`

.EXAMPLE
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1

.EXAMPLE
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1 -Preview

.EXAMPLE
pwsh -File .\scripts\manual\launch-streamlit-playwright-cli.ps1 -Stop
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8502,
    [string]$PythonCommand = "python",
    [string]$PlaywrightCliCommand = "playwright-cli",
    [switch]$Preview,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$Attempts = 40,
        [int]$DelaySeconds = 1
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds $DelaySeconds
        }
    }

    throw "Timed out waiting for Streamlit at $Url"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stateDir = Join-Path $repoRoot ".pwtmp"
$stateFile = Join-Path $stateDir "playwright-cli-local.json"
$targetUrl = "http://$HostAddress`:$Port"
$streamlitArgs = @(
    "-m", "streamlit", "run", "dashboard/app.py",
    "--server.headless", "true",
    "--server.address", $HostAddress,
    "--server.port", $Port.ToString(),
    "--browser.serverAddress", $HostAddress,
    "--browser.serverPort", $Port.ToString()
)

if ($Preview) {
    Write-Host "Activate the host env first:"
    Write-Host "  ca ai-fund"
    Write-Host "Repository root: $repoRoot"
    Write-Host "Target URL: $targetUrl"
    Write-Host "Streamlit command:"
    Write-Host "  $PythonCommand $($streamlitArgs -join ' ')"
    Write-Host "Playwright command:"
    Write-Host "  $PlaywrightCliCommand open $targetUrl"
    Write-Host "Follow-up commands:"
    Write-Host "  playwright-cli snapshot"
    Write-Host "  playwright-cli screenshot"
    Write-Host "  playwright-cli close"
    return
}

if ($env:CONDA_DEFAULT_ENV -ne "ai-fund") {
    Write-Warning "Expected CONDA_DEFAULT_ENV=ai-fund. Activate the repo env first with: ca ai-fund"
}

if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir | Out-Null
}

if ($Stop) {
    if (-not (Test-Path $stateFile)) {
        Write-Host "No saved Streamlit session state found at $stateFile"
        return
    }

    $state = Get-Content $stateFile | ConvertFrom-Json
    if ($state.streamlit_pid) {
        Stop-Process -Id $state.streamlit_pid -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped Streamlit PID $($state.streamlit_pid)"
    }
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    return
}

Test-CommandAvailable -Name $PythonCommand
Test-CommandAvailable -Name $PlaywrightCliCommand

$existingState = $null
if (Test-Path $stateFile) {
    try {
        $existingState = Get-Content $stateFile | ConvertFrom-Json
    } catch {
        $existingState = $null
    }
}

$streamlitProcess = $null
$reuseExisting = $false
if ($existingState -and $existingState.streamlit_pid) {
    $existingProc = Get-Process -Id $existingState.streamlit_pid -ErrorAction SilentlyContinue
    if ($existingProc) {
        $reuseExisting = $true
        Write-Host "Reusing existing Streamlit PID $($existingState.streamlit_pid)"
    }
}

if (-not $reuseExisting) {
    $streamlitOut = Join-Path $stateDir "streamlit-playwright.out.log"
    $streamlitErr = Join-Path $stateDir "streamlit-playwright.err.log"
    $streamlitProcess = Start-Process `
        -FilePath $PythonCommand `
        -ArgumentList $streamlitArgs `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -RedirectStandardOutput $streamlitOut `
        -RedirectStandardError $streamlitErr

    @{
        streamlit_pid = $streamlitProcess.Id
        started_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
        url = $targetUrl
        stdout_log = $streamlitOut
        stderr_log = $streamlitErr
    } | ConvertTo-Json | Set-Content $stateFile

    Write-Host "Started Streamlit PID $($streamlitProcess.Id)"
}

Wait-HttpReady -Url $targetUrl
Write-Host "Streamlit ready at $targetUrl"
Write-Host "Opening Playwright CLI..."

& $PlaywrightCliCommand open $targetUrl

Write-Host ""
Write-Host "Playwright session opened."
Write-Host "Next commands:"
Write-Host "  playwright-cli snapshot"
Write-Host "  playwright-cli screenshot"
Write-Host "  playwright-cli close"
Write-Host ""
Write-Host "When you are done, stop Streamlit with:"
Write-Host "  pwsh -File .\\scripts\\manual\\launch-streamlit-playwright-cli.ps1 -Stop"
