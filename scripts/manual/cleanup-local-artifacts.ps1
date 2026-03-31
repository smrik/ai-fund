<#
.SYNOPSIS
Remove obvious local temp and generated artifacts from the repo working tree.

.DESCRIPTION
Deletes browser scratch, Playwright output, Streamlit logs, pytest temp dirs,
and Python __pycache__ directories. It intentionally does not touch tracked
source files, `.agent/session-state.md`, `data/`, or other ambiguous local state.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$explicitTargets = @(
    ".playwright-cli",
    ".pwtmp",
    "test-results",
    "playwright-report",
    ".playwright-localhost-8502.png",
    ".playwright-streamlit.err.log",
    ".playwright-streamlit.out.log",
    ".tmp-ngrok.log",
    ".tmp-streamlit-epic1.log",
    ".tmp-streamlit-ngrok.log",
    "streamlit-check.err.log",
    "streamlit-check.out.log",
    "streamlit-live.err.log",
    "streamlit-live.out.log",
    "streamlit-live2.err.log",
    "streamlit-live2.out.log"
)

foreach ($target in $explicitTargets) {
    $path = Join-Path $repoRoot $target
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $path"
    }
}

Get-ChildItem -Path $repoRoot -Filter "streamlit*.log" -File -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $($_.FullName)"
    }

$agentDir = Join-Path $repoRoot ".agent"
if (Test-Path $agentDir) {
    Get-ChildItem -Path $agentDir -Filter "streamlit*.log" -File -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            Write-Host "Removed $($_.FullName)"
        }
}

Get-ChildItem -Path $repoRoot -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like ".pytest-tmp*" -or
        $_.Name -eq ".pytest_tmp" -or
        $_.Name -like "pytest_basetemp_*" -or
        $_.Name -like "tmp*"
    } |
    ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $($_.FullName)"
    }

Get-ChildItem -Path $repoRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "__pycache__" } |
    ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed $($_.FullName)"
    }
