#requires -Version 7.0
<#
.SYNOPSIS
Publish a sanitized snapshot of this repository to the public mirror.

.DESCRIPTION
The private repository stays the source of truth. This script builds an archive
from a git ref, scrubs every string listed in a local (never committed) config
file, overlays canonical public documents, runs a fail-closed leak scan, and
pushes the result to the public mirror.

The config lives outside the repository on purpose: the strings being hidden
must never land in git history, and the sanitizer must never ship its own
blocklist to the public repository.

Default config location: $HOME/.research-workflow-public-sync.json

Config schema (JSON):
  public_remote        string   clone URL of the public mirror (required)
  commit_author_name   string   author for public commits (default "Codex")
  commit_author_email  string   email for public commits (default codex@localhost)
  replacements         array    of [from, to] literal string pairs
  forbidden            array    of literal strings that must not survive
  overlays             object   export path -> tracked source file to copy in
  exclude              array    repo-relative paths dropped from the export

.PARAMETER Ref
Git ref to publish. Defaults to origin/master.

.PARAMETER ConfigPath
Path to the local JSON config.

.PARAMETER DryRun
Build and verify the sanitized export but do not clone or push the mirror.

.PARAMETER Force
Allow publishing when the working tree is dirty or HEAD is not at Ref.

.PARAMETER RunTests
Run the targeted tool tests against the export before pushing.

