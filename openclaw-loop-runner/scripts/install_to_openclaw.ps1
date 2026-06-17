param(
  [Parameter(Mandatory = $true)]
  [string]$OpenClawRoot,

  [switch]$Force
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$openClawPath = [System.IO.Path]::GetFullPath($OpenClawRoot)

if (-not (Test-Path -LiteralPath $openClawPath)) {
  throw "OpenClaw root does not exist: $openClawPath"
}

$pluginsDir = Join-Path $openClawPath "plugins"
$skillsDir = Join-Path $openClawPath "skills"
$targetPlugin = Join-Path $pluginsDir "openclaw-loop-runner"
$targetSkill = Join-Path $skillsDir "openclaw-loop-runner"

New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null

if ((Test-Path -LiteralPath $targetPlugin) -and (-not $Force)) {
  throw "Plugin already exists: $targetPlugin. Re-run with -Force to overwrite."
}

if ((Test-Path -LiteralPath $targetSkill) -and (-not $Force)) {
  throw "Skill already exists: $targetSkill. Re-run with -Force to overwrite."
}

if (Test-Path -LiteralPath $targetPlugin) {
  Remove-Item -LiteralPath $targetPlugin -Recurse -Force
}

if (Test-Path -LiteralPath $targetSkill) {
  Remove-Item -LiteralPath $targetSkill -Recurse -Force
}

Copy-Item -LiteralPath $pluginRoot -Destination $targetPlugin -Recurse -Force
Copy-Item -LiteralPath (Join-Path $pluginRoot "skills\openclaw-loop-runner") -Destination $targetSkill -Recurse -Force

Write-Host "[OK] Installed plugin: $targetPlugin"
Write-Host "[OK] Installed skill:  $targetSkill"
Write-Host ""
Write-Host "Initialize loop state from an OpenClaw project:"
Write-Host "python `"$targetPlugin\scripts\openclaw_loop.py`" --state-dir .openclaw-loop init"
Write-Host ""
Write-Host "Run/status/check:"
Write-Host "python `"$targetPlugin\scripts\openclaw_loop.py`" --state-dir .openclaw-loop status"
Write-Host "python `"$targetPlugin\scripts\openclaw_loop.py`" --state-dir .openclaw-loop run"
Write-Host "python `"$targetPlugin\scripts\openclaw_loop.py`" --state-dir .openclaw-loop check"
