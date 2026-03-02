param(
    [string]$MessagePrefix = "Backup",
    [string]$Note = "",
    [string]$Remote = "origin",
    [switch]$NoPush,
    [switch]$DryRun
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = & git -C $scriptDir rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    Write-Host "ERROR: git repository not found."
    exit 1
}

$repoRoot = $repoRoot.Trim()
$branch = (& git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
    Write-Host "ERROR: cannot detect current branch."
    exit 1
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$commitMessage = "$MessagePrefix $timestamp"
if (-not [string]::IsNullOrWhiteSpace($Note)) {
    $commitMessage = "$commitMessage | $($Note.Trim())"
}

Write-Host "========================================"
Write-Host "FULL BACKUP TO GITHUB"
Write-Host "========================================"
Write-Host "Repo: $repoRoot"
Write-Host "Branch: $branch"
Write-Host "Remote: $Remote"
Write-Host "Message: $commitMessage"
Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN: no changes will be committed or pushed."
    & git -C $repoRoot status --short
    exit 0
}

& git -C $repoRoot add -A
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: failed to stage changes."
    exit $LASTEXITCODE
}

& git -C $repoRoot diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "BACKUP INFO: no changes to commit."
    exit 0
}

& git -C $repoRoot commit -m $commitMessage
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: commit failed."
    exit $LASTEXITCODE
}

$commitHash = (& git -C $repoRoot rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commitHash)) {
    Write-Host "ERROR: cannot read commit hash."
    exit 1
}

if (-not $NoPush) {
    & git -C $repoRoot push $Remote $branch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: push failed."
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "========================================"
    Write-Host "BACKUP SUCCESS: $commitHash pushed to $Remote/$branch"
    Write-Host "========================================"
}
else {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "BACKUP SUCCESS (LOCAL ONLY): $commitHash"
    Write-Host "========================================"
}
