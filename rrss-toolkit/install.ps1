# RRSS Toolkit installer (PowerShell, Windows native)
#
# Usage:
#   .\install.ps1                                    (from a local clone)
#   iwr <raw>/install.ps1 -UseBasicParsing | iex    (bootstrap from GitHub)
#
# Flags:
#   -SkillsOnly      Install only the Claude Code skills
#   -SdkOnly         Install only the Python SDK
#   -NoBackup        Skip backing up existing SKILL.md files
#   -Repo            Override repo (default: dnzengou/browser-use)
#   -Branch          Override branch (default: workspace)

[CmdletBinding()]
param(
	[switch]$SkillsOnly,
	[switch]$SdkOnly,
	[switch]$NoBackup,
	[string]$Repo = "dnzengou/browser-use",
	[string]$Branch = "workspace"
)

$ErrorActionPreference = "Stop"

function Log($msg)  { Write-Host "> $msg" -ForegroundColor Blue }
function Ok($msg)   { Write-Host "[ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[x] $msg" -ForegroundColor Red }

$ToolkitSubdir = "rrss-toolkit"

# Resolve toolkit root: prefer local clone, fall back to GitHub clone.
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $null }
if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "skills/manifest.json"))) {
	$ToolkitRoot = $ScriptDir
	Log "Installing from local checkout: $ToolkitRoot"
} else {
	$Tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "rrss-toolkit-$(Get-Random)")
	Log "Bootstrapping from https://github.com/$Repo@$Branch"
	if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
		Err "git not found. Install git or run from a local clone."
		exit 1
	}
	& git clone --depth 1 --branch $Branch "https://github.com/$Repo.git" (Join-Path $Tmp "repo") *>$null
	$ToolkitRoot = Join-Path $Tmp "repo" $ToolkitSubdir
	if (-not (Test-Path $ToolkitRoot)) {
		Err "$ToolkitSubdir not found in $Repo@$Branch"
		exit 1
	}
}

$Manifest = Join-Path $ToolkitRoot "skills/manifest.json"
if (-not (Test-Path $Manifest)) {
	Err "manifest.json missing at $Manifest"
	exit 1
}

function Verify-Checksums {
	$ChecksumsFile = Join-Path $ToolkitRoot "checksums.txt"
	if (-not (Test-Path $ChecksumsFile)) {
		Warn "checksums.txt not present; skipping integrity check"
		return
	}
	$lines = Get-Content $ChecksumsFile
	foreach ($line in $lines) {
		if ($line -match '^([0-9a-f]{64})\s+\*?(.+)$') {
			$expected = $matches[1]
			$file = Join-Path $ToolkitRoot $matches[2].Trim()
			if (-not (Test-Path $file)) { Err "missing file: $file"; exit 1 }
			$actual = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
			if ($actual -ne $expected) {
				Err "checksum mismatch: $file"
				Err "  expected $expected"
				Err "  actual   $actual"
				exit 1
			}
		}
	}
	Ok "checksums verified"
}

function Install-Skills {
	Verify-Checksums
	$manifestObj = Get-Content $Manifest | ConvertFrom-Json
	$claudeSkills = Join-Path $env:USERPROFILE ".claude/skills"
	New-Item -ItemType Directory -Force -Path $claudeSkills | Out-Null

	foreach ($s in $manifestObj.skills) {
		$srcPath = Join-Path $ToolkitRoot $s.source
		$destPath = $s.dest -replace '^~', $env:USERPROFILE
		$destDir = Split-Path $destPath -Parent
		New-Item -ItemType Directory -Force -Path $destDir | Out-Null
		if ((Test-Path $destPath) -and -not $NoBackup) {
			$ts = Get-Date -Format "yyyyMMdd-HHmmss"
			Copy-Item $destPath "$destPath.backup.$ts" -Force
		}
		Copy-Item $srcPath $destPath -Force
		Ok "skill installed: $($s.name) -> $destPath"
	}
}

function Install-Sdk {
	$pipCmd = $null
	foreach ($c in @("pip3", "pip")) {
		if (Get-Command $c -ErrorAction SilentlyContinue) { $pipCmd = $c; break }
	}
	if (-not $pipCmd) {
		Warn "pip not found; skipping Python SDK install. Try: pip install rrss-arm"
		return
	}
	Log "Installing rrss-arm via $pipCmd"
	$sdkPath = Join-Path $ToolkitRoot "sdk/python"
	& $pipCmd install --upgrade $sdkPath
	if ($LASTEXITCODE -ne 0) {
		Err "pip install failed; try: pip install rrss-arm"
		return
	}
	Ok "rrss-arm installed"
}

Write-Host ""
Write-Host "=== RRSS Toolkit installer ===" -ForegroundColor Cyan
if (-not $SdkOnly)    { Install-Skills }
if (-not $SkillsOnly) { Install-Sdk }
Write-Host ""
Ok "Done."
Write-Host "Skills: /kafca, /kafcade, /evo-metaclaw, /rrss"
Write-Host "SDK:    python -c 'from rrss_arm import HostCircuitBreaker; print(HostCircuitBreaker.__doc__[:80])'"