.EXAMPLE
scripts/publish-public.ps1 -DryRun
scripts/publish-public.ps1
#>
[CmdletBinding()]
param(
    [string]$Ref = 'origin/master',
    [string]$ConfigPath = (Join-Path $HOME '.research-workflow-public-sync.json'),
    [string]$CommitMessage = '',
    [switch]$DryRun,
    [switch]$Force,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-UnderTemp([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $temp = [System.IO.Path]::GetFullPath($env:TEMP)
    if (-not $full.StartsWith($temp, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to touch a path outside TEMP: $full"
    }
    return $full
}

function Test-IsTextFile([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    foreach ($b in $bytes) {
        if ($b -eq 0) { return $false }
    }
    return $true
}

function Remove-PathForce([string]$Path) {
    $full = Assert-UnderTemp $Path
    if (-not (Test-Path -LiteralPath $full)) { return }
    $item = Get-Item -LiteralPath $full -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        [System.IO.Directory]::Delete($full, $false)
    } elseif ($item.PSIsContainer) {
        [System.IO.Directory]::Delete($full, $true)
    } else {
        [System.IO.File]::Delete($full)
    }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "sanitizer config not found: $ConfigPath"
}
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json

$publicRemote = [string]$config.public_remote
if ([string]::IsNullOrWhiteSpace($publicRemote)) {
    throw 'config.public_remote is required'
}
$authorName = if ($config.commit_author_name) { [string]$config.commit_author_name } else { 'Codex' }
$authorEmail = if ($config.commit_author_email) { [string]$config.commit_author_email } else { 'codex@localhost' }

$replacements = @()
foreach ($pair in @($config.replacements)) {
    $replacements += , @([string]$pair[0], [string]$pair[1])
}
$forbidden = @($config.forbidden | ForEach-Object { [string]$_ })
$exclude = @($config.exclude | ForEach-Object { [string]$_ })
$overlays = @{}
if ($config.overlays) {
    foreach ($property in $config.overlays.PSObject.Properties) {
        $overlays[$property.Name] = [string]$property.Value
    }
}

# --- preconditions: the private repository is the pushed source of truth ------
$head = (git -C $root rev-parse HEAD).Trim()
$refSha = (git -C $root rev-parse --verify $Ref).Trim()
if ($head -ne $refSha -and -not $Force) {
    throw ("HEAD ($head) is not $Ref ($refSha). Commit and push the private " +
        "repository first, or pass -Force to publish the ref anyway.")
}
if (git -C $root status --porcelain) {
    Write-Warning 'working tree has uncommitted changes; only the committed ref is published'
}

# --- build the sanitized export ----------------------------------------------
$stamp = [guid]::NewGuid().ToString('N').Substring(0, 8)
$export = Assert-UnderTemp (Join-Path $env:TEMP "public-sync-export-$stamp")
$tar = Assert-UnderTemp (Join-Path $env:TEMP "public-sync-$stamp.tar")

New-Item -ItemType Directory -Path $export | Out-Null
git -C $root archive --format=tar $Ref -o $tar
tar -xf $tar -C $export
[System.IO.File]::Delete($tar)
Write-Step "export built at $export"

foreach ($relative in $exclude) {
    $target = Join-Path $export $relative
    Remove-PathForce $target
}
Write-Step ("excluded fresh " + $exclude.Count + " maintainer path(s)")

$changed = 0
foreach ($file in Get-ChildItem -LiteralPath $export -Recurse -File) {
    if (-not (Test-IsTextFile $file.FullName)) { continue }
    $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding utf8
    if ($null -eq $text) { continue }
    $original = $text
    foreach ($pair in $replacements) {
        $text = $text.Replace($pair[0], $pair[1])
    }
    if ($text -ne $original) {
        Set-Content -LiteralPath $file.FullName -Value $text -Encoding utf8 -NoNewline
        $changed++
    }
}
Write-Step "scrubbed $changed file(s)"

foreach ($relative in $overlays.Keys) {
    $source = $overlays[$relative]
    $content = git -C $root show "${Ref}:$source"
    if ($LASTEXITCODE -ne 0) { throw "overlay source missing at ${Ref}: $source" }
    $target = Join-Path $export $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Set-Content -LiteralPath $target -Value ($content -join "`n") -Encoding utf8
}
Write-Step ("applied " + $overlays.Count + " public overlay(s)")

# --- fail-closed leak scan ----------------------------------------------------
$problems = New-Object System.Collections.Generic.List[string]
$files = Get-ChildItem -LiteralPath $export -Recurse -File
foreach ($pattern in $forbidden) {
    if ([string]::IsNullOrEmpty($pattern)) { continue }
    foreach ($hit in ($files | Select-String -SimpleMatch -Pattern $pattern)) {
        $relative = $hit.Path.Substring($export.Length).TrimStart('\')
        $problems.Add("${relative}:$($hit.LineNumber): forbidden literal '$pattern'")
    }
}
$secretPatterns = @(
    'gh[pousr]_[A-Za-z0-9]{30,}',
    'github_pat_[A-Za-z0-9_]{30,}',
    'sk-[A-Za-z0-9]{32,}',
    'AKIA[0-9A-Z]{16}',
    '-----BEGIN [A-Z ]*PRIVATE KEY-----\s*\n'
)
foreach ($pattern in $secretPatterns) {
    foreach ($hit in ($files | Select-String -Pattern $pattern)) {
        $relative = $hit.Path.Substring($export.Length).TrimStart('\')
        $problems.Add("${relative}:$($hit.LineNumber): secret-like value")
    }
}
if ($problems.Count -gt 0) {
    $problems | Select-Object -First 40 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "leak scan failed with $($problems.Count) finding(s); nothing was pushed"
}
Write-Step 'leak scan clean'

if ($RunTests) {
    $python = Join-Path $root 'tools\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw "test interpreter missing: $python" }
    $env:PYTHONPATH = Join-Path $export 'tools'
    $env:PYTHONUTF8 = '1'
    & $python -m unittest tools.tests.test_github_workflows tools.tests.test_docs_consistency tools.tests.test_scripts
    if ($LASTEXITCODE -ne 0) { throw 'targeted tests failed; nothing was pushed' }
    Write-Step 'targeted tests passed'
}

if ($DryRun) {
    Write-Host "dry run complete: $export" -ForegroundColor Green
    return
}

# --- push the sanitized snapshot to the public mirror -------------------------
$mirror = Assert-UnderTemp (Join-Path $env:TEMP "public-sync-mirror-$stamp")
git clone --quiet --depth 1 $publicRemote $mirror

Get-ChildItem -LiteralPath $mirror -Force | Where-Object { $_.Name -ne '.git' } | ForEach-Object {
    Remove-PathForce $_.FullName
}
Get-ChildItem -LiteralPath $export -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $mirror -Recurse -Force
}

git -C $mirror add -A
if (-not (git -C $mirror status --porcelain)) {
    Write-Host 'public mirror already up to date' -ForegroundColor Green
    return
}

if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    $CommitMessage = "sync: publish sanitized snapshot of $Ref"
}
git -C $mirror -c "user.name=$authorName" -c "user.email=$authorEmail" commit -m $CommitMessage
git -C $mirror push origin HEAD:master
Write-Host "published: $publicRemote" -ForegroundColor Green
